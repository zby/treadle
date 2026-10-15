import asyncio
import json
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from treadle import cached, use_store


def test_cached_requires_explicit_stable_name():
    with pytest.raises(TypeError):
        cached()
    with pytest.raises(ValueError):
        cached(name="")


def test_direct_store_roundtrip_annotations_and_stable_name(tmp_path):
    calls = []

    @cached(name="clock")
    def clock() -> tuple[datetime, int]:
        calls.append(1)
        return datetime.now(timezone.utc), 1

    path = tmp_path / "direct"
    with use_store(path):
        first = clock()
    assert isinstance(first, tuple) and isinstance(first[0], datetime)

    # Renaming the Python function preserves the operation's explicit identity.
    @cached(name="clock")
    def renamed() -> tuple[datetime, int]:
        raise AssertionError("cache was not reused")

    with use_store(path):
        second = renamed()
    assert first == second and calls == [1]
    clock()  # outside use_store, runs plainly
    assert calls == [1, 1]
    call = json.loads(next(path.glob("*/call.json")).read_text())
    assert call["scope"] == "" and call["occurrence"] == 0


def test_argument_spelling_is_durable_identity(tmp_path):
    calls = []

    @cached(name="argument-spelling")
    def operation(value=1):
        calls.append(1)
        return len(calls)

    with use_store(tmp_path):
        assert [operation(1), operation(value=1), operation()] == [1, 2, 3]
    with use_store(tmp_path):
        assert [operation(1), operation(value=1), operation()] == [1, 2, 3]
    assert len(calls) == 3
    arguments = [json.loads(path.read_text())["arguments"] for path in tmp_path.glob("*/call.json")]
    assert len(arguments) == 3
    for expected in (
        {"args": [1], "kwargs": {}},
        {"args": [], "kwargs": {"value": 1}},
        {"args": [], "kwargs": {}},
    ):
        assert expected in arguments


def test_first_cached_execution_uses_json_validation(tmp_path):
    # A string is coerced identically on first execution and replay.
    @cached(name="convert")
    def convert() -> int:
        return "3"

    with use_store(tmp_path):
        value = convert()
    with use_store(tmp_path):
        replay = convert()
    assert value == replay == 3 and type(value) is int


def test_cached_result_is_real_model(tmp_path):
    class Record(BaseModel):
        when: datetime

    # Annotation is concrete here so it also covers runtime TypeAdapter decoding.
    def make():
        return {"when": "2026-01-01T00:00:00Z"}

    make.__annotations__["return"] = Record
    operation = cached(name="record")(make)
    with use_store(tmp_path):
        first = operation()
    with use_store(tmp_path):
        second = operation()
    assert isinstance(first, Record) and first == second


def test_direct_pydantic_run_with_cached_io(tmp_path):
    executed = []
    agent = Agent(TestModel(custom_output_text="direct"), name="direct")

    @cached(name="async.read")
    async def read() -> int:
        executed.append(1)
        await asyncio.sleep(0.001)
        return 9

    async def workflow():
        return await read(), (await agent.run("hello")).output

    with use_store(tmp_path):
        one = asyncio.run(workflow())
    with use_store(tmp_path):
        two = asyncio.run(workflow())
    assert one == two == (9, "direct")
    assert executed == [1]


def test_cached_effect_and_clock_stable_across_cli_steps(cli, tmp_path):
    count_file = tmp_path / "count"
    inputs = {"path": str(count_file)}
    first = cli.calls(cli.step("operations", inputs=inputs))[0]
    assert count_file.read_text() == "1"
    op_answer = next(cli.store.glob("*/answer.json")).read_bytes()
    cli.settle(first, "a")
    second = cli.calls(cli.step("operations", inputs=inputs))[0]
    assert count_file.read_text() == "1"
    cli.settle(second, "b")
    output = cli.result(cli.step("operations", inputs=inputs, code=0))
    assert output["count"] == 1 and output["answers"] == ["a", "b"]
    assert output["tuple_type"] and output["datetime_type"]
    assert next(cli.store.glob("*/answer.json")).read_bytes() == op_answer
    replay = cli.step("operations", inputs=inputs, code=0)
    assert cli.result(replay) == output
    assert count_file.read_text() == "1"


@pytest.mark.parametrize("crash", [False, True])
def test_exception_and_interruption_retry_warn_about_uncertain_outcome(cli, tmp_path, crash):
    marker = tmp_path / "attempt"
    inputs = {"path": str(marker), "crash": crash}
    failed = cli.step("retry_operation", inputs=inputs, code=9 if crash else 1)
    if not crash:
        assert "first attempt failed" in failed.stderr
    assert marker.read_text() == "attempted"
    assert not list(cli.store.glob("*/commit.json"))
    retried = cli.step("retry_operation", inputs=inputs)
    assert "earlier attempt recorded no result" in retried.stderr
    assert "outcome is uncertain" in retried.stderr
    assert "side effects may already have occurred" in retried.stderr
    call = cli.calls(retried)[0]
    cli.settle(call)
    output = cli.step("retry_operation", inputs=inputs, code=0)
    assert cli.result(output) == {"value": 42, "answer": "ok"}
    assert not output.stderr


def test_uncommitted_cached_result_is_retried_not_delivered(tmp_path, capsys):
    calls = []

    @cached(name="interrupted-publication")
    def operation() -> int:
        calls.append(1)
        return len(calls)

    with use_store(tmp_path):
        assert operation() == 1
    # Simulate interruption after result publication but before attestation.
    next(tmp_path.glob("*/commit.json")).unlink()
    with use_store(tmp_path):
        assert operation() == 2
    assert "outcome is uncertain" in capsys.readouterr().err
    with use_store(tmp_path):
        assert operation() == 2
    assert len(calls) == 2


def test_cached_identical_operations_have_occurrence_indices(tmp_path):
    called = []

    @cached(name="same")
    def operation():
        called.append(1)
        return len(called)

    with use_store(tmp_path):
        assert [operation(), operation()] == [1, 2]
    with use_store(tmp_path):
        assert [operation(), operation()] == [1, 2]
    assert len(called) == 2
