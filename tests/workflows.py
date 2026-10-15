"""Offline functional workflow fixtures. This file is loaded by the installed CLI."""

import asyncio
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from treadle import CallFailed, cached

text = Agent("test", name="text", instructions="Text instructions.", system_prompt="System instructions.")
upstream = Agent("test", name="upstream")


class Verdict(BaseModel):
    count: int


typed_agent = Agent("test", name="typed", output_type=Verdict, retries=1)


async def one(prompt="hello"):
    return (await text.run(prompt)).output


async def fanout():
    return [r.output for r in await asyncio.gather(text.run("left"), text.run("right"))]


async def repeated():
    first = (await text.run("same")).output
    second = (await text.run("same")).output
    pair = await asyncio.gather(text.run("pair"), text.run("pair"))
    return [first, second, *[r.output for r in pair]]


async def typed():
    value = (await typed_agent.run("Return a count")).output
    return {"real_type": isinstance(value, Verdict), "count": value.count}


tooled_agent = Agent("test", name="tooled")


@tooled_agent.tool_plain
def unavailable_tool(value: str) -> str:
    """This tool must never execute in step mode."""
    raise AssertionError("function tools must not execute")


async def tooled():
    return (await tooled_agent.run("answer without tools")).output


async def caught_failure():
    try:
        await text.run("hello")
    except CallFailed as exc:
        return {"caught": True, "reason": str(exc)}
    raise AssertionError("failure was not delivered")


async def timed(mode="sleep"):
    async def late():
        if mode == "sleep":
            await asyncio.sleep(0.03)
        else:
            await asyncio.to_thread(time.sleep, 0.03)
        return await text.run("late")

    return [r.output for r in await asyncio.gather(text.run("early"), late())]


async def cancelled_timer():
    task = asyncio.create_task(asyncio.sleep(1000))
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return await fanout()


async def unsupported():
    """An unfulfilled Event/Future is outside the supported await subset."""
    await asyncio.Event().wait()


async def socket_read(delay):
    reader, writer = socket.socketpair()
    reader.setblocking(False)

    def send():
        try:
            writer.send(b"x")
        except OSError:
            pass
        finally:
            writer.close()

    timer = threading.Timer(delay, send)
    timer.daemon = True
    timer.start()
    try:
        return (await asyncio.get_running_loop().sock_recv(reader, 1)).decode()
    finally:
        timer.cancel()
        reader.close()
        writer.close()


@cached(name="fixture.socket-read")
async def cached_socket(delay: float) -> str:
    return await socket_read(delay)


async def sockets(protected=False):
    async def late():
        await (cached_socket(0.03) if protected else socket_read(0.03))
        return await text.run("late")

    return [r.output for r in await asyncio.gather(text.run("early"), late())]


@cached(name="fixture.effect")
def effect(path: str) -> tuple[datetime, int]:
    file = Path(path)
    count = int(file.read_text()) + 1 if file.exists() else 1
    file.write_text(str(count))
    return datetime.now(timezone.utc), count


async def operations(path):
    result = effect(path)
    stamp, count = result
    a = await one("before")
    b = await one("after")
    return {
        "stamp": stamp,
        "count": count,
        "tuple_type": isinstance(result, tuple),
        "datetime_type": isinstance(stamp, datetime),
        "answers": [a, b],
    }


@cached(name="fixture.flaky")
def flaky(path: str, crash: bool) -> int:
    marker = Path(path)
    if not marker.exists():
        marker.write_text("attempted")
        if crash:
            os._exit(9)
        raise RuntimeError("first attempt failed after side effect")
    return 42


async def retry_operation(path, crash=False):
    value = flaky(path, crash)
    return {"value": value, "answer": await one()}


@cached(name="fixture.slow")
async def slow(marker: str) -> int:
    path = Path(marker)
    path.write_text(str(int(path.read_text()) + 1 if path.exists() else 1))
    while not Path(marker + ".release").exists():
        await asyncio.sleep(0.01)
    return 1


async def slow_operation(marker):
    await slow(marker)
    return await one("after slow")


def sync_output(value: str) -> str:
    return "function:" + value


instructions_agent = Agent("test", name="sync-instructions")
system_agent = Agent("test", name="sync-system")
validator_agent = Agent("test", name="sync-validator")
output_agent = Agent("test", name="sync-output", output_type=sync_output)


@instructions_agent.instructions
def sync_instructions(ctx: RunContext[str | None]) -> str:
    if ctx.deps is not None:
        marker = Path(ctx.deps)
        marker.write_text("started")
        deadline = time.monotonic() + 10
        while not Path(ctx.deps + ".release").exists():
            if time.monotonic() > deadline:
                raise RuntimeError("test callback was not released")
            time.sleep(0.005)
    return "Synchronous instructions."


@system_agent.system_prompt
def sync_system() -> str:
    return "Synchronous system prompt."


@validator_agent.output_validator
def sync_validator(value: str) -> str:
    return value.upper()


async def sync_callbacks(single=False, gate=None):
    async def branch(agent):
        value = (await agent.run("initial", deps=gate)).output
        return (await text.run(f"after {agent.name}: {value}")).output

    if single:
        return await branch(instructions_agent)
    return await asyncio.gather(
        *(branch(agent) for agent in (instructions_agent, system_agent, validator_agent, output_agent))
    )


@cached(name="fixture.integrity")
def integrity_value() -> int:
    return 42


async def caught_integrity(kind="agent", wait_after=False):
    try:
        value = integrity_value() if kind == "op" else (await text.run("integrity")).output
    except Exception:
        value = "caught"
    if wait_after:
        await text.run("after integrity")
    return value


@cached(name="fixture.cleanup")
async def cleanup(path: str) -> int:
    marker = Path(path)
    await asyncio.sleep(0)
    if not marker.exists():
        marker.write_text("attempted")
        raise RuntimeError("cleanup first attempt failed")
    return 7


async def cleanup_finally(path, catch=True):
    try:
        return await one("pending cleanup")
    finally:
        try:
            await cleanup(path)
        except Exception:
            if not catch:
                raise


async def agent_in_finally():
    task = asyncio.create_task(one("pending"))
    try:
        await task
    finally:
        await one("cleanup agent")


@cached(name="fixture.cancelled-callback")
def cancelled_callback_operation() -> int:
    return 17


cancel_agent = Agent("test", name="cancel-callback")


@cancel_agent.instructions
def cancelled_instructions(ctx: RunContext[tuple[threading.Event, threading.Event]]) -> str:
    started, release = ctx.deps
    started.set()
    if not release.wait(timeout=10):
        raise RuntimeError("cancelled callback was not released")
    try:
        cancelled_callback_operation()
    except Exception:
        pass  # The runner must still see integrity failures in this thread.
    return "cancelled"


async def cancel_sync_callback():
    started, release = threading.Event(), threading.Event()
    task = asyncio.create_task(cancel_agent.run("cancel me", deps=(started, release)))
    try:
        await asyncio.to_thread(started.wait)
        task.cancel()
    finally:
        release.set()
    await asyncio.gather(task, return_exceptions=True)
    return "cancelled"


async def identity_overlap():
    async def branch(label):
        await upstream.run(label)
        return (await text.run("identical downstream")).output

    return await asyncio.gather(branch("left"), branch("right"))
