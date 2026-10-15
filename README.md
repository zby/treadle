# Treadle

**Write a workflow once. Run it in Pydantic AI or through your agent harness.**

You can run a [Pydantic AI](https://ai.pydantic.dev) workflow directly in Python,
but you may want the work done inside Claude Code, using its agents, tools and
subscription access rather than making separate model API calls from Python.
Starting that Python script from Claude Code still sends requests to the model
configured for the Python run; it does not hand them to Claude Code's agents.

Treadle makes the same workflow usable through Claude Code, Codex, pi or another
harness. It turns model calls into prompts for the harness's workers and returns
their committed answers to the workflow. Branches, loops and parallel work stay
in ordinary Python; workers use their harness's shell, editor or browser.
This is a portable API from code to harness: **prompts out, committed answers back**.

The orchestrator is the transmission: it runs `treadle step`, dispatches
the printed prompts, makes sure responses are committed, and repeats. The
workflow decides what happens next. Treadle does not include built-in harness
dispatch integrations.

```text
Python workflow → Treadle prompts → orchestrator → harness workers
                ← committed answers ←───────────┘
```

> **Status:** Early working prototype, tested with fake models and live agents
> in Pi, Claude Code and Codex. Treadle is an independent project, not affiliated
> with Pydantic.

## One call, end to end

[examples/explain.py](examples/explain.py) is a complete workflow. The agent has a
name but no configured model; step mode supplies Treadle's model adapter.

```python
from pydantic_ai import Agent

explainer = Agent(
    name="explainer",
    instructions="Explain the topic in one clear, concrete paragraph.",
)


async def workflow(topic: str) -> str:
    return (await explainer.run(f"Explain {topic}.")).output
```

From the repository, install dependencies and request the first prompt:

```sh
uv sync --locked
uv run treadle step examples/explain.py:workflow \
  --inputs '{"topic": "a loom"}' --store /tmp/treadle-explain-demo
```

Use a fresh store directory for a new demonstration. The command prints the
call's key and the path to `prompt.md`, then exits **2**: waiting for an answer is
expected, not a failure. Read the prompt for instructions and the answer path.

For this one-call example, an orchestrator answering alone can write and commit:

```sh
# Replace KEY with the full key printed by step.
printf '%s' 'A loom weaves cloth.' > /tmp/treadle-explain-demo/KEY/answer.md
uv run treadle commit KEY --store /tmp/treadle-explain-demo
uv run treadle step examples/explain.py:workflow \
  --inputs '{"topic": "a loom"}' --store /tmp/treadle-explain-demo
```

With that answer, the final step prints `result "A loom weaves cloth."` and a
`done:` line, exiting **0**. This example uses a hand-supplied answer.
`commit` records its hashes so replay can deliver it; drafts alone are not
delivered. Do not change committed files.

Claims are optional when answering alone. With parallel workers, each worker
first claims a call using its own unique ID; see the
[claim/write/commit instructions](docs/RUNNING.md#answer-a-workflow-by-hand-or-from-a-harness).
For unattended runs, see [harness permissions](docs/RUNNING.md#harness-permissions).

## Branches, limits and parallel work

[examples/review_loop.py](examples/review_loop.py) shows what code controls beyond
one call. For topics such as bicycle gears and bicycle brakes, it:

1. Starts a draft-and-review branch for each topic with `asyncio.gather`.
2. Asks a writer for a paragraph, then a reviewer for a typed verdict containing
   `accepted` and `problems`.
3. Returns an accepted paragraph, or asks the writer to revise the listed problems.
   `max_rounds` limits write/review attempts; a final rejection raises an error.
4. Summarizes the accepted paragraphs only after all branches succeed.

The workflow enforces the retry limit and decides when to summarize. Pydantic AI
validates the typed review answers.

Try the same workflow offline, without credentials or model API calls:

```sh
uv run python scripts/fake_review.py --store /tmp/treadle-review-demo
uv run python scripts/fake_review.py --direct
```

The first command drives the CLI through step, claim, answer and commit. The
second runs the same workflow directly in Pydantic AI with `FunctionModel`
overrides. Both use fixed test topics: `a` is accepted immediately and `b` after
one rewrite. They return the same result. Use a fresh store to watch the whole
cycle; reusing a completed store replays matching committed answers.

## Replay and limits

Each `step` reruns the Python workflow from the top, reusing matching committed
answers as model responses. When no branch can proceed, it prints all calls still
waiting. Progress is stored in plain files, so another session or harness can
continue with the same workflow, inputs and store.
The waiting calls also serve as a task list, without a separate tracker.

You can automate the orchestrator's duties one at a time with harness hooks or
a driver script. The workflow source can also run natively in
Pydantic AI by supplying models; that is a **fresh run**, not a way to resume a
step-mode store. See the [native example](docs/RUNNING.md#start-with-one-agent).

The workflow is a **monadic build**: later work depends on earlier results, as
when the review verdict above determines whether to revise. [Luigi's dynamic dependencies](https://luigi.readthedocs.io/en/stable/tasks.html#dynamic-dependencies)
use a similar restart pattern: yielding unfinished dependencies suspends a task,
and its `run()` restarts from the top when resumed. Treadle restarts the whole
workflow, with its own scheduler and answer keys. See the
[design lineage](docs/DESIGN.md#lineage-monadic-build-systems).

Keep replay deterministic. Put side effects in [cached operations](docs/RUNNING.md#cache-operations-not-whole-workflows)
and make them **idempotent**: repeating an operation has the same intended effect
as doing it once. Luigi requires this of restarting task code too. Even a cached
operation can repeat if its side effect happens before a crash or exception
prevents recording the result.

Treadle runs **trusted Python on a local POSIX filesystem**, not in a sandbox.
Step mode does not execute Pydantic AI function tools; these are distinct from
the tools a harness worker uses to answer a prompt. Run steps serially, though
workers may answer concurrently. Use distinct prompts when concurrent branches
need distinct answers. Read the [known limits](docs/DESIGN.md#non-guarantees-and-known-limits)
and [cancellation rules](docs/RUNNING.md#synchronous-callbacks-and-cancellation)
before writing workflows.

## Origins

The idea comes from [Commonplace](https://github.com/zby/commonplace), a sibling
project with working workflows on its own machinery, without Pydantic AI. The
author then tried rebuilding the Beads Lite issue tracker around that idea. The
project became a Pydantic AI workflow runner and was renamed Treadle; a treadle
is a pedal that drives a loom one step at a time.

## Documentation

- Next: [Running Treadle](docs/RUNNING.md) for commands, API and workflow rules.
- Internals: [Design](docs/DESIGN.md), then [decision records](adr/README.md) for reasons.
- Next work: [Plan](PLAN.md).
- Contributing: [Contributor instructions](AGENTS.md).

## License

MIT
