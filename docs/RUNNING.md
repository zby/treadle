# Running Treadle

Treadle runs trusted Python workflows. Use a local POSIX filesystem store
(locking uses `fcntl`; Windows is not supported) and keep workflow code
deterministic and free of side effects outside cached operations.
See the [design's known limits](DESIGN.md#non-guarantees-and-known-limits).

## Try it without a model API

From the repository, run `uv sync --locked` first.

### Start with one agent

[examples/explain.py](../examples/explain.py) contains a named, model-less
Pydantic AI agent and `async def workflow(topic)`. Step mode supplies the model:

```sh
uv run treadle step examples/explain.py:workflow \
  --inputs '{"topic": "a loom"}' --store /tmp/treadle-explain-demo
```

Follow the claim/write/commit instructions below, then repeat the step. For a
native run of the same workflow, supply a model using Pydantic AI's public
override context. This offline check needs no credentials or provider SDK:

```sh
PYDANTIC_AI_NO_BANNER=1 uv run python - <<'PY'
import asyncio
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.test import TestModel
from examples.explain import explainer, workflow

with override_allow_model_requests(False), explainer.override(
    model=TestModel(custom_output_text="A loom weaves cloth.")
):
    print(asyncio.run(workflow("a loom")))
PY
```

It prints `A loom weaves cloth.`. To run with a real model, supply your model in
`explainer.override(model=...)`, omit the offline
`override_allow_model_requests(False)` guard, install the provider extra in your
project and configure its credentials. The package itself depends on
`pydantic-ai-slim`.

### Then try a review loop

```sh
uv run python scripts/fake_review.py --store /tmp/treadle-review-demo
uv run python scripts/fake_review.py --direct
```

The two driver commands run the same `examples/review_loop.py` workflow. The
first parses the CLI's JSONL protocol, claims calls, writes fake answers and
commits them until the workflow finishes. The second runs directly in Pydantic
AI with `FunctionModel` overrides. Neither command calls a model API. Use a fresh
store to observe a new run; reusing a completed store replays its answers.

The review example adds gather fan-out, structured verdicts, bounded rewriting
and summarization. `max_rounds` must be positive and bounds the number of
write/review attempts; a final rejection raises without another rewrite.
Successful sections retain a `rounds` field counting **rewrites**, not reviews:
a first-draft acceptance has `rounds: 0`. The example defers its default provider
initialization, so step mode and fake-model overrides need no credentials.

## Answer a workflow by hand or from a harness

```sh
uv run treadle step examples/review_loop.py:workflow \
  --inputs '{"topics": ["a", "b"], "max_rounds": 3}' --store run/
```

The entry point must be an async function accepting the JSON object's keys as
keyword arguments. Agents need unique explicit `name=` values. Treadle discovers
module-level agents; for agents held elsewhere, expose a `TREADLE_AGENTS` list in
the workflow module. Version 1 supports plain text or one structured output type,
not output unions, streaming, native tools or multimodal prompts. Function tools
are listed as unavailable in prompts; step mode does not run them.

A waiting step exits **2**. Each line prefixed `call ` is a JSON object containing
`key`, `agent`, an absolute `prompt` path and the live claim's `holder` (or null).
The last line starts `waiting:` and gives the next action. Run steps serially;
workers may claim and commit concurrently.

For each open call:

```sh
uv run treadle claim --next --worker harness:SESSION_ID --store run/
# Read the returned prompt path. Write the answer at the path the prompt names.
uv run treadle commit KEY --worker harness:SESSION_ID --store run/
```

Use a unique opaque worker ID, not a role name shared by several workers. You
can claim a specific key instead of `--next`. `--lease 30m` is the default;
positive seconds and `s`, `m`, `h` suffixes are supported. To return a live claim:

```sh
uv run treadle release KEY --worker harness:SESSION_ID --store run/
```

A coordinator answering alone may skip claims and omit `--worker` on commit,
provided another worker does not hold a live claim. Keys accept unambiguous
hexadecimal prefixes.

### Answer files and commits

- Text calls use `answer.md`. The entire UTF-8 file is delivered without trimming
  or newline normalization: leading/trailing whitespace and a final newline are
  answer data. For native/step parity, supply the same exact text to both models.
  Structured calls use `answer.json` containing one JSON object; the prompt
  contains the output schema.
- To refuse or report failure, write `failure.md` **instead** of an answer. The
  workflow receives `CallFailed`, which it may catch.
- Drafts can be edited freely. A draft alone is never delivered.
- To attest auxiliary files, place them inside the call directory and pass
  their relative paths: `treadle commit KEY notes.md data/report.json ...`.
  Files outside that directory, symlinks and store metadata are refused.
- Commit records hashes, not copies. A second commit is refused. Do not edit or
  delete committed files: replay stops on a hash mismatch or missing file,
  including auxiliary files. Catching that exception in workflow code cannot
  make a step succeed or publish a waiting frontier. This is different from a
  worker's catchable `CallFailed` refusal.
- Commit checks JSON syntax and that a typed answer is an object, not its output
  schema. Pydantic AI validates on replay. An invalid answer produces a new call
  showing the validation error; answer that new prompt, not the committed one.

Run the same `step` command again after committing answers. Completion exits
**0**, prints `result ` followed by JSON, and ends with a `done:` line. An error
exits **1**. Worker commands return 0 on success and 1 on refusal. Invalid CLI
usage also exits 1; exit 2 is reserved for a waiting step.

### JSONL for scripts

All four commands support `--json`, for example:

```sh
uv run treadle step examples/explain.py:workflow \
  --inputs '{"topic": "a loom"}' --store run/ --json
uv run treadle claim --next --worker script:SESSION_ID --store run/ --json
uv run treadle commit KEY --worker script:SESSION_ID --store run/ --json
uv run treadle release KEY --worker script:SESSION_ID --store run/ --json
```

Each stdout line is one JSON object with a `type` field, with no prose footer:

- `call`: `key`, `agent`, `prompt`, `holder`; `waiting`: `open` count.
- `result`: `result`; `done`: no extra fields.
- `claimed`: `key`, `worker`, `expires_at`, `prompt`.
- `committed` or `released`: `key`.
- `error`: `error` string, including worker refusals, workflow failures and
  argument errors; exit 1.
- `warning`: `warning` string, notably when retrying a cached operation whose
  earlier outcome is uncertain. This does not replace the terminal record.

Exit codes are unchanged. Treadle's JSONL diagnostics go to stdout, not stderr.
`--help` remains human-readable. Workflow code is trusted Python: it must not
print its own prose to stdout if you need a clean protocol. Do not mix the text
and JSONL protocols in one parser. The offline review driver uses JSONL for
step, claim and commit, with explicit claims before writing each answer.

## Cache operations, not whole workflows

```python
from treadle import cached, use_store


@cached(name="read-revision")
def read_revision(repository: str) -> str: ...


# Optional in direct Pydantic AI runs; step mode supplies the store itself.
with use_store("operations/"):
    revision = read_revision("repository/")
```

The top-level Python API is `cached`, `use_store`, `StoreError` and `CallFailed`;
the step model adapter is internal, not a top-level export.

Names and argument serialization are durable identity. Positional and keyword
spelling is preserved: `read_revision("repository/")` and
`read_revision(repository="repository/")` use different keys. Omitted defaults
and explicitly supplied defaults also differ; keyword ordering does not.
Keep calling conventions stable to reuse stored results. Results must be
JSON-serializable; a return annotation is used to restore the type from JSON.
The first stored execution and subsequent replays use the same round trip.
Without an active store the decorated function runs plainly. Store read/write
or cached-result decoding failures are remembered for the whole replay:
`use_store` raises at context exit even if code caught the operation's error.
Finish and join all tasks/threads using that store before leaving the context;
errors from work outliving the context cannot retroactively fail its exit.

A crash before recording a result can cause a cached operation to run again.
Make side effects idempotent. Exceptions are not cached, and an unfinished
recorded attempt causes an uncertainty warning when retried. An async cached
operation counts as busy until it finishes: do not wrap an agent lifecycle
awaiting external answers in `@cached`.

Only agent runs, cached operations, tasks/gathers of them, `asyncio.sleep` and
`asyncio.to_thread` are supported awaits in workflow code. Put other I/O inside a
cached operation. Raw event-loop I/O can otherwise produce an incomplete frontier.
Use distinct prompts when identical concurrent calls need branch-specific
answers: arrival-order occurrence indices do not provide stable branch identity
as upstream answers become available in different steps.

### Synchronous callbacks and cancellation

Step mode runs Pydantic AI's synchronous instructions, system prompts, output
validators and output functions through its public `Agent.using_thread_executor`
context. These jobs count as busy, just like `asyncio.to_thread`. The executor is
owned by the step and joined before publishing results or a waiting frontier.
Cancelling a task does **not** kill its running Python thread; a cancelled sync
callback can still finish a cached operation. Its warnings and store-integrity
failures are still checked before step output. Callbacks must terminate; a
blocked thread can hold shutdown indefinitely. Explicitly replacing this
executor or disabling threads inside a workflow is outside the supported mode.

A waiting step snapshots its frontier, then cancels and awaits remaining tasks.
Consequently workflow `finally` blocks run on **every waiting step**, not just
on successful workflow completion. Use them for finite resource cleanup, not
for "the workflow succeeded" effects. Put success-only work after the required
answers have arrived, and keep durable side effects in idempotent cached
operations. Finite cached operations in task finalizers are recorded normally;
uncertain-attempt warnings are emitted, and swallowed store-integrity failures
still fail the step. An uncaught finalizer exception also fails the step rather
than publishing the earlier snapshot. Effects already performed remain.

Do not start agent runs during cancellation cleanup. System-prompt and
instruction callbacks can execute cached operations before a model request
reaches the adapter. Those effects can occur even if the run subsequently fails
and the finalizer catches that failure.
Pydantic AI may instead cancel such a run earlier. Any model request that does
reach the adapter during teardown is refused, even if an answer was previously
committed; it will not become an additional worker task. Do not suppress
cancellation and continue the workflow, spawn detached cleanup tasks, or wait
indefinitely in a finalizer. Explicitly close async generators/context managers
inside the workflow rather than relying on garbage-collection finalizers.

## Trusted Python and imports

Workflow files execute under a synthetic module name derived from their resolved
path, not their filename stem. A workflow named `types.py` therefore does not
replace `sys.modules["types"]`. The synthetic entry remains available for runtime
annotations through execution and teardown, then is removed (or its previous
entry restored), including after load failure. The prompt renderer and v1 key
encoding are unchanged; the synthetic name is not an explicit key field. If a
workflow renders its own `__name__`, or Pydantic uses module-qualified schema
labels to disambiguate same-named types, the new identity can change that prompt
and hence its affected keys. There is no global key-version bump. Prefer
unambiguous type names and semantic prompts rather than module identities.

The workflow directory is temporarily first on `sys.path` throughout the step,
so existing absolute sibling imports work, including imports inside callbacks.
The previous search path is restored afterwards. Normal Python import caching
still applies to sibling modules: imported dependencies remain in `sys.modules`,
and a sibling can shadow a not-yet-imported dependency. Avoid sibling names that
collide with stdlib/dependency names; prefer a normal uniquely named package for
larger workflows. Workflows are trusted Python and can mutate globals, modules
and the filesystem.

Hash attestations require intact, trusted store metadata. Keep commit records
and their files unchanged. Integrity failure stops publication; earlier workflow
effects remain.
