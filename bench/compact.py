"""Compaction economics, headless: build a big context, then ask N follow-ups, with and without /compact in between.
Isolates what the ledger estimates (cost of re-reading removed tokens). Cairn off in both arms (empty config dir).
  python compact.py --dry-run | --yes [--followups 8] [--model haiku]"""
import json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run
BUILD = ('Create 30 files data01.txt..data30.txt, each containing 60 lines of different made-up log entries (write them with a python script). '
         'Then print every file with cat so you have read them all, and tell me how many files you read.')
ASKS = ['How many lines does data05.txt have?', 'Does data10.txt exist? yes or no.', 'What is the first word of data01.txt? Check with head.',
        'List the file names in this folder in one line.', 'What is 12*12?', 'Count files starting with data1 using ls.',
        'Print the last line of data30.txt.', 'Say done.']
def call(claude, cfg, cwd, model, prompt, resume=None):
    cmd = [claude, '-p', prompt, '--model', model, '--output-format', 'json', '--dangerously-skip-permissions']
    if resume: cmd += ['--resume', resume]
    r = subprocess.run(cmd, cwd=cwd, env=dict(os.environ, CLAUDE_CONFIG_DIR=cfg), capture_output=True, text=True, timeout=600)
    try: return json.loads(r.stdout)
    except Exception: print('bad output:', (r.stdout or r.stderr)[:300]); return None
def main():
    a = sys.argv; n = int(a[a.index('--followups') + 1]) if '--followups' in a else 8
    model = a[a.index('--model') + 1] if '--model' in a else 'haiku'
    print(f'2 arms x (build + {n} follow-ups) on {model}: estimated ~$0.80 total')
    if '--dry-run' in a or '--yes' not in a: return
    claude = run.find_claude(); res = {}
    for arm in ('straight', 'compact'):
        cfg = run.cfg_dir(False); w = tempfile.mkdtemp(prefix='cairn-bench-'); tot = 0; ctx = []
        j = call(claude, cfg, w, model, BUILD)
        if not j: return
        sid = j['session_id']; tot += j['total_cost_usd']; build = j['total_cost_usd']
        if arm == 'compact':
            c = call(claude, cfg, w, model, '/compact', sid)
            if c: tot += c.get('total_cost_usd', 0); sid = c.get('session_id', sid); print('compact cost', c.get('total_cost_usd'), (c.get('result') or '')[:80])
        fu = 0
        for q in ASKS[:n]:
            j = call(claude, cfg, w, model, q, sid)
            if not j: break
            fu += j['total_cost_usd']; sid = j.get('session_id', sid)
            u = j.get('usage') or {}; ctx.append(u.get('input_tokens', 0) + u.get('cache_read_input_tokens', 0) + u.get('cache_creation_input_tokens', 0))
        res[arm] = dict(build=build, followups=fu, total=tot + fu, ctx_first=ctx[:1], ctx_last=ctx[-1:])
        shutil.rmtree(w, ignore_errors=True); shutil.rmtree(cfg, ignore_errors=True)
    print(json.dumps(res, indent=1)); json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results-compact.json'), 'w'), indent=1)
main()
