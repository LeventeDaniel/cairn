"""A/B benchmark: same small tasks with `claude -p`, Cairn off vs on, in throwaway folders.
  python run.py --dry-run          print the estimated cost, run nothing
  python run.py --runs 2 --model haiku [--yes]
Arm OFF: empty CLAUDE_CONFIG_DIR (no hooks, no Cairn CLAUDE.md block). Arm ON: copy of ~/.claude
settings.json hooks + CLAUDE.md + cairn/ kit. Needs a logged-in CLI (or ANTHROPIC_API_KEY).
Writes bench/results.json and ~/.claude/cairn/state/measured.json (bench part)."""
import json, os, shutil, subprocess, sys, tempfile, glob
HERE = os.path.dirname(os.path.abspath(__file__)); HOME = os.path.expanduser('~/.claude')
TASKS = [
 ('fizzbuzz', 'Create fizzbuzz.py that prints FizzBuzz for 1..30, then run it and show the output.'),
 ('rename', 'Create a.txt containing "hello world", then rename the word "world" to "cairn" in it and print the file.'),
 ('sum', 'Write sum.py that sums the numbers in nums.txt (create it with 1..10 first), run it, report the total.'),
 ('readme', 'Create README.md with a 3-line description of a todo CLI, then count its lines with wc -l.'),
]
PRICE = {'haiku': (1, 5, 0.1, 1.25), 'sonnet': (3, 15, 0.3, 3.75), 'opus': (15, 75, 1.5, 18.75)}
def estimate(runs, model):
    p = PRICE.get(model, PRICE['sonnet']); per = (6*82000*p[2] + 85000*p[3] + 1500*p[1]) / 1e6  # ~6 turns at the ~80k floor
    return per * runs * len(TASKS) * 2
def find_claude():
    for c in glob.glob(os.path.join(os.path.expanduser('~'), 'AppData/Local/Claude-Data/*/claude-code/*/*/claude.exe')): return c
    return shutil.which('claude') or 'claude'
def cfg_dir(on):
    d = tempfile.mkdtemp(prefix='cairn-bench-cfg-')
    if on:
        for f in ('settings.json', 'CLAUDE.md'):
            if os.path.exists(os.path.join(HOME, f)): shutil.copy(os.path.join(HOME, f), d)
        shutil.copytree(os.path.join(HOME, 'cairn'), os.path.join(d, 'cairn'), ignore=shutil.ignore_patterns('home', 'shots', 'state'))
    for f in ('.credentials.json',):
        if os.path.exists(os.path.join(HOME, f)): shutil.copy(os.path.join(HOME, f), d)
    return d
def parse(out):
    """claude -p --output-format json -> one Arm-like row, or None."""
    try: j = json.loads(out)
    except Exception: return None
    u = j.get('usage') or {}
    return dict(usd=float(j.get('total_cost_usd') or 0), turns=int(j.get('num_turns') or 0),
        fresh=u.get('input_tokens', 0), cacheRead=u.get('cache_read_input_tokens', 0),
        cacheWrite=u.get('cache_creation_input_tokens', 0), out=u.get('output_tokens', 0))
def agg(rows):
    n = max(1, len(rows)); t = max(1, sum(r['turns'] for r in rows))
    ctx = sum(r['fresh'] + r['cacheRead'] + r['cacheWrite'] for r in rows) / t
    return dict(usd=sum(r['usd'] for r in rows) / n, turns=t / n, ctxAvg=ctx,
        cacheRead=sum(r['cacheRead'] for r in rows) / n, cacheWrite=sum(r['cacheWrite'] for r in rows) / n, out=sum(r['out'] for r in rows) / n)
def main():
    a = sys.argv; runs = int(a[a.index('--runs') + 1]) if '--runs' in a else 2
    model = a[a.index('--model') + 1] if '--model' in a else 'haiku'
    est = estimate(runs, model); print(f'{len(TASKS)} tasks x {runs} runs x 2 arms on {model}: estimated ~${est:.2f}')
    if '--dry-run' in a: return
    if '--yes' not in a and input('run? [y/N] ').lower() != 'y': return
    claude = find_claude(); res = {'off': [], 'on': []}
    for arm in ('off', 'on'):
        cfg = cfg_dir(arm == 'on')
        for name, prompt in TASKS:
            for _ in range(runs):
                w = tempfile.mkdtemp(prefix='cairn-bench-')
                env = dict(os.environ, CLAUDE_CONFIG_DIR=cfg)
                r = subprocess.run([claude, '-p', prompt, '--model', model, '--output-format', 'json', '--dangerously-skip-permissions'],
                                   cwd=w, env=env, capture_output=True, text=True, timeout=300)
                row = parse(r.stdout)
                if row: res[arm].append(row)
                else: print('failed:', arm, name, (r.stdout or r.stderr)[:200])
                shutil.rmtree(w, ignore_errors=True)
        shutil.rmtree(cfg, ignore_errors=True)
    if not res['off'] or not res['on']: print('no usable runs (is the CLI logged in?)'); return
    out = dict(runs=min(len(res['off']), len(res['on'])), model=model, off=agg(res['off']), on=agg(res['on']))
    json.dump(dict(out, raw=res), open(os.path.join(HERE, 'results.json'), 'w'), indent=1)
    mf = os.path.join(HOME, 'cairn/state/measured.json')
    try: m = json.load(open(mf))
    except Exception: m = {}
    m['bench'] = out; json.dump(m, open(mf, 'w'), indent=1); print(json.dumps(out, indent=1))
if __name__ == '__main__': main()
