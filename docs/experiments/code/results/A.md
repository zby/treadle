# Runner A: bl step runner on Monty

## Outcome

The step runner works on Monty 1.1.0 for `shared/review_loop.py`, and the script is used unchanged. All
eight questions were answered with runs I actually did. In the main scenario (topics a, b, c;
max_rounds 2; the reviewer rejects the first draft of b once) the workflow finished in **6 steps and 9
agent calls**. Each step posted every independent pending call at once.

There were no blockers. The findings that matter most:

- Monty's `pending_call_ids` comes back in a random order, and the order of the resume dict decides
  which task wakes first. The fix is to sort the resume dict; after that, replay was identical in 50 of
  50 runs.
- Because a call's identity is its content, a repeated identical call inside a loop reuses the stored
  answer instead of asking again (Q4c).
- A step that ends in an error can leave prompts in the store that were posted but are never reported
  as open (Q4a).

Environment note: the venv runs **Python 3.13** (`.venv/lib/python3.13`), but the contract says 3.12.
Nothing seemed to depend on this.

## Code (all under `runner_step/`)

| File | Lines (total / non-blank non-comment) | Role |
|---|---|---|
| `bl.py` | 192 / 158 | The runner: `step`, `complete`, `fail` (argparse), the store, type-check stubs, and the Monty driver |
| `bl_cpython.py` | 81 / 64 | Q8: `step` on plain asyncio. It reuses bl.py's store, catalog, `complete` and `fail` |
| `tests/drive.py` | 66 | A fake harness: it runs step, answers each open prompt deterministically, runs complete or fail, and repeats |
| `probes/p1..p7*.py` | 124 | API probes and the determinism probe |

Of bl.py's 158 lines, the Monty-specific part is about 62 (`type_check_stubs` 17, `on_call` 16, `step`
29). The rest is store, catalog and CLI code that is the same for both runners. The CPython-specific part
of `bl_cpython.py` is about 55 lines, so the two runners are about the same size.

### How bl.py drives Monty

- It uses the sync API: `Monty(max_processes=1)`, then `pool.checkout(type_check=True,
  type_check_stubs=...)`, then `session.feed_start(code, inputs=inputs)`.
- **Every** agent call (`FunctionSnapshot`) is resumed with `{'future': ...}`, whether its answer is
  stored or not. The runner records the settled result (`{'return_value': ...}` or
  `{'exception': RuntimeError(text)}`) for calls that have one. For calls that do not, it writes
  `call.json` and `prompt.md`.
- At a `FutureSnapshot` it resumes with the subset of `pending_call_ids` that have a result. Monty
  accepts a partial resume (probe p3), so finished gather branches move on while others wait.
- If no pending id has a result, nothing can proceed. The runner prints `<key> <agent>` per open key,
  sorted, and exits 2.
- Other outcomes:
  - Unknown name or positional args: the runner raises NameError or TypeError in the sandbox.
  - `NameLookupSnapshot`: resumed without a value, so the script gets a NameError.
  - `MontyRuntimeError` or `MontyTypingError`: printed to stderr, exit 1.
  - `MontyComplete`: the output is printed as JSON, exit 0.

**Stopping with calls still pending:** the runner just leaves the `with session` and `with pool`
blocks. There is no cancel call. The suspended feed is thrown away, and the next step replays from the
top. Evidence that this is clean is under Q2.

**Static type check:** this works. The stubs are rendered with `pydantic_ai.function_signature.FunctionSignature`,
the same way the harness's `_build_type_check_stubs` does it: `class Verdict(TypedDict)` and
`async def writer(*, task: str) -> str`. The runner also adds `topics: Any` and `max_rounds: Any` for
the inputs. That addition is needed: without it the checker rejects the script with
`unresolved-reference: Name max_rounds used when not defined` (probe p7). Evidence is in
`A-logs/typecheck.txt`; each of these four bad copies exits 1 and leaves the store empty:

| Bad script copy | Diagnostic from the checker |
|---|---|
| `reviwer(task=...)` | `unresolved-reference` |
| `writer("...")` | `missing-argument` and `too-many-positional-arguments` |
| `verdict["acepted"]` | `invalid-key ... Did you mean "accepted"?` |
| `writer(task=len(topic))` | `invalid-argument-type: Expected str, found int` |

The checker does **not** flag `verdict["problems"]`, even though the stub declares that key
`NotRequired`. At runtime this is safe, because `complete` stores `model_dump()`, which always includes
`problems`.

### Store

- Layout: `<store>/<sha256(agent+"\n"+task)>/` holding `call.json` and `prompt.md`, plus one of
  `answer.json`, `answer.md` or `failure.txt`.
- `prompt.md` contains the catalog description, the JSON schema if the agent is typed, then `## Task`
  and the task text.
- Writes are atomic and never overwrite: the runner writes a temp file, then `os.link`s it to the final
  name. `complete` and `fail` also refuse a key that is already settled, and a key that has no
  `call.json`.

## Commands run

All commands were run from `experiment/`, with `S` set to the scratchpad. The full outputs are in
`results/A-logs/`.

```
uv run python runner_step/tests/drive.py shared/review_loop.py $S/q3 '{"topics":["a","b","c"],"max_rounds":2}' --reject-first b
uv run python runner_step/tests/drive.py ... --fail-agent-topic writer:b        # Q4a
uv run python runner_step/tests/drive.py ... --always-reject b                  # Q4b
uv run python runner_step/tests/drive.py ... '{"topics":["b"],"max_rounds":3}' --always-reject b   # Q4c
uv run python runner_step/bl.py complete <key> bad.json --store $S/q4a          # Q5
uv run python runner_step/probes/p6_determinism.py $S/q3 50 [sorted]            # Q6
uv run python runner_step/tests/drive.py $S/review_loop_edited.py $S/q7 ...     # Q7, on a copy of the q3 store
uv run python runner_step/tests/drive.py ... --runner bl_cpython.py             # Q8
uv run python -X dev -W always runner_step/bl.py step ...                       # Q2 warnings
```

## Answers

### Q1. Does gather post all independent pending calls in one step? Yes

Measured, with `A-logs/q3-full-run.txt`. These are the keys posted per step for topics a, b, c and
max_rounds 2:

| Step | Exit | Calls posted |
|---|---|---|
| 1 | 2 | writer a, writer b, writer c |
| 2 | 2 | reviewer a, reviewer b, reviewer c |
| 3 | 2 | writer (rewrite b) |
| 4 | 2 | reviewer b (second draft) |
| 5 | 2 | summarizer |
| 6 | 0 | none; prints the result |

The raw probe (p2) shows the same thing: three `FunctionSnapshot`s for writer, followed by one
`FutureSnapshot` with `pending_call_ids` covering all three.

### Q2. Can a step end with calls pending and the next step replay cleanly? Yes

- **Replay:** every step in Q3 replays from the top against stored answers and moves exactly one wave
  further.
- **Warnings:** three replays under `python -X dev -W always` printed 0 bytes to stderr, with exit 2 and
  the same 3 open keys each time.
- **Leftover processes:** `pgrep monty` found none after the runs.
- **Speed:** a step takes about 0.82–0.85 s wall time. I did not break that time down into Python
  startup, the pydantic_ai import and worker spawn.
- **Reusing the pool** (probes p4 and p5), relevant to a long-lived runner: after a session is dropped
  mid-feed, the same pool hands the **same worker pid** to the next checkout. The globals from the
  abandoned feed (`topics`, `draft_and_review`, `max_rounds`) are gone there (NameError). The drop and
  re-checkout took 1–5 ms.
- **No hangs** were seen.

### Q3. Full workflow with a fake answering loop: 6 steps, 9 calls

The table under Q1 is this run. The fake answers came from `tests/drive.py`: the writer returns
`DRAFT<n> <topic>`, and the reviewer rejects `DRAFT1 b`. Final result:

```
{"sections": [{"topic":"a","text":"DRAFT1 a","rounds":0},
              {"topic":"b","text":"DRAFT2 b","rounds":1},
              {"topic":"c","text":"DRAFT1 c","rounds":0}],
 "summary": "SUMMARY of DRAFT1 a, DRAFT2 b, DRAFT1 c"}
```

The store ended with 9 keys. Topics a and c spent steps 3–5 parked as finished gather branches while b
looped. That is inherent to gather, not to the runner.

### Q4. Failure path: works

**Q4a**, in `A-logs/q4a-fail.txt`: `bl fail <writer b key> "writer refused for b"` was recorded, and
step 2 exits 1 with:

```
  File "<python-input-0>", line 12, in draft_and_review
    text = await writer(task=f"Write one paragraph about {topic}.")
RuntimeError: writer refused for b
```

- **Orphan prompts:** before the gather raised, the a and c branches went on and posted their reviewer
  prompts. Those keys exist in the store with only `call.json` and `prompt.md`, but step 2 exited 1, so
  they were never reported as open. A harness should not look for open work by scanning the store.
- **Traceback filename:** the traceback names the file `<python-input-0>`, not the `script_name`
  passed to `checkout`. Type-check diagnostics do use the real file name.

**Q4b**, in `A-logs/q4b-out-of-attempts.txt`: when the reviewer always rejects b with max_rounds 2,
step 6 exits 1 with `RuntimeError: out of attempts for b`, raised by the script's own `raise` at line 19.

**Q4c**, in `A-logs/q4c-identical-retry.txt`: this shows a consequence of content identity.
- Setup: topics `["b"]`, max_rounds 3, always reject.
- What happened: the fake writer returned the same text twice (`DRAFT2 b`). So round 3's review task was
  byte-identical to round 2's, and round 3's rewrite task was identical too. Both reused stored answers.
- Result: the script ran 3 rounds but asked only 2 reviews, then raised out-of-attempts with no new
  prompt.
- What this means: identical calls inside a loop are memoized. In Pydantic AI, each call would be a
  fresh `Agent.run`. With real LLM answers, identical text is unlikely but possible.
- The same rule applies within one step: two identical calls in one step collapse into one key and get
  one answer.

### Q5. Typed validation: invalid answers are rejected, nothing is written

Evidence is in `A-logs/q5-validation.txt`.

- **Rejected, exit 1:** `not json`, `{"accepted": "maybe"}`, `{"problems": ["x"]}` (missing
  `accepted`), and `{"accepted": true, "problems": "x"}`. Each gave a Pydantic error on stderr. The key
  directory still held only `call.json` and `prompt.md` afterwards.
- **Accepted:** `{"accepted": true, "extra": 1}`. The extra field was dropped, and the stored answer is
  normalised to `{"accepted": true, "problems": []}`.
- **Pydantic lax mode:** this is a known behaviour; I did not test it here. Values like `"true"` would
  be coerced to booleans. Use strict validation if that matters.
- **Overwrite attempts:** a second `complete`, or a `fail` on a settled key, exits 1 with
  `already settled (answer.json); not overwriting`, and the file is unchanged. An unknown key exits 1.

### Q6. Determinism: one source of nondeterminism, fixed by sorting

Evidence is in `A-logs/q6-determinism*.txt`. I replayed the completed store 50 times in one pool.

- `FutureSnapshot.pending_call_ids` came back in every permutation, for example `(2,0,1)`, `(1,2,0)` and
  `(0,1,2)` for the same wave.
- When the resume dict follows that order, the order in which branches wake changes too. That gave
  **6 different call orderings** in 50 replays: the reviewer calls got different call_ids.
- With the resume dict built from `sorted(pending_call_ids)`: **1 trace in 50 out of 50 runs**. This is
  now in bl.py.
- The final output was identical in every run either way.
- The open keys a step prints are sorted, so they never depended on this. 10 repeated
  `bl step` runs at the same state gave the same md5.
- The order would only change results for a script whose branches share mutable state or whose call
  content depends on ordering. Sorting removes even that.

### Q7. Edit robustness: the edited prompt and calls downstream of it are re-asked

Evidence is in `A-logs/q7-edit.txt`. I changed `Review this paragraph about` to
`Critically review this paragraph about` in a copy of the script, and ran it against a copy of the
completed Q3 store.

- **Reused, never re-asked:** all 3 initial writer calls, the b rewrite and the summarizer.
- **Re-asked:** all 4 reviewer calls. They took 2 steps: 3 reviewers, then the second reviewer for b.
  Step 3 completed.
- The 4 old reviewer entries remain in the store as unreferenced orphans. There is no garbage
  collection.
- Calls downstream of an edited call are reused only when the new answer reproduces their task text
  exactly. Here the fake reviewer gave the same verdicts, so the rewrite task matched. With a real
  model, a different verdict would change the rewrite task and cascade re-asks.

### Q8. Plain CPython asyncio: same behaviour, fewer lines, no sandbox or type check

Evidence is in `A-logs/q8-cpython.txt`.

How `bl_cpython.py` works:
- It compiles the script with `ast.PyCF_ALLOW_TOP_LEVEL_AWAIT`. It rewrites the trailing expression in
  the AST to `__result__ = ...`; the file itself is not edited.
- Inputs and agent functions are passed in as globals.
- An agent with no answer awaits a future that is never resolved.
- To detect that nothing can proceed, it checks after `sleep(0)` that `loop._ready` is empty. That is a
  **private asyncio attribute**. It is sound only because the scripts do no I/O and use no timers.
  `asyncio.run` then cancels the waiting tasks.

Results:
- **Same behaviour:** 6 steps, the same keys per step, byte-identical `prompt.md`, and the same final
  output. Running `bl.py step` and `bl_cpython.py step` on the same completed store gave the same md5.
  The fail and out-of-attempts runs also matched.
- **Clean shutdown:** 0 bytes on stderr under `-X dev -W always`.
- **Faster:** about 0.36 s per step, against about 0.82 s on Monty.
- **What is lost:**
  - The sandbox: the script runs with full host privileges.
  - The static type check.
  - Enforcement of the Monty subset: a script that runs on CPython could still fail on Monty.
- **Errors are shorter:** `RuntimeError: writer refused for b`, without Monty's traceback.
- **Line count:** about 55 runner-specific lines, against about 62 for Monty.

## Problems and caveats

- Replay costs O(calls so far) per step, so O(n²) across a run.
- Monty's default `max_suspensions` is 1000 per checkout, and each call costs at least one suspension.
  A long workflow could hit this limit on replay. That is an expectation; I did not test it. bl.py does
  not raise the limit.
- Orphan prompts after an error step (Q4a), and stale keys after edits (Q7), build up in the store.
- `type_check_stubs` imports `pydantic_ai`, which is slow. I moved that import inside the function so
  that `complete` and `fail` stay at about 0.3 s.
- The repo also has unrelated root files (`catalog.py`, `workflows/review.py`, `smoke.py`). I did not
  use or change them.
