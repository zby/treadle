# Replay a completed store N times, recording the event sequence bl.step's loop sees.
import sys, json, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bl, pydantic_monty as pm
store, n = Path(sys.argv[1]), int(sys.argv[2])
cat = bl.load_catalog(bl.DEFAULT_CATALOG)
code = Path('shared/review_loop.py').read_text()
inputs = {'topics': ['a', 'b', 'c'], 'max_rounds': 2}
traces, outputs, pending_orders = collections.Counter(), collections.Counter(), collections.Counter()
with pm.Monty(max_processes=1) as pool:
    for _ in range(n):
        ev, outcomes = [], {}
        with pool.checkout() as s:
            snap = s.feed_start(code, inputs=inputs)
            while not isinstance(snap, pm.MontyComplete):
                if isinstance(snap, pm.FunctionSnapshot):
                    key = bl.call_key(snap.function_name, snap.kwargs['task'])
                    ev.append(f"call{snap.call_id}:{snap.function_name}:{key[:6]}")
                    outcomes[snap.call_id] = bl.lookup(store, key)
                    snap = snap.resume({'future': ...})
                else:
                    pending_orders[tuple(snap.pending_call_ids)] += 1
                    ready = {c: outcomes.pop(c) for c in (sorted(snap.pending_call_ids) if len(sys.argv) > 3 else snap.pending_call_ids) if outcomes.get(c)}
                    ev.append(f"resolve{sorted(ready)}")
                    snap = snap.resume(ready)
            outputs[json.dumps(snap.output)] += 1
        traces[' '.join(ev)] += 1
print('distinct call/resolve traces:', len(traces))
for t, c in traces.items(): print(c, 'x', t)
print('distinct outputs:', len(outputs))
print('pending_call_ids orders seen:', dict(pending_orders))
