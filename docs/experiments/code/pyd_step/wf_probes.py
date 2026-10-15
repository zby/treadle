"""Probe workflows for tests 3, 4 and 6. Agents come from review_loop by import (module attributes here)."""

import asyncio
import socket
import threading
import time

from pydantic_ai import Agent

from review_loop import MODEL, Verdict, reviewer, writer

counter = Agent(MODEL, name="counter", instructions="You count words.", defer_model_check=True)


@counter.tool_plain
def count_words(text: str) -> int:
    """Count the words in a text."""
    return len(text.split())


async def tooled() -> str:
    """How an agent's own function tools appear in the prompt (they are not run under bl)."""
    return (await counter.run("How many words are in 'a b c'?")).output


async def repeat() -> dict:
    """Test 3: the same prompt twice in sequence, then twice in one gather."""
    first = (await writer.run("Write one paragraph about x.")).output
    second = (await writer.run("Write one paragraph about x.")).output
    pair = await asyncio.gather(writer.run("Write one paragraph about y."), writer.run("Write one paragraph about y."))
    return {"sequential": [first, second], "gathered": [r.output for r in pair]}


async def typed() -> dict:
    """Test 4: what agent.run(...).output is on replay."""
    verdict = (await reviewer.run("Review this paragraph about t.\n\nParagraph about t.")).output
    return {"type": repr(type(verdict)), "is_Verdict": isinstance(verdict, Verdict), "value": verdict}


async def _call(topic: str) -> str:
    return (await writer.run(f"Write one paragraph about {topic}.")).output


async def sleepy() -> list:
    """Test 6a: a timer await before one branch's agent call."""
    async def late():
        await asyncio.sleep(0.05)
        return await _call("late")
    return await asyncio.gather(_call("early"), late())


async def threaded() -> list:
    """Test 6b: a thread await before one branch's agent call."""
    async def late():
        await asyncio.to_thread(time.sleep, 0.05)
        return await _call("late")
    return await asyncio.gather(_call("early"), late())


async def stuck() -> list:
    """Test 6c: a branch waits on an Event nobody sets (a real deadlock)."""
    async def never():
        await asyncio.Event().wait()
    return await asyncio.gather(_call("early"), never())


async def socket_io(delay: float = 0.05) -> list:
    """Test 6d (outside the rule): socket I/O woken by a plain thread, invisible to the idle check."""
    async def late():
        r, w = socket.socketpair()
        r.setblocking(False)
        threading.Timer(delay, w.send, [b"x"]).start()
        await asyncio.get_running_loop().sock_recv(r, 1)
        return await _call("late")
    return await asyncio.gather(_call("early"), late())


async def socket_io_cached(delay: float = 0.5) -> list:
    """Test 6e: the same socket read, inside an async @cached operation (counted as running work)."""
    from blstep import cached

    @cached(name="read_socket")
    async def read_socket(delay: float) -> str:
        r, w = socket.socketpair()
        r.setblocking(False)
        threading.Timer(delay, w.send, [b"x"]).start()
        return (await asyncio.get_running_loop().sock_recv(r, 1)).decode()

    async def late():
        await read_socket(delay)
        return await _call("late")
    return await asyncio.gather(_call("early"), late())
