# Portable workflow script: runs unchanged in the bl step runner and in Pydantic AI.
#
# Contract (see shared/CONTRACT.md):
# - Monty subset; no imports except asyncio and json; no classes needed.
# - Agents are async functions called as `await name(task=...)`; typed agents return dicts.
# - Inputs are top-level names provided by the runner: `topics` (list[str]), `max_rounds` (int).
# - The value of the last expression is the workflow result.
import asyncio


async def draft_and_review(topic):
    text = await writer(task=f"Write one paragraph about {topic}.")
    for round in range(max_rounds):
        verdict = await reviewer(task=f"Review this paragraph about {topic}.\n\n{text}")
        if verdict["accepted"]:
            return {"topic": topic, "text": text, "rounds": round}
        problems = "\n".join(verdict["problems"])
        text = await writer(task=f"Rewrite this paragraph about {topic} to fix:\n{problems}\n\n{text}")
    raise RuntimeError(f"out of attempts for {topic}")


sections = await asyncio.gather(*[draft_and_review(t) for t in topics])
summary = await summarizer(task="Summarize these paragraphs:\n\n" + "\n\n".join(s["text"] for s in sections))
{"sections": sections, "summary": summary}
