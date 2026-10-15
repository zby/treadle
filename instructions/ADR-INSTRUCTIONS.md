# Record decisions and their reasons

Keep a small set of plain Markdown records in `adr/NNN-short-decision-name.md`.
Record decisions whose reasoning will help future implementation, debugging, or
design changes. Related choices can share one coherent record. Do not create an
ADR for each commission or use ADRs as a second backlog.

Ground runtime behavior in acceptance tests and link them. Do not present an
unvalidated implementation detail as test-established behavior. Durable process
conventions are distinct from runtime acceptance and need not be executable test
contracts.
Record both informed decisions and conventions chosen to settle an open choice;
no experiment is required to acknowledge a deliberate preference.

Assignments, temporary permissions, worktrees, and scheduling belong in the
work's commission, not in ADRs. Unresolved options remain in a commission or
proposal until a choice is made.

## Writing a record

Read relevant ADRs before changing a contract. Record a decision alongside the
instructions or implementation that applies it, even if implementation is still
pending. Acceptance of a decision is not proof of completed behavior.

Choose the next numeric prefix; do not renumber or reuse retired numbers during
ordinary work. Coordinate concurrent authors. No frontmatter, generator, or
validation framework is required. Use these headings with proportional detail;
combine related sections when clearer:

```markdown
# NNN — <decision>

Status: accepted | superseded | deprecated
Confidence: firm | tentative
Decision date: YYYY-MM-DD, or unknown
Recorded: YYYY-MM-DD

## Context
<Problem, constraints, consequential uncertainty.>
## Decision
<Choice, scope, authorization, and implementation status.>
## Basis
<Evidence and links; distinguish observations, reports, deductions,
expectations, and preferences. Name missing evidence.>
## Alternatives and consequences
<Options actually considered, trade-offs, risks, limits, and consumers.>
## Revisit when
<Conditions or evidence that would reopen the choice.>
```

### Tentative decisions

Mark a decision `Confidence: tentative` when it was made without solid
arguments: by intuition, or by whoever was writing at the time to settle an
open choice and move on. A tentative decision is still followed; the mark says
it is cheap to reopen and should be checked first when something it touches
goes wrong. In its Basis, say plainly where it came from ("the operator's
intuition; no argument recorded", "chosen by the drafting agent; alternatives
looked equally good") and what evidence would settle it. Do not dress an
intuition up with reasons found afterwards.

Keep tentative choices in their own record rather than inside a firm one, so
the mark applies to the whole record. When evidence arrives, change the mark to
`firm` and add the evidence, or replace the decision. List the open ones with
`rg -l '^Confidence: tentative' adr/`, and keep the table in
[adr/README.md](../adr/README.md) current when adding or changing a record.

Do not invent an alternative debate, motivation, measurement, or precision.
“None developed” is valid. Link evidence with the claims it supports. For a
retrospective decision, inspect retained instructions and history; say it
is retrospective and leave unknown dates/reasons unknown.

## Applying and maintaining decisions

Link the ADR from the design document or instruction that uses it, and keep the
operative rule there. Relevant commissions must identify decisions that constrain
judgment. A record does not expand an agent's authority.

For a refinement, update the record and its consumers. For a replacement, create
a new ADR, mark the old superseded, and link both ways. Mark abandoned decisions
deprecated with their limits, and keep them discoverable. Git holds edit history.
This repository retains reusable decisions in ADRs.

This self-contained procedure adapts Commonplace's decision-recording practice;
no external checkout is required.
