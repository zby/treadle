# Runner lessons from fake-model development

October 2026. Treadle is an early working prototype. These findings come from
local CLI workflows and direct Pydantic AI runs with fake models. A later
[live-trial observation](#live-trials) follows below. Current semantics live in
[DESIGN](../DESIGN.md); operational guidance lives in [Running Treadle](../RUNNING.md).

## Callbacks must be visible to the scheduler

Pydantic AI's default synchronous callbacks use anyio threads, invisible to the
runner's event-loop executor tracking. This produced missing calls in single
and gather frontiers. The public `Agent.using_thread_executor` hook routes sync
instructions, system prompts, output validators and output functions through
tracked `run_in_executor` jobs, without patching Pydantic AI internals.

The step owns and joins that executor before output. Cancelling an asyncio
waiter does not kill its running Python thread: a callback may finish a cached
side effect after cancellation. Callbacks must terminate; a blocked thread can
hold shutdown indefinitely. See [callback guidance](../RUNNING.md#synchronous-callbacks-and-cancellation)
and [functional regressions](../../tests/test_correctness.py).

## Integrity failures cannot depend on exception propagation

A workflow could previously catch an edited answer's `StoreError` with
`except Exception` and return successfully. Replay now remembers fatal store I/O
and decoding failures independently of workflow handlers. Step publication and
`use_store` context exit check that state, including after cleanup and thread
join. Worker `CallFailed` refusals remain catchable.

Edited or missing answers and auxiliary files must fail replay even after a
caught error. This requires intact, trusted commit metadata. Effects already
performed remain. Work using `use_store` must finish before context exit.
See [answer rules](../RUNNING.md#answer-files-and-commits).

## Cancellation cleanup is not success

Waiting steps cancel and await pending tasks while model/cache contexts remain
active. Their `finally` blocks run on waiting steps, not only on completion.
Finite cached cleanup can record results and emit uncertainty warnings;
integrity failures and uncaught task-finalizer errors prevent publication.
Keep success-only effects after the required answers arrive.

Cleanup agent runs are unsupported. A system-prompt or instruction callback can
perform a cached operation before the model request is rejected. A probe recorded
such an effect, then caught a callback exception before the adapter and still
published the original waiting frontier. Letting the callback return instead reached adapter refusal,
but the effect had already happened. Finalizers must be finite; do not suppress
cancellation or spawn detached cleanup tasks. Explicitly close resources rather
than relying on GC.

## Loading and text have observable semantics

Synthetic module identities avoid overwriting `sys.modules` entries such as
`types` when loading `types.py`, while preserving runtime annotations through
teardown. Temporary sibling-import support still follows Python caching and
shadowing rules; imported siblings remain cached. This is trusted Python, not
package isolation or a sandbox. Synthetic names can affect module-derived
prompts or schema labels and thus affected answer keys, even without a global
prompt/key-format change. See [import constraints](../RUNNING.md#trusted-python-and-imports).

Text answers are the whole UTF-8 file: leading/trailing spaces, CRLF, LF and final
newlines are data, with no trimming or newline normalization. Native/step parity
must compare exact strings, not `.strip()` results.

## Keep distinct behavior, reduce duplicate setup

Functional tests use real CLI subprocesses, isolated stores and direct fake-model
runs, inspecting output, exit codes and files. Sharing setup within rejection
tests removed duplicate workflow launches while retaining the answer, JSON,
path and key variants. The trade-off is that an early failed loop assertion
prevents later variants from running. Exact export-shape assertions and some
redundant parser/example input permutations were deliberately dropped.

Keep distinct coverage for replay/fan-out, typed retries, failures, hash checks,
concurrent claims, cache uncertainty, unsupported awaits, text/JSONL rendering
and the installed console entrypoint. See the maintained [tests](../../tests/).
Identical concurrent calls can still exchange branch-specific answers as arrival
order changes; use distinct prompts.

Observed full-suite times on Linux/CPython 3.13.1 with locked Pydantic AI 2.54.0:

| Suite state | Items | Observed elapsed time |
|---|---:|---:|
| Before setup consolidation | 88 | about 163–165 s |
| After consolidation | 64 | about 143–149 s |
| After ten correctness regressions | 74 | about 172–174 s |

These are separate local development runs; elapsed times vary with the
environment. Fewer pytest items mostly reflected shared setup while retaining
functional cases. Each timing includes imports and subprocesses.

## Live trials

In Pi, `examples/explain.py` ran with the topic `bicycle gears`. The initial step
exited 2 with one call. After the call was claimed, a separate `pi --print`
worker, explicitly selected as `openai/gpt-6.1-sol`, read the prompt, wrote
`answer.md` and committed it itself. The next step exited 0. Repeating that step
returned the same result without another worker call.

The user also reported live runs in Claude Code and Codex.

## Next work

Stage 2's [task-tracker trial](../../PLAN.md#stage-2-a-tracker-trial-on-real-work)
will cover a real coding task, typed review and parallel workers, recording
prompt clarity problems and orchestrator mistakes. Long-run replay cost and
idempotency in real operations still need observation. Current locking supports
local POSIX filesystems; other Python versions and platforms remain untested.
The usefulness of hash-only commits, nested scopes and external naming conflicts
remain open questions.
