import asyncio, json, sys
sys.path.insert(0, "runner_pydantic")
import fakes
from route2 import run_script

async def main():
    agents = fakes.build_agents()
    r = await run_script(agents, {"topics": ["a", "b", "c"], "max_rounds": 3})
    print("RESULT", json.dumps(r, indent=1))
    ev = fakes.EVENTS
    print("max concurrent writer", fakes.max_overlap(ev, "writer"), "reviewer", fakes.max_overlap(ev, "reviewer"))
    print("events:"); [print(" ", e[0], e[1], round(e[2], 2)) for e in ev]
    # Failure
    fakes.FAIL_WRITER_TOPIC.append("c")
    try:
        r = await run_script(agents, {"topics": ["a", "b", "c"], "max_rounds": 3})
        print("FAIL-RESULT", r)
    except BaseException as e:
        print("FAIL-RAISED", type(e).__name__, "|", e)
    # Script catching failure is script-level; also check max_rounds=1 exhaustion
    fakes.FAIL_WRITER_TOPIC.clear()
    try:
        print(await run_script(agents, {"topics": ["b"], "max_rounds": 1}))
    except BaseException as e:
        print("EXHAUST-RAISED", type(e).__name__, "|", e)
    # missing inputs
    try:
        print(await run_script(agents, {"topics": ["a"]}))
    except BaseException as e:
        print("MISSING-INPUT", type(e).__name__, "|", e)
    # type of reviewer output seen by script
    probe = "v = await reviewer(task='Review this paragraph about a.')\n[type(v).__name__, v]"
    from pathlib import Path
    p = Path("/tmp/claude-1000/-home-zby-llm-beads-lite/d91deaa1-130d-4a9d-adce-b34cd20e2a10/scratchpad/probe.py"); p.write_text(probe)
    print("PROBE", await run_script(agents, {}, p))
asyncio.run(main())
