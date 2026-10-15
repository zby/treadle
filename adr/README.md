# Decision records

How to write them: [ADR-INSTRUCTIONS.md](../instructions/ADR-INSTRUCTIONS.md).

| ADR | Decision | Confidence |
|---|---|---|
| [001](001-step-runner-for-pydantic-ai-workflows.md) | Build Treadle as a step runner for Pydantic AI workflows | firm |
| [002](002-commit-attests-answer-files-by-hash.md) | A commit attests answer files by hash | tentative |
| [003](003-progressive-codification.md) | Progressive codification of the orchestrator | firm |
| [004](004-occurrence-indices-per-scope.md) | Count occurrence indices per scope | tentative |
| [005](005-name-treadle.md) | Name the project Treadle | tentative |

Tentative decisions were made without solid arguments and are the first to
reopen. List them with `rg -l '^Confidence: tentative' adr/`.
