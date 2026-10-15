"""Probe: does QuietLoop see a branch that waits on raw socket I/O woken by a plain thread?"""
import asyncio, socket, sys, threading, time
sys.path.insert(0, "pyd_step")
import bl

class Loud(bl.QuietLoop):
    def _check(self):
        print(f"  check t={time.monotonic()-T0:.3f} live={len(self.live)} jobs={self.jobs}", flush=True)
        super()._check()

async def main():
    loop = asyncio.get_running_loop()
    loop.idle = loop.create_future()
    r, w = socket.socketpair(); r.setblocking(False)
    threading.Timer(0.5, w.send, [b"x"]).start()
    rt = asyncio.ensure_future(loop.sock_recv(r, 1))
    await asyncio.wait([rt, loop.idle], return_when=asyncio.FIRST_COMPLETED)
    print(f"idle={loop.idle.done()} reader_done={rt.done()} t={time.monotonic()-T0:.2f}s")

T0 = time.monotonic()
with asyncio.Runner(loop_factory=Loud) as r: r.run(main())
