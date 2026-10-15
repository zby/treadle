# A workflow script in the Monty subset. Run unchanged by both runners.
# Agents are async functions taking only task=; typed outputs arrive as dicts.
# Input: `topics`, a list of strings. The last expression is the result.
import asyncio


async def polish(topic, draft):
    for attempt in range(3):
        verdict = await checker(task=f"Check this paragraph about {topic}.\n\n{draft}")
        if verdict["ok"]:
            return draft
        draft = await writer(task=f"Revise this paragraph about {topic} to fix: {verdict['problems']}\n\n{draft}")
    raise RuntimeError(f"out of attempts for {topic}")


drafts = await asyncio.gather(*[writer(task=f"Write one paragraph about {t}.") for t in topics])
polished = await asyncio.gather(*[polish(t, d) for t, d in zip(topics, drafts)])
"\n\n".join(polished)
