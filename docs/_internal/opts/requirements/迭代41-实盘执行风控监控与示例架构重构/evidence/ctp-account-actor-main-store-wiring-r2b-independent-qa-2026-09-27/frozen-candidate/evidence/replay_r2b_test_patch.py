from __future__ import annotations
import hashlib, shutil, subprocess, tempfile
from pathlib import Path

candidate=Path(__file__).resolve().parents[1]
base=Path(r"D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2a")
patch=candidate/'evidence'/'r2b-test-migration.patch'
modified='tests/unit/stores/test_managed_ctp_store_adapter.py'
new_file='tests/unit/stores/test_ctp_non_authorizing_contracts.py'
expected_base='2b5f929cac960ed6a7105eb2cc0b7401961fdb7c7b97761288d279b415b15e3f'
expected_modified='15d93e165ea817b5ba484adac52658baf67f89fb83d30eff142c3e1ba4203ae3'
expected_new='a61c8b0070a41c813d7c3adb1165f9ad38ea5b63986a9293e868e38d78f3b5cf'
base_bytes=(base/modified).read_bytes()
if hashlib.sha256(base_bytes).hexdigest()!=expected_base: raise SystemExit('frozen r2a test input hash mismatch')
scratch=Path(tempfile.mkdtemp(prefix='iter41-r2b-patch-replay-'))
try:
    target=scratch/modified
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(base_bytes)
    subprocess.run(['git','init','-q',str(scratch)],check=True)
    subprocess.run(['git','-C',str(scratch),'config','core.autocrlf','false'],check=True)
    subprocess.run(['git','-C',str(scratch),'apply','--check',str(patch)],check=True)
    subprocess.run(['git','-C',str(scratch),'apply',str(patch)],check=True)
    got_modified=hashlib.sha256(target.read_bytes()).hexdigest()
    got_new=hashlib.sha256((scratch/new_file).read_bytes()).hexdigest()
    if got_modified!=expected_modified or got_new!=expected_new: raise SystemExit('patched output hash mismatch')
    print('base_test_sha256='+expected_base)
    print('patch_sha256='+hashlib.sha256(patch.read_bytes()).hexdigest())
    print(f'{modified}_sha256='+got_modified)
    print(f'{new_file}_sha256='+got_new)
    print('core.autocrlf=false')
    print('R2B_TEST_PATCH_REPLAY_PASS')
finally:
    shutil.rmtree(scratch)
