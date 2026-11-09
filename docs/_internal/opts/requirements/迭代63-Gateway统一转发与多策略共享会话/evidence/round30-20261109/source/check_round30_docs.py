import hashlib,json,re,subprocess,unicodedata
from pathlib import Path
R=Path('/Users/yunjinqi/Documents/new_projects/backtrader');D=R/'docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话'
paths=[D/x for x in ('开发验收状态矩阵.md','实施基线与分轮记录-2026-11-08.md','开发问题记录.md','分轮合同冻结稿-2026-11-08.md','archived/实施第三十轮成交日期补充与一致性审阅-2026-11-09.md')]
rows=[];checked=0
for p in paths:
 raw=p.read_bytes();assert raw.startswith(b'\xef\xbb\xbf');s=raw.decode('utf-8-sig',errors='strict');assert '\ufffd' not in s
 for target in re.findall(r'\]\(([^)]+)\)',s):
  target=target.strip('<>');rel=target.split('#',1)[0]
  if not rel or '://' in rel or rel.startswith(('mailto:','codex:')):continue
  destination=(p.parent/rel).resolve();assert destination.exists(),(p.name,target)
  checked+=1
 rows.append({'path':str(p.relative_to(R)),'sha256':hashlib.sha256(raw).hexdigest(),'utf8_bom':True})
subprocess.run(['git','diff','--check','--',*[str(p.relative_to(R)) for p in paths]],cwd=R,check=True)
E=D/'evidence/round30-20261109';m=json.loads((E/'manifest.json').read_text())
for r in m['files']:
 data=(E/r['path']).read_bytes();assert len(data)==r['bytes'] and hashlib.sha256(data).hexdigest()==r['sha256']
assert len(list(E.rglob('*')))>len(m['files'])
report={'result':'PASS','docs':rows,'local_links_checked':checked,'evidence_files_checked':len(m['files']),'powershell_5_1':'NOT_RUN','note':'Local link paths checked; full historical heading-anchor audit not claimed. Raw logs preserve original whitespace.'}
Path('/tmp/iter63-r30-primary/document-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('DOCS',len(rows),'LINKS',checked,'EVIDENCE',len(m['files']),'PASS')
