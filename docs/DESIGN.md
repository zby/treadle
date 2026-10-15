# Design: step-runner internals

[Running Treadle](RUNNING.md) defines commands, API and workflow rules;
[ADR 001](../adr/001-step-runner-for-pydantic-ai-workflows.md) records the engine
choice. This document describes execution and durable identity. Future work and
open choices are in [PLAN.md](../PLAN.md).

## One step

1. Load the trusted workflow module and install an internal `StepModel` on its
   agents through Pydantic AI's public `agent.override(model=...)`.
2. Run the workflow function from the top. Each model request receives a matching
   committed answer as an ordinary model response, or becomes an open call whose
   branch waits. Branches of a supported `asyncio.gather` can all reach this boundary.
3. When no branch can proceed, snapshot the open set, cancel and await pending
   tasks, and finish executor shutdown.
4. Check teardown errors and remembered store-integrity failures before atomically
   publishing `<store>/open.json` and printing the whole frontier (exit 2).
   Completion returns the result (exit 0); an error exits 1.

Everything outside cached calls re-executes; replay cost therefore grows with
uncached work and call count. A native Pydantic AI run starts fresh: it does not
resume a step-mode store.

## Non-guarantees and known limits

- **At-least-once operations.** A crash or exception after a side effect but
  before recording its result can cause repetition. Cached operations must be
  idempotent; the cache does not make effects transactional.
- **No stable branch identity for identical concurrent calls.** Occurrence
  indices follow request arrival order within a scope. As upstream answers
  become available across steps, identical downstream calls can exchange indices
  and receive each other's answers. A [functional counterexample](../tests/test_runner.py)
  records this limit. Use distinct prompts for branch-specific answers, not
  arrival order; changing identity remains a separate design decision.
- **No simultaneous replays on one store.** A `.step.lock` rejects overlapping
  steps and `use_store` runs. Atomic file writes alone cannot establish a
  consistent frontier. Workers may still claim and commit during a step.
- **Local POSIX storage only.** Locking uses `fcntl`; Windows and network
  filesystems are unsupported. Integrity checks require intact, trusted commit
  metadata. Committing files inside a call directory does not attest repository
  edits elsewhere; those need their own version-control commit.

## Rules for workflows

The operational contract is in [Running Treadle](RUNNING.md#cache-operations-not-whole-workflows).
Its execution constraints are essential to frontier correctness:

- Code between calls is deterministic and side-effect-free except through cached
  operations. Mutable inputs may be reread on each step; changes flowing into a
  rendered prompt change its key.
- Supported awaits are agent runs, cached operations, tasks/gathers of them,
  `asyncio.sleep` and `asyncio.to_thread`. Other event-loop I/O is invisible to
  quiescence detection and belongs inside cached operations.
- Waiting steps run task finalizers on cancellation, not just on success.
  Finite cached cleanup retains normal recording, warning and integrity behavior.
  An uncaught finalizer error prevents frontier publication.

  Cleanup agent runs are unsupported. The adapter refuses requests during
  teardown even if committed answers exist. Before a request reaches the adapter,
  system-prompt and instruction callbacks can still perform cached effects.
  Those effects remain if the request is refused or a callback fails earlier,
  even if workflow code catches the failure.

  Do not suppress cancellation or spawn detached cleanup tasks. See
  [shutdown rules](RUNNING.md#synchronous-callbacks-and-cancellation).
- Workflows and imports are trusted Python, not sandboxed. Synthetic module
  names avoid clobbering filename-stem entries in `sys.modules`; temporary sibling
  import support still follows Python caching/shadowing rules. Module-derived
  prompts/schema labels can affect keys. See [import constraints](RUNNING.md#trusted-python-and-imports).
- Agents have unique names. Version 1 does not execute Pydantic AI function tools;
  prompts list them as unavailable, unlike the tools a harness worker uses.

## Prompts and answers

`StepModel` implements Pydantic AI's public `Model` interface; it is not a
package-level export. One model request is one call (for a tool-less agent,
ordinarily one `agent.run`). The versioned prompt renderer includes instructions,
message parts including retry requests, unavailable tools, output schema and
self-contained answer/commit instructions.

Only a commit makes a draft deliverable. Commits attest hashes rather than copy
files ([ADR 002](../adr/002-commit-attests-answer-files-by-hash.md), tentative).
For each reused call, replay verifies all committed files, including auxiliary
files. Missing or changed files, store I/O failures and decoding failures are
fatal even if workflow code catches the exception. After an integrity error,
the step cannot publish successful output or a waiting frontier. `use_store`
also checks at context exit. Earlier effects are not rolled back.

Worker refusals instead become catchable `CallFailed` (`ModelAPIError`)
exceptions.

Text is the exact UTF-8 file, including whitespace and newline spelling. Typed
JSON is returned as an output-tool call, leaving validation to Pydantic AI, not
the commit command. Invalid output causes a retry request with the validation
error: a new prompt and key. Exhausting retries raises Pydantic AI's usual error;
a valid answer becomes the real typed object. See [answer-file rules](RUNNING.md#answer-files-and-commits).

## Answer identity

A key is a SHA-256 over the prompt format version, the **scope**, agent name,
rendered prompt and **occurrence index**: the n-th identical call in its scope
within one replay gets index n. Version 1 has one scope, the workflow, encoded as
an empty string. Scopes reserve room for memoized tasks without changing keys
outside them ([ADR 004](../adr/004-occurrence-indices-per-scope.md), tentative).

- Editing a prompt or its inputs asks again; unchanged prompts reuse answers,
  including across workflow source edits.
- Occurrence indices make repeated identical calls ask again, as in Pydantic AI.
- Rendering and key encoding are compatibility data. Changing the rendering
  format requires a version bump and re-asks everything.
- Early cutoff: if a changed answer leads to unchanged downstream prompts, those
  calls still reuse their answers.

## Lineage: monadic build systems

In *Build Systems à la Carte* (Mokhov, Mitchell and Peyton Jones, ICFP 2018), a
build system combines a scheduler and a rebuilder. Treadle's mapping is:

- **Monadic dependencies:** later calls depend on earlier answers, as when a
  review verdict determines whether to revise; control flow discovers the graph.
- **Restarting scheduler** (§4.1.2) across steps: the whole workflow restarts,
  potentially redoing work. Within a step, asyncio suspends blocked branches
  (§4.1.3) to collect the complete missing frontier.
- **Constructive traces** (§4.2.3): rendered inputs determine content keys, with
  result reuse and early cutoff. Bazel is the paper's restarting/constructive
  neighbour, though its user rules cannot have dynamic dependencies. Cloud Shake
  names the suspending/constructive combination; Treadle's within-step suspension
  sits between these scheduler descriptions.

Unlike deterministic build tasks, workers are nondeterministic agents or people
outside the scheduler. Write-once commits fix one recorded result per call.
A scheduler or rebuilder change is a design change, not an implementation detail.

[Luigi's dynamic dependencies](https://luigi.readthedocs.io/en/stable/tasks.html#dynamic-dependencies)
use a similar restart pattern: yielding unfinished dependencies suspends the
task, and its `run()` restarts from the top when resumed. Its task code must be
idempotent: repeating an operation has the same intended effect as doing it once.
Treadle restarts the whole workflow rather than one task, and uses its own
scheduler and content-based answer keys. The source reading and engine choice
are recorded in [ADR 001](../adr/001-step-runner-for-pydantic-ai-workflows.md);
the project's Commonplace origins are in the [README](../README.md#origins).

## Claims

Claims apply only to calls in the latest `open.json`, not stale unreachable
prompts. A claim records an opaque worker ID, creation time and lease expiry;
expiry is checked on claim, with no background process. Expired leases can be
reclaimed; committed calls cannot be claimed. IDs are not authenticated.
A live claim blocks other workers' claims and commits. `--next` chooses the first
available key in sorted order. Release requires the live holder; expired,
repeated and post-commit releases fail. Commit records worker provenance and ends
the claim; without another holder's live claim, unclaimed commits are allowed.

Claim, release and commit transactions take the exclusive store `.lock`.
Steps and `use_store` hold a separate `.step.lock` replay guard, not the worker
lock throughout execution. A step briefly takes the worker lock to publish
`open.json`. Thus workers can transact concurrently with replay, while the latest
published frontier defines claim eligibility. See [worker commands](RUNNING.md#answer-a-workflow-by-hand-or-from-a-harness).

## Cached operations

Operations use the same store with keys from scope, explicit operation name,
JSON arguments and occurrence index. Names are stable data, independent of Python
function names. Argument spelling is preserved rather than bound to the function
signature: `f(1)` and `f(x=1)`, or omitted and explicit defaults, differ. Keyword
ordering does not matter.

Results are JSON-serialized and validated back through the return annotation;
the first execution returns the same round-tripped value as replay. Exceptions
are not stored. Recording follows execution, so retrying an unfinished recorded
attempt emits an uncertainty warning; repetition can occur after exceptions or
crashes. An async operation counts as busy until it finishes, so it cannot wrap
an agent lifecycle waiting for external answers. Direct runs use a cache only
inside `use_store(DIR)`; otherwise decorated operations run plainly. See the
[API and usage rules](RUNNING.md#cache-operations-not-whole-workflows).

## Store

```text
<store>/open.json            open set of the latest step
<store>/.lock                worker transactions and open-set publication
<store>/.step.lock           rejects overlapping steps and use_store runs
<store>/<key>/call.json      kind (agent | op), agent/operation name, occurrence
              prompt.md      agent instructions, answer/commit instructions
              answer.md      text answer          }
              answer.json    typed answer         } worker or cached-op result
              failure.md     refusal or failure   }
              ...            auxiliary committed files
              claim.json     worker, claimed-at, lease expiry
              commit.json    worker, committed-at, SHA-256 of committed files
```

Prompts, commits and open sets are published atomically. Answers are write-once:
a second commit is refused. Drafts remain ignored until committed; attestations
require files inside the call directory. Publication does not copy their content.

## Quiescence

"No branch can proceed" is detected by an event-loop subclass overriding only
public methods (`call_soon`, `call_at`, `run_in_executor`) to track queued
callbacks, timers and executor jobs. Pydantic AI's public
`Agent.using_thread_executor` routes synchronous callbacks through tracked jobs,
instead of its default invisible anyio threads. Running cached operations count
as busy. Raw socket I/O awaited directly by the workflow is the excluded blind
spot.

The step owns and joins its executor, including running threads whose waiters
were cancelled, before checking fatal replay state and publishing output. Python
cannot kill a running callback thread: callbacks must terminate or shutdown can
block indefinitely. Finite cleanup runs before publication; adapter refusal
during teardown does not undo pre-request callback effects.

## Not in version 1

The backlog is in [PLAN.md](../PLAN.md#later-each-on-a-demonstrated-need).
Memoized tasks have additional design constraints worth retaining before any
implementation:

- A finished lifecycle's result would be cached so replay skips its body,
  restarting at task granularity. Replay cost and determinism constraints would
  then apply only to unfinished tasks, and a tracker could show lifecycle tasks
  rather than individual model calls.
- A task must differ from an operation: while running it must remain transparent
  to quiescence, whereas an async cached operation counts as busy and would never
  let a waiting step finish.
- Each task needs a nested scope, proposed as its name plus a hash of JSON
  arguments. Skipping a body must not shift other calls' occurrence indices.
- Identity by name/arguments means edits to prompts inside finished tasks do not
  re-ask them: Luigi's invalidation trade-off, requiring an invalidation command.
- A task that raises would not be stored and would rerun next step.
