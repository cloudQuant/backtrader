import hashlib, json, shutil, subprocess, tempfile
from pathlib import Path
ROOT = Path(r'D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2')
BASE = ROOT / 'input-sources' / 'btapistore.py'
PATCH = ROOT / 'r2-apply.patch'
TARGETS = [
    'backtrader/stores/btapistore.py',
    'backtrader/stores/ctp_account_actor_port.py',
    'tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py',
]
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()
expected = {
 'backtrader/stores/btapistore.py':'a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8',
 'backtrader/stores/ctp_account_actor_port.py':'2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3',
 'tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py':'04968d98ae476d4b9ec33d448be11d19e0ffc9adb79585f423b37b37b759154f',
}
print(f'patch_sha256={sha(PATCH)}')
for mode in ('false','true'):
    root=Path(tempfile.mkdtemp(prefix=f'iter41-r2-apply-{mode}-'))
    (root/'backtrader'/'stores').mkdir(parents=True)
    shutil.copyfile(BASE,root/'backtrader'/'stores'/'btapistore.py')
    subprocess.run(['git','init','-q'],cwd=root,check=True)
    subprocess.run(['git','config','core.autocrlf',mode],cwd=root,check=True)
    subprocess.run(['git','add','backtrader/stores/btapistore.py'],cwd=root,check=True)
    subprocess.run(['git','-c','user.name=QA','-c','user.email=qa@example.invalid','commit','-qm','exact base'],cwd=root,check=True)
    subprocess.run(['git','apply','--check',str(PATCH)],cwd=root,check=True)
    subprocess.run(['git','apply',str(PATCH)],cwd=root,check=True)
    got={rel:sha(root/rel) for rel in TARGETS}
    print(f'core.autocrlf={mode} scratch={root}')
    print('  '+json.dumps(got,sort_keys=True))
    if mode == 'false' and got != expected:
        raise SystemExit('exact replay content mismatch')
    if mode == 'true' and got != expected:
        print('  NOTE: core.autocrlf=true changed bytes; inspect separately')
print('PATCH_APPLY_CHECK_PASS')
