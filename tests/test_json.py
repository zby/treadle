"""Exercise the JSONL worker protocol through real CLI processes."""

import json

import pytest


def records(output):
    assert not output.stderr
    lines = [json.loads(line) for line in output.stdout.splitlines()]
    assert lines and all(isinstance(line, dict) and "type" in line for line in lines)
    return lines


def error(output, contains):
    lines = records(output)
    assert len(lines) == 1 and lines[0]["type"] == "error"
    assert contains in lines[0]["error"]


def test_json_worker_success_and_refusals(cli):
    call, waiting = records(cli.step(extra=["--json"]))
    assert call["type"] == "call" and waiting == {"type": "waiting", "open": 1}
    key = call["key"]

    claimed = records(cli.command("claim", "--next", "--worker", "one", "--json"))
    assert len(claimed) == 1
    assert claimed[0].items() >= {"type": "claimed", "key": key, "worker": "one"}.items()
    assert claimed[0]["prompt"] == call["prompt"]
    assert isinstance(claimed[0]["expires_at"], float)
    error(cli.command("claim", key, "--worker", "two", "--json", code=1), "one")
    error(cli.command("release", key, "--worker", "two", "--json", code=1), "live claim holder")
    error(cli.command("commit", key, "--worker", "two", "--json", code=1), "one")

    assert records(cli.command("release", key, "--worker", "one", "--json")) == [
        {"type": "released", "key": key}
    ]
    error(cli.command("release", key, "--worker", "one", "--json", code=1), "live claim holder")
    records(cli.command("claim", key, "--worker", "two", "--json"))
    error(cli.command("commit", key, "--worker", "two", "--json", code=1), "exactly one")
    cli.write(call, "json worker answer")
    assert records(cli.command("commit", key, "--worker", "two", "--json")) == [
        {"type": "committed", "key": key}
    ]
    error(cli.command("commit", key, "--worker", "two", "--json", code=1), "already committed")
    error(cli.command("claim", "--next", "--worker", "two", "--json", code=1), "no unclaimed open call")
    assert records(cli.step(extra=["--json"], code=0)) == [
        {"type": "result", "result": "json worker answer"},
        {"type": "done"},
    ]
    directory = cli.directory(call)
    assert json.loads((directory / "commit.json").read_text())["worker"] == "two"
    assert not (directory / "claim.json").exists()
    assert json.loads((cli.store / "open.json").read_text()) == []


def test_json_worker_refusal_reaches_workflow_as_structured_error(cli):
    call = records(cli.step(extra=["--json"]))[0]
    records(cli.command("claim", call["key"], "--worker", "refuser", "--json"))
    cli.write(call, "cannot do this", filename="failure.md")
    records(cli.command("commit", call["key"], "--worker", "refuser", "--json"))
    output = cli.step(extra=["--json"], code=1)
    error(output, "CallFailed")
    assert "cannot do this" in records(output)[0]["error"]
    assert json.loads((cli.store / "open.json").read_text()) == []


@pytest.mark.parametrize(
    "arguments",
    [
        ("claim", "--worker", "w"),
        ("claim", "--next", "--worker", "w", "--lease", "0m"),
        ("step",),
        ("step", "missing.py:workflow"),
        ("step", "missing.py:workflow", "--unknown"),
    ],
)
def test_json_usage_and_load_errors_have_no_prose(cli, arguments):
    error(cli.command(*arguments, "--json", code=1), "")


def test_json_uncertain_operation_retry_is_a_warning_record(cli, tmp_path):
    inputs = {"path": str(tmp_path / "attempt")}
    error(cli.step("retry_operation", inputs=inputs, extra=["--json"], code=1), "first attempt failed")
    output = records(cli.step("retry_operation", inputs=inputs, extra=["--json"]))
    assert [record["type"] for record in output] == ["warning", "call", "waiting"]
    assert "outcome is uncertain" in output[0]["warning"]
    assert "side effects may already have occurred" in output[0]["warning"]
    cli.settle(output[1])
    assert records(cli.step("retry_operation", inputs=inputs, extra=["--json"], code=0)) == [
        {"type": "result", "result": {"value": 42, "answer": "ok"}},
        {"type": "done"},
    ]
