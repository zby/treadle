# Experiments

Reports from the October 2026 feasibility experiments behind
[ADR 001](../../adr/001-step-runner-for-pydantic-ai-workflows.md), plus lessons
from developing the current runner.

- [Runner lessons](2026-10-runner-lessons.md): callback tracking, integrity,
  cancellation, imports, exact text, test consolidation and observed runtimes.

## Historical feasibility experiments

Each report below was written by the agent that ran the experiment; the
coordinating session reran the main tests of each and got the same results.
These are the canonical copies; experiment code and recorded logs are in
[code/](code/). Paths in these reports are relative to `code/`, and runs used its
own `pyproject.toml`. Original session scratchpad stores are not retained.

**Historical commands, not current usage:** these prototypes were named `bl`
and used `complete`/`fail`. Their source and recorded output retain those names.
The current CLI is **`treadle step`, `treadle claim`, `treadle commit`, and
`treadle release`**; see [Running Treadle](../RUNNING.md). The current runner
is in `src/treadle/`, separate from these feasibility experiments.

The historical feasibility runs below used fake models. Current live-trial
observations are in [Runner lessons](2026-10-runner-lessons.md#live-trials).

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
