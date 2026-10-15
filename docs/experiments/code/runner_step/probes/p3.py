# Partial future resolution + type-check of inputs
import pydantic_monty as pm, sys
sys.path.insert(0,'runner_step')
code = open('shared/review_loop.py').read()
stubs = open('runner_step/probes/stubs.txt').read() if len(sys.argv)>1 else None
with pm.Monty() as pool:
    with pool.checkout(type_check=stubs is not None, type_check_stubs=stubs) as s:
        try:
            snap = s.feed_start(code, inputs={'topics':['a','b'],'max_rounds':2})
        except pm.MontyTypingError as e:
            print(e.display()); raise SystemExit
        while True:
            if isinstance(snap, pm.FunctionSnapshot):
                print('call', snap.call_id, snap.kwargs['task'][:40]); snap = snap.resume({'future': ...})
            elif isinstance(snap, pm.FutureSnapshot):
                ids = snap.pending_call_ids; print('future', ids)
                if 0 in ids:
                    snap = snap.resume({0: {'return_value': 'draft A'}})
                else:
                    break
            else:
                print(snap); break
