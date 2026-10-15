import hashlib
import json
import subprocess
import time

import pytest


def test_uncommitted_draft_is_ignored_write_once_and_aux_attestation(cli):
    call = cli.calls(cli.step())[0]
    cli.write(call, "draft")
    assert cli.calls(cli.step())[0]["key"] == call["key"]
    directory = cli.directory(call)
    (directory / "notes").mkdir()
    (directory / "notes/report.txt").write_text("supporting evidence")
    cli.commit(call, "notes/report.txt", worker="worker:coordinator")
    manifest = json.loads((directory / "commit.json").read_text())
    assert manifest["worker"] == "worker:coordinator"
    assert manifest["files"] == {
        "answer.md": hashlib.sha256(b"draft").hexdigest(),
        "notes/report.txt": hashlib.sha256(b"supporting evidence").hexdigest(),
    }
    assert isinstance(manifest["committed_at"], float)
    assert cli.result(cli.step(code=0)) == "draft"
    assert "already committed" in cli.commit(call, code=1).stderr


@pytest.mark.parametrize(
    "target,delete", [("answer.md", False), ("answer.md", True), ("report.md", False), ("report.md", True)]
)
def test_tampered_or_deleted_committed_files_stop_replay(cli, target, delete):
    call = cli.calls(cli.step())[0]
    cli.write(call, "answer")
    path = cli.directory(call) / "report.md"
    path.write_text("report")
    cli.commit(call, "report.md")
    path = cli.directory(call) / target
    if delete:
        path.unlink()
    else:
        path.write_text("changed")
    failure = cli.step(code=1)
    assert str(path) in failure.stderr
    assert "missing" in failure.stderr if delete else "hash mismatch" in failure.stderr


def test_commit_requires_exactly_one_correct_answer(cli):
    call = cli.calls(cli.step())[0]
    for files in (
        {},
        {"answer.md": "x", "failure.md": "no"},
        {"answer.md": "x", "answer.json": "{}"},
        {"answer.json": "{}"},
    ):
        for name, content in files.items():
            cli.write(call, content, filename=name)
        refused = cli.commit(call, code=1)
        assert "exactly one" in refused.stderr, (files, refused.stderr)
        assert not (cli.directory(call) / "commit.json").exists(), files
        for name in files:
            (cli.directory(call) / name).unlink()


def test_commit_typed_answer_requires_one_json_object(cli):
    call = cli.calls(cli.step("typed"))[0]
    for value in ("[]", "null", '"text"', "{} {}", "not json", '{"x":NaN}'):
        cli.write(call, value, filename="answer.json")
        refused = cli.commit(call, code=1)
        assert "one JSON object" in refused.stderr, (value, refused.stderr)
        assert not (cli.directory(call) / "commit.json").exists(), value


def test_commit_refuses_missing_outside_and_metadata_files(cli):
    call = cli.calls(cli.step())[0]
    cli.write(call)
    (cli.store / "outside.txt").write_text("outside")
    for extra in (
        "missing.txt",
        "../outside.txt",
        "/tmp/outside.txt",
        "commit.json",
        "prompt.md",
        "call.json",
    ):
        refused = cli.commit(call, extra, code=1)
        assert refused.stderr, extra
        assert not (cli.directory(call) / "commit.json").exists(), extra


@pytest.mark.parametrize("target", ["outside", "inside", "parent"])
def test_commit_rejects_symlink_files_and_parent_directories(cli, tmp_path, target):
    call = cli.calls(cli.step())[0]
    cli.write(call)
    directory = cli.directory(call)
    outside = tmp_path / "outside"
    outside.write_text("secret")
    if target == "parent":
        (directory / "linked").symlink_to(tmp_path, target_is_directory=True)
        extra = "linked/outside"
    else:
        (directory / "inside").write_text("inside")
        (directory / "linked").symlink_to(outside if target == "outside" else directory / "inside")
        extra = "linked"
    assert "symlink" in cli.commit(call, extra, code=1).stderr


def test_commit_rejects_answer_symlink_and_call_directory_symlink(cli, tmp_path):
    call = cli.calls(cli.step())[0]
    target = tmp_path / "target"
    target.write_text("outside")
    (cli.directory(call) / "answer.md").symlink_to(target)
    assert "symlink" in cli.commit(call, code=1).stderr
    (cli.directory(call) / "answer.md").unlink()
    moved = tmp_path / "moved"
    cli.directory(call).rename(moved)
    cli.directory(call).symlink_to(moved, target_is_directory=True)
    assert "symlink" in cli.commit(call, code=1).stderr
    assert "symlink" in cli.step(code=1).stderr


def test_replay_rejects_committed_file_replaced_by_symlink(cli, tmp_path):
    call = cli.calls(cli.step())[0]
    cli.settle(call, "content")
    target = tmp_path / "target"
    target.write_text("content")  # even with exactly the attested bytes
    path = cli.directory(call) / "answer.md"
    path.unlink()
    path.symlink_to(target)
    assert "symlink" in cli.step(code=1).stderr


@pytest.mark.parametrize("metadata", ["call.json", "prompt.md", "commit.json", "claim.json"])
def test_symlink_metadata_is_not_followed(cli, tmp_path, metadata):
    call = cli.calls(cli.step())[0]
    target = tmp_path / "metadata"
    target.write_text("{}")
    path = cli.directory(call) / metadata
    if path.exists():
        path.unlink()
    path.symlink_to(target)
    if metadata == "claim.json":
        cli.write(call)
        result = cli.commit(call, code=1)
    else:
        result = cli.step(code=1)
    assert "symlink" in result.stderr
    assert target.read_text() == "{}"


def test_claim_live_holder_release_commit_and_provenance(cli):
    call = cli.calls(cli.step())[0]
    cli.command("claim", call["key"], "--worker", "session:one", "--lease", "30m")
    assert cli.calls(cli.step())[0]["holder"] == "session:one"
    refused = cli.command("claim", call["key"], "--worker", "session:two", code=1)
    assert "session:one" in refused.stderr
    cli.write(call)
    assert "session:one" in cli.commit(call, worker="session:two", code=1).stderr
    assert "session:one" in cli.commit(call, code=1).stderr
    assert (
        "live claim holder" in cli.command("release", call["key"], "--worker", "session:two", code=1).stderr
    )
    cli.command("release", call["key"], "--worker", "session:one")
    cli.command("release", call["key"], "--worker", "session:one", code=1)
    cli.command("claim", call["key"], "--worker", "session:two")
    cli.commit(call, worker="session:two")
    directory = cli.directory(call)
    assert not (directory / "claim.json").exists()
    assert json.loads((directory / "commit.json").read_text())["worker"] == "session:two"
    cli.command("release", call["key"], "--worker", "session:two", code=1)
    cli.command("claim", call["key"], "--worker", "session:two", code=1)


def test_expired_claim_can_be_reclaimed_but_not_released(cli):
    call = cli.calls(cli.step())[0]
    cli.command("claim", call["key"], "--worker", "session:old", "--lease", "0.001s")
    time.sleep(0.01)
    cli.command("release", call["key"], "--worker", "session:old", code=1)
    cli.command("claim", call["key"], "--worker", "session:new")
    cli.settle(call, worker="session:new")


def test_claim_only_latest_frontier_and_next_ignores_committed(cli):
    call = cli.calls(cli.step())[0]
    fresh = cli.calls(cli.step(inputs={"prompt": "changed"}))[0]
    assert "latest open set" in cli.command("claim", call["key"], "--worker", "w", code=1).stderr
    out = cli.command("claim", "--next", "--worker", "w")
    assert fresh["key"] in out.stdout
    cli.settle(fresh, worker="w")
    assert "no unclaimed open call" in cli.command("claim", "--next", "--worker", "w", code=1).stderr


def test_concurrent_next_claims_get_different_calls(cli):
    calls = cli.calls(cli.step("fanout"))
    workers = []
    for worker in ("worker:a", "worker:b"):
        workers.append(
            subprocess.Popen(
                cli.argv("claim", "--next", "--worker", worker),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        )
    keys = []
    for process in workers:
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        keys.append(json.loads(stdout.splitlines()[0].removeprefix("claimed "))["key"])
    assert set(keys) == {c["key"] for c in calls}


def test_concurrent_commits_are_write_once(cli):
    call = cli.calls(cli.step())[0]
    cli.write(call)
    processes = [
        subprocess.Popen(
            cli.argv("commit", call["key"], "--worker", worker),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for worker in ("a", "b")
    ]
    outputs = [p.communicate(timeout=10) for p in processes]
    assert sorted(p.returncode for p in processes) == [0, 1], outputs
    assert cli.result(cli.step(code=0)) == "ok"


def test_key_path_patterns_are_not_interpreted(cli):
    cli.step()
    for key in ("../", "*", "", "xyz"):
        refused = cli.command("commit", key, code=1)
        assert "invalid key" in refused.stderr, (key, refused.stderr)
