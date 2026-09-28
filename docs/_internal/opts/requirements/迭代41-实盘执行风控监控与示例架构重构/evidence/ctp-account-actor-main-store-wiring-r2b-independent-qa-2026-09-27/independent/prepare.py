from pathlib import Path
import hashlib,json,shutil,sys
src=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b")
qa=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2b-independent-qa-20260927-v1")
dst=qa/'candidate'
manifest=src/'evidence/r2b-manifest.json'
expected='ecfdf31484133fdbab34b755941f95617e7055dd705dd4238d4daf71eaf2a619'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(manifest)==expected,(sha(manifest),expected)
m=json.loads(manifest.read_text(encoding='utf-8'))
assert len(m['files'])==724,len(m['files'])
records=[]
for item in m['files']:
 rel=Path(item['path'])
 assert not rel.is_absolute() and '..' not in rel.parts,item['path']
 a=src/rel;b=dst/rel
 assert a.is_file(),f'missing source: {rel}'
 assert a.stat().st_size==item['size_bytes'],f'source size mismatch: {rel}'
 assert sha(a)==item['sha256'],f'source hash mismatch: {rel}'
 b.parent.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(a,b)
 assert b.stat().st_size==item['size_bytes'] and sha(b)==item['sha256'],f'copy mismatch: {rel}'
 records.append({"path":item['path'],"sha256":sha(b),"size_bytes":b.stat().st_size})
(dst/'evidence').mkdir(parents=True,exist_ok=True)
shutil.copyfile(manifest,dst/'evidence/r2b-manifest.json')
shutil.copyfile(src/'evidence/r2b-manifest.sha256',dst/'evidence/r2b-manifest.sha256')
result={"status":"FROZEN_MANIFEST_COPY_VERIFIED","source_root":str(src),"qa_copy_root":str(dst),"manifest_sha256":sha(manifest),"manifest_payload_count":len(records),"payloads":records}
(qa/'independent-source-copy-manifest.json').write_text(json.dumps(result,indent=2)+"\n",encoding='utf-8')
print(f"COPY_OK files={len(records)} manifest={sha(manifest)} store={sha(dst/'backtrader/stores/btapistore.py')} actor={sha(dst/'backtrader/stores/ctp_account_actor_port.py')} test={sha(dst/'tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py')}")