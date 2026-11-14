import json,glob,os,collections
for p in sorted(glob.glob(os.path.expanduser('~/.claude/projects/**/*.jsonl'),recursive=True)):
    if 'subagents' in p: continue
    ms=collections.Counter(); first=None
    for l in open(p,encoding='utf-8',errors='replace'):
        try:o=json.loads(l)
        except: continue
        m=o.get('message') or {}
        if o.get('type')=='assistant' and m.get('usage') and m.get('model')!='<synthetic>':
            ms[m.get('model')]+=1
            if first is None:
                u=m['usage']; first=u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0)
    if ms: print(os.path.basename(p)[:8], first, dict(ms))
