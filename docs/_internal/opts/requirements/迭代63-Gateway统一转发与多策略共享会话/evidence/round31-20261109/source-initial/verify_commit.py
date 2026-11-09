import json,hashlib,subprocess
from pathlib import Path
BT=Path('/Users/yunjinqi/Documents/new_projects/backtrader');SDK=BT.parent/'bt_api_py';O=Path('/tmp/iter63-r31-primary');V=Path('/tmp/iter63-r31-primary-bt-v2');I=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H')
sha=lambda b:hashlib.sha256(b).hexdigest()
assert subprocess.check_output(['git','branch','--show-current'],cwd=BT).decode().strip()=='dev'
assert subprocess.check_output(['git','diff','--cached','--name-only'],cwd=BT)==b''
assert (O/'selectors.json').read_bytes()==(V/'selectors.json').read_bytes()==(I/'selectors.json').read_bytes()
for kind,root,folder in [('sdk',SDK,O),('bt',BT,V)]:
 rows=json.loads((folder/f'{kind}-frozen-inputs.json').read_text()); installed=json.loads((I/f'{kind}-frozen-inputs.json').read_text());assert rows==installed
 for row in rows:assert sha((root/row['path']).read_bytes())==row['sha256'],row
allrows=[]
for name in ['source-manifest.json','test-manifest.json']:
 rows=json.loads((I/name).read_text())
 for row in rows:
  assert sha(Path(row['source']).read_bytes())==row['sha256'],row['source']
  assert sha(Path(row['copy']).read_bytes())==row['sha256'],row['copy']
 allrows+=rows
files=json.loads((O/'bt-owned-files.json').read_text());subprocess.run(['git','add','--',*files],cwd=BT,check=True)
assert set(subprocess.check_output(['git','diff','--cached','--name-only'],cwd=BT).decode().splitlines())==set(files)
r=subprocess.run(['git','commit','-m','feat(gateway): consume durable execution streams through BT notifications'],cwd=BT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);(O/'bt-product-commit.log').write_bytes(r.stdout);r.check_returncode()
heads={str(root):subprocess.check_output(['git','rev-parse','HEAD'],cwd=root).decode().strip() for root in [BT,SDK]}
seen=set()
for row in allrows:
 key=(row['repo'],row['relative']);assert row['repo'] in heads
 if key in seen:continue
 seen.add(key)
 assert sha(subprocess.check_output(['git','show',heads[row['repo']]+':'+row['relative']],cwd=row['repo']))==row['sha256'],key
result={'heads':heads,'source_rows':len(json.loads((I/'source-manifest.json').read_text())),'test_rows':len(json.loads((I/'test-manifest.json').read_text())),'unique_git_paths_verified':len(seen),'bt_owned_files':files}
(O/'product-commits.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
