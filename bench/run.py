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
def estimate(runs, model, ntasks, narms, long=False):
    """Calibrated on the 2026-11-14 run: ~0.007 USD per short Haiku run (real cost was 26x below the first guess)."""
    scale = {'haiku': 1, 'sonnet': 3, 'opus': 15}.get(model, 3)
    return 0.007 * scale * (8 if long else 1) * runs * ntasks * narms
def find_claude():
    for c in glob.glob(os.path.join(os.path.expanduser('~'), 'AppData/Local/Claude-Data/*/claude-code/*/*/claude.exe')): return c
    return shutil.which('claude') or 'claude'
LONG = [
 ('audit', 'Create 12 files mod01.py..mod12.py, each with 3 small functions and docstrings. Then read every file and write REPORT.md listing each function name with its file. Then add a type-hint to every function, file by file. Finally run python -m py_compile on all and report.'),
 ('refactor', 'Create data.csv with 40 rows (id,name,score). Write stats.py computing mean, median and max of score, tests.py with 5 asserts, run them, then change stats.py to also compute stdev, update tests, run again, and summarise in 3 lines.'),
]
def cfg_dir(on, md=None):
    d = tempfile.mkdtemp(prefix='cairn-bench-cfg-')
    if on:
        for f in ('settings.json', 'CLAUDE.md'):
            if os.path.exists(os.path.join(HOME, f)): shutil.copy(os.path.join(HOME, f), d)
        if md: shutil.copy(md, os.path.join(d, 'CLAUDE.md'))
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
    tasks = LONG if '--set' in a and a[a.index('--set')+1] == 'long' else TASKS
    arms = a[a.index('--arms')+1].split(',') if '--arms' in a else ['off', 'on']
    old = os.path.expanduser('~/AppData/Local/Temp/CLAUDE.md.pre-lean')
    est = estimate(runs, model, len(tasks), len(arms), tasks is LONG); print(f'{len(tasks)} tasks x {runs} runs x {len(arms)} arms on {model}: estimated ~${est:.2f}')
    if '--dry-run' in a: return
    if '--yes' not in a and input('run? [y/N] ').lower() != 'y': return
    claude = find_claude(); res = {x: [] for x in arms}
    for arm in arms:
        cfg = cfg_dir(arm != 'off', old if arm == 'old' else None)
        for name, prompt in tasks:
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
    if any(not v for v in res.values()): print('no usable runs (is the CLI logged in?)', {k: len(v) for k, v in res.items()}); return
    tag = ('long' if tasks is LONG else 'short')
    out = dict(runs=min(len(v) for v in res.values()), model=model, **{k: agg(v) for k, v in res.items()})
    json.dump(dict(out, raw=res), open(os.path.join(HERE, f'results-{tag}-{len(os.listdir(HERE))}.json'), 'w'), indent=1)
    if set(arms) != {'off', 'on'}: print(json.dumps(out, indent=1)); return
    mf = os.path.join(HOME, 'cairn/state/measured.json')
    try: m = json.load(open(mf))
    except Exception: m = {}
    m['bench'] = out; json.dump(m, open(mf, 'w'), indent=1); print(json.dumps(out, indent=1))
if __name__ == '__main__': main()
