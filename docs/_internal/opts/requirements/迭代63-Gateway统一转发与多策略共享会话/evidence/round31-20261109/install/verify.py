"""Verify both rebuilt SDK/BT payloads, six fixed wheels and frozen manifests."""
from pathlib import Path
import hashlib,importlib,importlib.metadata,json,sys,zipfile
T=Path('/tmp/iter63-r31-install-20261109-mz1EwW5H');target=(T/'install/src').resolve();sys.path[:0]=[str(target),str(T/'bootstrap')]
from offline_guard import install as guard
guard();sha=lambda data:hashlib.sha256(data).hexdigest();source=json.loads((T/'source-manifest.json').read_text());lookup={r['copy']:r for r in source}
for kind,name,runtime in (('sdk','bt_api_py','bt_api_py'),('bt','backtrader','backtrader')):
 wheel,=(T/'wheels').glob(('back_trader_python' if kind=='bt' else name)+'-*.whl');root=T/'source'/kind/runtime;module=importlib.import_module(name)
 if not Path(module.__file__).resolve().is_relative_to(target):raise RuntimeError(('outside target',name))
 with zipfile.ZipFile(wheel) as z:
  prefix=name+'/';members=[n for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')]
  for member in members:
   data=z.read(member);copy=root/member[len(prefix):];row=lookup.get(str(copy))
   if row is None or data!=copy.read_bytes() or data!=Path(row['source']).read_bytes() or data!=(target/member).read_bytes() or sha(data)!=row['sha256']:raise RuntimeError(('payload mismatch',member))
  metadata,=[n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
  if (T/'source'/kind/'README.md').read_text() not in z.read(metadata).decode():raise RuntimeError(('README metadata mismatch',kind))
 print('REBUILT_PAYLOAD_MATCH',kind,len(members),sha(wheel.read_bytes()),flush=True)
for r in json.loads((T/'fixed-wheels.json').read_text()):
 wheel=T/'wheels'/r['filename']
 for p in (wheel,Path(r['source'])):
  if sha(p.read_bytes())!=r['sha256']:raise RuntimeError(('fixed wheel drift',str(p)))
 prefix=next((p for p in ('bt_api_base','bt_api_gateway','bt_api_ctp','bt_api_okx','bt_api_binance','msgpack') if wheel.name.startswith(p+'-')),None)
 if prefix is None:raise RuntimeError(('unexpected wheel',wheel.name))
 with zipfile.ZipFile(wheel) as z:
  members=[n for n in z.namelist() if n.startswith(prefix+'/') and not n.endswith('/')]
  for n in members:
   if z.read(n)!=(target/n).read_bytes():raise RuntimeError(('fixed payload mismatch',n))
 print('FIXED_PAYLOAD_MATCH',prefix,len(members),r['sha256'],flush=True)
for name in ('source-manifest.json','test-manifest.json'):
 rows=json.loads((T/name).read_text())
 for row in rows:
  for key in ('source','copy'):
   if sha(Path(row[key]).read_bytes())!=row['sha256']:raise RuntimeError(('manifest drift',name,row[key]))
 print('MANIFEST_MATCH',name,len(rows),flush=True)
for row in json.loads((T/'sdk-layout-manifest.json').read_text())['links']:
 link=Path(row['link'])
 if not link.is_symlink() or link.resolve()!=Path(row['target']).resolve() or not link.resolve().is_relative_to(target):raise RuntimeError(('layout mismatch',str(link)))
for dep in json.loads((T/'editable-deps-manifest.json').read_text()):
 for row in dep['files']:
  if sha(Path(row['source']).read_bytes())!=row['sha256']:raise RuntimeError(('editable drift',row['source']))
 print('EDITABLE_VERIFIED',dep['package'],dep['head'],len(dep['files']))
print('NO_FULL_RESOLVER; NO_ACCOUNT; NATIVE_REUSED; -I/-S CHILD GUARD GAP',flush=True)
