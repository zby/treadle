"""Focused runtime regressions from the reopened Stage 1 review."""

import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
import types
from contextlib import ExitStack
from pathlib import Path

import pytest
from conftest import WORKFLOWS
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from treadle import StoreError, cached, use_store


def test_sync_instruction_single_waits_for_callback_and_replays(cli, tmp_path):
    # A file rendezvous holds the actual callback open until this process
    # releases it. This is not a sleep-duration test of quiescence.
    gate = tmp_path / "callback"
    inputs = {"single": True, "gate": str(gate)}
    process = subprocess.Popen(
        cli.argv("step", f"{WORKFLOWS}:sync_callbacks", "--inputs", json.dumps(inputs)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not gate.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.005)
        assert gate.exists() and process.poll() is None
        Path(str(gate) + ".release").write_text("proceed")
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 2, (stdout, stderr)
        first = cli.calls(subprocess.CompletedProcess([], 2, stdout, stderr))[0]
    finally:
        Path(str(gate) + ".release").write_text("proceed")
        if process.poll() is None:
            process.kill()
            process.communicate()
    assert first["agent"] == "sync-instructions"
    cli.settle(first, "first\n")
    follow = cli.calls(cli.step("sync_callbacks", inputs=inputs))[0]
    assert cli.user(follow) == "after sync-instructions: first\n"
    cli.settle(follow, "finished\n")
    completed = cli.step("sync_callbacks", inputs=inputs, code=0)
    assert cli.result(completed) == "finished\n"
    assert cli.step("sync_callbacks", inputs=inputs, code=0).stdout == completed.stdout


def test_sync_callback_gather_frontiers_and_native_newline_parity(cli):
    # All four callback sites run under the same gather. The output validator
    # and output function must finish before their downstream calls can appear.
    first_output = cli.step("sync_callbacks")
    first = cli.calls(first_output)
    assert {call["agent"] for call in first} == {
        "sync-instructions",
        "sync-system",
        "sync-validator",
        "sync-output",
    }
    assert len(first) == 4
    assert cli.step("sync_callbacks").stdout == first_output.stdout
    for call in first:
        prompt = Path(call["prompt"]).read_text()
        if call["agent"] == "sync-instructions":
            assert "Synchronous instructions." in prompt
        if call["agent"] == "sync-system":
            assert "Synchronous system prompt." in prompt
        typed = call["agent"] == "sync-output"
        cli.settle(
            call,
            '{"value":"value\\n"}' if typed else "value\n",
            filename="answer.json" if typed else "answer.md",
        )
    second_output = cli.step("sync_callbacks")
    second = cli.calls(second_output)
    assert len(second) == 4
    expected_prompts = [
        "after sync-instructions: value\n",
        "after sync-system: value\n",
        "after sync-validator: VALUE\n",
        "after sync-output: function:value\n",
    ]
    assert sorted(cli.user(call) for call in second) == sorted(expected_prompts)
    assert cli.step("sync_callbacks").stdout == second_output.stdout
    for call in second:
        cli.settle(call, cli.user(call) + "\n")
    completed = cli.step("sync_callbacks", code=0)
    expected = [prompt + "\n" for prompt in expected_prompts]
    assert cli.result(completed) == expected
    assert cli.step("sync_callbacks", code=0).stdout == completed.stdout

    # Run the same workflow directly in Pydantic AI with an offline model.
    # Text includes the final newline, rather than comparing trimmed values.
    spec = importlib.util.spec_from_file_location("native_correctness_workflow", WORKFLOWS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    downstream = []

    def answer(messages, info):
        if info.output_tools:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"value": "value\n"})])
        prompt = messages[-1].parts[-1].content
        if prompt.startswith("after "):
            downstream.append(prompt)
            return ModelResponse(parts=[TextPart(prompt + "\n")])
        return ModelResponse(parts=[TextPart("value\n")])

    with ExitStack() as stack:
        for agent in (
            module.instructions_agent,
            module.system_agent,
            module.validator_agent,
            module.output_agent,
            module.text,
        ):
            stack.enter_context(agent.override(model=FunctionModel(answer)))
        assert asyncio.run(module.sync_callbacks()) == expected
    assert sorted(downstream) == sorted(expected_prompts)


def test_caught_agent_integrity_is_fatal_for_answers_and_auxiliary_files(cli):
    call = cli.calls(cli.step("caught_integrity"))[0]
    cli.write(call, "answer\n")
    directory = cli.directory(call)
    (directory / "notes.md").write_text("notes\n")
    cli.commit(call, "notes.md")
    _assert_caught_corruption(cli, directory, "agent", "answer.md")


def test_caught_operation_integrity_is_fatal_for_answers_and_auxiliary_files(cli):
    assert cli.result(cli.step("caught_integrity", inputs={"kind": "op"}, code=0)) == 42
    directory = next(cli.store.glob("*/commit.json")).parent
    # Operations normally attest only answer.json. Extend the on-disk attestation
    # to exercise auxiliary-file verification on this replay path as well.
    notes = directory / "notes.md"
    notes.write_text("notes\n")
    manifest = directory / "commit.json"
    commit = json.loads(manifest.read_text())
    commit["files"][notes.name] = hashlib.sha256(notes.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(commit))
    _assert_caught_corruption(cli, directory, "op", "answer.json")


def _assert_caught_corruption(cli, directory, kind, answer):
    # Four distinct integrity faults, not a cross-product of renderer and
    # workflow variants. Alternate return/wait after the broad except handler.
    for index, (name, missing) in enumerate(
        [(answer, False), (answer, True), ("notes.md", False), ("notes.md", True)]
    ):
        path = directory / name
        original = path.read_bytes()
        if missing:
            path.unlink()
        else:
            path.write_bytes(original + b"edited")
        try:
            failed = cli.step(
                "caught_integrity",
                inputs={"kind": kind, "wait_after": bool(index % 2)},
                extra=("--json",),
                code=1,
            )
            records = [json.loads(line) for line in failed.stdout.splitlines()]
            assert [record["type"] for record in records] == ["error"], records
            assert str(path) in records[0]["error"]
            assert ("missing" if missing else "hash mismatch") in records[0]["error"]
            assert json.loads((cli.store / "open.json").read_text()) == []
            assert not failed.stderr
        finally:
            path.write_bytes(original)


def test_use_store_raises_at_boundary_even_if_async_operation_error_is_caught(tmp_path):
    executed = []

    @cached(name="direct-integrity")
    async def operation() -> int:
        executed.append(1)
        return 42

    async def workflow():
        try:
            return await operation()
        except Exception:
            return "caught"

    with use_store(tmp_path):
        assert asyncio.run(workflow()) == 42
    answer = next(tmp_path.glob("*/answer.json"))
    answer.unlink()
    with pytest.raises(StoreError, match="committed file missing"):
        with use_store(tmp_path):
            assert asyncio.run(workflow()) == "caught"
    assert executed == [1]
    assert asyncio.run(workflow()) == 42  # ACTIVE was restored even on fatal exit.


def test_finally_cached_operations_warn_complete_replay_and_fail_fatally(cli, tmp_path):
    inputs = {"path": str(tmp_path / "cleanup")}
    first = cli.step("cleanup_finally", inputs=inputs)
    call = cli.calls(first)[0]
    assert Path(inputs["path"]).read_text() == "attempted"
    second = cli.step("cleanup_finally", inputs=inputs, extra=("--json",))
    records = [json.loads(line) for line in second.stdout.splitlines()]
    assert [record["type"] for record in records] == ["warning", "call", "waiting"]
    assert "outcome is uncertain" in records[0]["warning"]
    op_answer = next(cli.store.glob("*/answer.json"))
    original = op_answer.read_bytes()
    op_answer.unlink()
    failed = cli.step("cleanup_finally", inputs=inputs, extra=("--json",), code=1)
    records = [json.loads(line) for line in failed.stdout.splitlines()]
    assert [record["type"] for record in records] == ["error"]
    assert str(op_answer) in records[0]["error"]
    assert json.loads((cli.store / "open.json").read_text()) == []
    op_answer.write_bytes(original)
    cli.settle(call, "done\n")
    completed = cli.step("cleanup_finally", inputs=inputs, code=0)
    assert cli.result(completed) == "done\n"
    assert cli.step("cleanup_finally", inputs=inputs, code=0).stdout == completed.stdout


def test_uncaught_finally_exception_does_not_publish_waiting_frontier(cli, tmp_path):
    failed = cli.step("cleanup_finally", inputs={"path": str(tmp_path / "cleanup"), "catch": False}, code=1)
    assert "cleanup first attempt failed" in failed.stderr
    assert not failed.stdout
    assert json.loads((cli.store / "open.json").read_text()) == []


def test_agent_run_in_cancellation_finally_does_not_extend_frontier(cli):
    # In the locked Pydantic AI version, cancellation interrupts this attempted
    # cleanup run before it reaches the model adapter. It is not a cleanup task.
    calls = cli.calls(cli.step("agent_in_finally"))
    assert [cli.user(call) for call in calls] == ["pending"]
    assert len(list(cli.store.glob("*/prompt.md"))) == 1


def test_cancelled_sync_callback_is_joined_and_its_caught_integrity_error_is_fatal(cli):
    # Threading Events ensure the callback is running before cancellation. Its
    # cached call runs after release, even though its asyncio waiter is cancelled.
    assert cli.result(cli.step("cancel_sync_callback", code=0)) == "cancelled"
    answer = next(cli.store.glob("*/answer.json"))
    assert json.loads(answer.read_text()) == 17
    answer.write_text("edited")
    failed = cli.step("cancel_sync_callback", code=1)
    assert str(answer) in failed.stderr and "hash mismatch" in failed.stderr
    assert not failed.stdout
    assert json.loads((cli.store / "open.json").read_text()) == []


def test_loader_dangerous_name_sibling_imports_annotations_and_state_restoration(cli, tmp_path, capsys):
    sibling = tmp_path / "treadle_probe_sibling.py"
    sibling.write_text("VALUE = 9\n")
    workflow = tmp_path / "types.py"
    workflow.write_text("""from __future__ import annotations
import types
from dataclasses import dataclass
from typing import get_type_hints
from pydantic_ai import Agent
from treadle import cached

@dataclass
class Payload:
    value: int

@cached(name="loader.payload")
def payload() -> Payload:
    return Payload(9)

agent = Agent("test", name="loader", output_type=Payload)

async def workflow():
    from treadle_probe_sibling import VALUE
    assert types.SimpleNamespace(value=VALUE).value == 9
    assert get_type_hints(Payload) == {"value": int}
    assert isinstance(payload(), Payload)
    result = (await agent.run("payload")).output
    return {"value": result.value, "typed": isinstance(result, Payload)}
""")
    # Exercise two full step lifetimes in this interpreter as well as a real
    # CLI replay. Check public outcomes and global import state, not loader helpers.
    from treadle.cli import main

    previous_path = sys.path[:]
    previous_types = sys.modules["types"]
    module_names = set(sys.modules)
    args = ["step", f"{workflow}:workflow", "--store", str(cli.store)]
    try:
        assert main(args) == 2
        output = capsys.readouterr()
        call = cli.calls(subprocess.CompletedProcess([], 2, output.out, output.err))[0]
        assert sys.path == previous_path and sys.modules["types"] is previous_types is types
        assert not (set(sys.modules) - module_names) & {
            name for name in sys.modules if name.startswith("_treadle_workflow_")
        }
        cli.settle(call, '{"value":9}', filename="answer.json")
        assert main(args) == 0
        output = capsys.readouterr()
        assert json.loads(output.out.splitlines()[0].removeprefix("result ")) == {"value": 9, "typed": True}
        assert sys.path == previous_path and sys.modules["types"] is types
        replay = cli.command(*args[:-2], code=0)
        assert replay.stdout == output.out
        workflow.write_text("raise RuntimeError('load failed')\n")
        assert main(args) == 1
        assert "load failed" in capsys.readouterr().err
        assert sys.path == previous_path and sys.modules["types"] is types
        assert not any(name.startswith("_treadle_workflow_") for name in set(sys.modules) - module_names)
    finally:
        sys.modules.pop("treadle_probe_sibling", None)
