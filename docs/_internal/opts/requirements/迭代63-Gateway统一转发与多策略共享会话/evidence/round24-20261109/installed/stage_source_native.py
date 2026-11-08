"""Materialize only previously verified CTP native wheel payload into frozen source layout."""
import base64,csv,hashlib,io,json,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r24-install-20261109-fEuNyr35')
if not (T/'SOURCE_FROZEN').is_file():raise SystemExit('SOURCE_FREEZE required')
wheel=Path('/tmp/iter63-r21-install-20261109-QD2dgx3G/wheels/bt_api_ctp-2.1.0.dev63-cp311-cp311-macosx_11_0_arm64.whl')
expected='74b01167b703b5b8e57418ef8dd9ce680b40bac35f1aa0d60a50f0bbe3e1d619'
if hashlib.sha256(wheel.read_bytes()).hexdigest()!=expected:raise RuntimeError('R21 CTP wheel mismatch')
root=T/'source/ctp/src/bt_api_ctp/ctp';manifest=T/'source-native-manifest.json'
if not root.is_dir() or manifest.exists():raise RuntimeError('source missing or native stage exists')
rows=[]
with zipfile.ZipFile(wheel) as z:
    rec,=[x for x in z.namelist() if x.endswith('.dist-info/RECORD')]
    records={r[0]:r[1:] for r in csv.reader(io.StringIO(z.read(rec).decode()))}
    for name in z.namelist():
        prefix='bt_api_ctp/ctp/'
        if not name.startswith(prefix) or name.endswith(('.py','/')):continue
        rel=Path(name[len(prefix):])
        if rel.is_absolute() or '..' in rel.parts:raise RuntimeError('unsafe native member')
        data=z.read(name);digest=hashlib.sha256(data).digest();encoded=base64.urlsafe_b64encode(digest).rstrip(b'=').decode()
        if records.get(name)!=['sha256='+encoded,str(len(data))]:raise RuntimeError(('wheel RECORD mismatch',name))
        target=root/rel
        if target.exists():raise RuntimeError(('native source collision',str(target)))
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        rows.append({'member':name,'copy':str(target),'sha256':digest.hex(),'size':len(data)})
if not any(r['member'].endswith('_ctp.cpython-311-darwin.so') and r['sha256']=='b49b009529b197025afe6561285fda428959240b9de515fa76bfa165719971f5' for r in rows):raise RuntimeError('expected native extension missing')
manifest.write_text(json.dumps({'wheel':str(wheel),'wheel_sha256':expected,'members':rows,'note':'verified R21 wheel payload; no native compilation or factory calls'},indent=2)+'\n')
print('SOURCE_NATIVE_REUSED',len(rows),flush=True)
