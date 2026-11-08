"""Reproduce standard src/tests layout under the isolated install root."""
import hashlib
import json
from pathlib import Path
import shutil

T = Path('/tmp/iter63-r18-install-20261109-GvDCI8TF')
source, dest = T/'ctp-tests', T/'install'
manifest = T/'ctp-relocation-manifest.json'
if (dest/'tests').exists() or (dest/'selected-tests.txt').exists() or manifest.exists():
    raise RuntimeError('refusing existing relocated layout')
rows=[]
for item in sorted(source.rglob('*')):
    if not item.is_file() or item.suffix == '.pyc' or '__pycache__' in item.parts:
        continue
    relative=item.relative_to(source)
    target=dest/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(item,target)
    digest=hashlib.sha256(item.read_bytes()).hexdigest()
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError('relocated test digest mismatch')
    rows.append({'source':str(item),'copy':str(target),'sha256':digest})
manifest.write_text(json.dumps(rows,indent=2)+'\n')
print('CTP_TESTS_RELOCATED_EXACT',len(rows),'src_is_isolated_install_target')
