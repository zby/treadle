"""Internal adapter using Pydantic AI's public Model API, and versioned call keys."""

import asyncio
import json
import shlex
import threading
from collections import Counter
from contextlib import contextmanager

from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import (
    InstructionPart,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.profiles import ModelProfile

from .store import Store, StoreError, atomic_write, digest, json_text, safe_path

# Stable data. Bump when changing semantic prompt rendering or identity encoding.
FORMAT_VERSION = "treadle-prompt-v1"
ROOT_SCOPE = ""


def output_schema(params):
    if len(params.output_tools) > 1 or (params.output_tools and params.allow_text_output):
        raise StoreError("version 1 requires one structured output type, or plain text (not a union)")
    if params.output_tools:
        return params.output_tools[0].parameters_json_schema
    if params.output_object is not None:
        return params.output_object.json_schema
    return None


def render_prompt(name, messages, params):
    """Render semantic content only: no store paths, timestamps or random IDs.

    Unsupported message content is refused, not omitted from answer identity.
    Version 1 renders function tools as unavailable and never returns tool calls
    for them. Native tools and multimodal inputs are not supported.
    """
    if params.native_tools:
        raise StoreError("native tools are unsupported in version 1")
    out = [f"# Call to agent `{name}`", f"Prompt format: {FORMAT_VERSION}"]
    instructions = (
        InstructionPart.join(params.instruction_parts)
        if params.instruction_parts is not None
        else next(
            (m.instructions for m in reversed(messages) if isinstance(m, ModelRequest) and m.instructions),
            None,
        )
    )
    if instructions:
        out.append(f"## Instructions\n\n{instructions}")
    for message in messages:
        for part in message.parts:
            if isinstance(part, SystemPromptPart):
                out.append(f"## System prompt\n\n{part.content}")
            elif isinstance(part, UserPromptPart):
                content = part.content
                if not isinstance(content, str):
                    if not all(isinstance(item, str) for item in content):
                        raise StoreError("multimodal user content is unsupported in version 1")
                    # Preserve boundaries, including empty strings.
                    content = json.dumps(content, ensure_ascii=False)
                out.append(f"## User prompt\n\n{content}")
            elif isinstance(part, ToolReturnPart):
                out.append(f"## Tool `{part.tool_name}` returned\n\n{part.model_response_str()}")
            elif isinstance(part, RetryPromptPart):
                out.append(f"## Retry request\n\n{part.model_response()}")
            elif isinstance(part, TextPart):
                out.append(f"## Your earlier answer\n\n{part.content}")
            elif isinstance(part, ToolCallPart):
                out.append(f"## Your earlier call of `{part.tool_name}`\n\n{part.args_as_json_str()}")
            else:
                raise StoreError(f"unsupported message part: {part.part_kind}")
    if params.function_tools:
        tools = [
            {"name": t.name, "description": t.description, "schema": t.parameters_json_schema}
            for t in params.function_tools
        ]
        out.append(
            "## Tools (unavailable)\n\nThese tools are unavailable under treadle. Answer without them:\n\n"
            + json_text(tools)
        )
    schema = output_schema(params)
    if schema is not None:
        out.append(
            "## Answer format\n\nOne JSON object matching this schema (no fences or commentary):\n\n```json\n"
            + json_text(schema)
            + "```"
        )
    else:
        out.append("## Answer format\n\nPlain text; the whole file is the answer.")
    return "\n\n".join(out) + "\n"


def delivery_instructions(store, key, typed):
    directory = store.directory(key)
    answer = directory / ("answer.json" if typed else "answer.md")
    command = shlex.join(["treadle", "commit", key, "--worker", "WORKER_ID", "--store", str(store.path)])
    return (
        f"\n## Delivery\n\nCall key: {key}\n\n"
        f"Draft your answer at this absolute path: {answer}\n\n"
        f"For refusal or failure, write {directory / 'failure.md'} instead, with the reason. "
        "Write exactly one answer or failure file. Drafts are ignored until committed.\n\n"
        f"You may write additional files inside {directory}; list their relative paths after the key when committing. "
        "No paths outside this directory or symlinks may be committed.\n\n"
        "When finished, replace WORKER_ID with your opaque worker/session ID and run:\n\n"
        f"```sh\n{command}\n```\n\n"
        "Answers are write-once. Do not edit or delete committed files. "
        "Repository edits outside this directory need separate version-control discipline.\n"
    )


class CallFailed(ModelAPIError):
    """A worker committed failure.md instead of an answer."""


class StepModel(Model):
    def __init__(self, agent_name, replay):
        super().__init__(
            profile=ModelProfile(supports_json_schema_output=True, supports_json_object_output=True)
        )
        self.agent_name = agent_name
        self.replay = replay

    @property
    def model_name(self):
        return f"treadle-step:{self.agent_name}"

    @property
    def system(self):
        return "treadle-step"

    async def request(self, messages, model_settings, model_request_parameters):
        _, params = self.prepare_request(model_settings, model_request_parameters)
        return await self.replay.respond(self, messages, params)


class Replay:
    def __init__(self, store, *, warn=None):
        self.store = store if isinstance(store, Store) else Store(store)
        self.warn = warn
        self.seen = Counter()
        self.counter_lock = threading.Lock()  # cached calls can arrive via to_thread
        self.open = {}
        self.fatal = None
        self.tearing_down = False

    def raise_if_failed(self):
        """Integrity failures survive workflow exception handlers and cancellation."""
        with self.counter_lock:
            error = self.fatal
        if error is not None:
            raise error

    @contextmanager
    def checking_store(self):
        """Guard store I/O, not user operations or catchable worker refusals."""
        self.raise_if_failed()
        try:
            yield
        except Exception as exc:
            error = exc if isinstance(exc, StoreError) else StoreError(f"{type(exc).__name__}: {exc}")
            with self.counter_lock:
                if self.fatal is None:
                    self.fatal = error
            if error is exc:
                raise
            raise error from exc

    def key(self, kind, name, content):
        identity = [FORMAT_VERSION, ROOT_SCOPE, kind, name, content]
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self.counter_lock:
            occurrence = self.seen[encoded]
            self.seen[encoded] += 1
        key = digest(
            json.dumps(
                [*identity, occurrence], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        )
        return key, occurrence

    async def respond(self, model, messages, params):
        with self.checking_store():
            if self.tearing_down:
                raise StoreError("agent calls during step teardown are unsupported")
        prompt = render_prompt(model.agent_name, messages, params)
        key, occurrence = self.key("agent", model.agent_name, prompt)
        typed = output_schema(params) is not None
        call = {
            "kind": "agent",
            "agent": model.agent_name,
            "occurrence": occurrence,
            "format_version": FORMAT_VERSION,
            "scope": ROOT_SCOPE,
            "typed": typed,
        }
        with self.checking_store():
            directory = self.store.directory(key, create=True)
            atomic_write(safe_path(directory, "call.json"), json_text(call))
            atomic_write(
                safe_path(directory, "prompt.md"), prompt + delivery_instructions(self.store, key, typed)
            )
            committed = self.store.committed(directory)
            if committed is not None:
                files, answer = committed
                text = files[answer].decode()
        if committed is not None:
            if answer == "failure.md":
                raise CallFailed(model.model_name, f"call {key} ({model.agent_name}) failed: {text.strip()}")
            if typed and params.output_tools:
                return ModelResponse(
                    parts=[ToolCallPart(params.output_tools[0].name, text, tool_call_id=f"treadle-{key}")],
                    model_name=model.model_name,
                )
            return ModelResponse(parts=[TextPart(text)], model_name=model.model_name)
        self.open[key] = {"key": key, "agent": model.agent_name, "prompt": str(directory / "prompt.md")}
        try:
            await asyncio.get_running_loop().create_future()
        finally:
            # A workflow may cancel a branch intentionally (not only at step end).
            self.open.pop(key, None)
