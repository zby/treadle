"""bl step library: StepModel (a Pydantic AI model answered from the bl store), `cached` operations, QuietLoop.

The cache unit for agents is one model request; for operations, one call of a `@cached` function.
Store: <store>/<key>/call.json, prompt.md (agents), then answer.json | answer.md | failure.txt.

Rule: code between agent calls must be deterministic and side-effect free, except through `@cached`
operations (it is re-executed on every step), and the workflow awaits only agent runs, cached
operations, gathers/tasks of them, timers (asyncio.sleep) and executor threads (asyncio.to_thread).
"""

import asyncio
import functools
import hashlib
import inspect
import json
import os
import sys
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # the banner would land in the orchestrator's stderr

from pydantic import TypeAdapter
from pydantic_core import to_jsonable_python

from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import (InstructionPart, ModelRequest, ModelResponse, RetryPromptPart, SystemPromptPart,
                                  TextPart, ToolCallPart, ToolReturnPart, UserPromptPart)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.profiles import ModelProfile


class BlCallFailed(ModelAPIError):
    """A call the orchestrator marked failed with `bl fail`. Subclasses the error a provider failure raises."""


# ---------------------------------------------------------------- prompt rendering


def render_user_content(content):
    if isinstance(content, str):
        return content
    return "\n\n".join(c if isinstance(c, str) else f"[{type(c).__name__} not representable as text]" for c in content)


def instructions_of(messages, params: ModelRequestParameters):
    if params.instruction_parts:
        return InstructionPart.join(params.instruction_parts)
    return next((m.instructions for m in reversed(messages) if isinstance(m, ModelRequest) and m.instructions), None)


def output_schema(params: ModelRequestParameters):
    """JSON schema of a structured answer, or None for a text answer."""
    if params.output_tools:
        return params.output_tools[0].parameters_json_schema
    if params.output_object is not None:  # NativeOutput / PromptedOutput: the answer is JSON text (untested)
        return params.output_object.json_schema
    return None


def render_prompt(agent_name, messages, params: ModelRequestParameters):
    """Everything the request would send, as markdown. Volatile fields (timestamps, ids) are left out."""
    out = [f"# Call to agent `{agent_name}`"]
    if instructions := instructions_of(messages, params):
        out.append(f"## Instructions\n\n{instructions}")
    for message in messages:
        for part in message.parts:
            if isinstance(part, SystemPromptPart):
                out.append(f"## System prompt\n\n{part.content}")
            elif isinstance(part, UserPromptPart):
                out.append(f"## User prompt\n\n{render_user_content(part.content)}")
            elif isinstance(part, ToolReturnPart):
                out.append(f"## Tool `{part.tool_name}` returned\n\n{part.model_response_str()}")
            elif isinstance(part, RetryPromptPart):
                out.append(f"## Retry request\n\n{part.model_response()}")
            elif isinstance(part, TextPart):
                out.append(f"## Your earlier answer\n\n{part.content}")
            elif isinstance(part, ToolCallPart):
                out.append(f"## Your earlier call of `{part.tool_name}`\n\n{part.args_as_json_str()}")
            else:
                out.append(f"## [{part.part_kind} part omitted]")
    if params.function_tools:
        lines = [f"- `{t.name}`: {t.description or ''}".rstrip() for t in params.function_tools]
        out.append("## Tools (unavailable)\n\nThe agent has these tools, but bl does not run them. "
                   "Answer without them:\n\n" + "\n".join(lines))
    if (schema := output_schema(params)) is not None:
        out.append("## Answer format\n\nAnswer with one JSON object matching this schema "
                   f"(nothing else in the file):\n\n```json\n{json.dumps(schema, indent=2)}\n```")
    else:
        out.append("## Answer format\n\nAnswer with plain text; the whole file is the answer.")
    return "\n\n".join(out) + "\n"


# ---------------------------------------------------------------- store


def sha(*parts):
    return hashlib.sha256("\n".join(map(str, parts)).encode()).hexdigest()


def write_new(path, text):
    """Atomically create `path`; False if it already exists (never overwrites)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    try:
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    finally:
        tmp.unlink()


class StepModel(Model):
    """A Pydantic AI model whose answers come from the bl store. One request = one cached call."""

    def __init__(self, agent_name, replay):
        super().__init__(profile=ModelProfile(supports_json_schema_output=True, supports_json_object_output=True))
        self.agent_name, self.replay = agent_name, replay

    @property
    def model_name(self):
        return f"bl-step:{self.agent_name}"

    @property
    def system(self):
        return "bl-step"

    async def request(self, messages, model_settings, model_request_parameters):
        _, params = self.prepare_request(model_settings, model_request_parameters)
        return await self.replay.respond(self, messages, params)


class Replay:
    """Per-step state: occurrence counters and the open calls."""

    def __init__(self, store, workflow_path=None):
        self.store, self.workflow_path = Path(store), workflow_path
        self.store.mkdir(parents=True, exist_ok=True)
        self.seen, self.open = Counter(), {}

    def key(self, *identity):
        """Content key plus occurrence index: the n-th identical call in one replay gets index n."""
        content = sha(*identity)
        occurrence = self.seen[content]
        self.seen[content] += 1
        return sha(*identity[:1], occurrence, *identity[1:]), occurrence

    async def respond(self, model, messages, params):
        name = model.agent_name
        prompt = render_prompt(name, messages, params)
        key, occurrence = self.key(name, prompt)  # same key as before: sha(name, occurrence, prompt)
        d = self.store / key
        if (d / "answer.json").exists():
            args = (d / "answer.json").read_text()
            if params.output_tools:  # Pydantic AI validates the tool arguments into the output type
                return ModelResponse(parts=[ToolCallPart(params.output_tools[0].name, args)], model_name=model.model_name)
            return ModelResponse(parts=[TextPart(args)], model_name=model.model_name)  # native/prompted output
        if (d / "answer.md").exists():
            return ModelResponse(parts=[TextPart((d / "answer.md").read_text())], model_name=model.model_name)
        if (d / "failure.txt").exists():
            reason = (d / "failure.txt").read_text().strip()
            raise BlCallFailed(model.model_name, f"call {key[:12]} ({name}) failed: {reason}")
        self.suspend(key, name, occurrence, prompt, output_schema(params) is not None)
        await asyncio.get_running_loop().create_future()  # never resolved: this branch waits

    def suspend(self, key, agent_name, occurrence, prompt, typed):
        d = self.store / key
        d.mkdir(parents=True, exist_ok=True)
        call = {"kind": "agent", "agent": agent_name, "workflow": str(self.workflow_path),
                "occurrence": occurrence, "typed": typed}
        new = write_new(d / "call.json", json.dumps(call, indent=2) + "\n")
        write_new(d / "prompt.md", prompt)
        self.open[key] = (agent_name, d / "prompt.md", new)  # printed together once nothing can proceed


# ---------------------------------------------------------------- quiescence


class QuietLoop(asyncio.SelectorEventLoop):
    """Event loop that notices when nothing can run: no callback queued, no timer, no executor job.

    Only public loop methods are overridden (call_soon, call_at, run_in_executor). Socket I/O awaited
    directly on the loop (no timer, no thread) is invisible to it, except inside a running `@cached` op.
    """

    def __init__(self):
        super().__init__()
        self.live, self.jobs, self.idle = set(), 0, None

    def _tracked(self, schedule, callback, args, context):
        handle = None

        def run(*a):
            self.live.discard(handle)
            try:
                callback(*a)
            finally:
                self._check()

        handle = schedule(run, *args, context=context)
        self.live.add(handle)
        return handle

    def call_soon(self, callback, *args, context=None):
        return self._tracked(super().call_soon, callback, args, context)

    def call_at(self, when, callback, *args, context=None):  # call_later and sleep go through here
        return self._tracked(lambda cb, *a, context: super(QuietLoop, self).call_at(when, cb, *a, context=context),
                             callback, args, context)

    def run_in_executor(self, executor, func, *args):  # asyncio.to_thread goes through here
        future = super().run_in_executor(executor, func, *args)
        self.jobs += 1
        future.add_done_callback(self._job_done)
        return future

    def _job_done(self, _future):
        self.jobs -= 1
        self._check()

    def _check(self):
        self.live = {h for h in self.live if not h.cancelled()}
        if self.idle is not None and not self.idle.done() and not self.live and not self.jobs:
            self.idle.set_result(None)


# ---------------------------------------------------------------- cached operations

ACTIVE: ContextVar[Replay | None] = ContextVar("bl_active_replay", default=None)


@contextmanager
def use_store(store):
    """Direct runs: cache `@cached` operations in `store` (a fresh replay; agent calls are not cached)."""
    token = ACTIVE.set(Replay(store))
    try:
        yield
    finally:
        ACTIVE.reset(token)


def cached(fn=None, *, name=None):
    """Record a side-effecting, expensive or nondeterministic operation; replays get the recorded result.

    Key: sha256(operation name, occurrence index, JSON of the arguments). The result is stored as JSON
    and, when the function has a return annotation, validated back into that type; the first execution
    returns the same round-tripped value a replay will. Exceptions are not recorded: the operation runs
    again on the next step. Recording happens after the operation, so it is at-least-once.
    Without an active store (plain direct run) the function is simply called.
    """
    if fn is None:
        return lambda f: cached(f, name=name)
    op = name or f"{fn.__module__}.{fn.__qualname__}"
    adapter = TypeAdapter(fn.__annotations__["return"]) if "return" in fn.__annotations__ else None

    def lookup(args, kwargs):
        replay = ACTIVE.get()
        if replay is None:
            return None, None, None
        arguments = json.dumps(to_jsonable_python({"args": args, "kwargs": kwargs}), sort_keys=True)
        key, occurrence = replay.key("op:" + op, arguments)
        d = replay.store / key
        if (d / "answer.json").exists():
            return d, True, decode(json.loads((d / "answer.json").read_text()))
        d.mkdir(exist_ok=True)
        call = {"kind": "op", "op": op, "occurrence": occurrence, "arguments": json.loads(arguments)}
        if not write_new(d / "call.json", json.dumps(call, indent=2) + "\n"):
            print(f"bl: re-running {op} ({key[:12]}): an earlier attempt recorded no result", file=sys.stderr)
        return d, False, None

    def decode(value):
        return adapter.validate_python(value) if adapter else value

    def record(d, result):
        stored = to_jsonable_python(result)  # TypeError for values with no JSON form (and no annotation)
        write_new(d / "answer.json", json.dumps(stored) + "\n")
        return decode(stored)

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def run_async(*args, **kwargs):
            d, hit, value = lookup(args, kwargs)
            if hit:
                return value
            loop = asyncio.get_running_loop()
            if not isinstance(loop, QuietLoop):
                result = await fn(*args, **kwargs)
                return record(d, result) if d else result
            loop.jobs += 1  # its own I/O may be invisible to the loop: not quiescent while it runs
            try:
                result = await fn(*args, **kwargs)
            finally:
                loop.jobs -= 1
            return record(d, result) if d else result
        return run_async

    @functools.wraps(fn)
    def run_sync(*args, **kwargs):
        d, hit, value = lookup(args, kwargs)
        if hit:
            return value
        result = fn(*args, **kwargs)
        return record(d, result) if d else result
    return run_sync
