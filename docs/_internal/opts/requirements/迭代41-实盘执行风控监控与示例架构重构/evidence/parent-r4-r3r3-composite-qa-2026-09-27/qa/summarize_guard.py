import json, pathlib, collections
base=pathlib.Path(r'D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1\qa')
for label in ('origin-guard-original-three-r1','origin-guard-five-r1'):
    rows=[]
    for p in sorted((base/label).glob('*.jsonl')):
        for line in p.read_text(encoding='utf-8').splitlines():
            if line.strip(): rows.append(json.loads(line))
    print(label, 'files',len(list((base/label).glob('*.jsonl'))),'records',len(rows))
    print('kinds',dict(collections.Counter(r.get('kind') for r in rows)))
    print('parents',sorted({r.get('origin') for r in rows if r.get('kind')=='source-import' and r.get('fullname')=='bt_api_py'}))
    print('unexpected', [r for r in rows if r.get('kind') in {'origin-rejected','native-import-blocked','network-blocked','private-config-blocked'}][:12])
    print('source top modules',sorted({r.get('fullname') for r in rows if r.get('kind')=='source-import' and '.' not in r.get('fullname','')}))
