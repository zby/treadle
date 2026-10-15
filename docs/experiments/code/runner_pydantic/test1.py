import asyncio, json, sys
sys.path.insert(0, "runner_pydantic")
import fakes
from route1 import run_script, with_inputs, SCRIPT

INP = {"topics": ["a", "b", "c"], "max_rounds": 3}
text = SCRIPT.read_text()

async def main():
    agents = fakes.build_agents()
    out, log = await run_script(agents, with_inputs(text, INP))
    print("RESULT", json.dumps(json.loads(out), indent=1))
    ev = fakes.EVENTS
    print("max concurrent writer", fakes.max_overlap(ev, "writer"), "reviewer", fakes.max_overlap(ev, "reviewer"))
    [print(" ", e[0], e[1], round(e[2], 2)) for e in ev]
    print("--- unchanged script, no inputs")
    out, log = await run_script(agents, text); print(out, log)
    print("--- failure writer c, stop after first retry")
    fakes.EVENTS.clear(); fakes.FAIL_WRITER_TOPIC.append("c")
    out, log = await run_script(agents, with_inputs(text, INP)); print("OUT", out); print("LOG", log)
    print("--- failure, model repeats same code")
    fakes.EVENTS.clear()
    try:
        out, log = await run_script(agents, with_inputs(text, INP), on_retry="repeat"); print("OUT", out)
    except BaseException as e:
        print("RAISED", type(e).__name__, e)
    print("writer calls", sum(1 for e in fakes.EVENTS if e[0]=="writer" and e[1].startswith("start")))
    fakes.FAIL_WRITER_TOPIC.clear()
    print("--- exhaustion max_rounds=1 topic b")
    out, log = await run_script(agents, with_inputs(text, {"topics": ["b"], "max_rounds": 1})); print(out, log)
    print("--- probe typed output")
    probe = "v = await reviewer(task='Review this paragraph about a.')\n[type(v).__name__, v]"
    print(await run_script(agents, probe))
    print("--- probe positional / bad")
    print(await run_script(agents, "await writer('x')"))
asyncio.run(main())
