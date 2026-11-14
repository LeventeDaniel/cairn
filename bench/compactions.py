"""Measured per-compaction facts from transcripts: context before/after, replies that followed."""
import json,glob,os,statistics as st
rows=[]
for p in glob.glob(os.path.expanduser('~/.claude/projects/**/*.jsonl'),recursive=True):
    if 'subagents' in p: continue
    ctx=[]; marks=[]
    for l in open(p,encoding='utf-8',errors='replace'):
        try:o=json.loads(l)
        except: continue
        if o.get('isCompactSummary'): marks.append(len(ctx)); continue
        m=o.get('message') or {}
        if o.get('type')=='assistant' and m.get('usage') and not o.get('isSidechain') and m.get('model')!='<synthetic>':
            u=m['usage']; ctx.append(u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0))
    for i,mk in enumerate(marks):
        if mk<1 or mk>=len(ctx): continue
        nxt=marks[i+1] if i+1<len(marks) else len(ctx)
        rows.append((ctx[mk-1],ctx[mk],nxt-mk))
print('n',len(rows))
for r in rows: print(r)
if rows:
    print('median before',st.median(r[0] for r in rows),'after',st.median(r[1] for r in rows),'replies until next compaction/end',st.median(r[2] for r in rows),'mean',st.mean(r[2] for r in rows))
import sys, datetime
if '--write' in sys.argv and rows:
    firsts=[]
    for p in glob.glob(os.path.expanduser('~/.claude/projects/**/*.jsonl'),recursive=True):
        if 'subagents' in p: continue
        for l in open(p,encoding='utf-8',errors='replace'):
            try:o=json.loads(l)
            except: continue
            m=o.get('message') or {}
            if o.get('type')=='assistant' and m.get('usage') and m.get('model')!='<synthetic>' and not o.get('isSidechain'):
                u=m['usage']; firsts.append(u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0)); break
    mf=os.path.expanduser('~/.claude/cairn/state/measured.json')
    try: m=json.load(open(mf))
    except Exception: m={}
    m['generated']=datetime.datetime.now().isoformat(timespec='seconds')
    m['history']=dict(compactions=len(rows),medianBefore=st.median(r[0] for r in rows),medianAfter=st.median(r[1] for r in rows),
        minRepliesAfter=min(r[2] for r in rows),medianRepliesAfter=st.median(r[2] for r in rows),floor=st.median(firsts))
    json.dump(m,open(mf,'w'),indent=1); print('wrote',mf,m['history'])
