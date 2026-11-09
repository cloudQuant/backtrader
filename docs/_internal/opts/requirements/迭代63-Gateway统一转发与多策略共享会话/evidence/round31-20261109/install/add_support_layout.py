from pathlib import Path
import hashlib,json,shutil,subprocess
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H');repo=Path('/Users/yunjinqi/Documents/new_projects/backtrader');manifest=T/'test-manifest.json';backup=T/'test-manifest-before-support-layout.json'
if backup.exists():raise RuntimeError('refuse overwrite')
shutil.copyfile(manifest,backup);rows=json.loads(manifest.read_text());head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();added=[]
for rel in ('tests/integration/iter60_gateway_execution_support.py','tests/unit/brokers/__init__.py'):
 if subprocess.run(['git','-C',str(repo),'ls-files','--error-unmatch','--',rel],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:raise RuntimeError(('not tracked',rel))
 src=repo/rel;dst=T/'bt-tests'/rel
 if not src.is_file() or src.is_symlink():raise RuntimeError(('invalid',rel))
 if dst.exists():
  if dst.read_bytes()!=src.read_bytes() or not any(x['copy']==str(dst) for x in rows):raise RuntimeError(('collision',rel))
  continue
 data=src.read_bytes();dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data);added.append({'source':str(src),'copy':str(dst),'repo':str(repo),'relative':rel,'snapshot_head':head,'sha256':hashlib.sha256(data).hexdigest()})
rows+=added;manifest.write_text(json.dumps(rows,indent=2)+'\n');(T/'support-helpers-manifest.json').write_text(json.dumps(added,indent=2)+'\n')
target=T/'install/src';links=[]
for link,dest in ((target/'tests',T/'bt-tests/tests'),(target/'sitecustomize.py',T/'bootstrap/sitecustomize.py'),(target/'origin_guard.py',T/'bootstrap/origin_guard.py'),(target/'offline_guard.py',T/'bootstrap/offline_guard.py')):
 if link.exists() or link.is_symlink() or not dest.exists():raise RuntimeError(('invalid link',str(link)))
 link.symlink_to(dest,target_is_directory=dest.is_dir());links.append({'link':str(link),'resolved_target':str(link.resolve())})
(T/'bt-subprocess-layout.json').write_text(json.dumps({'links':links},indent=2)+'\n');print('PUBLIC_HELPERS_ADDED',len(added),'TEST_MANIFEST',len(rows),'LAYOUT_LINKS',len(links))
