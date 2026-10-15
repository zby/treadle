"""At-least-once operation recording. Operations must themselves be idempotent."""

import asyncio
import functools
import inspect
import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import get_type_hints

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from .loop import QuietLoop
from .replay import FORMAT_VERSION, ROOT_SCOPE, Replay
from .store import Store, StoreError, atomic_write, json_text, safe_path

ACTIVE: ContextVar[Replay | None] = ContextVar("treadle_active_replay", default=None)


@contextmanager
def use_store(path):
    """Cache operations in a direct run; models still run normally.

    Use one context for a complete run, not one per operation. Serializes against
    other direct runs and steps on this store; it does not cache agent calls.
    """
    store = Store(path)
    with store.lock(step=True):
        replay = Replay(store)
        token = ACTIVE.set(replay)
        try:
            yield
        finally:
            ACTIVE.reset(token)
            replay.raise_if_failed()


def cached(*, name):
    """Record results under an explicit stable name and JSON arguments.

    First execution and replay both validate the same JSON-round-tripped result
    into the return annotation. Positional and keyword argument spelling is part
    of the durable key: f(1), f(x=1) and f() with a default of 1 are distinct.
    Exceptions are not cached. An unfinished attempt
    causes an explicit warning on retry: its side effects may already have run.
    Async operations may await I/O, but must not call agents: they count as busy
    until completed, so an operation waiting for an external answer cannot yield
    a frontier. Wrap I/O operations, not whole workflows.
    """
    if not isinstance(name, str) or not name:
        raise ValueError("cached requires a nonempty stable name=")

    def decorate(fn):
        annotation = get_type_hints(fn).get("return")
        adapter = TypeAdapter(annotation) if annotation is not None else None

        def decode(text):
            return adapter.validate_json(text) if adapter else json.loads(text)

        def lookup(args, kwargs):
            replay = ACTIVE.get()
            if replay is None:
                return None, None, None
            arguments = json.loads(
                json.dumps(
                    to_jsonable_python({"args": args, "kwargs": kwargs}), sort_keys=True, allow_nan=False
                )
            )
            key, occurrence = replay.key("op", name, arguments)
            with replay.checking_store():
                directory = replay.store.directory(key, create=True)
                committed = replay.store.committed(directory)
                if committed is not None:
                    files, answer = committed
                    return replay, directory, (decode(files[answer]),)
            call = {
                "kind": "op",
                "op": name,
                "arguments": arguments,
                "occurrence": occurrence,
                "scope": ROOT_SCOPE,
                "format_version": FORMAT_VERSION,
            }
            with replay.checking_store():
                created = atomic_write(safe_path(directory, "call.json"), json_text(call))
            if not created:
                message = (
                    f"treadle: re-running {name} ({key}): an earlier attempt recorded no result; "
                    "its outcome is uncertain and side effects may already have occurred; ensure idempotency"
                )
                if replay.warn is not None:
                    replay.warn(message)
                else:
                    print(message, file=sys.stderr)
            return replay, directory, None

        def record(replay, directory, result):
            text = json.dumps(to_jsonable_python(result), ensure_ascii=False, allow_nan=False)
            value = decode(text)
            with replay.checking_store(), replay.store.lock():
                if replay.store.committed(directory) is not None:
                    raise StoreError(f"operation {name} was concurrently recorded; outcome uncertain")
                atomic_write(safe_path(directory, "answer.json"), text + "\n", replace=True)
                replay.store.attest(directory, "answer.json")
            return value

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def run_async(*args, **kwargs):
                replay, directory, hit = lookup(args, kwargs)
                if hit is not None:
                    return hit[0]
                loop = asyncio.get_running_loop()
                busy = isinstance(loop, QuietLoop)
                if busy:
                    loop.jobs += 1
                try:
                    result = await fn(*args, **kwargs)
                    return record(replay, directory, result) if replay is not None else result
                finally:
                    if busy:
                        # The surrounding task callback is still running. Its
                        # tracked finally checks quiet after callers can proceed.
                        loop.jobs -= 1

            return run_async

        @functools.wraps(fn)
        def run_sync(*args, **kwargs):
            replay, directory, hit = lookup(args, kwargs)
            if hit is not None:
                return hit[0]
            result = fn(*args, **kwargs)
            return record(replay, directory, result) if replay is not None else result

        return run_sync

    return decorate
