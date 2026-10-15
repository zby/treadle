# Implementation plan

## Purpose and current state

Build **treadle**, a task tracker where workflows come first: a step runner for
ordinary Pydantic AI workflows, as decided in
[ADR 001](adr/001-step-runner-for-pydantic-ai-workflows.md) and designed in
[DESIGN.md](docs/DESIGN.md).

Current state (2026-10-15): the repository holds the design, the ADR and the
experiment reports. `src/` is empty. A prototype of version 1 passed functional
tests with fake models in a session scratchpad
([report](docs/experiments/2026-10-pydantic-step-runner.md)); stage 1 ports it.
No real model or harness sub-agent has answered a prompt yet.

## Stage 1: the step runner with claims

Port the prototype into `src/treadle/` with functional tests, applying the
changes made since it ran:

- `treadle commit` replaces `treadle complete` and `treadle fail`: workers write `answer.md`,
  `answer.json` or `failure.md` (and any further files) in the call's directory
  however they like; `treadle commit KEY [FILE...]` writes `commit.json` with the
  SHA-256 of each committed file. Files are attested in place, not copied.
- Typed answers are validated by Pydantic AI on replay; an invalid answer turns
  into a retry request.
- Answers are write-once: a committed call cannot be committed again, and a
  step stops on a committed file whose hash no longer matches.
- Claims: `treadle claim`, `treadle claim --next`, `treadle release`, with leases, under a store
  lock, restricted to the latest open set; provenance recorded from the claim.
- Keys include a scope (the empty string for the workflow, the only scope in
  version 1) and count occurrence indices per scope.
- `@cached` requires an explicit `name=`; the prompt format carries a version in
  every key.

Acceptance, all with fake models and isolated stores:

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
