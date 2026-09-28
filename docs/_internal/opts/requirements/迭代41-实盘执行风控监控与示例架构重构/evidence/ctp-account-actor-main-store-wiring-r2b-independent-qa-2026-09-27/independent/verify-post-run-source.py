from __future__ import annotations
import hashlib,json
from pathlib import Path
qa=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1")
root=qa/'candidate'
man=json.loads((root/'evidence/r2b-manifest.json').read_text(encoding='utf-8'))
expected={x['path']:x for x in man['files']}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
for rel,item in expected.items():
 p=root/rel
 assert p.is_file(),f'missing {rel}'
 assert p.stat().st_size==item['size_bytes'],f'size {rel}'
 assert sha(p)==item['sha256'],f'hash {rel}'
actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
extra=actual-set(expected)
allowed={'evidence/r2b-manifest.json','evidence/r2b-manifest.sha256'}
ruff_cache={name for name in extra if name.startswith('.ruff_cache/')}
assert extra==allowed|ruff_cache,(len(actual),len(expected),sorted(extra-allowed-ruff_cache))
copy=json.loads((qa/'independent-source-copy-manifest.json').read_text(encoding='utf-8'))
assert copy['manifest_sha256']==sha(root/'evidence/r2b-manifest.json')
assert copy['manifest_payload_count']==len(expected)==724
assert all(item['match'] for item in json.loads((qa/'copy-source-hash-check.json').read_text(encoding='utf-8')).get('checks',[])) if (qa/'copy-source-hash-check.json').exists() else True
print(f"POST_RUN_SOURCE_HASH_OK manifest_payloads={len(expected)} extra_manifest_files=2 ruff_cache_files={len(ruff_cache)} source_payload_mismatches=0")
print('RUFF_CACHE_QA_ARTIFACTS',sorted(ruff_cache))