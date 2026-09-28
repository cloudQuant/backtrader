import hashlib,json,shutil
from pathlib import Path
src=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b")
qa=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1")
dst=qa/'patch-replay'
man=json.loads((src/'evidence/r2b-manifest.json').read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for item in man['files']:
 a=src/item['path']; b=dst/item['path']; b.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(a,b)
 assert sha(b)==item['sha256'] and b.stat().st_size==item['size_bytes'],item['path']
for name in ('evidence/r2b-manifest.json','evidence/r2b-manifest.sha256'):
 a=src/name;b=dst/name;b.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a,b)
print('PATCH_REPLAY_COPY_OK files=724')