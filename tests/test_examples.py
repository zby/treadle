import asyncio
import json
from contextlib import ExitStack

import pytest
from conftest import ROOT
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import FunctionModel

from examples import explain, review_loop


def test_minimal_example_direct_equals_cli(cli):
    prompts = []

    def respond(messages, info):
        prompts.extend(
            part.content for message in messages for part in message.parts if isinstance(part, UserPromptPart)
        )
        return ModelResponse(parts=[TextPart("A loom weaves cloth.")])

    assert explain.explainer.name == "explainer" and explain.explainer.model is None
    with explain.explainer.override(model=FunctionModel(respond)):
        direct = asyncio.run(explain.workflow("a loom"))
    assert prompts == ["Explain a loom."]
    args = ("step", f"{ROOT / 'examples/explain.py'}:workflow", "--inputs", '{"topic": "a loom"}')
    call = cli.calls(cli.command(*args, code=2))[0]
    assert call["agent"] == "explainer" and cli.user(call) == prompts[0]
    cli.settle(call, direct)
    assert cli.result(cli.command(*args)) == direct == "A loom weaves cloth."
    assert len(list(cli.store.glob("*/commit.json"))) == 1


@pytest.mark.parametrize("max_rounds,topics", [(0, []), (-1, ["a"])])
def test_invalid_review_rounds_make_no_requests_direct_or_cli(cli, max_rounds, topics):
    requests = []

    def unexpected(messages, info):
        requests.append(messages)
        raise AssertionError("no agent request should be made")

    with ExitStack() as stack:
        for agent in (review_loop.writer, review_loop.reviewer, review_loop.summarizer):
            stack.enter_context(agent.override(model=FunctionModel(unexpected)))
        # Keep both direct input shapes; the CLI needs only representative cases.
        for direct_topics in ([], ["a"]):
            with pytest.raises(ValueError, match="max_rounds must be positive"):
                asyncio.run(review_loop.workflow(direct_topics, max_rounds))
        with pytest.raises(ValueError, match="max_rounds must be positive"):
            asyncio.run(review_loop.draft_and_review("a", max_rounds))
    assert requests == []
    output = cli.command(
        "step",
        f"{ROOT / 'examples/review_loop.py'}:workflow",
        "--inputs",
        json.dumps({"topics": topics, "max_rounds": max_rounds}),
        code=1,
    )
    assert "ValueError: max_rounds must be positive" in output.stderr
    assert not list(cli.store.glob("*/call.json"))
    assert json.loads((cli.store / "open.json").read_text()) == []


def test_last_rejection_has_no_discarded_rewrite_direct_or_cli(cli):
    requests = []
    verdict = {"accepted": False, "problems": ["be concrete", "add an example"]}

    def model(name):
        def respond(messages, info):
            prompt = next(
                part.content
                for message in messages
                for part in message.parts
                if isinstance(part, UserPromptPart)
            )
            requests.append((name, prompt))
            part = (
                ToolCallPart(info.output_tools[0].name, verdict) if name == "reviewer" else TextPart("draft")
            )
            return ModelResponse(parts=[part])

        return FunctionModel(respond)

    expected = [
        ("writer", "Write one paragraph about a."),
        ("reviewer", "Review this paragraph about a.\n\ndraft"),
    ]
    with ExitStack() as stack:
        for name in ("writer", "reviewer", "summarizer"):
            stack.enter_context(getattr(review_loop, name).override(model=model(name)))
        for max_rounds in (1, 2):
            requests.clear()
            if max_rounds == 2:
                expected += [
                    (
                        "writer",
                        "Rewrite this paragraph about a to fix:\nbe concrete\nadd an example\n\ndraft",
                    ),
                    ("reviewer", "Review this paragraph about a.\n\ndraft"),
                ]
            with pytest.raises(RuntimeError, match="out of attempts for a"):
                asyncio.run(review_loop.workflow(["a"], max_rounds))
            assert requests == expected, max_rounds

    # Two rounds cover both a real rewrite and rejection at the final CLI boundary.
    max_rounds = 2
    args = (
        "step",
        f"{ROOT / 'examples/review_loop.py'}:workflow",
        "--inputs",
        json.dumps({"topics": ["a"], "max_rounds": max_rounds}),
    )
    observed = []
    for name, prompt in expected:
        call = cli.calls(cli.command(*args, code=2))[0]
        observed.append((call["agent"], cli.user(call)))
        cli.settle(
            call,
            json.dumps(verdict) if name == "reviewer" else "draft",
            filename="answer.json" if name == "reviewer" else "answer.md",
        )
    assert observed == expected
    output = cli.command(*args, code=1)
    assert "out of attempts for a" in output.stderr
    assert len(list(cli.store.glob("*/call.json"))) == 2 * max_rounds
    assert len(list(cli.store.glob("*/commit.json"))) == 2 * max_rounds
    assert json.loads((cli.store / "open.json").read_text()) == []
