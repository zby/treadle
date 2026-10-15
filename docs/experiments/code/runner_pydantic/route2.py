"""Route 2: minimal Monty driver. Agents are external functions; inputs via Monty `inputs=`."""
from pathlib import Path
from pydantic_core import to_jsonable_python
from pydantic_monty import AsyncMonty

SCRIPT = Path(__file__).resolve().parents[1] / "shared" / "review_loop.py"


async def run_script(agents, inputs, script=SCRIPT):
    def ext(agent):
        async def call(*, task: str):
            try:
                return to_jsonable_python((await agent.run(task)).output)
            except Exception as exc:
                raise RuntimeError(f"sub-agent {agent.name!r} raised {type(exc).__name__}") from exc
        return call
    async with AsyncMonty() as pool:
        async with pool.checkout() as session:
            return await session.feed_run(script.read_text(), inputs=inputs,
                                          external_lookup={n: ext(a) for n, a in agents.items()})
