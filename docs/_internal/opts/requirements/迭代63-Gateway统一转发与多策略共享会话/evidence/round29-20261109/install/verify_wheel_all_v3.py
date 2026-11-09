import base64,csv,hashlib,io,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4');wheel,=(T/'wheels').glob('bt_api_py-*.whl');target=T/'install/src'
def check(records,read,allow_bytecode=False):
 count=0
 for name,signature,size in records:
  if not signature:
   if name.endswith('/RECORD') and not size:continue
   if allow_bytecode and '/__pycache__/' in name and name.endswith('.pyc') and not size:
    read(name);continue
   raise RuntimeError(('missing digest',name))
  alg,encoded=signature.split('=',1)
  if alg!='sha256':raise RuntimeError(('unsupported digest',name))
  data=read(name);digest=base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
  if digest!=encoded or int(size)!=len(data):raise RuntimeError(('bad record',name))
  count+=1
 return count
with zipfile.ZipFile(wheel) as z:
 names=[n for n in z.namelist() if not n.endswith('/')];record,=[n for n in names if n.endswith('.dist-info/RECORD')]
 differences=[n for n in names if not (target/n).is_file() or (target/n).read_bytes()!=z.read(n)]
 if differences!=[record]:raise RuntimeError(('unexpected member differences',differences))
 wheel_records=list(csv.reader(io.StringIO(z.read(record).decode())));installed_records=list(csv.reader(io.StringIO((target/record).read_text())))
 a=check(wheel_records,z.read)
 def read_target(n):
  p=(target/n).resolve()
  if n=='../../bin/bt-gateway-operator':
   p=(target/'bin/bt-gateway-operator').resolve()
  if not p.is_relative_to(target.resolve()):raise RuntimeError(('unsafe installed record path',n))
  return p.read_bytes()
 b=check(installed_records,read_target,allow_bytecode=True)
 wheel_names={r[0] for r in wheel_records};installed_names={r[0] for r in installed_records}
 if wheel_names-installed_names:raise RuntimeError(('wheel record members missing',sorted(wheel_names-installed_names)))
 print('WHEEL_MEMBERS',len(names),'EXACT_MATCH',len(names)-1,'WHEEL_RECORD_VALID',a,'INSTALLED_RECORD_VALID',b,'RECORD_REWRITTEN_BY_PIP',record,'TARGET_SCRIPT_RECORD_REBASED','../../bin/bt-gateway-operator -> bin/bt-gateway-operator','INSTALLED_ADDITIONAL',json.dumps(sorted(installed_names-wheel_names)))
