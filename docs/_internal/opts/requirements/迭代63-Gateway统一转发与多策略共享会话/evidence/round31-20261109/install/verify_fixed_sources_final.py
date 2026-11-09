from pathlib import Path
import hashlib,json,subprocess
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H');old=json.loads(Path('/tmp/iter63-r30-install-20261109-ySExhdil/source-manifest.json').read_text());root=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api')
for name in ('base','gateway','ctp'):
 repo=root/('bt_api_'+name);head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();items=[x for x in old if x['repo']==str(repo)]
 for row in items:
  p=Path(row['source']);blob=subprocess.run(['git','-C',str(repo),'show',head+':'+row['relative']],capture_output=True)
  if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256'] or blob.returncode or hashlib.sha256(blob.stdout).hexdigest()!=row['sha256']:raise RuntimeError(('fixed drift',name,row['relative']))
 print('FIXED_COMMIT_AND_SOURCE_R30_MATCH',name,head,len(items),flush=True)
layout=json.loads((T/'bt-subprocess-layout.json').read_text())
for row in layout['links']:
 p=Path(row['link'])
 if not p.is_symlink() or str(p.resolve())!=row['resolved_target']:raise RuntimeError(('layout drift',str(p)))
print('BT_SUBPROCESS_LAYOUT_MATCH',len(layout['links']))
