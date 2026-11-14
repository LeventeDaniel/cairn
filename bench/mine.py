"""Mine ~/.claude/projects transcripts: per-session usage, split by kit install time.
Usage: python mine.py [--cutoff ISO] [--json]"""
import json, glob, os, sys, datetime as dt
CUT = '2026-11-13T20:37:00'
PRICE = {  # USD per Mtok: in, out, cache read, cache write(5m)
 'opus': (15, 75, 1.5, 18.75), 'sonnet': (3, 15, 0.3, 3.75), 'haiku': (1, 5, 0.1, 1.25)}
def fam(m):
    m = (m or '').lower()
    for k in PRICE:
        if k in m: return k
    return 'sonnet'
def cost(f, u):
    p = PRICE[f]
    return (u.get('input_tokens',0)*p[0] + u.get('output_tokens',0)*p[1] + u.get('cache_read_input_tokens',0)*p[2] + u.get('cache_creation_input_tokens',0)*p[3]) / 1e6
def mine(path):
    seen = {}; comp = 0; first = None; users = 0
    for line in open(path, encoding='utf-8', errors='replace'):
        try: o = json.loads(line)
        except Exception: continue
        ts = o.get('timestamp')
        if ts and not first: first = ts
        if o.get('isCompactSummary') or o.get('subtype') == 'compact_boundary': comp += 1
        if o.get('type') == 'user' and not o.get('isSidechain') and not o.get('isMeta') and not o.get('isCompactSummary'): users += 1
        m = o.get('message') or {}
        if o.get('type') == 'assistant' and m.get('usage') and not o.get('isSidechain'):
            seen[m.get('id') or o.get('uuid')] = (m.get('model'), m['usage'])
    if not seen or not first: return None
    n = len(seen); ctx = []; cr = cw = inp = out = 0; usd = 0
    for mod, u in seen.values():
        if mod == '<synthetic>': continue
        c = u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0)
        ctx.append(c); cr += u.get('cache_read_input_tokens',0); cw += u.get('cache_creation_input_tokens',0)
        inp += u.get('input_tokens',0); out += u.get('output_tokens',0); usd += cost(fam(mod), u)
    if not ctx: return None
    return dict(file=os.path.basename(path), first=first, turns=len(ctx), users=users, compactions=comp,
        avg_ctx=sum(ctx)/len(ctx), max_ctx=max(ctx), cache_read=cr, cache_write=cw, fresh_in=inp, out=out,
        read_share=cr/max(1,cr+cw+inp), usd=usd, usd_per_turn=usd/len(ctx))
def main():
    cut = CUT
    if '--cutoff' in sys.argv: cut = sys.argv[sys.argv.index('--cutoff')+1]
    rows = []
    for p in glob.glob(os.path.expanduser('~/.claude/projects/**/*.jsonl'), recursive=True):
        if '/subagents/' in p.replace(chr(92),'/'): continue
        r = mine(p)
        if r: r['proj'] = os.path.basename(os.path.dirname(p))[-30:]; rows.append(r)
    rows.sort(key=lambda r: r['first'])
    if '--json' in sys.argv: print(json.dumps(rows, indent=1)); return
    for r in rows:
        print(f"{'A' if r['first'][:19] >= cut else 'B'} {r['first'][:16]} turns={r['turns']:4} comp={r['compactions']} avgctx={r['avg_ctx']/1000:6.0f}k max={r['max_ctx']/1000:5.0f}k read%={r['read_share']*100:4.0f} ${r['usd']:7.2f} ${r['usd_per_turn']:.3f}/t {r['proj']}")
    for tag, sel in (('before', lambda r: r['first'][:19] < cut), ('after', lambda r: r['first'][:19] >= cut)):
        g = [r for r in rows if sel(r)]
        if not g: continue
        t = sum(r['turns'] for r in g)
        print(f"{tag}: n={len(g)} turns={t} usd/turn={sum(r['usd'] for r in g)/t:.3f} avgctx={sum(r['avg_ctx']*r['turns'] for r in g)/t/1000:.0f}k comp/session={sum(r['compactions'] for r in g)/len(g):.2f} read%={sum(r['cache_read'] for r in g)/sum(r['cache_read']+r['cache_write']+r['fresh_in'] for r in g)*100:.0f}")
main()
