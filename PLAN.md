# Implementation plan

## Current state

The early working prototype is described in the [README](README.md).
[Running Treadle](docs/RUNNING.md) defines usage and workflow rules;
[tests/](tests/) contains the functional acceptance cases, including CLI/direct
Pydantic AI parity and correctness regressions. Contributor checks are in
[AGENTS.md](AGENTS.md).

## Stage 2: a tracker trial on real work

The **next planned application is a task-tracker example**, suggested by the
user. It is not implemented. With real harness sub-agents answering, run on real
tasks in this repository:

- An inbox workflow reading `tasks/*.md` on each step, choosing a lifecycle by
  `type:` and running tasks in parallel; an `after:` line could await another task.
  Deleting a file would stop issuing its calls. This is a proposal, not a format
  decision.
- One task type with a lifecycle: implement, verify with typed review verdicts,
  repair up to N rounds.
- Two workers sharing a store through claims.

Open choices: the task-file format and which lifecycle functions ship; how a
person closes or drops a task; and when editing a done task reopens it. A changed
requirement and a typo fix should not accidentally have the same reopening
semantics just because both can change a content key.

Record step counts, prompt clarity problems, answer-format failures, claim
conflicts, orchestrator mistakes (missed commits, misrouted or skipped prompts,
early stops) and timings, including long-run replay cost. Observe idempotency of
real operations and whether workers find hash-only, multi-file commits useful.
Each orchestrator mistake is a candidate for moving a duty into a hook or script
([ADR 003](adr/003-progressive-codification.md)).

## Later, each on a demonstrated need

- Divide the growing functional test suite when separately commissioned.
- Stable branch identity for identical concurrent calls, if distinct prompts are
  insufficient; revisit [ADR 004](adr/004-occurrence-indices-per-scope.md) before
  changing answer keys.
- Agents with Pydantic AI function tools: a candidate route is worker-returned
  tool calls, executed by Pydantic AI during replay and cached through its public
  durable-execution API (`CallableOperationBackend`, `@durable_operation`).
- Cache-through for direct runs, making plain Pydantic AI runs resumable and
  able to continue a run started under `treadle step`.
- Ready-made hooks and driver scripts, once stage 2 shows which duties fail.
- Recording which model produced an answer (the worker is recorded via claims).
- An invalidation command.
- A Temporal runner for the same workflow files.
- Sharing answers between stores (constructive traces across runs).
- Memoized tasks (restarting at task granularity), when stage 2 replays get slow
  or the inbox holds many finished tasks; see the
  [design constraints](docs/DESIGN.md#not-in-version-1).
