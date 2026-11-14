"""Long multi-stage scenario: one growing session (A) vs stages in fresh sessions handed off through SESSION.md (B, what Cairn's
routing + handoff does). Headless, so the mod's compaction is NOT exercised; the idle gap and resume are.
  python scenario.py --dry-run | --yes [--model haiku] [--idle 330] [--stages 5]
Records per call: reported cost, context tokens (the context-size curve), cache write/read, wall time, and a correctness check per stage.
Also prints an 'interactive-equivalent' cost for A: `claude -p --resume` re-writes the cache on every call (measured in round 3), which
interactive replies inside the TTL do not; the equivalent re-prices the already-seen prefix at the cache-read price (assumed table, labelled)."""
import json, os, shutil, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run
STAGES = [
 ('pkg', 'In this folder create a python package shop/ with models.py (Item, Cart classes), pricing.py (total with 10% discount over 100) and __init__.py. Keep it small.',
  'python -c "import shop.models, shop.pricing"'),
 ('tests', 'Write tests.py with 6 plain-assert tests for the shop package and run it with python tests.py until it passes.', 'python tests.py'),
 ('feature', 'Add a coupon feature: Cart.apply_coupon(code) with codes SAVE5 (5 off) and HALF (50%). Add 3 tests and keep all tests passing.', 'python tests.py'),
 ('docs', 'Write README.md documenting every public function and class in shop/, then verify each name mentioned exists.', "python -c \"import os,sys;sys.exit(0 if os.path.getsize('README.md')>0 else 1)\""),
 ('bugfix', 'A bug report says totals are wrong when the cart is empty after a coupon. Reproduce it in a test, fix it, keep all tests passing.', 'python tests.py'),
]
NOTE = 'Continue the project in this folder. Read SESSION.md first for what exists, do ONLY the stage below, then update SESSION.md (state, files, next).\n\nStage: '
def call(claude, cfg, cwd, model, prompt, resume=None):
    cmd = [claude, '-p', prompt, '--model', model, '--output-format', 'json', '--dangerously-skip-permissions'] + (['--resume', resume] if resume else [])
    t = time.time(); r = subprocess.run(cmd, cwd=cwd, env=dict(os.environ, CLAUDE_CONFIG_DIR=cfg), capture_output=True, text=True, timeout=900)
    try: j = json.loads(r.stdout)
    except Exception: print('bad output', (r.stdout or r.stderr)[:200]); return None
    u = j.get('usage') or {}
    return dict(usd=j.get('total_cost_usd', 0), ctx=u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0),
                write=u.get('cache_creation_input_tokens', 0), read=u.get('cache_read_input_tokens', 0), out=u.get('output_tokens', 0),
                secs=round(time.time() - t, 1), sid=j.get('session_id'), turns=j.get('num_turns', 0))
def ok(cwd, check):
    return subprocess.run(check, shell=True, cwd=cwd, capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=cwd)).returncode == 0
def main():
    a = sys.argv; model = a[a.index('--model') + 1] if '--model' in a else 'haiku'
    idle = int(a[a.index('--idle') + 1]) if '--idle' in a else 330
    n = int(a[a.index('--stages') + 1]) if '--stages' in a else len(STAGES); st = STAGES[:n]
    per = {'haiku': 0.03, 'sonnet': 0.1, 'opus': 0.5}.get(model, 0.1)
    print(f'{n} stages x 2 arms on {model}, idle gap {idle}s before stage {n//2+1}: estimated ~${per*n*2:.2f}, wall ~{(n*2*60+idle*2)//60} min')
    if '--dry-run' in a or '--yes' not in a: return
    claude = run.find_claude(); res = {}
    for arm in ('A_one_session', 'B_handoff'):
        cfg = run.cfg_dir(arm == 'B_handoff'); w = tempfile.mkdtemp(prefix='cairn-bench-'); sid = None; rows = []
        for i, (name, prompt, check) in enumerate(st):
            if i == n // 2: time.sleep(idle)   # idle gap past the 5-minute cache TTL, then resume / new session
            if arm == 'A_one_session': r = call(claude, cfg, w, model, prompt, sid)
            else: r = call(claude, cfg, w, model, NOTE + prompt)
            if not r: break
            sid = r['sid']; r.update(stage=name, correct=ok(w, check)); rows.append(r)
            print(arm, name, {k: r[k] for k in ('usd', 'ctx', 'secs', 'correct')})
        res[arm] = dict(rows=rows, usd=sum(r['usd'] for r in rows), secs=sum(r['secs'] for r in rows), correct=sum(r['correct'] for r in rows),
                        ctx_curve=[r['ctx'] for r in rows])
        shutil.rmtree(w, ignore_errors=True); shutil.rmtree(cfg, ignore_errors=True)
    json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results-scenario.json'), 'w'), indent=1)
    for k, v in res.items(): print(k, 'usd', round(v['usd'], 3), 'secs', v['secs'], 'correct', v['correct'], '/', n, 'ctx', v['ctx_curve'])
main()
