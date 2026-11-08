import hashlib,importlib,importlib.metadata,json,sys,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r09-packaging-ySGAYCmv/final'); target=(T/'install/src').resolve(); sys.path.insert(0,str(target)); sdk=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
rows=[('bt_api_gateway','gateway','src/bt_api_gateway',sdk/'bt_api/bt_api_gateway'),('bt_api_ctp','ctp','src/bt_api_ctp',sdk/'bt_api/bt_api_ctp'),('bt_api_py','sdk','bt_api_py',sdk)]
for mod,sub,runtime,repo in rows:
 m=importlib.import_module(mod); d=importlib.metadata.distribution(mod); assert Path(m.__file__).resolve().is_relative_to(target) and Path(d._path).resolve().is_relative_to(target)
 roots=[target/mod,T/'source'/sub/runtime,repo/runtime]; sets=[{p.relative_to(r) for p in r.rglob('*.py')} for r in roots]
 print('PACKAGE',mod,m.__file__,d.version,d._path,'PY_SETS',*[len(s) for s in sets],flush=True)
 assert sets[0]==sets[1]==sets[2],(mod,'set mismatch',*[sorted(map(str,s-sets[0])) for s in sets[1:]],sorted(map(str,sets[0]-sets[2])))
 for p in sets[0]: assert (roots[0]/p).read_bytes()==(roots[1]/p).read_bytes()==(roots[2]/p).read_bytes(),(mod,p)
 raw=(repo/'README.md').read_bytes(); assert (T/'source'/sub/'README.md').read_bytes()==raw and d.metadata.get_payload().rstrip('\n')==raw.decode('utf-8').rstrip('\n')
 print('README_SHA256',mod,hashlib.sha256(raw).hexdigest(),flush=True)
old=Path('/tmp/iter63-r08-packaging-j8KrE0I2'); prior=json.loads((old/'artifact.json').read_text()); hashes={r['filename']:r['sha256'] for r in prior['fixed_wheels']+prior['changed_wheels']}
for mod,distname,prefix in [('backtrader','back-trader-python','back_trader_python'),('bt_api_base','bt_api_base','bt_api_base'),('bt_api_okx','bt_api_okx','bt_api_okx'),('bt_api_binance','bt_api_binance','bt_api_binance')]:
 m=importlib.import_module(mod); d=importlib.metadata.distribution(distname); wheel=next((T/'wheels').glob(prefix+'-*.whl')); h=hashlib.sha256(wheel.read_bytes()).hexdigest()
 assert h==hashes[wheel.name] and Path(m.__file__).resolve().is_relative_to(target) and Path(d._path).resolve().is_relative_to(target)
 with zipfile.ZipFile(wheel) as z:
  contents={Path(x[len(mod)+1:]) for x in z.namelist() if x.startswith(mod+'/') and x.endswith('.py')}; installed={p.relative_to(target/mod) for p in (target/mod).rglob('*.py')}
  assert contents==installed,(mod,'wheel set mismatch')
  for rel in contents: assert (target/mod/rel).read_bytes()==z.read(mod+'/'+rel.as_posix()),(mod,rel)
 print('R08_FIXED',mod,m.__file__,d.version,len(contents),h,flush=True)
for n in ['bt_api_gateway.account_read_model','bt_api_gateway.account_session_worker','bt_api_ctp.account_provider','bt_api_ctp.query','bt_api_py.ctp_gateway_trading','bt_api_py.gateway_direct_service']:
 m=importlib.import_module(n); print('MODULE',n,m.__file__,flush=True); assert Path(m.__file__).resolve().is_relative_to(target)
import bt_api_transport_zmq
print('EXTERNAL_TRANSPORT',bt_api_transport_zmq.__file__,flush=True)
for p in sorted((T/'wheels').glob('*.whl')): print('WHEEL_SHA256',p.name,hashlib.sha256(p.read_bytes()).hexdigest(),flush=True)
for kind in ('source','test'):
 entries=json.loads((T/(kind+'-manifest.json')).read_text())
 for row in entries:
  for field in ('source','snapshot') if kind=='source' else ('source','copy'):
   assert hashlib.sha256(Path(row[field]).read_bytes()).hexdigest()==row['sha256'],(kind,row[field])
 print(kind.upper()+'_MANIFEST_SHA_MATCH',len(entries),flush=True)
print('FULL_RESOLVER_AND_ACCOUNT_CALL_NOT_RUN',flush=True)
