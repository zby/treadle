# 001 — Build Treadle as a step runner for Pydantic AI workflows

Status: accepted
Confidence: firm
Decision date: 2026-10-15
Recorded: 2026-10-15

## Context

Treadle grew out of Beads Lite, an unpublished local issue tracker with
dependencies, readiness, claims, assignment, a journal and backups. Its
motivating case was the implementer–verifier relay that an operator ran by hand
between agent sessions.

Writing that relay down showed that the dependencies are the workflow, and that a
workflow is better written as code than as a graph of records: the next step
depends on answers (repair only if verification failed; fan out after a plan),
loops are bounded by attempts, and ordering follows from data flow. A
proposal there described such "step programs": workflow code
replayed from the top, expensive results cached, and work the program cannot do
itself handed out as prompt files to whatever agent harness is running.

Task trackers in general follow the same path: they start with tasks and
dependencies and then grow workflows (status fields, state machines, automation
rules), usually in a configuration language that becomes a weak programming
language. Commonplace's analysis workflow needed about 200 lines of YAML plan
expanded by about 400 lines of code. Starting from workflows as code, with the
tracker as a view of their state, avoids that growth.

The operator also wants the same workflows to run in Pydantic AI, whose agent
abstractions and durable-execution integrations they trust.

## Decision

Treadle is a step runner for ordinary Pydantic AI workflows, and through it a
task tracker where workflows come first. Open tasks
are model calls waiting for answers; a task type is an async lifecycle function;
dependencies are control flow. Version 1, as designed in
[DESIGN.md](../docs/DESIGN.md):

- A workflow is ordinary Pydantic AI code: agents with names, instructions and
  output types, and an async function calling `agent.run` and `asyncio.gather`.
- `treadle step` replays the workflow. A `StepModel`, a Pydantic AI `Model` installed
  with `agent.override(model=...)`, returns stored answers as model responses.
  When no branch can proceed, all uncached model calls are printed together and
  the step exits. Whoever answers a call writes the answer in files its prompt
  names and runs `treadle commit`; a task is done when its answer is committed.
  What a commit records is the tentative
  [ADR 002](002-commit-attests-answer-files-by-hash.md).
  Typed answers are validated by Pydantic AI on replay, not at commit. Status is
  a step.
- Claims with leases (`treadle claim`, `treadle release`) keep two workers off the same
  call; the committing worker is recorded as the answer's provenance.
- Other operations go through the same in-process cache (`@cached`), which is
  how workflows make side effects safe to replay.
- Answers are keyed by content plus an occurrence index (counted per scope:
  [ADR 004](004-occurrence-indices-per-scope.md)).
- Storage is a directory of files with a store lock for claims. No database
  and no server.

Treadle starts as a new repository; none of the tracker's code is carried
over. The name is
[ADR 005](005-name-treadle.md).

Implementation status: the Stage 1 runner, commit attestation, claims and
cached operations are implemented in `src/treadle/`, with functional fake-model
tests in `tests/` and an offline driver in `scripts/fake_review.py`.
Live agents have since answered workflow prompts in Pi, Claude Code and Codex;
[Runner lessons](../docs/experiments/2026-10-runner-lessons.md#live-trials)
records the Pi one-call trial. [PLAN.md](../PLAN.md) tracks the Stage 2 real coding
task, typed review and parallel-worker trial.

## Basis

Observations, from the [experiments](../docs/experiments/README.md), all with
fake models:

- Ordinary Pydantic AI workflow code ran unchanged both directly and under a
  step-runner prototype, with equal results; 6 steps for the example; typed
  answers came back as real model instances; 30 replays were identical
  ([report](../docs/experiments/2026-10-pydantic-step-runner.md)).
- A cached side-effecting operation ran exactly once over a multi-step run; the
  same operation uncached ran on every replay (same report).
- Without an occurrence index, an identical repeated call returned its stored
  answer instead of asking again, so loops behaved differently from Pydantic AI
  ([Monty runner report](../docs/experiments/2026-10-monty-step-runner.md)).

Source readings (not runs):

- Luigi 3.8.1 replays a task's `run()` from the top on each new dynamic
  dependency and requires idempotent tasks (`luigi/worker.py:144-167`,
  `doc/tasks.rst:207-210`), the same philosophy. Its workflows need class
  inheritance and generators, and an incomplete external task's requirements
  are not scheduled (`luigi/worker.py:865-870`).
- Pydantic AI 2.54 exposes a public durable-execution engine API
  (`CallableOperationBackend`, `@durable_operation`) used by its Temporal, DBOS
  and Prefect integrations. It is scoped to one agent run, not to a workflow
  calling several agents.

Framing (inspiration, not evidence): *Build Systems à la Carte* (Mokhov,
Mitchell, Peyton Jones, ICFP 2018). In its terms this is a monadic build system
with a restarting scheduler and constructive traces; the mapping is in
[DESIGN.md](../docs/DESIGN.md), "Lineage: monadic build systems". The operator
names monadic builds as one of the inspirations.

Framing (supporting argument, not evidence): Samuel Colvin, "The code IS the
graph" (2026-10-13, <https://x.com/samuelcolvin/status/2110055467007303729>).
It argues that control flow in code is the workflow graph, that durability comes
from replaying code against recorded results (Temporal outside a sandbox, Monty
snapshots inside), and that a `gather` pauses as one snapshot with all its
pending calls. Treadle is a third route to the same model: replay without a
server, with calls answered by any harness.

Carried over from the tracker, where they were tested: worker IDs are opaque strings, namespaced session IDs or kept UUIDs,
never role names; release succeeds only for the current holder. Claims keep both
rules.

Preferences: the operator prefers Pydantic AI for its depth and support, and an
in-process mechanism because the cache must serve operations other than model
calls.

Missing evidence at the decision: real models, real harness sub-agents, long
workflows, agents with tools, Python versions other than 3.13.

## Alternatives and consequences

- **Keep the tracker and add the step program beside it, using the tracker as
  the job queue.** The original proposal. Rejected: the tracker's dependencies
  and readiness are replaced by control flow. Of its coordination features only
  claims are kept, reimplemented on the store, because sharing a store between
  workers needs them.
- **A completion command (`treadle complete`) that takes and validates answers.**
  Used by the prototype. Replaced by `treadle commit`, which only marks a draft as
  final: Pydantic AI's own output validation and retry handle invalid answers,
  at the cost of one extra round per invalid answer, so `treadle` need not load the
  workflow to accept an answer.
- **Completion by the presence of an answer file.** Considered on 2026-10-15,
  before any implementation. Rejected: a file's presence cannot tell a finished
  answer from one being written. Writing elsewhere and renaming fixes that but
  makes every worker follow a file-system protocol; the operator wants workers
  free to solve their problem however they like, with one explicit command at the
  end. A commit also gives write-once and provenance a single point to happen.
- **Luigi as the engine.** Same replay philosophy and a mature scheduler, with a
  visualiser and history available later. Rejected: identity by parameters
  needs hand-written content keys, waiting on outside work needs a prompt task
  per job, and Luigi workflows cannot be ordinary Pydantic AI code. Sketches
  were written but are not kept.
- **A from-scratch engine with its own decorators.** Rejected in favour of
  ordinary Pydantic AI code, which runs natively in Pydantic AI as well.
- **Workflows as Monty-subset scripts, runnable in `DynamicWorkflow`.**
  Feasible: one script ran in both. Not the base, because Monty is a sandbox
  for model-written code; trusted workflows pay for it in lost imports, dicts
  instead of typed objects, and work moved out of the script. Kept as a later
  option for model-written workflows.
- **An HTTP gateway imitating a model API.** Would serve any framework, but
  needs a server per step and cannot cache non-model operations in process.
- **Pydantic AI's durable-execution engine API.** Per agent run only; the
  workflow-level replay stays ours. Candidate mechanism for agents with tools.
- **Temporal.** Durable and integrated with Pydantic AI, but needs a server and
  a long-running worker, keys results by history position, and runs model
  requests inside its own activities. A possible separate production runner,
  not the engine of `treadle step`.
- **Identity by job name and parameters** (Luigi's model). Gives readable keys
  and explicit invalidation; rejected because Pydantic AI calls carry only the
  prompt, and content keys reuse answers across edits.

Consequences: replaying costs grow with the number of calls per workflow; the
prompt rendering format becomes compatibility data; workflows must follow the
determinism rules; status requires a replay, cheap only when time-consuming
work is cached; tasks written by people need a well-designed inbox workflow,
which is still open; the tracker's assignment, journal and backup features are
gone until a consumer needs them.

## Revisit when

- Real runs show prompt files, typed answers or step counts that coordinators
  cannot handle.
- Pydantic AI changes `Model`, `agent.override`, or message structure in ways
  that break the runner or the key format.
- Agents with tools become necessary.
