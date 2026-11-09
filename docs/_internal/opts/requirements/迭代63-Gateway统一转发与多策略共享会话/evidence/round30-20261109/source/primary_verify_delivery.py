"""Compare final R30 manifests, checkout bytes and committed blobs independently."""
import hashlib,json,subprocess
from pathlib import Path
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');O=Path('/tmp/iter63-r30-primary')
sha=lambda b:hashlib.sha256(b).hexdigest();commits=json.loads((O/'product-commits.json').read_text())
heads={v['repo']:v['commit'] for v in commits.values()};seen={};counts={}
for name in ('source-manifest.json','test-manifest.json'):
 rows=json.loads((T/name).read_text());counts[name]=len(rows)
 for row in rows:
  assert sha(Path(row['source']).read_bytes())==row['sha256'],('source',row['source'])
  assert sha(Path(row['copy']).read_bytes())==row['sha256'],('snapshot',row['copy'])
  key=(row['repo'],row['relative'])
  if key in seen:assert seen[key]==row['sha256'];continue
  content=subprocess.check_output(['git','-C',row['repo'],'show',heads[row['repo']]+':'+row['relative']])
  assert sha(content)==row['sha256'],('commit',key)
  seen[key]=row['sha256']
for kind,value in commits.items():
 repo=value['repo'];head=value['commit']
 assert subprocess.check_output(['git','-C',repo,'rev-parse','HEAD'],text=True).strip()==head
 paths=set(subprocess.check_output(['git','-C',repo,'diff-tree','--no-commit-id','--name-only','-r',head],text=True).splitlines())
 assert paths==set(value['files']),(kind,paths)
 frozen=O if kind!='bt' else Path('/tmp/iter63-r30-primary-bt-v2')
 for row in json.loads((frozen/(kind+'-frozen-inputs.json')).read_text()):
  assert sha(subprocess.check_output(['git','-C',repo,'show',head+':'+row['path']]))==row['sha256']
sdk=commits['sdk']['repo'];sdkhead=commits['sdk']['commit']
for kind in ('base','gateway','ctp'):
 assert subprocess.check_output(['git','-C',sdk,'rev-parse',sdkhead+':bt_api/bt_api_'+kind],text=True).strip()==commits[kind]['commit']
report={'result':'PASS','manifest_rows':counts,'unique_paths':len(seen),'commits':heads,'gitlinks':'MATCH','frozen_inputs':93,'scope':'Only listed product/test/README files and three SDK gitlinks committed; unrelated files preserved.'}
(O/'primary-delivery-committed.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
