# 002 — A commit attests answer files by hash

Status: accepted
Confidence: tentative
Decision date: 2026-10-15
Recorded: 2026-10-15

## Context

[ADR 001](001-step-runner-for-pydantic-ai-workflows.md) settles that a worker
writes its answer as files and then runs `treadle commit`, and that a call is done
only when committed: a file's presence cannot tell a finished answer from one
being written, and workers should not have to follow a file-system protocol.
It leaves open what a commit records and what it may cover.

## Decision

- `treadle commit KEY [FILE...]` records, in `<key>/commit.json`, the worker, the
  time and the SHA-256 of each committed file: the answer file (`answer.md`,
  `answer.json` or `failure.md`) and any further files named. It copies nothing.
- A commit may cover several files. They must lie inside the call's directory.
- Every step checks the hashes of the committed files it reads; a changed or
  missing file stops the step with exit 1, naming the file.
- `treadle commit` checks only that the answer is present, unambiguous and, for a
  typed agent, one JSON object. Schema validation stays with Pydantic AI on
  replay.
- Committing without a claim is allowed when no other worker holds a live one.

Implementation status: design only ([DESIGN.md](../docs/DESIGN.md), "Prompts
and answers"); PLAN.md stage 1.

## Basis

- Hash-only commits and multi-file commits: the operator's intuition. The
  operator wants commits to stay small and expects to commit more than one file
  per answer, and has no solid argument beyond that.
- The remaining points were chosen by the drafting agent (Claude Opus 5.5) to
  settle open choices; no argument beyond the ones under Alternatives:
  the name `commit`; no schema check at commit; commits without claims;
  files restricted to the call's directory.
- No implementation or run has tested any of it.

Evidence that would settle it: stage 1 and 2 runs showing whether workers
produce extra files worth committing, whether hash mismatches occur and what
causes them, and whether invalid typed answers cost noticeable rounds.

## Alternatives and consequences

- **Copy the answer into `commit.json`.** Done is one atomic file, but the
  answer is escaped into JSON, unreadable for people and agents, and the commit
  grows with the answer. Rejected by the operator.
- **Copy the answer unchanged into a `committed/` directory**, built under a
  temporary name and renamed. Answers stay readable and immune to later edits;
  content is duplicated and multi-file commits copy everything. Replaced by this
  decision the same day.
- **Validate the schema at commit.** Tells the worker sooner, but `treadle commit`
  would have to load the workflow.
- **Name it `fill`**, the term of the original proposal, with the answer passed
  from anywhere. Equivalent; `commit` matches the operator's wording.

Consequences: committed files stay editable on disk, so a stray edit breaks the
next step instead of being ignored; files outside the call's directory, such as
repository code an implementer changed, cannot be committed and need another
rule.

## Revisit when

- Workers need to commit files outside the call's directory.
- Stray edits to committed files break steps in practice.
- Commits or answers grow large enough that hashing or copying matters.
