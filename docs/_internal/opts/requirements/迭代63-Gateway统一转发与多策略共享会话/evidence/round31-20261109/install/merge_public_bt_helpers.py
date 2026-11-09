"""Merge tracked public R28/R30 BT test helpers without replacing frozen R31 files."""
from pathlib import Path
import hashlib,json,shutil,subprocess
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H');repo=Path('/Users/yunjinqi/Documents/new_projects/backtrader');manifest=T/'test-manifest.json';backup=T/'test-manifest-before-r28-r30-merge.json';sources=[Path('/tmp/iter63-r28-candidate3-20261109-ijqQ26LC/test-manifest.json'),Path('/tmp/iter63-r30-install-20261109-ySExhdil/test-manifest.json')]
if backup.exists():raise RuntimeError('refuse overwrite')
shutil.copyfile(manifest,backup);rows=json.loads(manifest.read_text());existing={r['copy']:r for r in rows};head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();added=[];seen=set()
for source in sources:
 for r in json.loads(source.read_text()):
  if r['repo']!=str(repo):continue
  rel=r['relative'];path=Path(rel)
  if path.is_absolute() or '..' in path.parts or any(x.startswith('.env') or x in ('config.yaml','account_config.yaml') for x in path.parts):raise RuntimeError(('private path',rel))
  if rel in seen:continue
  seen.add(rel);src=repo/path;dest=T/'bt-tests'/path
  if str(dest) in existing:
   if not dest.is_file() or hashlib.sha256(dest.read_bytes()).hexdigest()!=existing[str(dest)]['sha256']:raise RuntimeError(('existing snapshot drift',rel))
   continue
  if subprocess.run(['git','-C',str(repo),'ls-files','--error-unmatch','--',rel],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:raise RuntimeError(('not tracked public helper',rel))
  if not src.is_file() or src.is_symlink() or dest.exists():raise RuntimeError(('invalid path',rel))
  data=src.read_bytes();dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);added.append({'source':str(src),'copy':str(dest),'repo':str(repo),'relative':rel,'snapshot_head':head,'sha256':hashlib.sha256(data).hexdigest()})
rows+=added;manifest.write_text(json.dumps(rows,indent=2)+'\n');(T/'merged-bt-helpers-manifest.json').write_text(json.dumps({'prior_manifests':[str(x) for x in sources],'added':added},indent=2)+'\n');print('BT_PRIOR_UNION',len(seen),'ADDED',len(added),'FINAL_TEST_MANIFEST',len(rows))
