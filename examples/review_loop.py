"""Draft, review and summarize paragraphs: a Pydantic AI workflow that runs unchanged under treadle step."""

import asyncio

from pydantic import BaseModel
from pydantic_ai import Agent

MODEL = "anthropic:claude-sonnet-4-5"  # resolved at run time (defer_model_check): no API key needed to import


class Verdict(BaseModel):
    accepted: bool
    problems: list[str]


writer = Agent(
    MODEL,
    name="writer",
    instructions="You write one clear, concrete paragraph of plain prose. No headings, no lists.",
    defer_model_check=True,
)
reviewer = Agent(
    MODEL,
    name="reviewer",
    output_type=Verdict,
    instructions=(
        "You review a paragraph for accuracy and clarity. Accept it if a general reader would "
        "understand it and it contains no errors; otherwise list each concrete problem."
    ),
    defer_model_check=True,
)
summarizer = Agent(
    MODEL,
    name="summarizer",
    instructions="You summarize several paragraphs in two or three sentences.",
    defer_model_check=True,
)


async def draft_and_review(topic: str, max_rounds: int) -> dict:
    """Return an accepted paragraph; rounds counts rewrites, not reviews."""
    if max_rounds <= 0:
        raise ValueError("max_rounds must be positive")
    prompt = f"Write one paragraph about {topic}."
    for rewrites in range(max_rounds):
        text = (await writer.run(prompt)).output
        verdict = (await reviewer.run(f"Review this paragraph about {topic}.\n\n{text}")).output
        if verdict.accepted:
            return {"topic": topic, "text": text, "rounds": rewrites}
        problems = "\n".join(verdict.problems)
        prompt = f"Rewrite this paragraph about {topic} to fix:\n{problems}\n\n{text}"
    raise RuntimeError(f"out of attempts for {topic}")


async def workflow(topics: list[str], max_rounds: int) -> dict:
    if max_rounds <= 0:
        raise ValueError("max_rounds must be positive")
    sections = await asyncio.gather(*(draft_and_review(t, max_rounds) for t in topics))
    summary = (
        await summarizer.run("Summarize these paragraphs:\n\n" + "\n\n".join(s["text"] for s in sections))
    ).output
    return {"sections": sections, "summary": summary}
