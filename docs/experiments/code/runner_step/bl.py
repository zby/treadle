"""bl step runner on Monty: replay a workflow script against stored answers.

step SCRIPT --store DIR --inputs JSON   exit 0 done (prints result), 1 script error, 2 waiting (prints open keys)
complete KEY FILE --store DIR           validate and store an answer (never overwrites)
fail KEY REASON --store DIR             store a failure; the call raises RuntimeError(REASON) in the script
"""

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pydantic_monty as pm
from pydantic import ValidationError

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "shared" / "catalog.py"
TASK_SCHEMA = {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}


def load_catalog(path):
    spec = importlib.util.spec_from_file_location("bl_catalog", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {agent.name: agent for agent in module.CATALOG}


def call_key(agent, task):
    return hashlib.sha256(f"{agent}\n{task}".encode()).hexdigest()


def type_check_stubs(catalog, inputs):
    """Agent signatures as Monty type-check stubs, rendered the way the harness renders them."""
    from pydantic_ai.function_signature import FunctionSignature  # slow import; only step needs it

    sigs = [
        FunctionSignature.from_schema(
            name=a.name,
            parameters_schema=TASK_SCHEMA,
            return_schema=a.output_type.model_json_schema() if a.output_type else {"type": "string"},
        )
        for a in catalog.values()
    ]
    clash = FunctionSignature.get_conflicting_type_names(sigs)
    parts = ["import asyncio\nfrom typing import Any, TypedDict, NotRequired, Literal"]
    parts += FunctionSignature.render_type_definitions(sigs, clash)
    parts += [s.render("raise NotImplementedError()", is_async=True, conflicting_type_names=clash) for s in sigs]
    parts += [f"{name}: Any" for name in inputs]  # inputs are bound as globals; declare them for the checker
    return "\n\n".join(parts)


def write_new(path, text):
    """Atomically create `path` with `text`; False if it already exists (never overwrites)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    try:
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    finally:
        tmp.unlink()


def post(store, key, agent, task):
    d = store / key
    d.mkdir(parents=True, exist_ok=True)
    write_new(d / "call.json", json.dumps({"agent": agent.name, "task": task}, indent=2) + "\n")
    schema = ""
    if agent.output_type:
        schema = f"Answer with JSON matching this schema:\n\n{json.dumps(agent.output_type.model_json_schema(), indent=2)}\n\n"
    write_new(d / "prompt.md", f"{agent.description}\n\n{schema}## Task\n\n{task}\n")


def lookup(store, key):
    """Settled Monty result for a stored call, or None while it is open."""
    d = store / key
    if (d / "answer.json").exists():
        return {"return_value": json.loads((d / "answer.json").read_text())}
    if (d / "answer.md").exists():
        return {"return_value": (d / "answer.md").read_text()}
    if (d / "failure.txt").exists():
        return {"exception": RuntimeError((d / "failure.txt").read_text().strip())}
    return None


def on_call(snap, catalog, store, outcomes, open_keys):
    name, kwargs = snap.function_name, snap.kwargs
    if snap.is_os_function:
        return snap.resume_not_handled()
    if name not in catalog:
        return snap.resume({"exception": NameError(f"unknown agent: {name}")})
    if snap.args or set(kwargs) != {"task"} or not isinstance(kwargs["task"], str):
        return snap.resume({"exception": TypeError(f"{name}() takes only task=<str>")})
    key = call_key(name, kwargs["task"])
    result = lookup(store, key)
    if result is None:
        post(store, key, catalog[name], kwargs["task"])
        open_keys.setdefault(key, name)
    else:
        outcomes[snap.call_id] = result
    return snap.resume({"future": ...})


def step(args):
    catalog, store, inputs = load_catalog(args.catalog), Path(args.store), json.loads(args.inputs)
    code = Path(args.script).read_text()
    outcomes, open_keys = {}, {}
    # The session is dropped while futures are still pending: leaving the `with` blocks returns the
    # worker and closes the pool; nothing of the suspended feed is kept (the next step replays).
    with pm.Monty(max_processes=1) as pool, pool.checkout(
        script_name=Path(args.script).name, type_check=True, type_check_stubs=type_check_stubs(catalog, inputs)
    ) as session:
        try:
            snap = session.feed_start(code, inputs=inputs)
            while not isinstance(snap, pm.MontyComplete):
                if isinstance(snap, pm.FunctionSnapshot):
                    snap = on_call(snap, catalog, store, outcomes, open_keys)
                elif isinstance(snap, pm.NameLookupSnapshot):
                    snap = snap.resume()  # undefined name -> NameError in the script
                else:  # FutureSnapshot: resolve every pending call that has a stored outcome
                    # pending_call_ids comes back in varying order; the dict order sets wake-up order, so sort
                    ready = {cid: outcomes.pop(cid) for cid in sorted(snap.pending_call_ids) if cid in outcomes}
                    if not ready:
                        for key in sorted(open_keys):
                            print(key, open_keys[key])
                        return 2
                    snap = snap.resume(ready)
        except pm.MontyTypingError as e:
            print(e.display(), file=sys.stderr)
            return 1
        except pm.MontyRuntimeError as e:
            print(e.display(), file=sys.stderr)
            return 1
        print(json.dumps(snap.output, indent=2))
        return 0


def call_dir(store, key):
    d = Path(store) / key
    if not (d / "call.json").exists():
        sys.exit(f"unknown key: {key}")
    for done in ("answer.json", "answer.md", "failure.txt"):
        if (d / done).exists():
            sys.exit(f"{key} already settled ({done}); not overwriting")
    return d


def complete(args):
    d = call_dir(args.store, args.key)
    agent = load_catalog(args.catalog)[json.loads((d / "call.json").read_text())["agent"]]
    text = Path(args.file).read_text()
    if agent.output_type is None:
        name, body = "answer.md", text
    else:
        try:
            body = json.dumps(agent.output_type.model_validate_json(text).model_dump(mode="json"), indent=2) + "\n"
        except ValidationError as e:
            print(f"invalid answer for {agent.name}: {e}", file=sys.stderr)
            return 1
        name = "answer.json"
    return 0 if write_new(d / name, body) else 1


def fail(args):
    d = call_dir(args.store, args.key)
    return 0 if write_new(d / "failure.txt", args.reason + "\n") else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="bl")
    p.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("step")
    s.add_argument("script")
    s.add_argument("--inputs", default="{}")
    c = sub.add_parser("complete")
    c.add_argument("key")
    c.add_argument("file")
    f = sub.add_parser("fail")
    f.add_argument("key")
    f.add_argument("reason")
    for sp in (s, c, f):
        sp.add_argument("--store", required=True)
    args = p.parse_args(argv)
    return {"step": step, "complete": complete, "fail": fail}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
