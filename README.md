# Treadle

Write an agent workflow once, as ordinary [Pydantic AI](https://ai.pydantic.dev)
code. Step through it from Claude Code, Codex or pi, where the harness's own
agents do the work, and run it natively in Pydantic AI when you are ready.

Your code is the graph[^graph]: `if` is a branch, `gather` is a fan-out, a `for`
around a `try` is a retry. Treadle lets any harness be its runtime.

- **Portable and resumable.** Progress lives in a directory of plain files, not
  in an agent's context. Any session or harness can pick a run up.
- **Agents do the steps.** Each model call becomes a prompt that a harness
  sub-agent, with its own tools, or a person answers. The workflow gets a typed
  answer either way.
- **Codify progressively.** The orchestrating agent only follows what
  `treadle step` prints. When it slips, move that duty into a hook, then a
  script, then a native Pydantic AI run. The workflow never changes.
- **Finished work is never redone.** Treadle is a small build system: results
  are stored under content hashes and the workflow is replayed against them. The
  calls it waits on form a task list, so it is also a tracker where workflows
  come first.

A treadle is the foot pedal that drives a loom: each push turns the machine one
step, and one day a motor takes over.

> **Status:** An early working prototype, exercised with fake models. No real
> model or harness sub-agent has answered a workflow prompt yet; the task-tracker
> trial is still planned. Start with the
> [offline example and CLI guide](docs/RUNNING.md); see the
> [design](docs/DESIGN.md) for semantics and limits and the
> [runner lessons](docs/experiments/2026-10-runner-lessons.md) for findings so far.
> Treadle grew out of Beads Lite, an issue tracker.

[^graph]: From Samuel Colvin's
    [The code IS the graph](https://x.com/samuelcolvin/status/2110055467007303729).
    Treadle is not a Pydantic project.

## How it works

```python
# examples/explain.py: an ordinary Pydantic AI workflow
from pydantic_ai import Agent

explainer = Agent(
    name="explainer",
    instructions="Explain the topic in one clear, concrete paragraph.",
)


async def workflow(topic: str) -> str:
    return (await explainer.run(f"Explain {topic}.")).output
```

A coordinating agent steps through it (keys and paths abbreviated):

```text
$ treadle step examples/explain.py:workflow --inputs '{"topic": "a loom"}' --store run/
call {"agent": "explainer", "holder": null, "key": "3f9c2a1b...", "prompt": "/work/run/3f9c2a1b.../prompt.md"}
waiting: 1 open call(s). Next: claim, read prompts, write answers, treadle commit, then treadle step.
$ treadle claim 3f9c --worker harness:session-1 --store run/
  ... read prompt.md and draft answer.md where it says ...
$ treadle commit 3f9c --worker harness:session-1 --store run/
$ treadle step examples/explain.py:workflow --inputs '{"topic": "a loom"}' --store run/
result "A loom weaves cloth."
done: workflow completed. Next: no action.
```

Claims are optional when a coordinator answers alone. No model or credentials
are needed for step mode: Treadle supplies the model adapter. For a native run,
supply a model with `explainer.override(model=...)`; the
[offline native instructions](docs/RUNNING.md#start-with-one-agent) use Pydantic
AI's `TestModel` without credentials.

The second example, [review_loop.py](examples/review_loop.py), adds parallel
drafting, typed reviews, bounded rewriting and summarization. Its
[offline driver](scripts/fake_review.py) demonstrates explicit claims and the
JSONL worker protocol.

Each `treadle step` replays the workflow from the top. Stored answers are delivered
to their `agent.run` calls as ordinary model responses, so Pydantic AI validates
typed answers itself. When no branch can proceed, every call still waiting for an
answer is printed, and the step exits. Whoever answers a call (the coordinator,
a sub-agent, a person) drafts the answer where the prompt says and runs
`treadle commit`; a task is done when its answer is committed. Claims with leases
keep two workers from doing the same call. Text answers preserve the whole UTF-8
file, including a trailing newline. Changed or missing attested files are fatal
at the step boundary even if workflow code catches the read error; worker
`CallFailed` refusals remain catchable.

The workflow's progress lives in the store, not in anyone's context, so another
session or another harness can continue it, and `treadle step` is also the status
command.

The orchestrating agent's job is small on purpose: run `treadle step`, hand out the
prompts, make sure answers are committed, repeat. If it starts making mistakes,
move that duty into code: a harness hook, then a driver script, and finally a
native run of the same workflow in Pydantic AI. The workflow file stays the same
throughout.

Operations with side effects use the same store to reuse recorded results.
They must be idempotent: an exception or a crash before recording the result can
cause another execution. This is not an exactly-once guarantee. Operation names
and argument spelling are durable identity: `acquire("url", "rev")` and
`acquire(url="url", commit="rev")` have different keys. The cache does not
normalize positional/keyword arguments or defaults:

```python
from treadle import cached


@cached(name="acquire")
def acquire(url: str, commit: str) -> str: ...  # later steps reuse the recorded result
```

Other [non-guarantees and known limits](docs/DESIGN.md#non-guarantees-and-known-limits)
include arrival-order identity for identical concurrent calls: use distinct
prompts for branch-specific answers. Multiple workers can share claims, but
overlapping `step` commands on one store are rejected. Waiting steps cancel
pending tasks, so workflow `finally` blocks are cleanup, not evidence of success.
See [callback/cancellation guidance](docs/RUNNING.md#synchronous-callbacks-and-cancellation)
and [trusted-Python import constraints](docs/RUNNING.md#trusted-python-and-imports).

## Documentation

- [Running Treadle](docs/RUNNING.md): offline example, CLI protocol, answers,
  claims and cached operations.
- [Positioning](docs/POSITIONING.md): who it is for, what it is not, neighbours.
- [Design](docs/DESIGN.md): step semantics, rules for workflows, answer identity,
  cached operations, store layout, and what version 1 leaves out.
- [Decision records](adr/README.md), starting with
  [ADR 001](adr/001-step-runner-for-pydantic-ai-workflows.md): why this design,
  and the alternatives considered (Luigi, Monty, Temporal, a queue).
- [Experiments](docs/experiments/README.md): the feasibility runs behind it.
- [Plan](PLAN.md): implementation stages.
- [Contributor instructions](AGENTS.md).

## License

MIT
