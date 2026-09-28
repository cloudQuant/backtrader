import hashlib,json,shutil
from pathlib import Path
repo=Path(r'D:\source_code\backtrader')
cand=Path(r'D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r0')
assert not (cand/'backtrader').exists(), cand
ignore=shutil.ignore_patterns('__pycache__','*.pyc','.pytest_cache','.ruff_cache','.mypy_cache','.coverage','build','dist')
shutil.copytree(repo/'backtrader',cand/'backtrader',ignore=ignore)
shutil.copytree(repo/'backtrader_runtime',cand/'backtrader_runtime',ignore=ignore)
for rel in ('tests/unit/runtime/test_runtime_live_dispatch_guard.py',):
    target=cand/rel
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(repo/rel,target)
base=cand/'input-sources'/'btapistore.py'
base.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(repo/'backtrader'/'stores'/'btapistore.py',base)
r3=Path(r'D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r3-r1')
r4=Path(r'D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r4')
for src,name in ((r3/'manifest.json','r3-r1-manifest.json'),(r3/'manifest.sha256','r3-r1-manifest.sha256'),(r3/'receipt.md','r3-r1-receipt.md'),(r4/'manifest.json','r4-manifest.json'),(r4/'manifest.sha256','r4-manifest.sha256'),(r4/'receipt.md','r4-receipt.md')):
    (cand/'upstream-contracts').mkdir(exist_ok=True)
    shutil.copy2(src,cand/'upstream-contracts'/name)
shutil.copy2(r4/'account_actor_port.py',cand/'backtrader'/'stores'/'ctp_account_actor_port.py')
shutil.copy2(r4/'store_boundary_harness.py',cand/'upstream-contracts'/'store_boundary_harness.py')
shutil.copy2(r3/'account_actor_port.py',cand/'upstream-contracts'/'account_actor_port_r3r1.py')
files={}
for rel in ['backtrader/stores/btapistore.py','backtrader_runtime/runner.py','backtrader_runtime/registry.py','backtrader_runtime/cli.py','tests/unit/runtime/test_runtime_live_dispatch_guard.py','input-sources/btapistore.py','backtrader/stores/ctp_account_actor_port.py']:
    p=cand/rel
    files[rel]={'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
print(json.dumps({'candidate_root':str(cand),'copied_backtrader_py':sum(1 for p in (cand/'backtrader').rglob('*.py')),'copied_runtime_py':sum(1 for p in (cand/'backtrader_runtime').rglob('*.py')),'snapshots':files},indent=2))
