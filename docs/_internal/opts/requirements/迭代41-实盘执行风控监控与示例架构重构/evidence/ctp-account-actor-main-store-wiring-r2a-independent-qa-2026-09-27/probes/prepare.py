import hashlib,json,pathlib,shutil,subprocess
src=pathlib.Path(r'D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2a')
qa=pathlib.Path(r'D:\temp\iteration41-ctp-account-actor-main-store-wiring-r2a-independent-qa-20260927')
manifest_path=src/'evidence/candidate-manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
expected_manifest='5ad9cce0851fbebd9ac07d520919b7a02f793ab99a133cf96e91f58cede405fb'
if sha(manifest_path)!=expected_manifest: raise SystemExit('candidate manifest hash mismatch')
if (src/'evidence/candidate-manifest.sha256').read_text(encoding='utf-8').split()[0]!=expected_manifest: raise SystemExit('candidate manifest sidecar mismatch')
if len(manifest['files'])!=679: raise SystemExit(f'expected 679 files, got {len(manifest["files"])}')
parent=src/'evidence/r2-parent/candidate-manifest.json'
parent_sha='5b68f9ed2a457e51941bbd60052a100d2e045907b9b2e3bb454482304badd27a'
if sha(parent)!=parent_sha or manifest['parent_r2_manifest_sha256']!=parent_sha: raise SystemExit('parent R2 manifest mismatch')
parent_manifest=json.loads(parent.read_text(encoding='utf-8'))
if len(parent_manifest['files'])!=649: raise SystemExit('parent R2 manifest payload count mismatch')
for p in [src/'input-sources/r2/backtrader-stores-btapistore.py', src/'backtrader/stores/btapistore.py', src/'tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py']:
 print('source',str(p.relative_to(src)),sha(p))
if sha(src/'input-sources/r2/backtrader-stores-btapistore.py')!=manifest['r2_parent_store_sha256']: raise SystemExit('R2 parent Store base mismatch')
if sha(src/'input-sources/r2/backtrader-stores-btapistore.py')!=parent_manifest['candidate_store_sha256']: raise SystemExit('R2 parent manifest Store mismatch')
if sha(src/'r2a-apply.patch')!=manifest['r2a_patch_sha256']: raise SystemExit('R2a patch hash mismatch')
# Check all 679 declared payload files before copying, then copy into a fresh QA root.
for rec in manifest['files']:
 rel=pathlib.PurePosixPath(rec['path'])
 if rel.is_absolute() or '..' in rel.parts: raise SystemExit(f'unsafe path {rel}')
 p=src.joinpath(*rel.parts)
 if not p.is_file() or p.stat().st_size!=rec['size_bytes'] or sha(p)!=rec['sha256']:
  raise SystemExit(f'candidate payload mismatch: {rel}')
candidate=qa/'candidate'; candidate.mkdir()
for rec in manifest['files']:
 rel=pathlib.PurePosixPath(rec['path']); s=src.joinpath(*rel.parts); d=candidate.joinpath(*rel.parts); d.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(s,d)
 if sha(d)!=rec['sha256']: raise SystemExit(f'copied payload mismatch: {rel}')
(qa/'candidate-manifest.json').write_bytes(manifest_path.read_bytes())
(qa/'parent-r2-manifest.json').write_bytes(parent.read_bytes())
# Replay only the two-file R2a patch against the exact R2 Store/test base bytes.
replay=qa/'patch-replay'; (replay/'backtrader/stores').mkdir(parents=True); (replay/'tests/unit/stores').mkdir(parents=True)
shutil.copyfile(src/'input-sources/r2/backtrader-stores-btapistore.py',replay/'backtrader/stores/btapistore.py')
shutil.copyfile(src/'input-sources/r2/test-ctp-account-actor-store-wiring-candidate.py',replay/'tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py')
subprocess.run(['git','init','-q'],cwd=replay,check=True)
patch=candidate/'r2a-apply.patch'
for mode in ('--check',''):
 cmd=['git','-c','core.autocrlf=false','apply']+([mode] if mode else [])+[str(patch)]
 p=subprocess.run(cmd,cwd=replay,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 print('PATCH',mode or 'apply','exit',p.returncode,p.stdout.strip())
 if p.returncode: raise SystemExit('patch replay failed')
for rel,want in [('backtrader/stores/btapistore.py',manifest['candidate_store_sha256']),('tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py',manifest['candidate_test_sha256'])]:
 got=sha(replay/rel); print('REPLAY_HASH',rel,got,'expected',want)
 if got!=want: raise SystemExit(f'patch output mismatch {rel}')
print('CANDIDATE_MANIFEST_SHA',sha(manifest_path),'PARENT_R2_MANIFEST_SHA',sha(parent),'PAYLOAD_COUNT',len(manifest['files']))
print('PATCH_SHA',sha(patch),'R2_BASE_STORE_SHA',sha(src/'input-sources/r2/backtrader-stores-btapistore.py'))
print('PREPARE_OK')
