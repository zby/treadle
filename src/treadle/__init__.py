"""Replay ordinary Pydantic AI workflows, with external answers and cached I/O.

Workflows must be deterministic outside cached operations. Step mode supports
agent runs, cached operations, gathers/tasks, timers and executor threads, not
raw event-loop I/O. Identical concurrent requests use arrival-order occurrence
indices: do not rely on branch-specific identity for identical concurrent calls
as upstream answers become available in different steps. Use distinct prompts.
"""

import os

# Keep the CLI's machine-readable line protocol free of the upstream banner.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from .cache import cached, use_store
from .replay import CallFailed
from .store import StoreError

__all__ = ["CallFailed", "StoreError", "cached", "use_store"]
