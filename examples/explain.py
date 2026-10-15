"""One named agent and one workflow; supply the model at execution time."""

from pydantic_ai import Agent

explainer = Agent(
    name="explainer",
    instructions="Explain the topic in one clear, concrete paragraph.",
)


async def workflow(topic: str) -> str:
    return (await explainer.run(f"Explain {topic}.")).output
