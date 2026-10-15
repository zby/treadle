"""Draft, review and summarize paragraphs: an ordinary Pydantic AI workflow (runs under bl step unchanged)."""

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
    text = (await writer.run(f"Write one paragraph about {topic}.")).output
    for round in range(max_rounds):
        verdict = (await reviewer.run(f"Review this paragraph about {topic}.\n\n{text}")).output
        if verdict.accepted:
            return {"topic": topic, "text": text, "rounds": round}
        problems = "\n".join(verdict.problems)
        text = (await writer.run(f"Rewrite this paragraph about {topic} to fix:\n{problems}\n\n{text}")).output
    raise RuntimeError(f"out of attempts for {topic}")


async def workflow(topics: list[str], max_rounds: int) -> dict:
    sections = await asyncio.gather(*[draft_and_review(t, max_rounds) for t in topics])
    summary = (await summarizer.run("Summarize these paragraphs:\n\n" + "\n\n".join(s["text"] for s in sections))).output
    return {"sections": sections, "summary": summary}
