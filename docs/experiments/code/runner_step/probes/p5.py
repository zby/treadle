# After dropping a mid-feed session, does a new checkout on the same worker see old globals?
import pydantic_monty as pm
code = open('shared/review_loop.py').read()
with pm.Monty(max_processes=1) as pool:
    with pool.checkout() as s:
        snap = s.feed_start(code, inputs={'topics': ['a'], 'max_rounds': 2})
        while isinstance(snap, pm.FunctionSnapshot):
            snap = snap.resume({'future': ...})
        pid = s.worker_pid
    with pool.checkout() as s2:
        print('same worker:', s2.worker_pid == pid)
        for name in ('topics', 'draft_and_review', 'max_rounds'):
            try:
                print(name, '->', s2.feed_run(name))
            except pm.MontyRuntimeError as e:
                print(name, '->', e.display('type-msg'))
