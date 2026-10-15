# 005 — Name the project Treadle

Status: accepted
Confidence: tentative
Decision date: 2026-10-15
Recorded: 2026-10-15

## Context

The project began as Beads Lite, a lighter take on the Beads issue tracker, with
the CLI `bl`. After [ADR 001](001-step-runner-for-pydantic-ai-workflows.md) it
targets running one workflow from any agent harness; the tracker became a
consequence, and "Beads Lite" described a product that no longer exists.

## Decision

The project, package, import name and CLI are all `treadle`. It starts as a
new repository.

## Basis

- Taste: the operator chose it from candidates proposed by the drafting agent
  (Claude Opus 5.5). A treadle is the foot pedal that drives a loom or lathe one
  step per push and can later be replaced by a motor, which matches stepping and
  progressive codification ([ADR 003](003-progressive-codification.md)).
- Checked 2026-10-15: no PyPI project named `treadle`; no `treadle` command on
  the operator's machine. GitHub names and trademarks were not checked.

## Alternatives and consequences

Considered: `steprelay` (CLI `relay`, which collides with other tools),
`steprun` (plain, forgettable), `amake` (build-system lineage, undersells
portability). Taken on PyPI: `baton`, `cairn`, `waymark`, `trellis`, `spool`,
`loom`, `relayer`, `handover`, `agentmake`, `stepwright`. Skipped: `cadence`
(an established workflow engine).

Consequences: the metaphor needs one sentence of explanation in the README.

## Revisit when

- A GitHub, PyPI or trademark conflict appears before the first release.
- Users find the name unclear after the README explains it.
