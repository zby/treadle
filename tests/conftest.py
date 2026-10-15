import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = Path(__file__).with_name("workflows.py")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    from pydantic_ai.models import override_allow_model_requests

    with override_allow_model_requests(False):
        yield


@pytest.fixture
def cli(tmp_path):
    class CLI:
        store = tmp_path / "store"

        def argv(self, *args):
            return [sys.executable, "-m", "treadle.cli", *map(str, args), "--store", str(self.store)]

        def command(self, *args, code=0):
            result = subprocess.run(self.argv(*args), text=True, capture_output=True, timeout=15)
            if code is not None:
                assert result.returncode == code, (result.stdout, result.stderr)
            return result

        def step(self, function="one", *, inputs=None, code=2, extra=()):
            return self.command(
                "step", f"{WORKFLOWS}:{function}", "--inputs", json.dumps(inputs or {}), *extra, code=code
            )

        def calls(self, result):
            calls = [json.loads(line[5:]) for line in result.stdout.splitlines() if line.startswith("call ")]
            assert result.stdout.splitlines()[-1].startswith("waiting:")
            return calls

        def result(self, output):
            assert output.stdout.splitlines()[-1].startswith("done:")
            return json.loads(output.stdout.splitlines()[0].removeprefix("result "))

        def directory(self, call):
            return Path(call["prompt"]).parent

        def write(self, call, value="ok", *, filename="answer.md"):
            (self.directory(call) / filename).write_text(value)

        def commit(self, call, *files, worker=None, code=0):
            return self.command(
                "commit", call["key"], *files, *(["--worker", worker] if worker else []), code=code
            )

        def settle(self, call, value="ok", *, filename="answer.md", worker=None):
            self.write(call, value, filename=filename)
            self.commit(call, worker=worker)

        def user(self, call):
            return Path(call["prompt"]).read_text().split("## User prompt\n\n", 1)[1].split("\n\n## ", 1)[0]

    return CLI()
