# Runner D: bl step for ordinary Pydantic AI workflows

## Outcome

It works. `pyd_step/review_loop.py` is a plain Pydantic AI workflow: three `Agent(...)`s, an
`async def workflow`, `asyncio.gather`, and a Pydantic `Verdict`. The same file runs unchanged in two
ways:

- **Directly**, with `FunctionModel` fakes installed through `agent.override(model=...)`.
- **Under `bl step`**, where each agent model request is answered from a file store.

With equivalent fake answers, both give the same result. All 9 requested tests ran; their outputs are
in `results/D-logs/`. These choices follow the coordinator's later corrections:

- **Interception:** a `Model` subclass, `StepModel`, installed with the public `Agent.override(model=...)`.
  Stored answers come back as normal model responses, and Pydantic AI validates the output itself.
- **Cache unit:** one model request.
- **Output timing:** nothing is printed while the step runs. When no branch can proceed, the step
  prints every open call together, sorted by key, and exits 2.
- **Everything runs in process.** A public `@cached` API in the same module routes side effects and
  nondeterminism through the same store.
- **Quiescence uses only public asyncio API.** It is an `asyncio.SelectorEventLoop` subclass that
  overrides `call_soon`, `call_at` and `run_in_executor`. It does not read `loop._ready`.

**Rule the workflow must follow (stated in `blstep.py`):**
- Code between agent calls must be deterministic and free of side effects, **except** through
  `@cached` operations. That code runs again on every step.
- The workflow may await only these: agent runs, cached operations, gathers or tasks of them, timers
  (`asyncio.sleep`) and executor threads (`asyncio.to_thread`).

Environment: the venv runs Python 3.13.1 with pydantic-ai-slim 2.54.0. Every command below was run from
`experiment/`. The stores are in `../scratch_d` (the scratchpad). `pyd_step/run_tests.sh` regenerates
`results/D-logs/t1..t9`; a full run took 4 min 26 s.

## Design

### Files

| File | Role |
|---|---|
| `pyd_step/blstep.py` | Library: `StepModel`, `Replay` (store, keys), `cached`/`use_store`, `QuietLoop`, `BlCallFailed`, prompt rendering |
| `pyd_step/bl.py` | CLI: `step`, `complete`, `fail`; workflow loading; the step driver |
| `pyd_step/review_loop.py` | The test workflow |
| `pyd_step/wf_probes.py`, `pyd_step/wf_ops.py` | Probe workflows for tests 3, 4, 6, 8 and 9 |
| `pyd_step/test_direct.py`, `pyd_step/test_ops_direct.py` | Direct Pydantic AI runs with FunctionModel fakes |
| `pyd_step/orchestrator.py`, `pyd_step/fake_answers.py` | Fake orchestrator: `step --json` → answer each prompt → `complete`, repeated |

### How a step works

1. **Load the workflow.** `bl step FILE.py:FUNC` imports the file as a module, with the file's
   directory added to `sys.path`.
2. **Find the agents.** By default these are every module-level `Agent` instance. If the module defines
   a `BL_AGENTS` list, that list is used instead. Agents that are imported count too: `wf_probes.py`
   uses `writer` and `reviewer` imported from `review_loop`. Each agent needs a unique `name=`.
3. **Guard against real providers.** The step sets `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False`.
   An agent that bl missed (for example, one created inside a function) then raises instead of
   reaching a provider. That is an expectation; I did not test it.
4. **Run the workflow.** `drive()` enters `agent.override(model=StepModel(name, replay))` for every
   agent and sets the active replay in a ContextVar. It then starts `FUNC(**inputs)` as the main task.
   The overrides are ContextVars, so the gather child tasks copy them.
5. **Answer each request.** `StepModel.request(...)` calls `prepare_request` and renders the prompt. It
   computes the key and then does one of four things:
   - **Typed answer stored:** it returns `ModelResponse([ToolCallPart(output_tool, stored_json)])`.
     Pydantic AI then validates it into `Verdict`.
   - **Text answer stored:** it returns `ModelResponse([TextPart(text)])`.
   - **Failure stored:** it raises `BlCallFailed`.
   - **Nothing stored:** it writes `call.json` and `prompt.md`, records the call as open, and awaits a
     future that is never resolved.
6. **Decide.** The step waits for either main to finish or `QuietLoop.idle` to be set:
   - Main finished with a result: print it as JSON, exit 0.
   - Main raised: print the error, exit 1.
   - Idle with open calls: print all open calls sorted by key, exit 2.
   - Idle with no open calls: `workflow is stuck`, exit 1.
   `asyncio.Runner.close()` then cancels the suspended tasks. Under `-X dev -W always`, stderr was 0
   bytes (t7).

### Store

The layout is phase 1's: `<store>/<key>/` holds `call.json`, plus `prompt.md` for agent calls, and then
one of `answer.json`, `answer.md` or `failure.txt`.

`call.json` contains:
- for an agent call: `{"kind": "agent", agent, workflow, occurrence, typed}`
- for a cached operation: `{"kind": "op", op, occurrence, arguments}`

Writes are atomic and never overwrite (temp file plus `os.link`).

### Answer identity

The key is `sha256(agent name, occurrence index, rendered prompt)`. The occurrence index is n for the
n-th request in one replay with the same `sha256(agent name, rendered prompt)`.

The rendered prompt is the full `prompt.md`: the instructions, every message part, the tools section
and the answer format. That is a superset of "the rendered request messages", so a change to the output
schema also changes the key. Timestamps, tool_call_ids and run ids are left out of the rendering, which
keeps it stable.

### Prompt file

It contains:
- `# Call to agent`
- `## Instructions`: from `ModelRequestParameters.instruction_parts`, which is public, falling back to
  `ModelRequest.instructions`
- one section per message part: system prompt, user prompt, tool return, retry request, and earlier
  answers or tool calls
- `## Tools (unavailable)`: lists the agent's function tools by name and description
- `## Answer format`: the output tool's JSON schema and a one-line instruction, or "Answer with plain
  text; the whole file is the answer"

Text answers drop one trailing newline, because editors add one.

### Typed answers

- **When `complete` runs:** it re-imports the workflow file, takes `agent.output_type`, and validates
  with `TypeAdapter(output_type).validate_json`. It stores the normalised JSON.
- **On replay:** the stored JSON goes back through Pydantic AI's own output-tool validation, so
  `.output` is a real `Verdict`.
- **Limit:** `NativeOutput`/`PromptedOutput` (sent back as a JSON `TextPart`) and union output types
  are implemented in outline only and **untested**. `TypeAdapter` also cannot validate output-spec
  wrapper objects such as `ToolOutput(...)`.

### Failure

`bl fail KEY REASON` writes `failure.txt`. On replay, that `agent.run` raises
**`BlCallFailed(ModelAPIError)`**, with the message `call <key12> (<agent>) failed: <reason>`.

Why this type: `ModelAPIError` is what `agent.run` raises when a real provider call fails. A workflow
written for Pydantic AI that handles provider failures (`except ModelAPIError`, or `FallbackModel`)
therefore handles a bl failure the same way. The subclass lets code tell the two apart if it needs to.
Measured: Pydantic AI does not wrap or retry it; `agent.run` raises it unchanged (t5).

### Output to the orchestrator

**Human mode:** one line per open call, `<key[:12]> <agent> <prompt path>`, followed by
`waiting: N open call(s)`. If a call was posted by an earlier step and is still open, the line is
marked `(posted earlier)`.

**`--json` mode:** one JSON line per open call, `{"key", "agent", "prompt", "new"}`, then
`{"status": "waiting", "open": N}`. When the run finishes: `{"status": "done", "result": ...}`. On an
error: `{"status": "error", "error": "..."}`.

In human mode, the error goes to stderr together with the workflow-file frames of the traceback.

`complete` and `fail` accept any unambiguous key prefix. An empty, unknown or ambiguous prefix exits 1
(t4).

**The printed stream in the gather case:** stdout is empty while the step runs. When the three writer
branches of the gather have all suspended, the step prints all three lines together, sorted by key,
then the status line (t2, first step):

```
346ba8b489d1 writer     ../scratch_d/t2h/346ba8b4.../prompt.md
4d9c7decd285 writer     ../scratch_d/t2h/4d9c7dec.../prompt.md
e730df309faf writer     ../scratch_d/t2h/e730df30.../prompt.md
waiting: 3 open call(s)
```

A call made later inside a gather branch is issued only once that branch's task runs. Because the step
waits for quiescence and not for the first blocked branch, every call issued in a gather is posted in
the same step.

### Quiescence mechanism (public API only)

`QuietLoop(asyncio.SelectorEventLoop)` overrides three public loop methods:

- **`call_soon`:** wraps the callback and keeps its handle in a `live` set until it runs. I verified with
  `pyd_step/probes/p1_callsoon.py` that the C-accelerated Task and Future schedule through the
  overridable `loop.call_soon`. That covers task steps, wakeups and gather callbacks.
- **`call_at`:** the same for timers. `call_later` and `asyncio.sleep` go through it.
- **`run_in_executor`:** counts in-flight jobs (`asyncio.to_thread` goes through it). The count drops in
  a done-callback on the asyncio future, which is itself scheduled with `call_soon`, so there is no gap
  where the loop looks idle.

After each wrapped callback, the loop checks the `live` set (cancelled handles are pruned) and the job
count. If both are empty, it sets `idle`. A running async `@cached` operation also counts as a job, so
socket I/O inside a cached operation is waited for.

**Not seen:** socket I/O awaited directly on the loop, outside a cached operation, that is woken by
something the loop does not track (test 6d). That is why the rule lists only the allowed awaits.

## Tests

The commands are the ones in `pyd_step/run_tests.sh`; the logs are `results/D-logs/t<N>-*.txt`. "Measured"
below means taken from those logs.

### 1. Direct Pydantic AI run with FunctionModel fakes (`t1-direct.txt`)

Command: `uv run python pyd_step/test_direct.py`. This is `agent.override(model=FunctionModel(fake))` for
the three agents and then `await review_loop.workflow(topics=["a","b","c"], max_rounds=2)`.

Measured:

```
{"sections": [{"topic":"a","text":"Paragraph about a.","rounds":0},
              {"topic":"b","text":"Paragraph about b (revised).","rounds":1},
              {"topic":"c","text":"Paragraph about c.","rounds":0}],
 "summary": "SUMMARY: 3 paragraphs."}
```

The direct run prints Pydantic AI's banner on stderr. `bl` suppresses it with `PYDANTIC_AI_NO_BANNER=1`.

### 2. bl step driven by the fake orchestrator (`t2-orchestrated.txt`)

Command:

```
uv run python pyd_step/orchestrator.py pyd_step/review_loop.py:workflow $S/t2 '{"topics":["a","b","c"],"max_rounds":2}'
```

Measured, 6 steps:

| Step | Exit | Calls posted |
|---|---|---|
| 1 | 2 | writer ×3 |
| 2 | 2 | reviewer ×3 |
| 3 | 2 | writer (rewrite of b) |
| 4 | 2 | reviewer (b, second round) |
| 5 | 2 | summarizer |
| 6 | 0 | `{"status":"done", ...}` |

`final result equal to the direct run's: True`. The fake answers come from the same `fake_answers.answer`
function in both runs. The orchestrator reads the `## User prompt` section out of `prompt.md` to get its
input.

A step takes about 0.8 s wall time. `complete` takes about 0.75 s; most of that is the pydantic_ai import.

### 3. A repeated identical call is asked again (`t3-repeat.txt`)

`wf_probes.py:repeat` makes these calls:
- `writer.run("Write one paragraph about x.")` twice in sequence;
- then `gather` of two identical `writer.run("... about y.")` calls.

Measured: there were 4 distinct keys and 4 answers.
- Step 1 posted one call (occurrence 0).
- After it was completed, step 2 posted the identical prompt again as a new key (occurrence 1).
- Step 3 posted both gathered identical calls together (occurrences 0 and 1).
- The final result kept all four different answers:
  `"sequential": ["Paragraph 1-9200", "Paragraph 2-829e"]`, `"gathered": ["Paragraph 3-1bac", "Paragraph 3-661f"]`.

This matches Pydantic AI, where each run is a new request.

### 4. Typed validation (`t4-typed.txt`)

Rejected with exit 1, nothing written, and Pydantic's error on stderr:
- `not json`
- `{"accepted": "maybe"}`
- `{"problems": ["x"]}`
- `{"accepted": true, "problems": "x"}`

Other cases:
- **Accepted:** `{"accepted": false, "problems": ["vague"], "extra": 1}`, stored as
  `{"accepted": false, "problems": ["vague"]}`.
- **Second `complete` on the same key:** refused (`already settled`).

Replay of `wf_probes.py:typed`:

```
"type": "<class 'review_loop.Verdict'>", "is_Verdict": true
```

Lax-mode coercion (`"true"` → `True`) is not blocked. I did not test it.

### 5. Failure path (`t5-fail.txt`)

The orchestrator ran `bl fail <writer-b prefix> "writer refused"` after step 1. Measured: step 2 exits
1. In `--json` mode it prints:

```
{"status": "error", "error": "BlCallFailed: call 346ba8b489d1 (writer) failed: writer refused"}
```

In human mode it prints the workflow frames, `review_loop.py` line 52 (gather) and line 41
(`writer.run`), then:

```
error: BlCallFailed: call 346ba8b489d1 (writer) failed: writer refused
```

No orphan reviewer prompts were posted in this run. Main finished with the error before branches a and c
reached their reviewer requests, and the Runner cancelled them. Phase 1 (A.md Q4a) did see orphans. This
depends on scheduling, so a harness should still never look for open work by scanning the store.

### 6. Quiescence: rule, mechanism, and non-agent awaits (`t6-quiescence.txt`)

The rule and the mechanism are described above. In each probe, one gather branch calls the writer at once
and the other branch first awaits something else.

| Probe | Other branch awaits | Measured | Verdict |
|---|---|---|---|
| 6a `sleepy` | `asyncio.sleep(0.05)` | 2 calls posted (early, late), exit 2, 0.85 s | correct: the timer is tracked |
| 6b `threaded` | `asyncio.to_thread(time.sleep, 0.05)` | 2 calls posted, exit 2 | correct: the executor job is tracked |
| 6c `stuck` | `asyncio.Event().wait()`, never set | step 1: 1 call posted, exit 2. After completing it: `error: workflow is stuck: nothing runnable and no open agent calls`, exit 1 | a real deadlock is reported, but only once no agent call is open |
| 6d `socket_io` | raw `loop.sock_recv` on a socket a plain thread writes after 0.05 s or 0.5 s | **1 call posted** (only early), exit 2 | **outside the rule**: the late branch's call is missed this step |
| 6e `socket_io_cached` | the same socket read inside an async `@cached` operation (0.5 s) | 2 calls posted, exit 2, 1.33 s | correct: a running cached operation counts as work |

About 6d: the missed call is not lost. On the next step, the late branch gets past its socket read only
if the data arrives before quiescence; otherwise it is missed again. That is why direct socket awaits
are outside the rule.

A probe bug I fixed: my first 6d used a blocking socket, so `sock.recv` blocked the loop thread and the
test passed for the wrong reason. `pyd_step/probes/p2_idle_debug.py` found this.

### 7. Determinism (`t7-determinism.txt`)

Measured with `md5sum` of stdout, sorted and counted with `uniq -c`:

| What was replayed | Distinct outputs in 30 runs |
|---|---|
| Completed store, human mode | 1 |
| Completed store, `--json` | 1 |
| Mid-run store (3 reviewer calls open), human mode | 1 |
| Mid-run store, `--json` | 1 |
| 30 fresh stores, each run through 2 steps (every writer answered `Paragraph` with `bl complete`), `--json` output of step 2 | 1 |

`-X dev -W always` on a waiting step: exit 2, 0 bytes on stderr.

Expectation, not tested: occurrence indices of identical concurrent calls follow task scheduling order.
That order is deterministic for a given workflow and store, but it could change across Python versions.

### 8. Full prompt files (`t8-prompts.txt`)

A reviewer prompt from the t2 store (the second review of topic b), verbatim:

````
# Call to agent `reviewer`

## Instructions

You review a paragraph for accuracy and clarity. Accept it if a general reader would understand it and it contains no errors; otherwise list each concrete problem.

## User prompt

Review this paragraph about b.

Paragraph about b (revised).

## Answer format

Answer with one JSON object matching this schema (nothing else in the file):

```json
{
  "properties": {
    "accepted": {
      "type": "boolean"
    },
    "problems": {
      "items": {
        "type": "string"
      },
      "type": "array"
    }
  },
  "required": [
    "accepted",
    "problems"
  ],
  "title": "Verdict",
  "type": "object"
}
```
````

The same log also has a prompt for an agent with a function tool (`wf_probes.py:tooled`). It contains:

```
## Tools (unavailable)

The agent has these tools, but bl does not run them. Answer without them:

- `count_words`: Count the words in a text.
```

### 9. Cached operations (`t9-cached-ops.txt`)

**The API, in `blstep.py`:**
- `@cached` or `cached(fn, name=...)` wraps sync and async functions.
- `use_store(path)` is a context manager for direct runs.

**Key:** `sha256("op:"+name, occurrence, JSON of {args, kwargs})`. The default name is
`module.qualname`. Pass `name=` to keep it stable when the module name could differ.

**Results:**
- Results are stored as JSON with `to_jsonable_python`.
- If the function has a return annotation, the JSON is validated back into that type with `TypeAdapter`
  (a `datetime` stays a `datetime`).
- The first execution returns the same round-tripped value a replay will get, so the first run and
  replays cannot diverge.
- A result with no JSON form raises `TypeError` after the operation has run. Fix this by annotating a
  type Pydantic can serialise, or by returning a JSON-friendly value.

**Exceptions are not cached.** The exception propagates, nothing is recorded, and the operation runs
again on the next step (or the next direct run). Reasons:
- Failures of fetch, clone or publish are usually transient. Caching one would make it permanent and
  require editing the store by hand.
- A deterministic failure simply fails each step with exit 1. The orchestrator sees it.

If an operation re-runs and finds its `call.json` already written without a result, it prints
`bl: re-running <op> (<key>): an earlier attempt recorded no result` to stderr. That covers both a
crash and an earlier exception.

**At-least-once:** the result is recorded after the operation returns. A process that dies between the
side effect and the record re-runs it on the next step. The operation itself should therefore be
idempotent: clone into a fixed path only if absent, publish with an idempotency key, write files
atomically.

**Direct runs:**
- Without a store, `cached` simply calls the function.
- With `with use_store(dir):`, operations are cached. A second direct run with the same store replays
  them, which gives resume-after-crash.
- Agent calls are **not** cached in direct mode; they use their real models. Recording real model
  answers would be a separate option, and I left it out.

Measured. `wf_ops.py:workflow` has:
- `now()` and `roll()`, both cached
- `append_line_cached` (wrapped) and `append_line` (unwrapped), each writing a log line
- an async cached `publish` that awaits `asyncio.sleep` and `to_thread`
- 3 agent waves

| Test | Result |
|---|---|
| (a) wrapped append | 4 steps plus 1 extra replay. `cached.log` has exactly 3 lines: `drafted 2`, `reviewed accepted=True`, `PUBLISHED SUMMARY: 2 paragraphs.` Each operation ran once. |
| (b) unwrapped append | `unwrapped.log` got `replay sees ...` on all 5 replays and `drafted 2` on the 4 replays that got past the writer wave: 9 lines. This is why wrapping matters. |
| (c) cached clock and random | Every replay line shows the same `started=2026-10-15T06:41:18.598996+00:00 roll=0.344755`. The final result carries the same values on step 4 and on the extra replay. |
| Direct runs | No store: plain execution. With a store, run 1 and run 2 return the same `started` and `roll`, and the log still has 3 lines after both runs. |
| Exceptions | `flaky_fetch` raises `ConnectionError` on attempt 1 (exit 1, nothing recorded). Attempt 2 re-runs it, with the warning on stderr, and succeeds. Attempt 3 uses the cache. |

### 10. Line counts

| File | Total | Non-blank, non-comment |
|---|---|---|
| `blstep.py` | 307 | 240 |
| `bl.py` | 154 | 124 |
| `review_loop.py` | 54 | 43 |
| `wf_probes.py` | 92 | 66 |
| `wf_ops.py` | 65 | 47 |
| `orchestrator.py` | 53 | 43 |
| `test_direct.py` | 35 | 25 |
| `test_ops_direct.py` | 33 | 26 |
| `fake_answers.py` | 17 | 14 |
| `run_tests.sh` | 64 | 53 |
| `probes/p1_callsoon.py` | 15 | 15 |
| `probes/p2_idle_debug.py` | 21 | 18 |

Inside `blstep.py`, counting non-blank non-comment lines:

| Part | Lines |
|---|---|
| Prompt rendering | ~46 |
| `StepModel` | 15 |
| `Replay` | 37 |
| `QuietLoop` | 36 |
| `cached`/`use_store` | 66 |

## Agents with tools (v1 has none): what happens and a recommendation

With tools, one `agent.run` is several model requests:
1. The model answers with tool calls.
2. Pydantic AI executes the tools.
3. Pydantic AI sends another request carrying the `ToolReturnPart`s, until the model gives a final
   output.

v1 lists the tools as unavailable, and the worker must answer finally in one request.

Options:

1. **v1 as is:** tools are listed but never run. It is simple, but an agent that relies on its tools
   loses capability.
2. **The worker may answer with tool calls; Pydantic AI runs the tools in process.**
   - The answer format allows either a final output or `{"tool_calls": [{name, args}]}`.
   - `StepModel` returns `ToolCallPart`s, and Pydantic AI executes the tools during the replay.
   - The next request includes the tool returns, so it renders and posts as a new cached call. The
     renderer already handles `ToolReturnPart` and earlier `ToolCallPart`.
   - The tools run again on every replay, so they must follow the same rule. Route their execution
     through the cache: a `WrapperToolset`
     (`pydantic_ai/toolsets/wrapper.py`) whose `call_tool` is keyed like `@cached`
     (tool name + args + occurrence).
   - Cost: one orchestrator round trip per tool turn.
3. **The worker executes the tool calls itself in its own harness,** using Pydantic AI's deferred-tool
   mechanism (`CallDeferred` / external toolsets). This suits tools that exist only on the worker's
   side, but the tool code in the workflow is then never run.

**Recommendation:** option 2, with tool executions cached automatically through the wrapper toolset.
- It keeps "Pydantic AI runs the workflow's own code" true.
- Each request stays one cache unit.
- It reuses the `@cached` semantics: at-least-once, exceptions not cached.

Use option 3 only for tools that are meant to run in the worker.

**Alternative, out of scope:** an HTTP gateway that speaks a provider API and parks requests. It would
intercept without touching the agents, but it needs a server, and quiescence would then rest on socket
I/O, which `QuietLoop` cannot see.

## Problems and caveats

- **Replay cost:** each step replays from the top. That is O(calls) per step and O(n²) per run, plus
  about 0.8 s of startup (mostly the pydantic_ai import).
- **Store hygiene:** keys left behind by edits, errors or cancelled branches stay in the store. Nothing
  removes them.
- **Untested output modes:** structured output other than a single output tool (`NativeOutput`,
  `PromptedOutput`, unions) is unverified. Streaming (`run_stream`, `event_stream_handler`) is not
  implemented; `StepModel` has no `request_stream`.
- **Workflow location:** `blstep` must be importable by the workflow. Here it sits next to it in
  `pyd_step/`.
- **The guard against real providers is untested:** an agent bl does not find (created inside a
  function, or not reachable from module attributes) relies on `ALLOW_MODEL_REQUESTS = False` to fail
  loudly.
- **Occurrence index and branching:** the index counts identical requests in replay order. If code
  before an identical call changes between steps, indices can shift. Under the stated rule (determinism
  between calls) they cannot.
