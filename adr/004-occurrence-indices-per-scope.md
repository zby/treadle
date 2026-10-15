# 004 — Count occurrence indices per scope

Status: accepted
Confidence: tentative
Decision date: 2026-10-15
Recorded: 2026-10-15

## Context

Answer keys include an occurrence index so that a repeated identical call is
asked again ([ADR 001](001-step-runner-for-pydantic-ai-workflows.md)). Counted
across the whole replay, the index of a call depends on every identical call
made before it anywhere in the workflow.

A later feature, memoized tasks, would skip the body of a finished lifecycle
function on replay, restarting at task granularity as the build systems in
*Build Systems à la Carte* do (DESIGN.md, "Lineage" and "Not in version 1").
Skipped bodies stop counting their calls, so whole-replay indices would shift
and an identical call elsewhere could receive another call's answer. Fixing that
then would change the key format, and changing the format re-asks every stored
answer.

## Decision

Keys include a scope, and occurrence indices are counted per scope, from
version 1. Version 1 has one scope, the workflow, written as the empty string;
behaviour is the same as whole-replay counting. Cached operations use the same
scheme.

Memoized tasks themselves are not decided; they are recorded under "Later" in
[PLAN.md](../PLAN.md) and in DESIGN.md.

Implementation status: design only; PLAN.md stage 1.

## Basis

- Proposed by the drafting agent (Claude Opus 5.5) and accepted by the operator
  to keep the option of memoized tasks open at no cost now. The argument is a
  deduction, not a measurement: with scopes in the key, adding tasks changes
  only the keys of calls inside tasks.
- Tentative because the feature it prepares for is undesigned. The scope's form
  (the empty string at the root; name plus argument hash for tasks) is a guess
  at what that design will need.

## Alternatives and consequences

- **Whole-replay counting, as in the prototype.** Simpler; adding memoized
  tasks later would need a format version bump that re-asks every answer in
  every store.

Consequences: wrapping existing code in a task later still changes the keys of
the calls moved inside it, so those calls are asked again. Root-level calls and
workflows that never use tasks keep their answers.

## Revisit when

- Memoized tasks are designed and need a different scope form.
- Memoized tasks are dropped for good; the scope can then be removed at the next
  format version change.
