import hashlib,importlib,importlib.metadata,json,sys,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r08-packaging-j8KrE0I2'); target=(T/'target').resolve(); sys.path.insert(0,str(target))
rows=[('backtrader','back-trader-python','bt',Path('/Users/yunjinqi/Documents/new_projects/backtrader')),('bt_api_py','bt_api_py','sdk',Path('/Users/yunjinqi/Documents/new_projects/bt_api_py'))]
for mod,distname,sub,repo in rows:
 m=importlib.import_module(mod); d=importlib.metadata.distribution(distname)
 assert Path(m.__file__).resolve().is_relative_to(target) and Path(d._path).resolve().is_relative_to(target)
 roots=[target/mod,T/'source'/sub/mod,repo/mod]; sets=[{p.relative_to(r) for p in r.rglob('*.py')} for r in roots]
 print('PACKAGE',mod,m.__file__,d.version,d._path,'SETS',*[len(s) for s in sets],flush=True)
 assert sets[0]==sets[1]==sets[2],(mod,'set mismatch',*[sorted(map(str,s-sets[0])) for s in sets[1:]],sorted(map(str,sets[0]-sets[2])))
 for p in sets[0]: assert (roots[0]/p).read_bytes()==(roots[1]/p).read_bytes()==(roots[2]/p).read_bytes(),(mod,p)
 readme=(repo/'README.md').read_bytes(); assert (T/'source'/sub/'README.md').read_bytes()==readme
 assert d.metadata.get_payload().rstrip('\n')==readme.decode('utf-8').rstrip('\n'),(mod,'README mismatch')
 print('README_SHA256',mod,hashlib.sha256(readme).hexdigest(),flush=True)
old=Path('/tmp/iter63-r07-final-packaging-5t99PHD1')
prior={r['filename']:r['sha256'] for r in json.loads((old/'artifact.json').read_text())['wheels']}
for name in ['bt_api_base','bt_api_gateway','bt_api_ctp','bt_api_okx','bt_api_binance']:
 m=importlib.import_module(name); d=importlib.metadata.distribution(name); p=next((T/'wheels').glob(name+'-*.whl'))
 assert Path(m.__file__).resolve().is_relative_to(target) and Path(d._path).resolve().is_relative_to(target)
 h=hashlib.sha256(p.read_bytes()).hexdigest(); assert h==prior[p.name]
 with zipfile.ZipFile(p) as z:
  contents={Path(x[len(name)+1:]) for x in z.namelist() if x.startswith(name+'/') and x.endswith('.py')}; installed={p.relative_to(target/name) for p in (target/name).rglob('*.py')}
  assert contents==installed,(name,'set mismatch')
  for rel in contents: assert (target/name/rel).read_bytes()==z.read(name+'/'+rel.as_posix()),(name,rel)
 print('R07_FIXED',name,m.__file__,d.version,len(contents),h,flush=True)
for n in ['bt_api_py.direct_write','bt_api_py.gateway_direct_client','backtrader.live_state.gateway_pending']:
 m=importlib.import_module(n); print('MODULE',n,m.__file__,flush=True); assert Path(m.__file__).resolve().is_relative_to(target)
try:
 import bt_api_transport_zmq
 print('EXTERNAL_TRANSPORT',bt_api_transport_zmq.__file__,flush=True)
except ImportError: print('EXTERNAL_TRANSPORT_UNAVAILABLE',flush=True)
for p in sorted((T/'wheels').glob('*.whl')): print('WHEEL_SHA256',p.name,hashlib.sha256(p.read_bytes()).hexdigest(),flush=True)
print('NO_DEPENDENCY_RESOLUTION_OR_ACCOUNT_CALL',flush=True)
