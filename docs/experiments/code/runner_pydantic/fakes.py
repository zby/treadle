"""Deterministic fake-model agents built from shared/catalog.py (shared by both routes)."""
import asyncio, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
from catalog import CATALOG  # noqa: E402
from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart  # noqa: E402
from pydantic_ai.models.function import AgentInfo, FunctionModel  # noqa: E402

EVENTS: list[tuple[str, str, float]] = []  # (agent, 'start'|'end', t)
FAIL_WRITER_TOPIC: list[str] = []  # topics for which the writer raises
DELAY = 0.3
T0 = time.monotonic()


def _task(messages) -> str:
    for m in reversed(messages):
        for p in m.parts:
            if p.part_kind == "user-prompt":
                return p.content if isinstance(p.content, str) else str(p.content)
    raise AssertionError("no user prompt")


def _topic(task: str) -> str:
    return re.search(r"about (\w+)", task).group(1)


async def _timed(name, task, fn):
    EVENTS.append((name, "start:" + task.splitlines()[0][:40], time.monotonic() - T0))
    await asyncio.sleep(DELAY)
    try:
        return fn()
    finally:
        EVENTS.append((name, "end:" + task.splitlines()[0][:40], time.monotonic() - T0))


async def writer_fn(messages, info: AgentInfo):
    task = _task(messages)
    def go():
        topic = _topic(task)
        if topic in FAIL_WRITER_TOPIC:
            raise ValueError(f"writer exploded on {topic} (secret detail)")
        if task.startswith("Rewrite"):
            return ModelResponse(parts=[TextPart(f"Paragraph about {topic} (revised).")])
        return ModelResponse(parts=[TextPart(f"Paragraph about {topic}.")])
    return await _timed("writer", task, go)


async def reviewer_fn(messages, info: AgentInfo):
    task = _task(messages)
    def go():
        topic = _topic(task)
        bad = topic == "b" and "(revised)" not in task
        args = {"accepted": False, "problems": ["too vague", "add an example"]} if bad else {"accepted": True, "problems": []}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])
    return await _timed("reviewer", task, go)


async def summarizer_fn(messages, info: AgentInfo):
    task = _task(messages)
    return await _timed("summarizer", task, lambda: ModelResponse(parts=[TextPart(f"SUMMARY: {task.count('Paragraph about')} paragraphs. Done.")]))


FNS = {"writer": writer_fn, "reviewer": reviewer_fn, "summarizer": summarizer_fn}


def build_agents() -> dict[str, Agent]:
    return {
        c.name: Agent(FunctionModel(FNS[c.name]), name=c.name, description=c.description,
                      **({"output_type": c.output_type} if c.output_type else {}))
        for c in CATALOG
    }


def max_overlap(events, agent):
    """Max number of simultaneously running calls of `agent`."""
    cur = best = 0
    for a, kind, _t in sorted((e for e in events if e[0] == agent), key=lambda e: e[2]):
        cur += 1 if kind.startswith("start") else -1
        best = max(best, cur)
    return best
