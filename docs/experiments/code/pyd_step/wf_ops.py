"""Cached operations probe: a workflow with side effects and nondeterminism routed through @cached."""

import asyncio
import random
from datetime import datetime, timezone

from blstep import cached
from review_loop import reviewer, summarizer, writer


def append_line(path: str, line: str) -> int:
    """Side effect: append a line; return the file's line count."""
    with open(path, "a") as f:
        f.write(line + "\n")
    with open(path) as f:
        return sum(1 for _ in f)


append_line_cached = cached(append_line, name="append_line")


@cached
def now() -> datetime:
    return datetime.now(timezone.utc)


@cached
def roll() -> float:
    return random.random()


@cached
async def publish(path: str, text: str) -> str:
    """An async operation with its own awaits (a stand-in for a network call)."""
    await asyncio.sleep(0.01)
    await asyncio.to_thread(append_line, path, "PUBLISHED " + text)
    return f"published {len(text)} chars"


async def workflow(log: str, plain_log: str, topics: list[str]) -> dict:
    started, dice = now(), roll()
    append_line(plain_log, f"replay sees started={started.isoformat()} roll={dice:.6f}")  # unwrapped: every replay
    drafts = await asyncio.gather(*[writer.run(f"Write one paragraph about {t}.") for t in topics])
    texts = [d.output for d in drafts]
    n = append_line_cached(log, f"drafted {len(texts)}")  # wrapped: once per run
    append_line(plain_log, f"drafted {len(texts)}")  # unwrapped: once per replay that gets here
    verdict = (await reviewer.run("Review this paragraph about all.\n\n" + " ".join(texts))).output
    append_line_cached(log, f"reviewed accepted={verdict.accepted}")
    summary = (await summarizer.run("Summarize these paragraphs:\n\n" + "\n\n".join(texts))).output
    receipt = await publish(log, summary)
    return {"started": started, "roll": dice, "log_lines_after_draft": n, "receipt": receipt, "summary": summary}


@cached
def flaky_fetch(marker: str) -> str:
    """Fails on its first attempt (no marker file yet), succeeds on the next."""
    import os
    if not os.path.exists(marker):
        open(marker, "w").close()
        raise ConnectionError("transient failure")
    return "fetched"


async def flaky(marker: str) -> str:
    return flaky_fetch(marker)
