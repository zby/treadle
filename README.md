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

> **Status:** designed, not built. The design is in [docs/DESIGN.md](docs/DESIGN.md)
> and a prototype passed functional tests with fake models; the package does not
> implement it yet ([PLAN.md](PLAN.md)). Treadle grew out of Beads Lite, an issue
> tracker.

[^graph]: From Samuel Colvin's
    [The code IS the graph](https://x.com/samuelcolvin/status/2110055467007303729).
    Treadle is not a Pydantic project.

## How it works

```python
# review.py: an ordinary Pydantic AI workflow
import asyncio
from pydantic import BaseModel
from pydantic_ai import Agent


class Verdict(BaseModel):
    accepted: bool
    problems: list[str]


writer = Agent("anthropic:claude-sonnet-4-5", name="writer", instructions="Write one clear paragraph.")
reviewer = Agent(
    "anthropic:claude-sonnet-4-5",
    name="reviewer",
    output_type=Verdict,
    instructions="Accept the paragraph or list concrete problems.",
)


async def workflow(topics: list[str]) -> dict:
    async def draft(topic):
        text = (await writer.run(f"Write one paragraph about {topic}.")).output
        verdict = (await reviewer.run(f"Review this paragraph:\n\n{text}")).output
        return {"topic": topic, "text": text, "accepted": verdict.accepted}

    return {"sections": await asyncio.gather(*[draft(t) for t in topics])}
```

A coordinating agent steps through it:

```text
$ treadle step review.py:workflow --inputs '{"topics": ["a", "b"]}' --store run/
3f9c2a1b  writer  run/3f9c2a1b.../prompt.md
81aa02c4  writer  run/81aa02c4.../prompt.md
$ treadle claim 3f9c --worker session-1 --store run/     (optional: only needed when workers share a store)
  ... sub-agents read each prompt.md and draft the answer where it says ...
$ treadle commit 3f9c --worker session-1 --store run/
$ treadle step review.py:workflow --inputs '{"topics": ["a", "b"]}' --store run/
...                                   (the two reviewer calls)
```

Each `treadle step` replays the workflow from the top. Stored answers are delivered
to their `agent.run` calls as ordinary model responses, so Pydantic AI validates
typed answers itself. When no branch can proceed, every call still waiting for an
answer is printed, and the step exits. Whoever answers a call (the coordinator,
a sub-agent, a person) drafts the answer where the prompt says and runs
`treadle commit`; a task is done when its answer is committed. Claims with leases
keep two workers from doing the same call.

The workflow's progress lives in the store, not in anyone's context, so another
session or another harness can continue it, and `treadle step` is also the status
command.

The orchestrating agent's job is small on purpose: run `treadle step`, hand out the
prompts, make sure answers are committed, repeat. If it starts making mistakes,
move that duty into code: a harness hook, then a driver script, and finally a
native run of the same workflow in Pydantic AI. The workflow file stays the same
throughout.

Operations with side effects use the same store, so replaying them is safe:

```python
from treadle import cached


@cached(name="acquire")
def acquire(url: str, commit: str) -> str: ...  # runs once; later steps get the recorded result
```

## Documentation

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
