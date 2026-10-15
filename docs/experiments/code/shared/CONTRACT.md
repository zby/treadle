# Experiment: one workflow script, two runners

Root: this `experiment/` directory (a throwaway uv project, Python 3.12).
Installed: pydantic-monty 1.1.0, pydantic-ai-slim 2.54.0, pydantic-ai-harness 0.54.0.
Run code with `uv run python ...` from the experiment root. Do not add or upgrade packages.
Do not touch /home/zby/llm/beads_lite. No network access is needed.

Reference sources:
- Monty Python API: the installed package (`.venv/lib/python3.12/site-packages/pydantic_monty/`,
  read the `.pyi` stubs and docstrings). Do not guess the API; read it.
- pydantic-ai-harness source clone (commit 4399efa): `../pah/`. Dynamic workflow:
  `pydantic_ai_harness/dynamic_workflow/_toolset.py`, Monty driver: `pydantic_ai_harness/_monty_exec.py`,
  docs: `docs/dynamic-workflow.md`.

## The idea under test

A workflow is one script in the Monty Python subset. It calls agents as
`await name(task="...")` and runs in two places, unchanged:

1. **Pydantic AI**: the script runs once, end to end; each agent call is `Agent.run(task)`.
2. **The bl step runner**, executed by a coordinating agent in its own harness (Claude Code,
   Codex). One `step` executes the script until every branch waits for an answer that does
   not exist yet, writes the missing prompts as files and exits. The harness gets the prompts
   answered by its own sub-agents, stores each answer with `complete`, and runs `step` again.
   Each step replays the script from the top against the stored answers.

## The shared files

- `shared/review_loop.py`: the example script (gather, sequential dependency, loop, typed output,
  `raise`). Inputs `topics` and `max_rounds` are top-level names supplied by the runner.
- `shared/catalog.py`: the agent catalog (name, description, output type).

## Rules both runners follow

- The script file is used byte-for-byte unchanged. A runner may supply inputs (Monty `inputs=`,
  or prepended assignments if a route offers no inputs) but must not edit the script.
- A typed agent (output_type set) returns a dict to the script; an untyped one returns a str.
- An agent failure raises `RuntimeError(message)` inside the script, as DynamicWorkflow does.

## bl step runner semantics (runner A)

- Answer identity is content: `key = sha256(agent_name + "\n" + task)` as hex.
- Store layout: `<store>/<key>/` with `call.json` (agent, task), `prompt.md` (catalog description,
  output schema if typed, then the task), and after completion `answer.json` (typed) or
  `answer.md` (untyped), or `failure.txt` (the agent failed or refused).
- `step SCRIPT --store DIR --inputs JSON`: replay. Each agent call: answer exists -> return it;
  failure exists -> raise RuntimeError in the script; otherwise write `call.json`/`prompt.md` if
  absent and leave the call pending. When nothing can proceed: print the open keys and exit 2.
  Script finished: print the result as JSON, exit 0. Uncaught script error: print it, exit 1.
- `complete KEY FILE --store DIR`: validate against the agent's output type (typed: JSON matching
  the Pydantic model), write the answer atomically, never overwrite. Invalid answer: exit 1, nothing
  written.
- `fail KEY REASON --store DIR`: write `failure.txt`.
- Independent pending calls must all be posted in the same step (gather branches each progress
  as far as they can).

## Reporting

Write your findings to `results/<your-letter>.md`: what you ran (commands), what happened
(outputs, pasted or summarized faithfully), answers to your questions with evidence, problems,
and the size of your code. Separate measured facts from expectations. Negative results are
results; do not hide a failure behind a workaround without saying so.
