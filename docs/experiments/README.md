# Experiments

Reports from the October 2026 feasibility experiments behind
[ADR 001](../../adr/001-step-runner-for-pydantic-ai-workflows.md). Each report
was written by the agent that ran the experiment; the coordinating session
reran the main tests of each and got the same results. The experiment code,
raw agent reports (`results/A.md` to `D.md`) and logs are in [code/](code/);
paths in the reports are relative to it, and runs used its own `pyproject.toml`.
Paths into the original session scratchpad (stores, `../scratch_d`) are not
retained. The prototype CLI was called `bl` and Treadle was then named Beads
Lite; the reports keep those names. Stage 1 ports the code that matters into
`src/` (see [PLAN.md](../../PLAN.md)). `code/catalog.py` and `code/workflows/`
at the top level were left by an agent and are not referenced by any report.

All runs used fake models. No real model or harness sub-agent answered a prompt.

| Report | Question | Outcome |
|---|---|---|
| [Monty step runner](2026-10-monty-step-runner.md) | Can a step runner replay a script in the Monty sandbox, post every pending agent call per step, and resume? | Yes; 6 steps for the example; found that identical repeated calls reuse answers and that Monty's pending-call order is random |
| [Monty script in Pydantic AI](2026-10-monty-in-pydantic-ai.md) | Does the same script run unchanged in Pydantic AI's `DynamicWorkflow` and in a small Monty driver? | Yes, with identical results |
| [Analysis workflow port](2026-10-analysis-port.md) | Does a real multi-agent workflow fit the Monty subset, and what must leave the script? | Fits; acquisition, publication and provenance move to the runner |
| [Pydantic AI step runner](2026-10-pydantic-step-runner.md) | Can ordinary Pydantic AI code run unchanged under the `bl step` prototype, with answers delivered through a Pydantic AI `Model`? | Yes; this is the chosen design |

The first three use Monty, a sandbox for model-written scripts. The chosen design
does not: workflows are trusted code written by people. Monty and
`DynamicWorkflow` remain a possible later addition for model-written workflows.

One finding postdates the reports: `DynamicWorkflowToolset.call_tool` runs a
fixed script without any orchestrator model, as the harness's own tests do
(`tests/dynamic_workflow/test_dynamic_workflow.py`, pydantic-ai-harness commit
`4399efa`). The Monty report's route 1 used a fake orchestrator model instead.
