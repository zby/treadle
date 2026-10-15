"""Route 3: run the fixed script through DynamicWorkflowToolset.call_tool directly, no orchestrator LLM.

The same pattern the harness's own tests use (tests/dynamic_workflow/test_dynamic_workflow.py:84-132).
"""

import asyncio
import json
import sys
from pathlib import Path

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.dynamic_workflow import DynamicWorkflowToolset, WorkflowAgent

sys.path.insert(0, str(Path(__file__).parent))
from fakes import build_agents  # noqa: E402


async def main() -> None:
    script = Path("shared/review_loop.py").read_text()
    code = "topics = ['a', 'b', 'c']\nmax_rounds = 3\n" + script  # inputs: DynamicWorkflow takes only code
    toolset = DynamicWorkflowToolset[object](agents=[WorkflowAgent(a) for a in build_agents().values()])
    ctx = RunContext[object](deps=None, model=TestModel(), usage=RunUsage(), prompt=None, messages=[], run_step=1)
    tool = (await toolset.get_tools(ctx))[toolset.tool_name]
    print(json.dumps(await toolset.call_tool(toolset.tool_name, {"code": code}, ctx, tool), indent=1))


asyncio.run(main())
