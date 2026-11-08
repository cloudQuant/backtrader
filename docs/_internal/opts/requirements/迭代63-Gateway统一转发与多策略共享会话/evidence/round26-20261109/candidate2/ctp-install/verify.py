"""Verify CTP frozen input, wheel, installed target and R25 fixed payloads."""
import hashlib,importlib,importlib.metadata,json,sys,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r26-ctp-final-v2-20261109-UFGxjkbS');target=(T/'install/src').resolve();sys.path[:0]=[str(target),str(T/'bootstrap')]
from origin_guard import audit,install as origin
from offline_guard import install as offline
origin('r26-verify');offline()
for name in ('source-manifest.json','test-manifest.json','ctp-relocation-manifest.json'):
    rows=json.loads((T/name).read_text())
    for r in rows:
        for field in ('source','copy'):
            if hashlib.sha256(Path(r[field]).read_bytes()).hexdigest()!=r['sha256']:raise RuntimeError(('manifest drift',name,r[field]))
    print('MANIFEST_MATCH',name,len(rows),flush=True)
packages={'back_trader_python-':('backtrader','back-trader-python'),'bt_api_base-':('bt_api_base','bt_api_base'),'bt_api_gateway-':('bt_api_gateway','bt_api_gateway'),'bt_api_py-':('bt_api_py','bt_api_py'),'bt_api_okx-':('bt_api_okx','bt_api_okx'),'bt_api_binance-':('bt_api_binance','bt_api_binance'),'msgpack-':('msgpack','msgpack'),'bt_api_ctp-':('bt_api_ctp','bt_api_ctp')}
for prefix,(package,distname) in packages.items():
    wheel,=list((T/'wheels').glob(prefix+'*.whl'));module=importlib.import_module(package);dist=importlib.metadata.distribution(distname)
    if not Path(module.__file__).resolve().is_relative_to(target) or not Path(dist._path).resolve().is_relative_to(target):raise RuntimeError(('outside target',package))
    with zipfile.ZipFile(wheel) as z:
        base=package+'/';members=[n for n in z.namelist() if n.startswith(base) and not n.endswith('/')]
        for name in members:
            if not (target/name).is_file() or (target/name).read_bytes()!=z.read(name):raise RuntimeError(('wheel target mismatch',name))
        if package=='bt_api_ctp':
            src=T/'source/ctp/src/bt_api_ctp';py={Path(n[len(base):]) for n in members if n.endswith('.py')};sp={p.relative_to(src) for p in src.rglob('*.py')};tp={p.relative_to(target/package) for p in (target/package).rglob('*.py')}
            if py!=sp or py!=tp:raise RuntimeError('CTP python path mismatch')
            for p in py:
                if z.read(base+p.as_posix())!=(src/p).read_bytes():raise RuntimeError(('CTP wheel source mismatch',str(p)))
            if dist.metadata.get_payload().rstrip('\n')!=(T/'source/ctp/README.md').read_text().rstrip('\n'):raise RuntimeError('README mismatch')
    print('VERIFIED',package,'origin',module.__file__,'wheel_sha256',hashlib.sha256(wheel.read_bytes()).hexdigest(),flush=True)
native=json.loads((T/'ctp-native-reuse-manifest.json').read_text());old=Path(native['source_wheel']);new,=list((T/'wheels').glob('bt_api_ctp-*.whl'))
if hashlib.sha256(old.read_bytes()).hexdigest()!=native['source_wheel_sha256']:raise RuntimeError('old native wheel drift')
with zipfile.ZipFile(old) as a,zipfile.ZipFile(new) as b:
    for r in native['members']:
        data=a.read(r['member'])
        if hashlib.sha256(data).hexdigest()!=r['sha256'] or b.read(r['member'])!=data or (target/r['member']).read_bytes()!=data:raise RuntimeError(('native bytes drift',r['member']))
print('CTP_NATIVE_REUSED_NO_COMPILATION',len(native['members']),native['native_extension_sha256'],flush=True)
if importlib.metadata.version('msgpack')!='1.2.4' or not audit():raise RuntimeError('bad dependency/origin')
print('SDK_FIXED_R25_NOT_CURRENT_WORKTREE; NO_FULL_RESOLVER; NO_REAL_ACCOUNT',flush=True)
