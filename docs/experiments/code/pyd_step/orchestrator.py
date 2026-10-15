"""Fake orchestrator: runs `bl step --json`, answers each open prompt with fake_answers, `bl complete`s it, repeats.

usage: orchestrator.py WORKFLOW STORE INPUTS_JSON [--fail AGENT:TOPIC] [--answer-dir DIR]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from fake_answers import answer

BL = [sys.executable, str(Path(__file__).with_name("bl.py"))]


def user_prompt(prompt_md):
    return re.search(r"## User prompt\n\n(.*?)(?=\n\n## |\Z)", prompt_md, re.S).group(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("workflow")
    p.add_argument("store")
    p.add_argument("inputs")
    p.add_argument("--fail", default="")
    a = p.parse_args()
    answers = Path(a.store + "-answers")
    answers.mkdir(parents=True, exist_ok=True)
    for n in range(1, 50):
        r = subprocess.run([*BL, "step", a.workflow, "--inputs", a.inputs, "--store", a.store, "--json"],
                           capture_output=True, text=True)
        lines = [json.loads(line) for line in r.stdout.splitlines()]
        calls = [x for x in lines if "key" in x]
        print(f"step {n}: exit {r.returncode}; open: " + ", ".join(f"{c['key'][:8]} {c['agent']}" for c in calls))
        if r.returncode != 2:
            print(r.stdout if r.returncode == 0 else r.stdout + r.stderr, end="")
            return r.returncode
        for c in calls:
            task = user_prompt(Path(c["prompt"]).read_text())
            if a.fail and a.fail == f"{c['agent']}:{re.search(r'about (\w+)', task).group(1)}":
                subprocess.run([*BL, "fail", c["key"][:8], f"{c['agent']} refused", "--store", a.store], check=True)
                continue
            value = answer(c["agent"], task)
            f = answers / f"{c['key'][:12]}.txt"
            f.write_text(value if isinstance(value, str) else json.dumps(value))
            subprocess.run([*BL, "complete", c["key"][:8], str(f), "--store", a.store], check=True)
    return 3


if __name__ == "__main__":
    sys.exit(main())
