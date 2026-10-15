# Drop a session mid-feed (futures pending), then reuse the same pool: is the worker clean?
import pydantic_monty as pm, time, warnings
warnings.simplefilter('always')
code = open('shared/review_loop.py').read()
with pm.Monty(max_processes=1) as pool:
    for i in range(3):
        t = time.perf_counter()
        with pool.checkout() as s:
            pid = s.worker_pid
            snap = s.feed_start(code, inputs={'topics': ['a', 'b', 'c'], 'max_rounds': 2})
            while isinstance(snap, pm.FunctionSnapshot):
                snap = snap.resume({'future': ...})
            print(i, 'pid', pid, type(snap).__name__, snap.pending_call_ids)
        with pool.checkout() as s2:
            print('  next checkout pid', s2.worker_pid, 'topics defined?', s2.feed_run("'topics' in globals()") if False else s2.feed_run("x = 1\nx"))
        print('  elapsed %.3fs' % (time.perf_counter() - t))
print('pool closed')
