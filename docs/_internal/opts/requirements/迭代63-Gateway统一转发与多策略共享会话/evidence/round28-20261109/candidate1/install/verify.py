import hashlib,importlib,importlib.metadata,json,os,sys,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r28-install-20261109-Bx3u2bPP'); target=T/'install/src'; sys.path[:0]=[str(target),str(T/'bootstrap')]
from origin_guard import install,audit
from offline_guard import install as offline
install('verification'); offline()
sha=lambda b:hashlib.sha256(b).hexdigest()
for manifest in ('source-manifest.json','test-manifest.json'):
 rows=json.loads((T/manifest).read_text())
 for row in rows:
  for key in ('source','copy'):
   if sha(Path(row[key]).read_bytes())!=row['sha256']: raise RuntimeError(('manifest drift',manifest,row[key]))
 print('MANIFEST_VERIFIED',manifest,len(rows),flush=True)
for row in json.loads(Path('/tmp/iter63-r28-install-20261109-Bx3u2bPP/primary-frozen-inputs.json').read_text()):
 if sha(Path(row['path']).read_bytes())!=row['sha256']: raise RuntimeError(('primary drift',row['relative_path']))
print('PRIMARY_FROZEN_INPUTS_VERIFIED',flush=True)
for dep in json.loads((T/'editable-deps-manifest.json').read_text()):
 for row in dep['files']:
  if sha(Path(row['source']).read_bytes())!=row['sha256']: raise RuntimeError(('editable drift',row['source']))
 print('EDITABLE_DEPENDENCY',dep['package'],dep['version'],dep['head'],dep['origin'],len(dep['files']),flush=True)
fixed={r['filename']:r['sha256'] for r in json.loads((T/'fixed-wheels.json').read_text())}
wheels=sorted((T/'wheels').glob('*.whl')); assert len(wheels)==8
all_members={}; bt_count=0
for wheel in wheels:
 digest=sha(wheel.read_bytes())
 if wheel.name in fixed and digest!=fixed[wheel.name]: raise RuntimeError(('fixed wheel drift',wheel.name))
 with zipfile.ZipFile(wheel) as z:
  members={}
  for member in z.namelist():
   if member.endswith('/'):continue
   data=z.read(member); members[member]=sha(data); installed=target/member
   if member.endswith('.dist-info/RECORD'): continue
   if not installed.is_file() or installed.read_bytes()!=data:raise RuntimeError(('wheel install mismatch',wheel.name,member))
   if wheel.name.startswith('back_trader_python-') and member.startswith('backtrader/'):
    original=T/'source/bt'/member
    if not original.is_file() or original.read_bytes()!=data:raise RuntimeError(('BT source wheel mismatch',member))
    bt_count+=1
  all_members[wheel.name]={'sha256':digest,'members':members}
 print('WHEEL_INSTALL_MEMBERS_MATCH',wheel.name,digest,len(members),'RECORD_EXCLUDED',flush=True)
wheel_bt,=list((T/'wheels').glob('back_trader_python-*.whl'))
with zipfile.ZipFile(wheel_bt) as z:
 wp={n for n in z.namelist() if n.startswith('backtrader/') and n.endswith('.py')}
 sp={str(p.relative_to(T/'source/bt')) for p in (T/'source/bt/backtrader').rglob('*.py')}
 ip={str(p.relative_to(target)) for p in (target/'backtrader').rglob('*.py')}
 assert wp==sp==ip,(len(wp),len(sp),len(ip),sorted(wp^sp)[:10],sorted(wp^ip)[:10])
 metadata,= [n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
 desc=z.read(metadata).split(b'\n\n',1)[1]
 readme=(T/'source/bt/README.md').read_bytes()
 if desc.rstrip(b'\n')!=readme.rstrip(b'\n'):raise RuntimeError('README metadata mismatch')
 print('BT_README_MATCH',sha(readme),'PY_SET',len(wp),'ALL_PAYLOAD_MEMBERS',bt_count,flush=True)
for name in ('backtrader','bt_api_base','bt_api_gateway','bt_api_ctp','bt_api_py','bt_api_okx','bt_api_binance','msgpack'):
 module=importlib.import_module(name)
 if not Path(module.__file__).resolve().is_relative_to(target.resolve()):raise RuntimeError(('invalid import',name,module.__file__))
 print('IMPORT_ORIGIN',name,module.__file__,flush=True)
(T/'wheel-members.json').write_text(json.dumps(all_members,indent=2,sort_keys=True)+'\n')
for folder in ('install/src','bt-tests'):
 result={str(p.relative_to(T/folder)):sha(p.read_bytes()) for p in sorted((T/folder).rglob('*')) if p.is_file()}
 path=T/(folder.replace('/','-')+'-before.json')
 if path.exists():
  before=json.loads(path.read_text()); extra=set(result)-set(before); changed=[k for k in before if result.get(k)!=before[k]]
  if changed or (folder!='bt-tests' and extra) or any('__pycache__' not in Path(k).parts or not k.endswith('.pyc') for k in extra):raise RuntimeError(('installed or test files changed after test',folder,changed,sorted(extra)))
  (T/(folder.replace('/','-')+'-after.json')).write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
  print('INVENTORY_UNCHANGED_FROZEN_INPUTS',folder,len(before),'GENERATED_PYC',len(extra),flush=True)
 else:
  path.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n'); print('INVENTORY_FROZEN',folder,len(result),flush=True)
if not audit():raise RuntimeError('origin audit failed')
print('NO_FULL_RESOLVER_NO_REAL_ACCOUNT',flush=True)
