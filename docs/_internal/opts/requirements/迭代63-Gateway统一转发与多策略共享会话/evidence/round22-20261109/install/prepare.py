"""Freeze only public Gateway source and the five requested tests."""
import hashlib,json,shutil,subprocess
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv')
repo=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_gateway')
tests=['tests/test_iter63_bootstrap_regrant_floor.py','tests/test_iter63_market_hub_confirmed_owner_close.py','tests/test_market_hub.py','tests/test_market_hub_runtime_revocation_iter60.py','tests/test_market_history_service.py']
paths=subprocess.check_output(['git','-C',str(repo),'ls-files','-z','--','src/bt_api_gateway','pyproject.toml','setup.py','setup.cfg','README.md','LICENSE','MANIFEST.in']).decode().split('\0')
untracked=subprocess.check_output(['git','-C',str(repo),'ls-files','-z','--others','--exclude-standard','--','src/bt_api_gateway']).decode().split('\0')
if any(x.endswith('.py') for x in untracked): raise RuntimeError('unexpected untracked runtime')
head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
rows=[]
for group,items in [('source',sorted(filter(None,paths))),('test',tests)]:
    for rel in items:
        path=Path(rel)
        if path.is_absolute() or '..' in path.parts or any(x.startswith('.env') or x in {'config.yaml','account_config.yaml'} for x in path.parts): raise RuntimeError(('private path',rel))
        src=repo/path;dst=T/group/path
        if not src.is_file() or src.is_symlink() or dst.exists(): raise RuntimeError(('missing/symlink/collision',rel))
        data=src.read_bytes();dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data)
        rows.append({'group':group,'repo':str(repo),'source':str(src),'copy':str(dst),'relative':rel,'snapshot_head':head,'sha256':hashlib.sha256(data).hexdigest()})
(T/'manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
(T/'selectors.json').write_text(json.dumps(tests,indent=2)+'\n')
old=Path('/tmp/iter63-r21-install-20261109-QD2dgx3G/wheels/bt_api_base-0.16.0.dev63-py3-none-any.whl')
digest=hashlib.sha256(old.read_bytes()).hexdigest()
if digest!='67f2e489053c06cc154c8edb1f05015aa9ec8be77e9e723e270e9a726072671f': raise RuntimeError('R21 Base wheel mismatch')
(T/'wheels').mkdir(); shutil.copyfile(old,T/'wheels'/old.name)
(T/'fixed-wheel.json').write_text(json.dumps({'source':str(old),'sha256':digest,'provenance':'R21 verified Base wheel'},indent=2)+'\n')
print('SNAPSHOT_HEAD',head,'source_files',sum(r['group']=='source' for r in rows),'test_files',sum(r['group']=='test' for r in rows),flush=True)
