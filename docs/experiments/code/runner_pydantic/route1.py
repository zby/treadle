"""Route 1: DynamicWorkflow as shipped. Orchestrator agent whose FunctionModel emits run_workflow(code=...)."""
import json
from pathlib import Path
from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai_harness.dynamic_workflow import DynamicWorkflow

SCRIPT = Path(__file__).resolve().parents[1] / "shared" / "review_loop.py"


def with_inputs(script_text: str, inputs: dict) -> str:
    """Supply inputs by prepending assignment lines (DynamicWorkflow has no inputs parameter)."""
    return "".join(f"{k} = {json.dumps(v)}\n" for k, v in inputs.items()) + script_text


async def run_script(agents, code, *, on_retry="stop"):
    """Returns (final_text, log). log: list of ('tool-return'|'retry', content) the orchestrator saw."""
    log = []

    async def orch(messages, info):
        last = messages[-1].parts[-1]
        if last.part_kind == "user-prompt":
            return ModelResponse(parts=[ToolCallPart("run_workflow", {"code": code})])
        if last.part_kind == "tool-return":
            log.append(("tool-return", last.content))
            return ModelResponse(parts=[TextPart(json.dumps(last.content))])
        log.append(("retry", last.content))  # retry-prompt
        if on_retry == "repeat":
            return ModelResponse(parts=[ToolCallPart("run_workflow", {"code": code})])
        return ModelResponse(parts=[TextPart("GAVE UP AFTER RETRY PROMPT")])

    orchestrator = Agent(FunctionModel(orch), capabilities=[DynamicWorkflow(agents=list(agents.values()))])
    result = await orchestrator.run("go")
    return result.output, log
