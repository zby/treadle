"""bl `step` on plain CPython asyncio (no sandbox, no type check). complete/fail are bl.py's.

Same CLI and exit codes as `bl.py step`. The script is exec'd with top-level await; its trailing
expression is captured by rewriting the AST (the file itself is not edited).
"""

import ast
import asyncio
import json
import sys
from pathlib import Path

import bl


def compile_script(path):
    tree = ast.parse(Path(path).read_text(), filename=str(path))
    if tree.body and isinstance(tree.body[-1], ast.Expr):  # keep the last expression's value
        tree.body[-1] = ast.Assign(targets=[ast.Name("__result__", ast.Store())], value=tree.body[-1].value)
        ast.fix_missing_locations(tree)
    return compile(tree, str(path), "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)


def make_agent(name, agent, store, open_keys):
    async def call(*args, **kwargs):
        if args or set(kwargs) != {"task"} or not isinstance(kwargs["task"], str):
            raise TypeError(f"{name}() takes only task=<str>")
        key = bl.call_key(name, kwargs["task"])
        result = bl.lookup(store, key)
        if result is None:
            bl.post(store, key, agent, kwargs["task"])
            open_keys.setdefault(key, name)
            await asyncio.get_running_loop().create_future()  # never resolved: this branch waits
        if "exception" in result:
            raise result["exception"]
        return result["return_value"]

    return call


async def drive(code, globs):
    loop = asyncio.get_running_loop()
    main = asyncio.ensure_future(eval(code, globs))  # a coroutine because of top-level await
    while not main.done():
        await asyncio.sleep(0)
        # Quiescent: no other callback is runnable, and the script does no I/O or timers, so every
        # task waits on a never-resolved agent future. `_ready` is a private asyncio attribute.
        if not loop._ready and not main.done():
            return False  # asyncio.run cancels the waiting tasks on exit
    main.result()  # re-raise the script's error
    return True


def step(script, store, inputs, catalog_path=bl.DEFAULT_CATALOG):
    catalog, store, open_keys = bl.load_catalog(catalog_path), Path(store), {}
    globs = {"__name__": "__workflow__", **inputs}
    globs.update({n: make_agent(n, a, store, open_keys) for n, a in catalog.items()})
    try:
        done = asyncio.run(drive(compile_script(script), globs))
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if not done:
        for key in sorted(open_keys):
            print(key, open_keys[key])
        return 2
    print(json.dumps(globs.get("__result__"), indent=2))
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["step"]:
        import argparse

        p = argparse.ArgumentParser(prog="bl_cpython step")
        p.add_argument("script")
        p.add_argument("--store", required=True)
        p.add_argument("--inputs", default="{}")
        a = p.parse_args(sys.argv[2:])
        sys.exit(step(a.script, a.store, json.loads(a.inputs)))
    sys.exit(bl.main())
