"""Quiescence for the supported await subset, without asyncio private attributes.

Direct socket/subprocess I/O and arbitrary unresolved Futures are NOT supported:
wrap I/O in @cached, or use timers / asyncio.to_thread. Such I/O can otherwise be
mistaken for a waiting frontier; this loop is not a general deadlock detector.
"""

import asyncio


class QuietLoop(asyncio.SelectorEventLoop):
    def __init__(self):
        super().__init__()
        self.live = set()
        self.jobs = 0
        self.idle = None

    def _tracked(self, schedule, callback, args, context):
        handle = None

        def run(*args):
            self.live.discard(handle)
            try:
                callback(*args)
            finally:
                self.check_quiet()

        handle = schedule(run, *args, context=context)
        self.live.add(handle)
        return handle

    def call_soon(self, callback, *args, context=None):
        return self._tracked(super().call_soon, callback, args, context)

    def call_at(self, when, callback, *args, context=None):
        def schedule(cb, *args, context):
            return super(QuietLoop, self).call_at(when, cb, *args, context=context)

        return self._tracked(schedule, callback, args, context)

    def run_in_executor(self, executor, func, *args):
        future = super().run_in_executor(executor, func, *args)
        self.jobs += 1
        future.add_done_callback(self._job_done)
        return future

    def _job_done(self, future):
        self.jobs -= 1
        self.check_quiet()

    def check_quiet(self):
        self.live = {handle for handle in self.live if not handle.cancelled()}
        if self.idle is not None and not self.idle.done() and not self.live and not self.jobs:
            self.idle.set_result(None)
