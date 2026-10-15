"""Harness: (a) Monty static type check of analysis.py against stubs built from catalog.py,
(b) execution in Monty with a deterministic fake dispatch, (c) a step-style replay simulation.

Run from the experiment root:  uv run python analysis/check.py
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pydantic_monty as pm
from pydantic import TypeAdapter
from pydantic_ai.function_signature import FunctionSignature

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from catalog import CATALOG  # noqa: E402

SCRIPT = (HERE / "analysis.py").read_text()
PARAMS = {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}
INPUT_DECLS = "system: str\ncheckout_path: str\nsource_commit: str\nmethod_commit: str\nsource_files: list[str]\n"
REPORT_CHARS = 12000  # size of each fake report, an assumption (see ../../2026-10-analysis-port.md)


def build_stubs() -> str:
    """Same recipe as DynamicWorkflow._build_type_check_stubs, plus declarations for the runner inputs."""
    sigs = []
    for e in CATALOG:
        ret = TypeAdapter(e.output_type).json_schema() if e.output_type is not None else None
        sigs.append(FunctionSignature.from_schema(name=e.name, parameters_schema=PARAMS, return_schema=ret))
    conflicting = FunctionSignature.get_conflicting_type_names(sigs)
    parts = ["import asyncio\nfrom typing import Any, TypedDict, NotRequired, Literal", INPUT_DECLS]
    parts.extend(FunctionSignature.render_type_definitions(sigs, conflicting))
    parts.extend(s.render("raise NotImplementedError()", is_async=True, conflicting_type_names=conflicting) for s in sigs)
    return "\n\n".join(parts)


FILES = ["src/app/main.py", "src/app/memory/store.py", "src/app/memory/recall.py", "src/app/flow.py", "README.md"]
INPUTS = {
    "system": "demo-agent",
    "checkout_path": "/work/demo-agent",
    "source_commit": "a" * 40,
    "method_commit": "b" * 40,
    "source_files": FILES,
}


# ---- deterministic fake agents: content-based (not call-count based), so replays are stable ----


def filler(tag: str) -> str:
    return (f"{tag} finding with evidence. " * 600)[:REPORT_CHARS]


def fake(agent: str, task: str, scenario: str):
    retry = "Earlier attempts were rejected" in task
    if agent == "boundary_declarer":
        if scenario == "out_of_scope":
            return {"kind": "refusal", "reason": "the repository is a fork with no agent code"}
        paths = ["src/app"] if retry else ["src/app", "../outside"]  # first attempt escapes the source
        return {"kind": "boundary", "statement": "The agent loop and memory.", "paths": paths}
    if agent.endswith("_analyst"):
        role = agent.split("_")[0]
        if role == "epistemic" and "Correct your" not in task and not retry and scenario == "full":
            return {"kind": "refusal", "reason": "needs credentials the checkout does not contain"}
        text = filler(role) + (" STALE" if role == "memory" and "Correct your" not in task else "")
        answers = "Replied to request." if "Correct your" in task else "No requests yet."
        return {"kind": "report", "report": text, "answers": answers, "cited_paths": ["src/app/main.py"]}
    if agent == "reconciler":
        return {
            "kind": "reconciliation",
            "text": "One conflict.",
            "conflicts": [
                {"report_a": "runtime", "finding_a": "r", "report_b": "memory", "finding_b": "m", "prevented_conclusion": "c"}
            ],
        }
    if agent == "report_verifier" and "target: profile" in task or "target: synthesis" in task:
        return {"kind": "verdict", "accepted": True, "requests": [], "problem": None}
    if agent == "report_verifier":
        if scenario == "problem":
            return {"kind": "verdict", "accepted": False, "requests": [], "problem": "reports contradict on every point"}
        reqs = []
        if "REFUSED" in task:
            reqs.append({"target": "epistemic", "request": "write the report from the source alone"})
        if "STALE" in task:
            reqs.append({"target": "memory", "request": "remove stale claims"})
        return {"kind": "verdict", "accepted": not reqs, "requests": reqs, "problem": None}
    if agent == "profile_mapper":
        return {"kind": "profile", "profile": "memory profile " * 50, "cited_paths": ["src/app/memory"]}
    if agent in ("profile_verifier", "synthesis_verifier"):
        return {"kind": "verdict", "accepted": True, "requests": [], "problem": None}
    if agent == "synthesizer":
        return {"kind": "synthesis", "synthesis": "The synthesis. " * 80}
    raise AssertionError(agent)


def key(agent: str, task: str) -> str:
    return hashlib.sha256((agent + "\n" + task).encode()).hexdigest()


def externals(scenario: str, log: list, answered=None, pending=None):
    """External async functions. With `answered`/`pending` it behaves like a step runner: an unanswered
    call is recorded and never returns."""

    def make(name: str):
        async def call(task: str):
            k = key(name, task)
            log.append((name, task, k))
            if answered is not None and k not in answered:
                pending[k] = (name, task)
                await asyncio.Event().wait()
            return fake(name, task, scenario)

        return call

    return {e.name: make(e.name) for e in CATALOG}


async def run(scenario: str, stubs: str, script: str = SCRIPT, inputs=INPUTS, **kw):
    log: list = []
    async with pm.AsyncMonty() as pool:
        async with pool.checkout(type_check=True, type_check_stubs=stubs) as s:
            out = await s.feed_run(script, inputs=inputs, external_lookup=externals(scenario, log, **kw))
    return out, log


def summarize(log):
    from collections import Counter

    c = Counter(a for a, _, _ in log)
    sizes = [len(t) for _, t, _ in log]
    return dict(c), max(sizes), sum(sizes)


async def main():
    stubs = build_stubs()
    (HERE / "stubs.pyi").write_text(stubs)
    print("== type check ==")
    async with pm.AsyncMonty() as pool:
        async with pool.checkout(type_check=True, type_check_stubs=stubs) as s:
            for label, bad in [
                ("misspelled key", SCRIPT.replace('len(r["cited_paths"]) == 0', 'len(r["cited_pathz"]) == 0', 1)),
                ("positional task", SCRIPT.replace("await call(task=make_task", "await call(make_task", 1)),
                ("unknown agent", SCRIPT.replace("await report_verifier(", "await report_verifer(", 1)),
            ]:
                try:
                    await s.feed_run(bad, inputs=INPUTS, external_lookup=externals("full", []))
                    print(f"  negative test '{label}': NOT rejected")
                except pm.MontyTypingError as e:
                    print(f"  negative test '{label}': rejected: {e.display().splitlines()[0]}")
                except pm.MontyError as e:
                    print(f"  negative test '{label}': rejected at runtime only: {type(e).__name__}: {str(e)[:80]}")
    for scenario in ["full", "problem", "out_of_scope"]:
        out, log = await run(scenario, stubs)
        counts, biggest, total = summarize(log)
        print(f"== scenario {scenario}: type check passed, {len(log)} agent calls, max prompt {biggest} chars, total {total}")
        print("  calls:", counts)
        brief = {k: v for k, v in out.items() if k not in ("members", "overview")}
        print("  result:", json.dumps(brief)[:900])
    # failure: out of attempts (the boundary never gets valid)
    try:
        bad_fake = fake

        async def always_bad(task):
            return {"kind": "boundary", "statement": "x", "paths": ["/etc"]}

        async with pm.AsyncMonty() as pool:
            async with pool.checkout(type_check=True, type_check_stubs=stubs) as s:
                ext = externals("full", [])
                ext["boundary_declarer"] = always_bad
                await s.feed_run(SCRIPT, inputs=INPUTS, external_lookup=ext)
    except pm.MontyRuntimeError as e:
        print("== out of attempts raises:", e.display("type-msg")[:200])

    print("== step-style replay (scenario full) ==")
    answered: dict = {}
    step = 0
    while True:
        step += 1
        pending: dict = {}
        log: list = []
        try:
            async with pm.AsyncMonty() as pool:
                async with pool.checkout(type_check=True, type_check_stubs=stubs) as s:
                    out = await asyncio.wait_for(
                        s.feed_run(SCRIPT, inputs=INPUTS, external_lookup=externals("full", log, answered, pending)),
                        timeout=3,
                    )
            print(f"  step {step}: finished; {len(log)} calls replayed, result outcome {out['outcome']}")
            break
        except asyncio.TimeoutError:
            names = [n for n, _ in pending.values()]
            print(f"  step {step}: {len(log)} calls replayed, {len(pending)} open: {names}")
            for k, (n, t) in pending.items():
                answered[k] = fake(n, t, "full")
    print("  distinct answered keys:", len(answered), "; total steps:", step)
    print("  largest prompt among answered keys:", max(len(json.dumps(a)) for a in answered.values()), "(answer json)")


if __name__ == "__main__":
    asyncio.run(main())
