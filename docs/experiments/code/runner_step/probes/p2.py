import pydantic_monty as pm
code = open('shared/review_loop.py').read()
with pm.Monty() as pool:
    with pool.checkout() as s:
        snap = s.feed_start(code, inputs={'topics':['a','b','c'],'max_rounds':2})
        n=0
        while not isinstance(snap, pm.MontyComplete) and n<10:
            n+=1
            print(type(snap).__name__, getattr(snap,'function_name',None), getattr(snap,'call_id',None), getattr(snap,'kwargs',None), getattr(snap,'pending_call_ids',None), getattr(snap,'variable_name',None))
            if isinstance(snap, pm.FunctionSnapshot):
                snap = snap.resume({'future': ...})
            elif isinstance(snap, pm.NameLookupSnapshot):
                snap = snap.resume()
            else:
                print('future snapshot; dropping'); break
print('exited session cleanly')
