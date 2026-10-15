# Design: a task tracker where workflows come first

**Status:** version 1 design and Stage 1 implementation, 2026-10-15. The runner
is in `src/treadle/`, with functional fake-model tests in `tests/` and an offline
driver in `scripts/fake_review.py`. Live agents have answered prompts in Pi,
Claude Code and Codex. Stage 2 of [PLAN.md](../PLAN.md) covers a
real coding task, typed review and parallel workers. See [Running Treadle](RUNNING.md)
for commands and supported inputs. Earlier feasibility evidence is in the
[prototype report](experiments/2026-10-pydantic-step-runner.md); the decision and
alternatives are in
[ADR 001](../adr/001-step-runner-for-pydantic-ai-workflows.md).

## Purpose

Treadle runs one workflow, written as ordinary Pydantic AI code, from any agent
harness and natively in Pydantic AI; who it is for is in
[POSITIONING.md](POSITIONING.md). It is also a task tracker built the other way
round. Task trackers start with tasks and dependencies, then grow workflows: status
fields, per-type state machines, automation rules, and eventually a
configuration language that turns into a weak programming language. Treadle
starts from the other end. Workflows are ordinary [Pydantic AI](https://ai.pydantic.dev)
code with the full language available, and the tracker is a view of their state:

- an open task is a model call waiting for an answer;
- a done task is a call whose answer is committed;
- a task type is an async function: its lifecycle (for example implement, verify,
  repair up to N rounds);
- dependencies are control flow: a task appears once its inputs exist.

The same workflow file runs in two places:

1. **In Pydantic AI**, with real models, the normal way.
2. **Under `treadle step`**, from any agent harness (Claude Code, Codex, pi, a script).
   Every model call becomes a prompt for the harness's own sub-agents, or for a
   person. The workflow's progress lives in a store, not in anyone's context.

The workflow does not import Treadle unless it uses
[cached operations](#cached-operations).

Between the two lies a path: an agent runs the loop at first, and users move its
duties into code as needed ([progressive codification](#progressive-codification)).

## The loop

```text
treadle step WORKFLOW.py:FUNCTION --inputs JSON --store DIR
  exit 2: prints every open call: key, agent, prompt file, holder of a live claim
treadle claim KEY --worker W --store DIR            (or: treadle claim --next --worker W)
  ── the worker reads prompt.md and drafts its answer in the call's directory
treadle commit KEY [FILE...] --worker W --store DIR  records the files' hashes
treadle step ...                                     (again, same arguments)
  exit 0: prints the result as JSON
  exit 1: the workflow raised; prints the error
```

A task is done when its answer is committed. A draft file alone is not an
answer: its presence cannot tell a finished answer from one still being written,
and making it tell (write elsewhere, then rename) would be one more rule every
worker must follow. With `treadle commit`, workers write and rewrite drafts however
they like, and one command marks the end. A coordinator answering alone needs no
claims, but still commits. Anyone can continue a workflow by running `treadle step`
again; status is always obtained this way.

## Progressive codification

At first an orchestrator agent in the harness runs the loop: it runs `treadle step`,
hands each printed prompt to a sub-agent (or answers it), makes sure each answer
is committed, and runs `treadle step` again. This is deliberately contained work. The
workflow code decides what happens next; the orchestrator mostly follows what
the step output tells it, so its job stays small however complex the workflow.

When the orchestrator starts failing at a duty (forgets to commit, misroutes a
prompt, stops early), that duty moves into code, one at a time, with the
workflow file unchanged:

1. **Agent:** the orchestrator does everything, following the step output.
2. **Hooks:** harness hooks take over mechanical duties, for example committing
   when a sub-agent finishes or re-running `treadle step` after a commit.
3. **Driver script:** a script runs the whole loop and dispatches prompts to the
   harness's non-interactive mode or to a model API; the agent only watches.
4. **Native:** the workflow runs in Pydantic AI itself, or in any harness that
   runs Python code.

This sets rules for the CLI:

- Every orchestrator duty is a `treadle` command with defined exit codes, so a hook
  or script can do it without an agent.
- Step output is stable and line-based, one line per open call, and ends with
  the next action in plain words, so the same text serves an agent and a script.
- Prompts are self-contained: a sub-agent needs nothing from the orchestrator's
  context, and a script can hand a prompt file to any worker.

Moving a run that is already in progress from levels 1–3 to level 4 needs
cache-through (see [Not in version 1](#not-in-version-1)); until then a native
run starts fresh.

## One step

1. Load the workflow module. Install a `StepModel` on each of its agents with
   Pydantic AI's public `agent.override(model=...)`.
2. Run the workflow function from the top.
3. Each model request either gets its stored answer, returned as an ordinary
   model response, or is recorded as an open call; that branch then waits.
4. When no branch can proceed, snapshot the open set, cancel and await pending
   tasks, and finish executor shutdown. Only after checking for teardown and
   remembered store-integrity failures, write the open set atomically to
   `<store>/open.json`, print all open calls together, and exit 2. Calls issued in
   every branch of a supported `asyncio.gather` appear in the same step.

A step re-executes everything that is not cached, so status is cheap only when
every time-consuming operation is a cached call. The prototype took about 0.8 s
per step, mostly importing Pydantic AI.

## Non-guarantees and known limits

These limits apply to version 1. Deferred work is tracked in
[PLAN.md](../PLAN.md#later-each-on-a-demonstrated-need).

- **Cached operations can repeat.** An operation can run again after an
  exception or a crash between its side effect and recording its result.
  Operations must be idempotent.
- **No stable branch identity for identical concurrent calls.** Occurrence
  indices follow request arrival order within a scope. As upstream answers
  become available across steps, identical downstream calls can exchange their
  occurrence indices and receive each other's answers. A
  [functional counterexample](../tests/test_runner.py) records this limit. Use
  distinct prompts when answers are branch-specific; do not rely on arrival
  order. Changing the identity rule remains a separate design decision.
- **No simultaneous steps on one store.** Atomic file writes alone do not
  establish a consistent frontier between concurrent replays. A separate
  `.step.lock` guard rejects overlapping steps and `use_store` runs. Workers may
  still claim and commit while a step runs.
- **Answer commits cover files inside the call's directory.** Code a worker
  edits elsewhere needs its own version-control commit.

## Rules for workflows

- Code between agent calls must be deterministic and free of side effects,
  except through cached operations. It is re-executed on every step.
- Reading mutable inputs (for example a directory of task files) on every step is
  allowed. Changes that flow into a rendered prompt change its content key.
  Identical concurrent calls still have the arrival-order limitation above.
- The workflow awaits only agent runs, cached operations, gathers and tasks of
  them, `asyncio.sleep` and `asyncio.to_thread`. Other I/O awaited directly on
  the event loop is invisible to quiescence detection; do it inside a cached
  operation.
- A waiting step cancels pending tasks, so their `finally` blocks run on every
  step. Use finalizers for finite resource cleanup, not success-only effects.
  Finite cached cleanup operations retain normal recording/warning/integrity
  behavior. Cleanup agent runs are prohibited. Model requests reaching the
  adapter during teardown are refused. System-prompt and instruction callbacks
  can execute cached operations before the adapter, even if the run subsequently
  fails and that failure is caught. Do not suppress cancellation or create
  detached cleanup tasks. See
  [cancellation guidance](RUNNING.md#synchronous-callbacks-and-cancellation).
- Workflows are trusted Python, not sandboxed. A synthetic module name avoids
  clobbering `sys.modules` by filename; temporary sibling import support still
  follows ordinary Python import caching/shadowing rules. See
  [import constraints](RUNNING.md#trusted-python-and-imports).
- Every agent has a unique `name=`.
- Version 1 agents have no Pydantic AI function tools. Their tools are listed in
  the prompt as unavailable.

## Prompts and answers

`StepModel` is an internal Pydantic AI `Model` subclass, not a top-level package
export. One model request is one call;
for an agent without tools, one request is one `agent.run`.

`<store>/<key>/prompt.md` contains the agent's instructions, every message part
(system prompt, user prompt, retry requests), the unavailable tools, and the
answer instructions:

- **Where:** draft the answer in `answer.md` (text agents) or `answer.json`
  (typed agents) in the key's directory, in any way and as many times as needed.
- **Format:** plain text, or one JSON object matching the output schema, which
  the prompt includes. Text is the entire UTF-8 file, including leading/trailing
  whitespace and final newlines; no stripping or newline normalization occurs.
- **Refusal or failure:** draft `failure.md` with the reason instead. The
  `agent.run` then raises `CallFailed`, a subclass of `ModelAPIError`, the error
  a provider failure raises. Uncaught, it ends the step with exit 1.
- **Other files:** the worker may produce further files in the key's directory
  (notes, reports, data) and refer to them in the answer.
- **Commit:** run `treadle commit KEY [FILE...] --worker W --store DIR`, the command
  printed in the prompt, naming any further files to commit with the answer.

A commit attests files; it does not copy them (tentative:
[ADR 002](../adr/002-commit-attests-answer-files-by-hash.md)). `treadle commit`, under
the store lock:

- refuses if another worker holds a live claim, if the call is already
  committed, if there is no answer file or both an answer and a failure file, if
  a typed answer is not one JSON object, or if a named file is missing or lies
  outside the key's directory;
- writes `<key>/commit.json` atomically: worker, committed-at, and the SHA-256 of
  each committed file (the answer file plus the named files);
- ends the worker's claim.

`commit.json` stays small however large the answer, and the files stay plain,
readable by people and agents where the worker wrote them. A call is done when
`commit.json` exists; before that, `treadle step` ignores the files. Schema checks are
not done at commit: the command does not load the workflow.

**Validation is Pydantic AI's.** On replay the stored JSON is returned as the
output-tool call. If it does not validate, Pydantic AI sends a retry request with
the error, as it would to any model; that request is a new call with a new
prompt showing the error. After the agent's retry limit, the workflow gets
Pydantic AI's usual error. A valid answer reaches the workflow as the real typed
object.

**Answers are write-once.** A committed call cannot be committed again. Every
step checks the hashes of the files it reads against `commit.json`; a changed or
missing committed file stops the step with exit 1, naming the file, instead of
silently changing a past result. Replay remembers store I/O and decoding failures
independently of workflow exception handlers; a caught integrity error cannot
produce a successful result or waiting frontier. `use_store` also raises at its
context boundary. Worker refusals remain catchable `CallFailed` exceptions.
These checks require intact, trusted commit metadata and a local POSIX store.
Keep committed files and metadata unchanged so workflow code reads the same
content on every replay.
Replacing an answer is a future invalidation command, not an edit.

## Answer identity

A key is a SHA-256 over the prompt format version, the **scope**, the agent
name, the rendered prompt, and an **occurrence index**: the n-th identical call
within its scope in one replay gets index n. In version 1 there is one scope,
the workflow itself, written as the empty string; scopes exist so that memoized
tasks can be added later without changing the keys of calls outside them
([ADR 004](../adr/004-occurrence-indices-per-scope.md), tentative).

- Content keys: editing a prompt, or anything that flows into it, asks again;
  calls whose prompts did not change keep their answers, also after the workflow
  code is edited.
- The occurrence index makes a repeated identical call ask again, as a model
  would be asked again in Pydantic AI.
- The rendering format is part of every key, so it is compatibility data.
  Changing it means bumping the format version, which re-asks everything.
- Early cutoff: when a call is asked again but its new answer leads to the same
  downstream prompts, those calls keep their answers.

## Lineage: monadic build systems

The design follows *Build Systems à la Carte* (Mokhov, Mitchell and Peyton
Jones, ICFP 2018), which splits a build system into a scheduler and a rebuilder
and distinguishes applicative tasks, whose dependencies are known in advance,
from monadic ones, whose dependencies depend on the results of other tasks.

- **Monadic.** A workflow is a monadic build: which calls it makes depends on
  earlier answers. This is why dependencies are control flow and not a graph
  declared up front, and why task trackers that declare graphs end up growing
  workflow languages.
- **Restarting scheduler** (§4.1.2). The paper's restarting scheduler aborts a
  task that fetches an out-of-date dependency, builds the dependency, and
  restarts the task later; it is not minimal, since a task may redo work before
  aborting again. Each `treadle step` does this to the whole workflow: it runs from
  the top until it needs results it lacks. Within one step, asyncio suspends
  blocked branches (the paper's suspending scheduler, §4.1.3), so every missing
  result of a `gather` is collected before the step stops.
- **Constructive traces** (§4.2.3). Answers are stored under a hash of
  everything the call depends on (the rendered prompt carries its inputs), so a
  result can be reused wherever the same call appears, with early cutoff.
- **Neighbours in the paper's Table 2.** Excel is restarting with a dirty bit;
  Bazel is restarting with constructive traces, the closest match, though
  Bazel's user-defined rules cannot have dynamic dependencies (Table 1, §2.4).
  Suspending with constructive traces was the empty cell the paper names Cloud
  Shake (§5.4); our within-step suspension sits between the two.
- **Restarting single tasks.** The paper restarts one task, not the whole
  build. Our equivalent would be memoized tasks (see
  [Not in version 1](#not-in-version-1)): a finished lifecycle call is skipped
  on replay, so only unfinished tasks re-run.
- **Where it differs.** Build tasks are deterministic programs; here most tasks
  are agents or people, nondeterministic and slow. Write-once commits make each
  answer the single recorded result, and the restart cost is small compared to
  the work. The worker is outside the build system, reached through prompts and
  claims.

The paper's vocabulary is a check on later changes: a change of scheduler or
rebuilder is a change to this design, not an implementation detail.

## Claims

Claims stop two workers from doing the same call.

| Command | Effect |
|---|---|
| `treadle claim KEY --worker W [--lease 30m]` | Claim one call. Fails if another worker holds a live claim or the call is answered. |
| `treadle claim --next --worker W` | Claim the first unclaimed call of the latest open set (sorted by key). |
| `treadle release KEY --worker W` | Give a claim back. Fails unless W holds a live claim on the call: a repeated release, another worker's claim, an expired one and a committed call all fail. |

- Only calls in the latest `open.json` can be claimed, so a prompt from an
  earlier step that control flow no longer reaches is not handed out.
- A claim is `<key>/claim.json`: worker, claimed-at, lease expiry. An expired
  lease can be claimed again; expiry is checked when claiming, with no
  background process.
- `treadle commit` ends the claim and records the committing worker in
  `commit.json`: that is the answer's provenance. Committing without
  a claim is allowed when no other worker holds a live one; `--worker` is then
  optional.
- The worker ID is an opaque string. Use the harness session ID, namespaced
  (`claude:<session-id>`), or a UUID kept for the session's lifetime. A resumed
  session keeps its ID; a replacement session gets a new one. Names such as
  "implementer" are not IDs: two workers would share them. `treadle` does not
  authenticate IDs.
- Claim, release and commit take an exclusive `.lock` on the store, so they are
  atomic with respect to each other. Steps and `use_store` runs take a separate
  `.step.lock` guard to reject overlapping replays, without holding the worker
  lock throughout execution. A step briefly takes the worker lock to publish
  `open.json`; prompts, commits and the open set are published atomically.
- Local POSIX filesystems only in the current implementation (`fcntl` locking).
  Windows and network filesystems are not supported.

## Cached operations

Operations other than agent calls go through the same store:

```python
from treadle import cached


@cached(name="acquire")
def acquire(source: str, commit: str) -> str:
    """Idempotent clone and checkout; replays reuse the recorded path."""
```

- Key: scope, operation name, JSON of the arguments, occurrence index. The name is
  required, so renaming the Python function does not lose stored results.
  Positional and keyword argument spelling is preserved, not bound to the
  function signature: `f(1)` and `f(x=1)` differ, as do omitted and explicit
  defaults. Keyword ordering does not matter. Keep spelling stable for reuse;
  this describes the existing key format, not a normalization or format change.
- The result is stored as JSON and validated back into the return annotation.
  The first execution returns the same round-tripped value a replay gets.
- Exceptions are not stored: the operation runs again on the next step.
- Recording happens after the operation. If the process dies in between, the
  operation runs again (at-least-once), so it must be idempotent itself.
- In a direct Pydantic AI run, cached operations use a store only inside
  `use_store(DIR)`; otherwise they run plainly.

## Store

```text
<store>/open.json            open set of the latest step
<store>/.lock                serializes worker transactions and open-set publication
<store>/.step.lock           rejects overlapping steps and use_store runs
<store>/<key>/call.json      kind (agent | op), agent or operation name, occurrence
              prompt.md      agent calls: what to do, where to answer, how to commit
              answer.md      text answer          }
              answer.json    typed answer         } written by the worker,
              failure.md     refusal or failure   } or by treadle for cached operations
              ...            further files the worker commits with the answer
              claim.json     worker, claimed-at, lease expiry
              commit.json    worker, committed-at, SHA-256 of each committed file
```

## Quiescence

"No branch can proceed" is detected by an event-loop subclass that overrides only
public methods (`call_soon`, `call_at`, `run_in_executor`) and tracks queued
callbacks, timers and executor jobs. Pydantic AI's public
`Agent.using_thread_executor` context routes sync callbacks through the tracked
`run_in_executor`, rather than its default invisible anyio threads. The step
owns and joins that executor, including running threads whose waiters were
cancelled, before checking fatal replay state and publishing output. Python
cannot kill a running callback thread; callbacks must terminate. A running
cached operation counts as busy. Raw socket I/O awaited directly by the workflow
is the known blind spot, excluded by the rules.

## Tasks written by people (open design)

Tasks that people write go through a standard inbox workflow: it reads
`tasks/*.md` on every step and runs each task's lifecycle function, chosen by a
`type:` line, in parallel. An `after:` line becomes an `await` on another task.
Deleting a file stops its calls from being issued. Open questions:

- How a person closes or drops a task (`status: dropped`?).
- Editing a done task changes its prompt and so asks again. When that is wanted
  (a changed requirement) and when not (a typo fix) must be a decision, not an
  accident of content keys.
- The task-file format and which lifecycle functions ship with Treadle.

## Not in version 1

- Agents with Pydantic AI tools. Recommended route: the worker may answer with
  tool calls; Pydantic AI runs the tools during replay, and each tool run is
  cached like an operation. Pydantic AI's durable-execution API
  (`CallableOperationBackend`, `@durable_operation`) is the candidate mechanism.
- Cache-through for direct runs: a real model behind `StepModel`, storing as it
  goes, so a plain Pydantic AI run becomes resumable and can continue a run
  started under `treadle step`.
- Harness-specific hooks and driver scripts for codification levels 2 and 3.
  The offline fake driver demonstrates the CLI protocol, not harness dispatch.
- Recording the model that produced an answer (the worker is recorded via claims).
- An invalidation command.
- Model-written workflows in the Monty subset (`DynamicWorkflow`).
- Running the same workflow under Temporal.
- Sharing answers between stores, as constructive traces allow (a cloud build
  cache for agent work).
- **Memoized tasks**, restarting at task granularity. A lifecycle function marked
  as a task (for example `draft(topic)`) stores its result when it finishes;
  replays skip its body, so replay cost and the determinism rules apply only to
  unfinished tasks, and the tracker can show tasks rather than model calls.
  Needed before it works:
  - a task kind distinct from cached operations: memoized when finished, but
    transparent to quiescence while running (the prototype's async `@cached`
    counts as busy and would never let a step finish);
  - nested scopes: each task opens a scope named by its name and the hash of its
    JSON arguments, so a skipped body cannot shift other calls' occurrence
    indices;
  - task identity by name and arguments: editing a prompt inside a finished task
    does not re-ask it, which is Luigi's trade-off and needs an invalidation
    command;
  - a task that raises is not stored and re-runs on the next step.
