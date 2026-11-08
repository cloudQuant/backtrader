"""Copy the remaining tracked Base test-only helpers, preserving first manifest."""
import hashlib
import json
import subprocess
from pathlib import Path
T=Path('/tmp/iter63-r17-install-20261109-oNtWsjp3')
repo=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_base')
out=T/'base-test-helpers-manifest.json'
if out.exists():
    raise RuntimeError('refusing helper manifest overwrite')
head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
tracked=subprocess.check_output(['git','-C',str(repo),'ls-files','--','tests'],text=True).splitlines()
rows=[]
for rel in tracked:
    source=repo/rel
    target=T/'base-tests'/rel
    if not rel.endswith('.py') or target.exists():
        continue
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(('untrusted helper',rel))
    raw=source.read_bytes()
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(raw)
    digest=hashlib.sha256(raw).hexdigest()
    if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
        raise RuntimeError('helper copy mismatch')
    rows.append({'repo':str(repo),'relative':rel,'source':str(source),'copy':str(target),
                 'snapshot_head':head,'sha256':digest})
out.write_text(json.dumps(rows,indent=2)+'\n')
print('COPIED_TRACKED_BASE_TEST_HELPERS',len(rows))
