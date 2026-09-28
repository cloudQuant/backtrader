from __future__ import annotations
import hashlib,json
from pathlib import Path
root=Path(r'D:\temp\iteration41-g5-order-authority-independent-qa-20260927')
manifest=root/'qa-manifest.json'; data=json.loads(manifest.read_text(encoding='utf-8'))
errors=[]
for item in data['files']:
    path=root/item['path']
    if not path.is_file() or path.stat().st_size!=item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest().upper()!=item['sha256']:
        errors.append(item['path'])
manifest_sha=hashlib.sha256(manifest.read_bytes()).hexdigest().upper()
sidecar=(root/'qa-manifest.sha256').read_text(encoding='ascii').split()[0]
result={'entries':len(data['files']),'bad_entries':errors,'manifest_sha256':manifest_sha,'sidecar_matches':manifest_sha==sidecar}
print(json.dumps(result,indent=2)); assert not errors and manifest_sha==sidecar
