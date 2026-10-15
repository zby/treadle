# 003 — Progressive codification of the orchestrator

Status: accepted
Confidence: firm
Decision date: 2026-10-15
Recorded: 2026-10-15

## Context

Under `treadle step` ([ADR 001](001-step-runner-for-pydantic-ai-workflows.md)) an
orchestrator agent in the harness runs the loop and does the bookkeeping:
stepping, dispatching prompts, committing answers. Agents are unreliable at long
bookkeeping, and harnesses differ in what they can automate.

## Decision

The orchestrator's work is kept small and mechanical, and users move it into
code duty by duty when the agent fails at it: agent, then harness hooks, then a
driver script, then a native run in Pydantic AI or another harness that runs
Python. The workflow file does not change between levels. The CLI is designed
for this: every duty is a command with defined exit codes, step output is stable
and line-based and states the next action, and prompts are self-contained.

Implementation status: the CLI and the offline script driver
[`scripts/fake_review.py`](../scripts/fake_review.py) implement the mechanical
loop. [Functional tests](../tests/test_runner.py) compare the script-driven run
with direct Pydantic AI execution. Live trials have since run in Pi, Claude Code
and Codex; [Runner lessons](../docs/experiments/2026-10-runner-lessons.md#live-trials)
records the Pi one-call trial. Stage 2 still needs to record orchestrator mistakes
on real coding work, typed review and parallel workers ([PLAN.md](../PLAN.md)).

## Basis

- The operator's argument: control flow lives in workflow code, so the
  orchestrator only follows step output; that work is well contained and its
  complexity does not grow with the workflow's. Where an agent still fails,
  the failure names a specific duty that code can take over.
- Deduction: each level is possible because every duty is already a CLI command
  and the workflow is ordinary Pydantic AI code.
- At the decision, no real orchestrator had run a workflow. Stage 2 will record
  how often agents fail at each duty and whether harness hooks can take over.

## Alternatives and consequences

- **Require a driver script from the start.** Reliable, but needs per-harness
  dispatch code before anyone can use a workflow, and loses the harness's own
  sub-agents and judgement where they help.
- **Agent-only operation.** Simplest, but leaves no remedy when the agent fails.

Consequences: CLI output and exit codes become an interface for scripts as well
as agents, so changing them needs care; moving a run in progress to a native run
needs cache-through, which is not in version 1.

## Revisit when

- Stage 2 shows orchestrators failing at duties that hooks or scripts cannot
  take over, or failing so often that agent-run loops are not worth offering.
