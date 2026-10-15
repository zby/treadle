# Implementation plan

## Purpose and current state

Build **treadle**, a task tracker where workflows come first: a step runner for
ordinary Pydantic AI workflows, as decided in
[ADR 001](adr/001-step-runner-for-pydantic-ai-workflows.md) and designed in
[DESIGN.md](docs/DESIGN.md).

Current state (2026-10-15): Stage 1 is implemented in `src/treadle/`, with
functional tests in `tests/`, an introduction in `examples/explain.py`, a
second example in `examples/review_loop.py`, and an
offline driver in `scripts/fake_review.py`. Usage and supported limits are in
[Running Treadle](docs/RUNNING.md). Earlier prototype evidence is in the
[experiment report](docs/experiments/2026-10-pydantic-step-runner.md).
The early working prototype has also run with live agents in Pi, Claude Code and
Codex. In Pi, a separate worker answered and committed the
single call from `examples/explain.py`; the next step completed and a repeat
replayed the same result. [Runner lessons](docs/experiments/2026-10-runner-lessons.md)
collects the technical findings, live-trial observation and observed test runtimes.
Stage 2's real coding task, typed review and parallel-worker trial remain planned.

## Stage 1: the step runner with claims

The [design](docs/DESIGN.md) defines runtime semantics and
[known limits](docs/DESIGN.md#non-guarantees-and-known-limits).
The current commands are `treadle step`, `treadle claim`, `treadle commit`, and
`treadle release`.

### Current capabilities

- Tracked synchronous Pydantic AI callbacks participate in complete step
  frontiers; executor threads are joined before output.
- Store I/O and decoding failures remain fatal even when workflow code catches
  them, including during finite cached cleanup. Worker refusals remain catchable.
- Synthetic workflow module identities avoid overwriting filename-stem modules;
  workflows and their imports remain trusted Python, not isolated or sandboxed.
- Text answers preserve exact whitespace and newlines. Cancellation runs
  finalizers on waiting steps; cleanup agent runs are unsupported and adapter
  refusal does not prevent pre-request callback side effects.

See [Running Treadle](docs/RUNNING.md) for operational limits and
[correctness regressions](tests/test_correctness.py) for functional examples.

### Development checklist

Functional goals exercised with fake models and isolated stores:

- The example workflow (`examples/review_loop.py`) runs unchanged directly in
  Pydantic AI and under `treadle step` driven by a fake coordinator that writes answer
  files, with equal results.
- All calls issued in the branches of a gather are printed in the same step.
- A repeated identical call is asked again (occurrence index).
- A valid typed answer reaches the workflow as the real typed object; an invalid
  one produces a retry prompt containing the validation error; exhausted retries
  end the step with exit 1.
- `failure.md` raises `CallFailed` in the workflow; uncaught, the step exits 1.
- An answer without a commit is not delivered; a second commit is refused; a
  committed file that is edited or deleted stops the next step with exit 1,
  naming it; a commit with no answer file, with both answer and failure files,
  with a typed answer that is not one JSON object, or naming a missing file or a
  file outside the call's directory is refused; further committed files are
  listed with their hashes in `commit.json`.
- Two concurrent workers claiming with `--next` get different calls; a live claim
  blocks another worker; an expired lease can be reclaimed; a call outside the
  latest open set cannot be claimed; release by anyone but the live holder, and
  a repeated release, fail; a commit while another worker holds a live
  claim is refused; the committing worker is recorded as provenance and the claim
  ends.
- A cached side-effecting operation runs once across a multi-step run; a cached
  clock value is stable across replays; an exception is retried on the next step.
- Replays are deterministic: identical output over repeated runs.
- Step output has one stable line per open call and ends with the next action;
  a test script parses it and drives a workflow to completion with no agent
  (codification level 3, with a fake worker).
- A workflow that awaits unsupported I/O is documented, not silently wrong.
- `uv sync --locked`, `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .` and `uv build` pass.

## Stage 2: a tracker trial on real work

The **next planned application is a task-tracker example**, suggested by the
user. It is not implemented. Use it to explore real work without yet choosing
the task-file format or closing, dropping and reopening semantics; those remain
open design questions.

With real harness sub-agents answering, run on real tasks in this repository:

- the inbox workflow (DESIGN.md, "Tasks written by people"): settle the task-file
  format, closing and dropping, and what editing a done task means;
- one task type with a lifecycle: implement, verify, repair up to N rounds;
- two workers sharing a store through claims.

Record step counts, prompt clarity problems, answer-format failures, claim
conflicts, orchestrator mistakes (missed commits, misrouted or skipped prompts,
early stops) and timings. Each orchestrator mistake is a candidate for moving a
duty into a hook or script (DESIGN.md, "Progressive codification").

## Later, each on a demonstrated need

- Divide the growing functional test suite when separately commissioned.
- Stable branch identity for identical concurrent calls, if distinct prompts are
  insufficient; revisit ADR 004 before changing answer keys.
- Agents with Pydantic AI tools (see DESIGN.md, "Not in version 1").
- Cache-through for direct runs, making plain Pydantic AI runs resumable and
  able to continue a run started under `treadle step`.
- Ready-made hooks and driver scripts, once stage 2 shows which duties fail.
- Recording which model produced an answer (the worker is recorded via claims).
- An invalidation command.
- Model-written workflows in the Monty subset.
- A Temporal runner for the same workflow files.
- Sharing answers between stores (constructive traces across runs).
- Memoized tasks (restarting at task granularity), when stage 2 replays get slow
  or the inbox holds many finished tasks.
