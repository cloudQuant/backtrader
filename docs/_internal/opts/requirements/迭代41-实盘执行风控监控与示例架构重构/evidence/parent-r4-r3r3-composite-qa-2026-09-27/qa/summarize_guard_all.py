import json,pathlib,collections
base=pathlib.Path(r'D:\temp\iteration41-parent-r4-r3r3-composite-20260927-r1\qa')
labels=['origin-guard-parent-focus-r3','origin-guard-original-three-r1','origin-guard-five-r1','origin-guard-cancel-control-r1']
for label in labels:
 rows=[]
 for p in sorted((base/label).glob('*.jsonl')):
  for line in p.read_text(encoding='utf-8').splitlines():
   if line.strip(): rows.append(json.loads(line))
 print(label, 'processes',len(list((base/label).glob('*.jsonl'))),'records',len(rows),'kinds',dict(collections.Counter(r.get('kind') for r in rows)))
 print('module top imports',sorted({r['fullname'] for r in rows if r.get('kind')=='source-import' and '.' not in r.get('fullname','')}))
 print('parent origins',sorted({r['origin'] for r in rows if r.get('kind')=='source-import' and r.get('fullname')=='bt_api_py'}))
 print('guard-denials', [r for r in rows if r.get('kind') in {'origin-rejected','native-import-blocked','network-blocked','private-config-blocked'}])
