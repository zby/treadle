"""Stable line protocol: `call {JSON}`, `result {JSON}`, final next-action line.

`--json` emits JSONL instead (including worker outcomes and errors). Steps return
0 when done, 2 when waiting, 1 on error; worker commands return 0/1. Unsupported
awaits: direct socket/subprocess I/O can produce an incomplete frontier. Use
@cached for I/O; supported awaits are agent runs, cached operations, tasks and
gathers of these, asyncio.sleep and asyncio.to_thread.
"""

import argparse
import asyncio
import importlib.util
import inspect
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models import override_allow_model_requests
from pydantic_core import to_jsonable_python

from .cache import ACTIVE
from .loop import QuietLoop
from .replay import Replay, StepModel
from .store import Store, StoreError, digest


@contextmanager
def load_workflow(spec):
    filename, separator, function = spec.rpartition(":")
    if not separator or not filename or not function:
        raise StoreError("workflow must be FILE.py:FUNCTION")
    path = Path(filename).resolve()
    # Never replace an importable name such as `types` or `json`. Keep the
    # synthetic entry alive through execution for runtime annotation resolution.
    module_name = "_treadle_workflow_" + digest(str(path).encode())
    module_spec = importlib.util.spec_from_file_location(module_name, path)
    if module_spec is None or module_spec.loader is None:
        raise StoreError(f"cannot load workflow: {path}")
    module = importlib.util.module_from_spec(module_spec)
    previous = sys.modules.get(module_name)
    search_path = sys.path[:]
    sys.modules[module_name] = module
    sys.path.insert(0, str(path.parent))
    try:
        module_spec.loader.exec_module(module)
        declared = getattr(module, "TREADLE_AGENTS", None)
        agents = (
            declared
            if declared is not None
            else [value for value in vars(module).values() if isinstance(value, Agent)]
        )
        names, objects = {}, set()
        for agent in agents:
            if id(agent) in objects:
                continue  # aliases of one agent are not duplicate names
            if not isinstance(agent, Agent) or not agent.name or agent.name in names:
                raise StoreError("every agent must have a unique explicit name=")
            objects.add(id(agent))
            names[agent.name] = agent
        fn = getattr(module, function)
        if not inspect.iscoroutinefunction(fn):
            raise StoreError("workflow function must be async")
        yield fn, names
    finally:
        sys.path[:] = search_path
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous


async def drive(fn, inputs, replay):
    loop = asyncio.get_running_loop()
    loop.idle = loop.create_future()
    main = None
    try:
        main = asyncio.create_task(fn(**inputs))
        await asyncio.wait([main, loop.idle], return_when=asyncio.FIRST_COMPLETED)
        replay.raise_if_failed()
        if main.done():
            return True, main.result(), []
        records = [replay.open[key].copy() for key in sorted(replay.open)]
        if not records:
            raise StoreError(
                "workflow is stuck: no open calls; unsupported await or deadlock (wrap I/O in @cached)"
            )
        return False, None, records
    finally:
        # Await workflow finally blocks explicitly. Runner.close otherwise only
        # logs task exceptions. Cache/model contexts outlive all runner teardown.
        replay.tearing_down = True
        tasks = asyncio.all_tasks() - {asyncio.current_task()}
        if main is not None:
            tasks.add(main)  # retrieve exceptions even if fatal state won the race
        for task in tasks:
            task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                raise outcome


def emit(args, kind, payload, text, *, error=False):
    if getattr(args, "json", False):
        print(json.dumps({"type": kind, **payload}, ensure_ascii=False, sort_keys=True), flush=True)
    else:
        print(text, file=sys.stderr if error else sys.stdout, flush=True)


def step(args):
    store = Store(args.store)
    with store.lock(step=True), override_allow_model_requests(False):
        # Loading is inside the serial-step guard: top-level code must also be
        # deterministic and side-effect free, just like the workflow body.
        replay = None
        try:
            inputs = json.loads(args.inputs)
            if not isinstance(inputs, dict):
                raise StoreError("--inputs must be a JSON object")
            replay = Replay(
                store, warn=lambda message: emit(args, "warning", {"warning": message}, message, error=True)
            )
            with load_workflow(args.workflow) as (fn, agents):
                # Pydantic AI defaults to anyio threads, invisible to QuietLoop.
                # The public executor context routes all sync callbacks through
                # run_in_executor. Join even cancelled callbacks before checking
                # fatal state or publishing output; Python cannot kill threads.
                with ExitStack() as stack:
                    token = ACTIVE.set(replay)
                    stack.callback(ACTIVE.reset, token)
                    executor = stack.enter_context(ThreadPoolExecutor())
                    stack.enter_context(Agent.using_thread_executor(executor))
                    for name, agent in agents.items():
                        stack.enter_context(agent.override(model=StepModel(name, replay)))
                    with asyncio.Runner(loop_factory=QuietLoop) as runner:
                        done, result, records = runner.run(drive(fn, inputs, replay))
            replay.raise_if_failed()
        except BaseException:
            store.publish_open([])
            if replay is not None:
                replay.raise_if_failed()
            raise
        store.publish_open(records)
        if done:
            result = to_jsonable_python(result)
            emit(
                args,
                "result",
                {"result": result},
                "result " + json.dumps(result, ensure_ascii=False, sort_keys=True),
            )
            emit(args, "done", {}, "done: workflow completed. Next: no action.")
            return 0
        for record in records:
            claim = store.live_claim(store.directory(record["key"]))
            record = {**record, "holder": claim["worker"] if claim else None}
            emit(args, "call", record, "call " + json.dumps(record, ensure_ascii=False, sort_keys=True))
        emit(
            args,
            "waiting",
            {"open": len(records)},
            f"waiting: {len(records)} open call(s). Next: claim, read prompts, write answers, treadle commit, then treadle step.",
        )
        return 2


def lease_seconds(value):
    try:
        factor = {"s": 1, "m": 60, "h": 3600}.get(value[-1:], 1)
        number = float(value[:-1] if value[-1:] in ("s", "m", "h") else value)
        seconds = number * factor
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError
        return seconds
    except ValueError as exc:
        raise argparse.ArgumentTypeError("lease must be positive seconds, or e.g. 30m / 1h") from exc


def worker_command(args):
    store = Store(args.store)
    if args.command == "claim":
        key, claim = store.claim(None if args.next else args.key, args.worker, args.lease)
        directory = store.directory(key)
        record = {
            "key": key,
            "worker": claim["worker"],
            "expires_at": claim["expires_at"],
            "prompt": str(directory / "prompt.md"),
        }
        emit(args, "claimed", record, "claimed " + json.dumps(record, sort_keys=True))
        if not args.json:
            print("Next: read prompt, write answer, then treadle commit.")
    elif args.command == "release":
        key = store.release(args.key, args.worker)
        emit(args, "released", {"key": key}, f"released {key}. Next: treadle claim --next or treadle step.")
    else:
        key, _ = store.commit(args.key, args.files, args.worker)
        emit(
            args,
            "committed",
            {"key": key},
            f"committed {key}. Next: treadle step with the same workflow, inputs and store.",
        )
    return 0


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, json=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.json = json

    def error(self, message):
        # Exit 2 belongs exclusively to a step waiting for external answers.
        if self.json:
            emit(self, "error", {"error": message}, "")
            self.exit(1)
        self.print_usage(sys.stderr)
        self.exit(1, f"error: {message}\nNext: run treadle --help.\n")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in argv
    parser = ArgumentParser(prog="treadle", description=__doc__, json=json_output)
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=lambda **kwargs: ArgumentParser(json=json_output, **kwargs),
    )
    s = sub.add_parser("step", help="replay an ordinary Pydantic AI workflow")
    s.add_argument("workflow", help="FILE.py:FUNCTION; module-level agents or TREADLE_AGENTS")
    s.add_argument("--inputs", default="{}")
    c = sub.add_parser("commit", help="attest an answer and optional additional relative files")
    c.add_argument("key")
    c.add_argument("files", nargs="*")
    c.add_argument("--worker")
    claim = sub.add_parser("claim", help="claim a call in the latest open frontier")
    group = claim.add_mutually_exclusive_group(required=True)
    group.add_argument("key", nargs="?")
    group.add_argument("--next", action="store_true")
    claim.add_argument("--worker", required=True)
    claim.add_argument("--lease", type=lease_seconds, default=1800)
    release = sub.add_parser("release", help="release your live claim")
    release.add_argument("key")
    release.add_argument("--worker", required=True)
    for command in (s, c, claim, release):
        command.add_argument("--store", required=True)
        command.add_argument("--json", action="store_true", help="emit JSONL")
    args = parser.parse_args(argv)
    try:
        return step(args) if args.command == "step" else worker_command(args)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        emit(
            args,
            "error",
            {"error": message},
            f"error: {message}\nNext: inspect the error before retrying.",
            error=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
