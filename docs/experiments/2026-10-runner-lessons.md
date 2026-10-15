# Runner lessons from fake-model development

October 2026. These observations come from local CLI workflows and direct
Pydantic AI runs with fake models, followed by the [live trials](#live-trials).
Current semantics are in [DESIGN](../DESIGN.md); commands and workflow rules are
in [Running Treadle](../RUNNING.md). Functional regressions are in
[test_correctness.py](../../tests/test_correctness.py).

## Callbacks must be visible to the scheduler

Pydantic AI's default synchronous callbacks used anyio threads, invisible to the
runner's executor tracking. This produced missing calls in single and gather
frontiers. The public `Agent.using_thread_executor` hook let the runner track
instructions, system prompts, output validators and output functions without
patching Pydantic AI internals. Cancelling an asyncio waiter did not kill its
running thread: a callback could finish a cached effect after cancellation.
See [callback and shutdown guidance](../RUNNING.md#synchronous-callbacks-and-cancellation).

## Integrity failures cannot depend on exception propagation

A workflow could catch an edited answer's `StoreError` with `except Exception`
and return successfully. The fix remembers fatal store I/O and decoding failures
independently of workflow handlers and checks them before publication and at
`use_store` exit, including after cleanup/thread join. Worker refusals remain a
separate, catchable case; see [answer rules](../RUNNING.md#answer-files-and-commits).

## Cancellation cleanup is not success

Waiting-step cancellation ran `finally` blocks before workflow completion.
Finite cached cleanup could record results and emit uncertainty warnings;
integrity failures and uncaught task-finalizer errors prevented publication.

A cleanup-agent probe recorded an effect in a pre-request callback, then caught
a callback exception before the adapter and still published the original waiting
frontier. Letting the callback return instead reached adapter refusal, but the
effect had already happened. See [cancellation rules](../RUNNING.md#synchronous-callbacks-and-cancellation).

## Loading and text have observable semantics

Synthetic module identities avoided overwriting entries such as `sys.modules["types"]`
when loading `types.py`, while preserving runtime annotations through teardown.
Sibling imports still followed Python caching/shadowing rules. Module-derived
prompts/schema labels could change affected keys without a global format bump;
see [import constraints](../RUNNING.md#trusted-python-and-imports).

Text parity checks needed exact strings, not `.strip()`: spaces, CRLF, LF and
final newlines were answer data. See [answer-file semantics](../RUNNING.md#answer-files-and-commits).

## Keep distinct behavior, reduce duplicate setup

Sharing setup within rejection tests removed duplicate workflow launches while
retaining answer, JSON, path and key variants. An early failed loop assertion
would prevent later variants from running. Exact export-shape assertions and
some redundant parser/example input permutations were deliberately dropped.
Identical concurrent calls could exchange branch-specific answers as arrival
order changed; the counterexample remains in [test_runner.py](../../tests/test_runner.py).

Observed full-suite times on Linux/CPython 3.13.1 with locked Pydantic AI 2.54.0:

| Suite state | Items | Observed elapsed time |
|---|---:|---:|
| Before setup consolidation | 88 | about 163–165 s |
| After consolidation | 64 | about 143–149 s |
| After ten correctness regressions | 74 | about 172–174 s |

These were separate local development runs, including imports and subprocesses;
elapsed times vary with the environment. Fewer pytest items mostly reflected
shared setup while retaining functional cases.

## Live trials

In Pi, `examples/explain.py` ran with the topic `bicycle gears`. The initial step
exited 2 with one call. After the call was claimed, a separate `pi --print`
worker, explicitly selected as `openai/gpt-6.1-sol`, read the prompt, wrote
`answer.md` and committed it itself. The next step exited 0. Repeating that step
returned the same result without another worker call.

The user also reported live runs in Claude Code and Codex.
