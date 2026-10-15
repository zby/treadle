"""Deterministic fake answers, shared by the direct Pydantic AI test and the fake orchestrator."""

import re


def answer(agent: str, user_prompt: str):
    """Text for text agents, a dict for the reviewer. The reviewer rejects topic b's first draft."""
    topic = re.search(r"about (\w+)", user_prompt).group(1) if "about" in user_prompt else None
    if agent == "writer":
        return f"Paragraph about {topic} (revised)." if user_prompt.startswith("Rewrite") else f"Paragraph about {topic}."
    if agent == "reviewer":
        if topic == "b" and "(revised)" not in user_prompt:
            return {"accepted": False, "problems": ["too vague", "add an example"]}
        return {"accepted": True, "problems": []}
    if agent == "summarizer":
        return f"SUMMARY: {user_prompt.count('Paragraph about')} paragraphs."
    raise KeyError(agent)
