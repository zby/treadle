"""Test 1: run review_loop.workflow directly in Pydantic AI, with FunctionModel fakes via agent.override."""

import asyncio
import json
import sys
from contextlib import ExitStack

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

import review_loop
from fake_answers import answer


def fake(name):
    async def respond(messages, info: AgentInfo):
        prompt = [p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart)][-1]
        a = answer(name, prompt)
        if info.output_tools:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, a)])
        return ModelResponse(parts=[TextPart(a)])

    return FunctionModel(respond)


async def main(inputs):
    with ExitStack() as stack:
        for agent in (review_loop.writer, review_loop.reviewer, review_loop.summarizer):
            stack.enter_context(agent.override(model=fake(agent.name)))
        return await review_loop.workflow(**inputs)


if __name__ == "__main__":
    inputs = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"topics": ["a", "b", "c"], "max_rounds": 2}
    print(json.dumps(asyncio.run(main(inputs)), indent=2))
