"""Fake harness: step, answer every open prompt deterministically, complete, repeat.

usage: drive.py SCRIPT STORE INPUTS_JSON [--reject-first TOPIC] [--fail-agent-topic AGENT:TOPIC] [--always-reject TOPIC]
Writer answers are "DRAFT<n> <topic>"; the reviewer rejects the first draft of --reject-first topics.
"""
import argparse, json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BL = [sys.executable, str(HERE.parent / "bl.py")]


def topic_of(task):
    m = re.search(r"about (\w+)", task)
    return m and m.group(1)


def answer(agent, task, opts):
    topic = topic_of(task)
    if opts.fail_agent_topic == f"{agent}:{topic}":
        return "fail", f"{agent} refused for {topic}"
    if agent == "writer":
        n = len(re.findall(r"DRAFT\d", task)) + 1  # rewrite tasks embed the previous draft
        return "ok", f"DRAFT{n} {topic}"
    if agent == "reviewer":
        if topic in opts.always_reject or (topic in opts.reject_first and "DRAFT1" in task):
            return "ok", json.dumps({"accepted": False, "problems": [f"too vague about {topic}"]})
        return "ok", json.dumps({"accepted": True})
    return "ok", "SUMMARY of " + ", ".join(re.findall(r"DRAFT\d \w+", task))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("script"); p.add_argument("store"); p.add_argument("inputs")
    p.add_argument("--reject-first", nargs="*", default=[])
    p.add_argument("--always-reject", nargs="*", default=[])
    p.add_argument("--fail-agent-topic")
    p.add_argument("--max-steps", type=int, default=50)
    p.add_argument("--runner", default="bl.py", help="bl.py (Monty) or bl_cpython.py")
    opts = p.parse_args()
    store = Path(opts.store)
    for n in range(1, opts.max_steps + 1):
        r = subprocess.run([sys.executable, str(HERE.parent / opts.runner), "step", opts.script, "--store", opts.store, "--inputs", opts.inputs],
                           capture_output=True, text=True)
        if r.returncode != 2:
            print(f"step {n}: exit {r.returncode}\n{r.stdout}{r.stderr}")
            return r.returncode
        keys = [line.split() for line in r.stdout.splitlines()]
        print(f"step {n}: exit 2, {len(keys)} open:")
        for key, agent in keys:
            task = json.loads((store / key / "call.json").read_text())["task"]
            kind, text = answer(agent, task, opts)
            print(f"  {key[:12]} {agent:10} {task.splitlines()[0][:50]!r} -> {kind}: {text.splitlines()[0][:50]}")
            if kind == "fail":
                cmd = BL + ["fail", key, text, "--store", opts.store]
            else:
                f = store / key / ".fake_answer"
                f.write_text(text)
                cmd = BL + ["complete", key, str(f), "--store", opts.store]
            c = subprocess.run(cmd, capture_output=True, text=True)
            assert c.returncode == 0, c.stderr
    return 3


if __name__ == "__main__":
    sys.exit(main())
