"""Enumerate public run evidence only; do not copy product, test or wheel payloads."""
from pathlib import Path
import hashlib
import json
T=Path('/tmp/iter63-r21-install-20261109-QD2dgx3G')
output=T/'public-evidence-allowlist.json'
if output.exists(): raise RuntimeError('refuse overwrite')
allowed_suffix={'.py','.json','.jsonl','.txt','.log','.md','.sha256'}
allowed_top={'bootstrap','plans','origin-logs'}
rows=[]
for p in sorted(T.rglob('*')):
    if not p.is_file() or p.is_symlink(): continue
    rel=p.relative_to(T)
    if len(rel.parts)>1 and rel.parts[0] not in allowed_top: continue
    if '__pycache__' in rel.parts or (p.suffix not in allowed_suffix and p.name!='SOURCE_FROZEN'): continue
    data=p.read_bytes();rows.append({'relative':rel.as_posix(),'sha256':hashlib.sha256(data).hexdigest(),'size':len(data)})
output.write_text(json.dumps({'scope':'public harness logs manifests plans and origin events; excludes snapshots installs tests wheel payloads and tmp','files':rows},indent=2)+'\n')
print('PUBLIC_EVIDENCE_FILES',len(rows),flush=True)
