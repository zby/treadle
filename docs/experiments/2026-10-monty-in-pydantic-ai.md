# Runner B: review_loop.py in Pydantic AI

All measured facts below come from runs of `runner_pydantic/test1.py` (Route 1) and
`runner_pydantic/test2.py` (Route 2), via `uv run python ...` from the experiment root (venv is Python 3.13.1,
not 3.12 as the contract says). `shared/review_loop.py` was read with `Path.read_text()` and never edited.
Inputs used: `topics=["a","b","c"]`, `max_rounds=3`.

## Code
- `runner_pydantic/fakes.py` (82 lines): FunctionModel agents built from `CATALOG` (`Agent(name, description, output_type)`).
  Each model call does `asyncio.sleep(0.3)` and records start/end times. Writer: "Paragraph about X." (or "... (revised)." for
  a Rewrite task). Reviewer (output_type Verdict, answered via `info.output_tools[0]`): rejects topic b unless the task
  contains "(revised)". Summarizer: `SUMMARY: N paragraphs. Done.`. Writer can be told to raise for a topic.
- `runner_pydantic/route1.py` (35 lines): Route 1 glue. `runner_pydantic/route2.py` (20 lines): Route 2 driver.
- Tests: `test1.py` (36), `test2.py` (36).

## Route 1: DynamicWorkflow as shipped
What I did: built `Agent(FunctionModel(orch), capabilities=[DynamicWorkflow(agents=[writer, reviewer, summarizer])])`.
`orch` returns `ToolCallPart("run_workflow", {"code": code})` on the first step, then echoes the tool return as JSON.
**Inputs**: `DynamicWorkflow` / `DynamicWorkflowToolset` have no inputs parameter (tool args are only `code`). I prepended
two lines to the code string: `topics = ["a", "b", "c"]` and `max_rounds = 3` (via `json.dumps`). The script text itself is
unchanged, but its line numbers in tracebacks shift by 2 (traceback showed line 14 for the script's line 12).
I did not call `call_tool` directly; running through a real orchestrator Agent was simpler than building a RunContext.

## Route 2: own Monty driver
`AsyncMonty()` -> `pool.checkout()` -> `session.feed_run(script_text, inputs={...}, external_lookup={name: async fn})`.
Inputs go through Monty's `inputs=` (eagerly bound globals). Each agent is an `async def call(*, task: str)` that does
`to_jsonable_python((await agent.run(task)).output)`; on error it raises `RuntimeError(f"sub-agent 'x' raised {type}")`.
Monty awaits the async externals concurrently itself. No snapshot loop needed.

## Answers

### 1. Runs to completion with correct results? Yes, both routes, identical output
```
{"sections": [{"topic":"a","text":"Paragraph about a.","rounds":0},
              {"topic":"b","text":"Paragraph about b (revised).","rounds":1},
              {"topic":"c","text":"Paragraph about c.","rounds":0}],
 "summary": "SUMMARY: 3 paragraphs. Done."}
```
Topic b was rejected once, rewritten, accepted at round 1. Route 1 returns this as the tool-return value (a dict) to the
orchestrator model; Route 2 returns it as a Python dict from `feed_run`.
Also: `max_rounds=1` with topic b -> script's own `raise RuntimeError("out of attempts for b")` fires in both routes.

### 2. Concurrency: yes in both
Measured max simultaneous calls: writer 3, reviewer 3 in both routes. Timeline (Route 2; Route 1 identical in shape):
3 writers start at t=0.25 and end at 0.55; 3 reviewers 0.57-0.87; b's rewrite 0.89-1.19; b's re-review 1.21-1.51;
summarizer 1.53-1.83. Total about 1.6 s of work, vs. 3.0 s if serial for the 10 calls at 0.3 s. Route 1 timeline: 0.16 .. 1.73.

### 3. Typed output is a dict in both
Probe script `v = await reviewer(task=...); [type(v).__name__, v]` -> `['dict', {'accepted': True, 'problems': []}]` in both.
(Route 1's static type checker sees the Verdict as a TypedDict stub, and `verdict["accepted"]` passed it.)

### 4. Failure (writer raises ValueError for topic c)
- Script sees: `RuntimeError: sub-agent 'writer' raised ValueError` in both routes (I wrote the same message format in Route 2 on
  purpose, copying DynamicWorkflow's `_run_one`; the original exception message "(secret detail)" is deliberately not exposed).
  The script has no try/except, so the exception propagates out of `gather` and ends the script. a and b had finished
  their writer calls but their results are lost to the script.
- Route 2 returns: raises `MontyRuntimeError` to the caller with text `RuntimeError: sub-agent 'writer' raised ValueError`.
- Route 1 returns: `call_tool` raises `ModelRetry`; the orchestrator model receives a RetryPromptPart:
  ```
  Runtime error in workflow:
  Traceback (most recent call last):
    File "<python-input-0>", line 14, in draft_and_review
      text = await writer(task=f"Write one paragraph about {topic}.")
  RuntimeError: sub-agent 'writer' raised ValueError

  Completed sub-agent results from the failed script (up to 20 bounded previews; ...):
  - writer(task="Write one paragraph about a.") -> "Paragraph about a."
  - writer(task="Write one paragraph about b.") -> "Paragraph about b."
  ```
  If the model resends the same code, it re-runs everything. Measured: after 3 retries the run raised
  `UnexpectedModelBehavior: Tool 'run_workflow' exceeded max retries count of 3`, and the writer FunctionModel had been
  called 12 times (4 attempts x 3 topics). Each attempt spends from the shared `max_agent_calls` (default 50) budget.
  Same retry path for the script's own `raise` (out of attempts) and for type errors.

### 5. APIs relied on, and stability
Route 1 (all public, documented in `docs/dynamic-workflow.md`): `pydantic_ai_harness.dynamic_workflow.DynamicWorkflow`,
`Agent(capabilities=[...])`, `FunctionModel`, `ToolCallPart`. No private modules. Behaviour I depend on but that is not an
API promise: error message formats, and the fact that the only input channel is the code string. Package is 0.54.0 pre-1.0
and the capability has a fast-changing surface (reveal, budgets, durability notes), so expect churn; DynamicWorkflow is
designed for an LLM writing the code, and a fixed-script use is outside its design.
Route 2: `pydantic_monty.AsyncMonty`, `.checkout()`, `AsyncMontySession.feed_run(inputs=, external_lookup=)` - all in the
`.pyi` stubs with docstrings, not underscore modules. Monty 1.1.0 is new; the stub's wording ("external_lookup ... callable
entry (sync or a coroutine function) ... awaited concurrently") is the contract I rely on. I did not read
`_monty_exec.py` for Route 2 beyond learning the snapshot loop; `feed_run` made it unnecessary. Not used: `MontyExecutor`
(that is in the underscore module `pydantic_ai_harness._monty_exec`, private).

### 6. Line counts
Route 1 glue: 35 lines (`route1.py`, including docstrings, imports, input prepending, and the fake orchestrator).
Real glue without the fake orchestrator model: about 8 lines (`with_inputs` plus `DynamicWorkflow(agents=...)` plus the call).
Route 2: 20 lines (`route2.py`). Shared fake-agent code: 82 lines.

### 7. Differences in what each route accepts
- Undefined inputs: Route 1 rejects the unchanged script before running, via the static type checker:
  `Type error in workflow: error[unresolved-reference]: Name 'max_rounds' used when not defined` (also `topics`). That is a
  ModelRetry, no agent budget spent. Route 2 (no type check by default) raises `MontyRuntimeError: NameError: name
  'max_rounds' is not defined` at runtime, only when execution reaches the use.
- Route 1 type-checks agent calls against stubs generated from the catalog: `await writer('x')` is rejected statically
  (`missing-argument`, `too-many-positional-arguments`). Route 2 has no stubs; positional args would need my own check
  (Route 1's runtime dispatch checks `task` presence/type, extra kwargs; mine does not - `call(*, task)` gives a plain TypeError).
- Top-level `await` and `import asyncio` are accepted by both. `asyncio.gather` over a list comprehension works in both.
- Route 1 refuses nested workflows and caps calls (50 default); Route 2 has neither. Route 1 prints/captured output are
  merged into the result (`{'output': printed, 'result': ...}`) if the script prints; not exercised here.
- Not tested: Route 2 with `type_check=True` plus hand-written stubs (possible per `checkout(type_check_stubs=)`).

## Problems and caveats
- Route 1 requires an orchestrator Agent turn even though no model is needed to write the code; the result passes through
  a tool return, and failures turn into model retries (cost: re-running completed sub-agents). A fixed script wants
  the failure returned, not retried.
- The Route 1 result is returned to the orchestrator as a tool return, and I json-dumped it in my fake model; the raw
  dict is in `ToolReturnPart.content` (not extracted via the final `result.output`).
- Python is 3.13 in the venv, contrary to the contract header.
- Fake-model timing numbers include about 0.15-0.25 s startup before the first call; relative overlap is what matters.
