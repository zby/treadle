# Treadle — contributor instructions

CLAUDE.md is a symlink to this file. Edit AGENTS.md directly.

## Project and navigation

Treadle runs one agent workflow, written as ordinary Pydantic AI code, from any
agent harness. The CLI, package and import name are all `treadle`.
`treadle step` replays a workflow, delivers stored answers to its model calls
through a Pydantic AI `Model`, and prints every call still waiting for an answer
when no branch can proceed. Workers write answers where each prompt says and
`treadle commit` them; `treadle claim` keeps two workers off the same call.
Start with [README.md](README.md); usage is in [docs/RUNNING.md](docs/RUNNING.md).

Read [PLAN.md](PLAN.md), the [design](docs/DESIGN.md), and
[ADR 001](adr/001-step-runner-for-pydantic-ai-workflows.md) before implementation.
Decisions marked `Confidence: tentative` were made without solid arguments;
list them with `rg -l '^Confidence: tentative' adr/`, follow them, and report
evidence for or against them. Use `rg` first to locate scoped context.
Collection, lint, and packaging success do not establish runtime acceptance.

| Work | Procedure |
|---|---|
| Recording or changing durable decisions | [ADR-INSTRUCTIONS.md](instructions/ADR-INSTRUCTIONS.md) |

Implementation commissions require independent verification before acceptance.

## Development and safety

- Use **uv** for environments, dependencies, builds, and command execution. Run
  `uv sync --locked`, `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, and `uv build`. Commit uv.lock after deliberate
  dependency changes. Do not install dependencies into the system interpreter.
- All applicable checks must pass before implementation acceptance. Do not
  disguise missing behavior with blanket skips.
- YAGNI: record unnecessary features instead of implementing them (PLAN.md,
  "Later"). Use one term per concept and few dependencies. Pydantic AI is the
  framework; build on its public interfaces (`Model`, `agent.override`,
  durable-execution APIs) rather than copying or patching its internals. Use the
  standard library (argparse, json, pathlib, asyncio) for the rest. No unsolicited
  queue, database, server, or workflow automation.
- No compatibility layer or migration without a consumer need. The prompt
  rendering format and cached-operation names are part of answer keys: changing
  them invalidates stored answers, so version the format and treat names as
  stable data.
- Tests are functional: run workflows through the `treadle` CLI and directly in
  Pydantic AI, and inspect printed output, exit codes and store files, not
  internal helpers. Use isolated stores and fake models (`FunctionModel`,
  `TestModel`); tests never call a real model API. Cover replay determinism,
  gather fan-out, repeated identical calls, typed validation, failure, commits,
  claims between concurrent workers, cached operations and their exceptions, and
  unsupported awaits. Read Pydantic AI and
  asyncio source rather than guessing their behavior.
- Store writes are atomic and never overwrite an answer. Do not perform side
  effects in workflow code outside cached operations, and do not retry an
  operation whose outcome is uncertain without saying so.
- Save reusable tools in scripts/. For downloads use `curl -fsSL -o` with literal
  paths in a standalone command; keep setup/extraction separate and request
  escalation if blocked.

## Execution and delegation boundaries

Work from purpose, observable success, and binding constraints. Choose methods
within delegated authority; do not ask permission for ordinary implementation
choices already delegated. A suggested route may change with evidence, but goals,
acceptance, shared interfaces, and ownership may not silently change.

For an unstated consequential choice, follow a verified inherited rule or exercise
explicitly delegated judgment using authorized evidence. Choose freely only when
alternatives are acceptable and independent of peer work; otherwise return the
gap. Stop affected work when authority, evidence, resources, or ownership are
missing or conflicting. Continue safe independent work and return the concrete
blocker, observations, preserved state, and decision needed.

Delegation does not expand authority. The parent retains scheduling, integration,
verification of composed results, and recovery unless explicitly transferred.
Parallel writers need disjoint ownership or explicit coordination; shared
interfaces need a common decision owner. Nested handoffs retain the original
intent and boundaries. A cheaper executor is not a reason to weaken acceptance.

Dispatch **Sol (`gpt-6.1-sol`)** implementers and **Astra (`gpt-6-astra`)** independent
verifiers explicitly, in separate sessions. Record the selected model in the
handoff. If unavailable, return that constraint rather than substitute silently.

Report partial and negative results honestly. Lead with the outcome or decision;
use short, literal sentences, keep uncertainty beside claims, and link evidence.
Distinguish design targets from measurements. Close work only against acceptance
evidence.

## Git

- Review status and diff; preserve others' work. Never overwrite, revert, or stash
  another contributor's changes, or reset hard/force-push without permission.
- Stage explicit files, never `git add -A`. Prefer complete artifacts and atomic
  `git add <files> && git commit ...`; do not partially stage shared files merely
  to expose an artifact. Handle unrelated changes separately. If either step is
  blocked, retry the whole operation with escalation when available.
- Use one imperative subject under about 72 characters, without `feat:` prefixes.
  Explain the intended result in the body when unclear. For sweeps/relocations,
  state what moved, how many, and what was kept, cut, or deferred. Keep change
  history in commits, not reference documents.
- Commit relocations separately from content edits so history follows renames.
  Add applicable trailers only; use `Model: <model id>` when the exact identity
  is available.
