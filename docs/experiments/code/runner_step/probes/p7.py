# Does the type checker need the inputs declared in the stubs?
import sys; from pathlib import Path
sys.path.insert(0, 'runner_step'); import bl, pydantic_monty as pm
cat = bl.load_catalog(bl.DEFAULT_CATALOG); code = Path('shared/review_loop.py').read_text()
with pm.Monty() as pool:
    for decl in ({}, {'topics': 0, 'max_rounds': 0}):
        with pool.checkout(type_check=True, type_check_stubs=bl.type_check_stubs(cat, decl)) as s:
            try:
                snap = s.feed_start(code, inputs={'topics': ['a'], 'max_rounds': 2}); print('declared' if decl else 'undeclared', '-> ok', type(snap).__name__)
            except pm.MontyTypingError as e:
                print('undeclared' if not decl else 'declared', '->', e.display().splitlines()[0])
