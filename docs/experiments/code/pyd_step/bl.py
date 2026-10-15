"""bl CLI for ordinary Pydantic AI workflows: replay a workflow against the store (see blstep.py).

step FILE.py:FUNC --inputs JSON --store DIR [--json]   0 done (result JSON), 1 error, 2 waiting
complete KEY FILE --store DIR                           validate against the agent's output type, store
fail KEY REASON --store DIR                             that agent.run raises BlCallFailed(REASON)

Interception: every module-level `Agent` of the workflow file (or the list `BL_AGENTS`, if the module
defines it) runs under `agent.override(model=StepModel(...))`. A request returns the stored answer as a
model response (Pydantic AI validates it as usual), raises the stored failure, or posts a prompt file and
awaits forever. When no branch can proceed, the step prints all open calls (sorted by key) and exits 2.
"""

import argparse
import asyncio
import importlib.util
import json
import sys
import traceback
from contextlib import ExitStack
from pathlib import Path

from blstep import ACTIVE, QuietLoop, Replay, StepModel, write_new  # also sets PYDANTIC_AI_NO_BANNER

from pydantic import TypeAdapter, ValidationError
from pydantic_core import to_jsonable_python

import pydantic_ai.models
from pydantic_ai import Agent


# ---------------------------------------------------------------- workflow loading


def load_workflow(spec):
    path, _, func = spec.rpartition(":")
    path = Path(path).resolve()
    sys.path.insert(0, str(path.parent))  # the workflow may import its siblings
    module_spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[path.stem] = module
    module_spec.loader.exec_module(module)
    agents = getattr(module, "BL_AGENTS", None) or [v for v in vars(module).values() if isinstance(v, Agent)]
    by_name = {}
    for agent in agents:
        if not agent.name or agent.name in by_name:
            sys.exit(f"bl: every agent needs a unique name= (got {agent.name!r})")
        by_name[agent.name] = agent
    return path, (getattr(module, func) if func else None), by_name


async def drive(func, inputs, agents, replay):
    loop = asyncio.get_running_loop()
    loop.idle = loop.create_future()
    ACTIVE.set(replay)  # @cached operations use the same store; the main task copies this context
    with ExitStack() as stack:
        for name, agent in agents.items():
            stack.enter_context(agent.override(model=StepModel(name, replay)))
        main = asyncio.ensure_future(func(**inputs))
        await asyncio.wait([main, loop.idle], return_when=asyncio.FIRST_COMPLETED)
    return main  # not done: every branch is suspended (Runner.close cancels the waiting tasks)


# ---------------------------------------------------------------- commands


def emit(as_json, record, text, stream=sys.stdout):
    print(json.dumps(record) if as_json else text, file=stream, flush=True)


def step(args):
    path, func, agents = load_workflow(args.workflow)
    pydantic_ai.models.ALLOW_MODEL_REQUESTS = False  # an agent bl did not intercept must not reach a provider
    replay = Replay(args.store, path)
    with asyncio.Runner(loop_factory=QuietLoop) as runner:
        main = runner.run(drive(func, json.loads(args.inputs), agents, replay))
        if not main.done():
            keys = sorted(replay.open)
            if not keys:
                emit(args.json, {"status": "error", "error": "stuck: no open calls"},
                     "error: workflow is stuck: nothing runnable and no open agent calls", sys.stderr)
                return 1
            for key in keys:
                agent, prompt, new = replay.open[key]
                emit(args.json, {"key": key, "agent": agent, "prompt": str(prompt), "new": new},
                     f"{key[:12]} {agent:<10} {prompt}{'' if new else '  (posted earlier)'}")
            emit(args.json, {"status": "waiting", "open": len(keys)}, f"waiting: {len(keys)} open call(s)")
            return 2
        if main.exception() is not None:
            error = main.exception()
            frames = [f for f in traceback.extract_tb(error.__traceback__) if Path(f.filename) == path]
            where = "".join(traceback.format_list(frames))
            emit(args.json, {"status": "error", "error": f"{type(error).__name__}: {error}"},
                 f"{where}error: {type(error).__name__}: {error}", sys.stderr if not args.json else sys.stdout)
            return 1
        result = to_jsonable_python(main.result())
        emit(args.json, {"status": "done", "result": result}, json.dumps(result, indent=2))
        return 0


def resolve(store, prefix):
    store = Path(store)
    hits = [d for d in store.glob(f"{prefix}*") if (d / "call.json").exists()] if prefix else []
    if len(hits) != 1:
        sys.exit(f"bl: key prefix {prefix!r} matches {len(hits)} calls")
    d = hits[0]
    for done in ("answer.json", "answer.md", "failure.txt"):
        if (d / done).exists():
            sys.exit(f"bl: {d.name} already settled ({done}); not overwriting")
    return d, json.loads((d / "call.json").read_text())


def complete(args):
    d, call = resolve(args.store, args.key)
    if call["kind"] != "agent":
        sys.exit(f"bl: {d.name} is a cached operation; the workflow records its result")
    text = Path(args.file).read_text()
    if not call["typed"]:  # the file is the answer; one final newline (an editor artifact) is dropped
        return 0 if write_new(d / "answer.md", text.removesuffix("\n")) else 1
    _, _, agents = load_workflow(call["workflow"] + ":")
    adapter = TypeAdapter(agents[call["agent"]].output_type)
    try:
        value = adapter.validate_json(text)
    except ValidationError as e:
        print(f"bl: invalid answer for {call['agent']}: {e}", file=sys.stderr)
        return 1
    return 0 if write_new(d / "answer.json", json.dumps(adapter.dump_python(value, mode="json")) + "\n") else 1


def fail(args):
    d, _ = resolve(args.store, args.key)
    return 0 if write_new(d / "failure.txt", args.reason + "\n") else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="bl")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("step")
    s.add_argument("workflow", help="path/to/file.py:function")
    s.add_argument("--inputs", default="{}")
    s.add_argument("--json", action="store_true")
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
