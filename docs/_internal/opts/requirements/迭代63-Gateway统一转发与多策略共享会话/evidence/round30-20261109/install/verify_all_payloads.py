"""Verify each wheel payload against its source/target and approved CTP native reuse."""
import hashlib,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');rows=json.loads((T/'source-manifest.json').read_text());lookup={r['copy']:r for r in rows};native={x['member']:x for x in json.loads((T/'ctp-native-reuse-manifest.json').read_text())['members']};target=T/'install/src'
for kind,name,runtime in (('base','bt_api_base','src/bt_api_base'),('gateway','bt_api_gateway','src/bt_api_gateway'),('ctp','bt_api_ctp','src/bt_api_ctp'),('sdk','bt_api_py','bt_api_py'),('bt','backtrader','backtrader')):
 prefix=name+'/';wheel,=(T/'wheels').glob(('back_trader_python' if kind=='bt' else name)+'-*.whl');root=T/'source'/kind/runtime
 with zipfile.ZipFile(wheel) as z:
  members=[n for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')];reused=0
  for member in members:
   data=z.read(member);copy=root/member[len(prefix):];row=lookup.get(str(copy))
   if (target/member).read_bytes()!=data:raise RuntimeError(('target drift',member))
   if row is not None:
    if data!=copy.read_bytes() or data!=Path(row['source']).read_bytes() or hashlib.sha256(data).hexdigest()!=row['sha256']:raise RuntimeError(('source drift',member))
   elif kind=='ctp' and member in native and hashlib.sha256(data).hexdigest()==native[member]['sha256']:reused+=1
   else:raise RuntimeError(('wheel payload missing frozen source',member))
  print('ALL_WHEEL_PAYLOAD_MATCH',kind,len(members),'NATIVE_REUSED',reused,'SHA256',hashlib.sha256(wheel.read_bytes()).hexdigest(),flush=True)
