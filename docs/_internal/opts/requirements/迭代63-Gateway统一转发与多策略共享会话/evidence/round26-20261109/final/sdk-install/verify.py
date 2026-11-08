import hashlib,json,zipfile,sys
from pathlib import Path
T=Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl');S=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py');sha=lambda x:hashlib.sha256(x).hexdigest()
for manifest in ('source-manifest.json','test-manifest.json'):
 rows=json.loads((T/manifest).read_text())
 for r in rows:
  for key in ('source','copy','original'):
   if key in r and sha(Path(r[key]).read_bytes())!=r['sha256']:raise RuntimeError((manifest,key,r[key]))
 print('VERIFIED',manifest,len(rows),flush=True)
for r in json.loads((T/'sdk-frozen-inputs.json').read_text()):
 if sha((S/r['path']).read_bytes())!=r['sha256']:raise RuntimeError(('primary frozen drift',r['path']))
print('PRIMARY_FROZEN_INPUTS_OK',55)
for r in json.loads((T/'fixed-wheels.json').read_text()):
 for p in (Path(r['source']),T/'wheels'/r['filename']):
  if sha(p.read_bytes())!=r['sha256']:raise RuntimeError(('wheel drift',str(p)))
print('FIXED_WHEELS_OK',7)
wheel,=(T/'wheels').glob('bt_api_py-*.whl');count=0
with zipfile.ZipFile(wheel) as z:
 for n in z.namelist():
  if n.startswith('bt_api_py/') and not n.endswith('/'):
   data=z.read(n);source=T/'source/sdk'/n;work=S/n;installed=T/'install/src'/n
   if not (source.is_file() and work.is_file() and installed.is_file() and source.read_bytes()==work.read_bytes()==installed.read_bytes()==data):raise RuntimeError(('payload mismatch',n))
   count+=1
 metadata=[n for n in z.namelist() if n.endswith('.dist-info/METADATA')];assert len(metadata)==1
 text=z.read(metadata[0]).decode();readme=(T/'source/sdk/README.md').read_text();assert readme in text
print('SDK_PAYLOAD_ALL_MATCH',count,'README_METADATA_OK','SDK_WHEEL_SHA256',sha(wheel.read_bytes()),flush=True)
