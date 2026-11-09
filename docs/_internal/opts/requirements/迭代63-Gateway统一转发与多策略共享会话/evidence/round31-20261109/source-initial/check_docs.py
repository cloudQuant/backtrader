from pathlib import Path
from urllib.parse import unquote
import hashlib,json,re
BT=Path('/Users/yunjinqi/Documents/new_projects/backtrader');R=BT/'docs/_internal/opts/requirements/迭代63-Gateway统一转发与多策略共享会话';E=R/'evidence/round31-20261109'
files=[R/'archived/实施第三十一轮BT稀疏事件消费与通知恢复审阅-2026-11-09.md',R/'实施基线与分轮记录-2026-11-08.md',R/'开发验收状态矩阵.md',R/'开发问题记录.md',R/'分轮合同冻结稿-2026-11-08.md',BT/'docs/source/developer-guide/repository-responsibilities_zh.md']
links=0
for p in files:
 raw=p.read_bytes();assert raw.startswith(b'\xef\xbb\xbf'),p
 text=raw.decode('utf-8-sig',errors='strict');assert '\ufffd' not in text,p
 for target in re.findall(r'\[[^\]]*\]\(([^\n)]+)\)',text):
  target=target.split('#',1)[0].strip('<>')
  if not target or re.match(r'^[a-zA-Z]+:',target):continue
  resolved=p.parent/unquote(target);assert resolved.exists(),(p,target)
  links+=1
manifest=json.loads((E/'manifest.json').read_text())
for row in manifest['files']:
 p=E/row['archive'];assert p.is_file();assert hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],p
summary={'files':[str(p.relative_to(BT)) for p in files],'strict_utf8_bom':True,'replacement_characters':False,'local_file_links_checked':links,'anchor_validation':'NOT_RUN','windows_powershell_5_1':'NOT_RUN','evidence_files_verified':len(manifest['files'])}
(E/'document-validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
Path('/tmp/iter63-r31-primary/docs-owned-files.json').write_text(json.dumps(summary['files'],ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='files'},indent=2))
