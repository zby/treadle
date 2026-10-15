import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT, WORKFLOWS


def test_installed_cli_help():
    process = subprocess.run(
        [str(Path(sys.executable).parent / "treadle"), "--help"], text=True, capture_output=True
    )
    assert process.returncode == 0
    assert "step" in process.stdout and "claim" in process.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ("claim", "--next", "--worker", "w", "--lease", "0m"),
        ("step",),
    ],
)
def test_bad_cli_usage_is_error_not_waiting(cli, arguments):
    result = cli.command(*arguments, code=1)
    assert "error:" in result.stderr and "Next:" in result.stderr


def test_example_direct_equals_cli_driver(tmp_path):
    def run(*args):
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts/fake_review.py"), *map(str, args)],
            text=True,
            capture_output=True,
            timeout=45,
        )
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)

    direct = run("--direct")
    store = tmp_path / "example"
    assert run("--store", store) == direct
    calls = [json.loads(p.read_text()) for p in store.glob("*/call.json")]
    assert len(calls) == 7  # three writer, three reviewer, one summarizer
    assert (store / "open.json").read_text().strip() == "[]"
    assert direct == {
        "sections": [
            {"topic": "a", "text": "Paragraph about a.", "rounds": 0},
            {"topic": "b", "text": "Paragraph about b (revised).", "rounds": 1},
        ],
        "summary": "SUMMARY: 2 paragraphs.",
    }
    commits = [json.loads(path.read_text()) for path in store.glob("*/commit.json")]
    assert len(commits) == 7 and all(commit["worker"] == "fake:review-driver" for commit in commits)
    assert not list(store.glob("*/claim.json"))


def test_gather_frontier_and_determinism(cli):
    output = cli.step("fanout")
    calls = cli.calls(output)
    assert len(calls) == 2
    assert cli.step("fanout").stdout == output.stdout
    assert cli.step("fanout").stdout == output.stdout
    assert json.loads((cli.store / "open.json").read_text()) == [
        {k: v for k, v in call.items() if k != "holder"} for call in calls
    ]
    for call in calls:
        cli.settle(call, cli.user(call))
    assert cli.result(cli.step("fanout", code=0)) == ["left", "right"]


def test_keys_location_independent_and_prompt_self_contained(cli, tmp_path):
    first = cli.calls(cli.step())[0]
    metadata = json.loads((cli.directory(first) / "call.json").read_text())
    assert metadata["scope"] == "" and metadata["format_version"] == "treadle-prompt-v1"
    prompt = Path(first["prompt"]).read_text()
    assert "System instructions." in prompt and "Text instructions." in prompt
    assert str(cli.directory(first) / "answer.md") in prompt
    assert f"treadle commit {first['key']}" in prompt
    assert "--worker WORKER_ID" in prompt and "failure.md" in prompt
    cli.store = tmp_path / "other location"
    second = cli.calls(cli.step())[0]
    assert first["key"] == second["key"]
    assert Path(second["prompt"]).is_absolute()
    assert "'" + str(cli.store) + "'" in Path(second["prompt"]).read_text()
    changed = cli.calls(cli.step(inputs={"prompt": "edited"}))[0]
    assert changed["key"] != first["key"]


def test_repeated_identical_calls(cli):
    first = cli.calls(cli.step("repeated"))[0]
    cli.settle(first, "first")
    second = cli.calls(cli.step("repeated"))[0]
    assert first["key"] != second["key"]
    assert json.loads((cli.directory(second) / "call.json").read_text())["occurrence"] == 1
    cli.settle(second, "second")
    pair = cli.calls(cli.step("repeated"))
    assert len(pair) == 2 and pair[0]["key"] != pair[1]["key"]
    for call in pair:
        index = json.loads((cli.directory(call) / "call.json").read_text())["occurrence"]
        cli.settle(call, f"pair{index}")
    assert cli.result(cli.step("repeated", code=0)) == ["first", "second", "pair0", "pair1"]


def test_typed_retry_real_object_and_deterministic_retry_prompt(cli):
    first = cli.calls(cli.step("typed"))[0]
    assert '"count"' in Path(first["prompt"]).read_text()
    cli.settle(first, '{"count":"not an integer"}', filename="answer.json")
    retry_output = cli.step("typed")
    retry = cli.calls(retry_output)[0]
    assert retry["key"] != first["key"]
    prompt = Path(retry["prompt"]).read_text()
    assert "Retry request" in prompt and "int_parsing" in prompt
    assert "not an integer" in prompt
    assert cli.step("typed").stdout == retry_output.stdout
    cli.settle(retry, '{"count":7}', filename="answer.json")
    assert cli.result(cli.step("typed", code=0)) == {"real_type": True, "count": 7}


def test_typed_exhausted_retries(cli):
    for _ in range(2):
        call = cli.calls(cli.step("typed"))[0]
        cli.settle(call, '{"count":"bad"}', filename="answer.json")
    failure = cli.step("typed", code=1)
    assert "UnexpectedModelBehavior" in failure.stderr and "retries" in failure.stderr
    assert json.loads((cli.store / "open.json").read_text()) == []


def test_failure_is_model_api_error_catchable_and_uncaught(cli):
    call = cli.calls(cli.step())[0]
    cli.settle(call, "worker refused", filename="failure.md")
    error = cli.step(code=1)
    assert "CallFailed" in error.stderr and "worker refused" in error.stderr
    value = cli.result(cli.step("caught_failure", code=0))
    assert value["caught"] and "worker refused" in value["reason"]


@pytest.mark.parametrize("mode", ["sleep", "thread"])
def test_frontier_waits_for_timers_and_threads(cli, mode):
    calls = cli.calls(cli.step("timed", inputs={"mode": mode}))
    assert sorted(cli.user(c) for c in calls) == ["early", "late"]


def test_cancelled_timer_does_not_prevent_frontier(cli):
    assert len(cli.calls(cli.step("cancelled_timer"))) == 2


def test_unsupported_await_is_reported_or_documented_blind_spot(cli):
    result = cli.step("unsupported", code=1)
    assert "unsupported await" in result.stderr
    # Raw socket readiness bypasses the tracked scheduling API. This is an
    # intentional limitation, not a silently asserted general-I/O guarantee.
    assert [cli.user(c) for c in cli.calls(cli.step("sockets"))] == ["early"]
    calls = cli.calls(cli.step("sockets", inputs={"protected": True}))
    assert sorted(cli.user(c) for c in calls) == ["early", "late"]


def test_tools_are_listed_as_unavailable_not_executed(cli):
    call = cli.calls(cli.step("tooled"))[0]
    prompt = Path(call["prompt"]).read_text()
    assert "Tools (unavailable)" in prompt
    assert "unavailable_tool" in prompt and "value" in prompt
    cli.settle(call, "without tools")
    assert cli.result(cli.step("tooled", code=0)) == "without tools"


def test_failed_load_does_not_leave_claimable_stale_frontier(cli):
    cli.step()
    cli.command("step", "missing.py:workflow", code=1)
    assert json.loads((cli.store / "open.json").read_text()) == []
    cli.command("claim", "--next", "--worker", "w", code=1)


def test_serial_steps_reject_overlap_without_blocking_workers(cli, tmp_path):
    # A real running operation holds the step guard, not the worker lock.
    old_call = cli.calls(cli.step())[0]
    marker = tmp_path / "slow-marker"
    args = cli.argv("step", f"{WORKFLOWS}:slow_operation", "--inputs", json.dumps({"marker": str(marker)}))
    running = subprocess.Popen(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        import time

        deadline = time.monotonic() + 10
        while not marker.exists() and running.poll() is None and time.monotonic() < deadline:
            time.sleep(0.005)
        assert marker.exists()
        refused = cli.step(code=1)
        assert "another step" in refused.stderr
        cli.command("claim", old_call["key"], "--worker", "worker:independent")
        cli.settle(old_call, worker="worker:independent")
        assert running.poll() is None  # the step stayed active during worker transactions
        assert marker.read_text() == "1"  # the overlapping step ran no operation
        Path(str(marker) + ".release").write_text("proceed")
        stdout, stderr = running.communicate(timeout=10)
        assert running.returncode == 2, (stdout, stderr)
    finally:
        if running.poll() is None:
            running.kill()
            running.communicate()


def test_identical_concurrent_calls_can_swap_branch_identity(cli):
    """Evidence against stable branch identity, preserving the accepted scheme.

    Restriction: concurrent identical downstream calls must be interchangeable,
    or include branch identity in their prompts. A fix needs a parent decision.
    """
    initial = cli.calls(cli.step("identity_overlap"))
    by_prompt = {cli.user(c): c for c in initial}
    cli.settle(by_prompt["right"], "gate")
    next_calls = cli.calls(cli.step("identity_overlap"))
    downstream = next(c for c in next_calls if cli.user(c) == "identical downstream")
    cli.settle(downstream, "right-owned")
    cli.settle(by_prompt["left"], "gate")
    next_calls = cli.calls(cli.step("identity_overlap"))
    assert len(next_calls) == 1
    assert next_calls[0]["key"] != downstream["key"]
    cli.settle(next_calls[0], "new-occurrence")
    # LEFT now receives the answer originally obtained by RIGHT.
    assert cli.result(cli.step("identity_overlap", code=0)) == ["right-owned", "new-occurrence"]
