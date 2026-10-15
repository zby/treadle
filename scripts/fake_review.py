"""Offline example driver: uv run python scripts/fake_review.py --store DIR.

Use --direct to run the SAME workflow with Pydantic AI FunctionModels instead.
No provider SDKs, credentials, harness or real model calls are required.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.function import FunctionModel

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "review_loop.py"
INPUTS = {"topics": ["a", "b"], "max_rounds": 3}


def answer(agent, prompt):
    match = re.search(r"about (\w+)", prompt)
    topic = match[1] if match else None
    if agent == "writer":
        return f"Paragraph about {topic}" + (" (revised)." if prompt.startswith("Rewrite") else ".")
    if agent == "reviewer":
        rejected = topic == "b" and "(revised)" not in prompt
        return {"accepted": not rejected, "problems": ["too vague", "add an example"] if rejected else []}
    if agent == "summarizer":
        return f"SUMMARY: {prompt.count('Paragraph about')} paragraphs."
    raise ValueError(agent)


def model_for(name):
    def respond(messages, info):
        prompt = next(
            part.content
            for message in reversed(messages)
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        value = answer(name, prompt)
        part = ToolCallPart(info.output_tools[0].name, value) if info.output_tools else TextPart(value)
        return ModelResponse(parts=[part])

    return FunctionModel(respond)


def direct():
    spec = importlib.util.spec_from_file_location("review_loop", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    with override_allow_model_requests(False), ExitStack() as stack:
        for name in ("writer", "reviewer", "summarizer"):
            stack.enter_context(getattr(module, name).override(model=model_for(name)))
        return asyncio.run(module.workflow(**INPUTS))


def command(*args):
    return subprocess.run(
        [sys.executable, "-m", "treadle.cli", *map(str, args), "--json"],
        text=True,
        capture_output=True,
        check=False,
    )


def drive(store):
    for _ in range(20):
        step = command("step", f"{EXAMPLE}:workflow", "--inputs", json.dumps(INPUTS), "--store", store)
        records = [json.loads(line) for line in step.stdout.splitlines()]
        if step.returncode == 0:
            if [record["type"] for record in records] != ["result", "done"]:
                raise RuntimeError(f"bad step protocol: {step.stdout}")
            return records[0]["result"]
        if step.returncode != 2:
            raise RuntimeError(step.stdout or step.stderr)
        calls = [record for record in records if record["type"] == "call"]
        if not calls or records[-1] != {"type": "waiting", "open": len(calls)}:
            raise RuntimeError(f"bad step protocol: {step.stdout}")
        for call in calls:
            claimed = command("claim", call["key"], "--worker", "fake:review-driver", "--store", store)
            if claimed.returncode:
                raise RuntimeError(claimed.stdout or claimed.stderr)
            prompt_file = Path(call["prompt"])
            prompt = prompt_file.read_text().split("## User prompt\n\n", 1)[1].split("\n\n## ", 1)[0]
            value = answer(call["agent"], prompt)
            typed = isinstance(value, dict)
            (prompt_file.parent / ("answer.json" if typed else "answer.md")).write_text(
                json.dumps(value) if typed else value
            )
            committed = command("commit", call["key"], "--worker", "fake:review-driver", "--store", store)
            if committed.returncode:
                raise RuntimeError(committed.stdout or committed.stderr)
    raise RuntimeError("fake driver exceeded 20 steps")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--store", type=Path)
    group.add_argument("--direct", action="store_true")
    args = parser.parse_args()
    print(json.dumps(direct() if args.direct else drive(args.store), sort_keys=True))
