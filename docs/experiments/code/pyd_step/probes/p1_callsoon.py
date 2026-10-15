"""Probe: do C-accelerated Task/Future schedule through the overridable public loop.call_soon?"""
import asyncio
calls = []
class L(asyncio.SelectorEventLoop):
    def call_soon(self, cb, *a, context=None):
        calls.append(getattr(cb, "__qualname__", repr(cb)))
        return super().call_soon(cb, *a, context=context)
async def child(): await asyncio.sleep(0); return 1
async def main():
    f = asyncio.get_running_loop().create_future()
    asyncio.get_running_loop().call_later(0.01, f.set_result, 2)
    return await asyncio.gather(child(), f)
print(type(asyncio.Task), asyncio.Task.__module__)
with asyncio.Runner(loop_factory=L) as r: print(r.run(main()))
print(len(calls), sorted(set(calls)))
