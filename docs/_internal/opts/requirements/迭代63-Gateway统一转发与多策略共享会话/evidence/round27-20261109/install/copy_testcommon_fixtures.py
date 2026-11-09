"""Stage exactly the tracked public testcommon helper and its data fixtures."""
import hashlib,json,shutil,subprocess
from pathlib import Path
T=Path('/tmp/iter63-r27-install-20261109-E3J4NZZw');repo=Path('/Users/yunjinqi/Documents/new_projects/backtrader');manifest=T/'test-manifest.json';backup=T/'test-manifest-before-testcommon.json'
if backup.exists():raise RuntimeError('refuse overwrite')
shutil.copyfile(manifest,backup);rows=json.loads(manifest.read_text());head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();added=[]
for rel in ('tests/testcommon.py','tests/datas/2006-day-001.txt','tests/datas/2006-week-001.txt'):
    if subprocess.run(['git','-C',str(repo),'ls-files','--error-unmatch','--',rel],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:raise RuntimeError(('untracked fixture',rel))
    src=repo/rel;dst=T/'bt-tests'/rel
    if not src.is_file() or src.is_symlink() or dst.exists():raise RuntimeError(('invalid fixture',rel))
    data=src.read_bytes();dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data)
    added.append({'source':str(src),'copy':str(dst),'sha256':hashlib.sha256(data).hexdigest(),'repo':str(repo),'relative':rel,'snapshot_head':head})
rows.extend(added);manifest.write_text(json.dumps(rows,indent=2)+'\n');(T/'testcommon-fixtures-manifest.json').write_text(json.dumps(added,indent=2)+'\n')
print('PUBLIC_FIXTURES_ADDED',len(added),'TEST_MANIFEST_ROWS',len(rows),flush=True)
