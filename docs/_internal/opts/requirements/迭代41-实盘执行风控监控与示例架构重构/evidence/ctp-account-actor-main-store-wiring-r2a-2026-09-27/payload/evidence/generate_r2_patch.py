import hashlib, shutil, subprocess, tempfile
from pathlib import Path
root = Path(r'D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2')
base = root / 'input-sources' / 'btapistore.py'
source_files = {
    'backtrader/stores/btapistore.py': root / 'backtrader/stores/btapistore.py',
    'backtrader/stores/ctp_account_actor_port.py': root / 'backtrader/stores/ctp_account_actor_port.py',
    'tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py': root / 'tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py',
}
patch = root / 'r2-apply.patch'
scratch = Path(tempfile.mkdtemp(prefix='iter41-r2-patch-'))
repo = scratch / 'repo'
(repo / 'backtrader' / 'stores').mkdir(parents=True)
shutil.copyfile(base, repo / 'backtrader' / 'stores' / 'btapistore.py')
subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
subprocess.run(['git', 'config', 'core.autocrlf', 'false'], cwd=repo, check=True)
subprocess.run(['git', 'config', 'user.name', 'QA Freeze'], cwd=repo, check=True)
subprocess.run(['git', 'config', 'user.email', 'qa-freeze@example.invalid'], cwd=repo, check=True)
subprocess.run(['git', 'add', 'backtrader/stores/btapistore.py'], cwd=repo, check=True)
subprocess.run(['git', 'commit', '-qm', 'exact base'], cwd=repo, check=True)
for rel, src in source_files.items():
    dst = repo / Path(rel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
subprocess.run(['git', 'add', '-A'], cwd=repo, check=True)
diff = subprocess.run(['git', 'diff', '--cached', '--binary', '--full-index', '--no-ext-diff', '--no-renames', 'HEAD'], cwd=repo, check=True, stdout=subprocess.PIPE)
patch.write_bytes(diff.stdout)
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()
print(f'patch_path={patch}')
print(f'patch_bytes={len(diff.stdout)}')
print(f'patch_sha256={sha(patch)}')
print(f'scratch_repo={repo}')
for rel in source_files:
    print(f'{rel} sha256={sha(root / Path(rel))}')
