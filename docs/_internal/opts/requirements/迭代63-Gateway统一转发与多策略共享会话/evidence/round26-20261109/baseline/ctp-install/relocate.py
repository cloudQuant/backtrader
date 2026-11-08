"""Copy frozen test mirror to install/tests for public source-layout checks."""
import hashlib,json,shutil
from pathlib import Path
T=Path('/tmp/iter63-r26-ctp-install-20261109-sqM3vqAE');src=T/'ctp-tests';dst=T/'install';out=T/'ctp-relocation-manifest.json'
if (dst/'tests').exists() or out.exists():raise RuntimeError('relocation exists')
rows=[]
for p in sorted(src.rglob('*')):
    if not p.is_file() or p.suffix=='.pyc' or '__pycache__' in p.parts:continue
    q=dst/p.relative_to(src);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    if hashlib.sha256(q.read_bytes()).hexdigest()!=sha:raise RuntimeError('test copy drift')
    rows.append({'source':str(p),'copy':str(q),'sha256':sha})
out.write_text(json.dumps(rows,indent=2)+'\n');print('CTP_TEST_RELOCATION',len(rows),flush=True)
