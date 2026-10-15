"""wf_ops run directly in Pydantic AI (FunctionModel fakes): without a store, then twice with use_store."""

import asyncio
import json
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

from pydantic_core import to_jsonable_python

import wf_ops
from blstep import use_store
from test_direct import fake


async def run(log, plain):
    with ExitStack() as stack:
        for agent in (wf_ops.writer, wf_ops.reviewer, wf_ops.summarizer):
            stack.enter_context(agent.override(model=fake(agent.name)))
        return to_jsonable_python(await wf_ops.workflow(str(log), str(plain), ["a", "c"]))


if __name__ == "__main__":
    tmp = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp())
    tmp.mkdir(parents=True, exist_ok=True)
    for label, store in [("no store", None), ("store, run 1", tmp / "store"), ("store, run 2", tmp / "store")]:
        stem = "plain" if store is None else "stored"  # both stored runs share one log file
        log, plain = tmp / f"{stem}.log", tmp / f"{stem}.unwrapped.log"
        with use_store(store) if store else ExitStack():
            result = asyncio.run(run(log, plain))
        print(f"== {label}: result {json.dumps(result)}")
        print(f"   log ({log.name}): {log.read_text().splitlines()}")
