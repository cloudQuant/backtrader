"""Check R23 source, rebuilt wheels, target bytes and fixed wheel provenance."""
import hashlib
import importlib
import importlib.metadata
import json
import sys
import zipfile
from pathlib import Path

T = Path('/tmp/iter63-r23-install-v2-20261109-vGLghOFU')
if not (T/'SOURCE_FROZEN').is_file():
    raise SystemExit('R23 freeze marker absent')
TARGET = (T/'install/src').resolve()
sys.path[:0] = [str(TARGET), str(T/'bootstrap')]
from offline_guard import install as install_offline
install_offline()

for name, staged, runtime in (
    ('bt_api_base', 'base', 'src/bt_api_base'),
    ('bt_api_gateway', 'gateway', 'src/bt_api_gateway'),
    ('bt_api_ctp', 'ctp', 'src/bt_api_ctp'),
    ('bt_api_py', 'sdk', 'bt_api_py'),
    ('backtrader', 'bt', 'backtrader'),
):
    module = importlib.import_module(name)
    distribution = importlib.metadata.distribution('back-trader-python' if name == 'backtrader' else name)
    wheels = list((T/'wheels').glob(('back_trader_python' if name == 'backtrader' else name)+'-*.whl'))
    if len(wheels) != 1 or not Path(module.__file__).resolve().is_relative_to(TARGET) or not Path(distribution._path).resolve().is_relative_to(TARGET):
        raise RuntimeError(('wrong installed origin or wheel cardinality', name))
    snapshot = T/'source'/staged/runtime
    installed = TARGET/name
    with zipfile.ZipFile(wheels[0]) as archive:
        prefix = name+'/'
        wheel_py = {Path(x[len(prefix):]) for x in archive.namelist() if x.startswith(prefix) and x.endswith('.py')}
        snap_py = {p.relative_to(snapshot) for p in snapshot.rglob('*.py')}
        installed_py = {p.relative_to(installed) for p in installed.rglob('*.py')}
        if wheel_py != snap_py or wheel_py != installed_py:
            raise RuntimeError(('python set mismatch', name, sorted(map(str, wheel_py ^ snap_py)), sorted(map(str, wheel_py ^ installed_py))))
        for rel in wheel_py:
            data = archive.read(prefix+rel.as_posix())
            if data != (snapshot/rel).read_bytes() or data != (installed/rel).read_bytes():
                raise RuntimeError(('python byte mismatch', name, str(rel)))
        members = [x for x in archive.namelist() if x.startswith(prefix) and not x.endswith('/')]
        for item in members:
            destination = TARGET/item
            if not destination.is_file() or archive.read(item) != destination.read_bytes():
                raise RuntimeError(('wheel-target byte mismatch', item))
    readme = (T/'source'/staged/'README.md').read_bytes()
    if distribution.metadata.get_payload().rstrip('\n') != readme.decode('utf-8').rstrip('\n'):
        raise RuntimeError(('README metadata mismatch', name))
    print('REBUILT' if staged == 'sdk' else ('REUSED_R23_V1' if staged == 'gateway' else ('REUSED_R21' if staged == 'ctp' else 'REUSED_R19')), name, module.__file__, distribution.version, 'PY_COUNT', len(wheel_py), 'README_SHA256', hashlib.sha256(readme).hexdigest(), flush=True)

fixed = json.loads((T/'fixed-wheels.json').read_text())
names = {'bt_api_okx-':('bt_api_okx','bt_api_okx'), 'bt_api_binance-':('bt_api_binance','bt_api_binance')}
for row in fixed:
    if row['filename'].startswith(('back_trader_python-', 'bt_api_base-', 'bt_api_ctp-', 'bt_api_gateway-')):
        wheel = T/'wheels'/row['filename']
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != row['sha256']:
            raise RuntimeError(('fixed wheel hash mismatch', wheel.name))
        continue
    wheel = T/'wheels'/row['filename']
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != row['sha256']:
        raise RuntimeError(('fixed wheel hash mismatch', wheel.name))
    prefix, = [key for key in names if wheel.name.startswith(key)]
    name, distribution_name = names[prefix]
    module, distribution = importlib.import_module(name), importlib.metadata.distribution(distribution_name)
    if not Path(module.__file__).resolve().is_relative_to(TARGET) or not Path(distribution._path).resolve().is_relative_to(TARGET):
        raise RuntimeError(('wrong fixed package origin', name))
    with zipfile.ZipFile(wheel) as archive:
        members = [item for item in archive.namelist() if item.startswith(name+'/') and not item.endswith('/')]
        for item in members:
            if not (TARGET/item).is_file() or archive.read(item) != (TARGET/item).read_bytes():
                raise RuntimeError(('fixed wheel target mismatch', item))
    print('FIXED', name, module.__file__, distribution.version, len(members), row['sha256'], flush=True)

for manifest in ('source-manifest.json', 'test-manifest.json'):
    rows = json.loads((T/manifest).read_text())
    for row in rows:
        for field in ('source', 'copy'):
            if hashlib.sha256(Path(row[field]).read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError(('source snapshot drift', manifest, row[field]))
    print('MANIFEST_SHA_MATCH', manifest, len(rows), flush=True)
import bt_api_transport_zmq
print('EXTERNAL_EDITABLE_TRANSPORT', bt_api_transport_zmq.__file__, flush=True)
for wheel in sorted((T/'wheels').glob('*.whl')):
    print('WHEEL_SHA256', wheel.name, hashlib.sha256(wheel.read_bytes()).hexdigest(), flush=True)
native=next((TARGET/'bt_api_ctp/ctp').glob('_ctp*.so'))
if hashlib.sha256(native.read_bytes()).hexdigest()!='b49b009529b197025afe6561285fda428959240b9de515fa76bfa165719971f5': raise RuntimeError('R21_CTP_NATIVE_MISMATCH')
print('CTP_REUSED_R21_NATIVE_SHA256',hashlib.sha256(native.read_bytes()).hexdigest(),flush=True)
msgpack=json.loads((T/'msgpack-wheel-manifest.json').read_text());mp_wheel=T/'wheels'/msgpack['filename']
if hashlib.sha256(mp_wheel.read_bytes()).hexdigest()!=msgpack['sha256']: raise RuntimeError('MSGPACK_WHEEL_DRIFT')
import msgpack as mp
mp_dist=importlib.metadata.distribution('msgpack')
if mp_dist.version!='1.2.4' or not Path(mp.__file__).resolve().is_relative_to(TARGET) or not Path(mp_dist._path).resolve().is_relative_to(TARGET): raise RuntimeError('MSGPACK_ORIGIN_OR_VERSION')
with zipfile.ZipFile(mp_wheel) as archive:
    for item in (x for x in archive.namelist() if x.startswith('msgpack/') and not x.endswith('/')):
        if (TARGET/item).read_bytes()!=archive.read(item): raise RuntimeError(('MSGPACK_TARGET_DRIFT',item))
print('TEMP_MSGPACK_VERIFIED',mp_dist.version,mp.__file__,msgpack['sha256'],flush=True)
layout=json.loads((T/'sdk-layout-manifest.json').read_text())
for row in layout['links']:
    link=Path(row['link']);expected=Path(row['target']).resolve()
    if not link.is_symlink() or link.resolve()!=expected or not expected.is_relative_to(TARGET): raise RuntimeError(('SDK_LAYOUT_DRIFT',str(link)))
print('SDK_LAYOUT_LINKS_RESOLVE_INSTALLED_TARGET',len(layout['links']),flush=True)
print('GAP_SDK_ISOLATED_MINUS_I_CHILD_NO_SITECUSTOMIZE see sdk-minus-i-audit-gap.md',flush=True)
for dep in json.loads((T/'editable-deps-manifest.json').read_text()):
    for row in dep['files']:
        if hashlib.sha256(Path(row['source']).read_bytes()).hexdigest()!=row['sha256']: raise RuntimeError(('editable dependency source drift',row['source']))
    print('EXTERNAL_EDITABLE_VERIFIED',dep['package'],dep['version'],dep['head'],dep['origin'],len(dep['files']),flush=True)
print('NO_FULL_RESOLVER_NO_ACCOUNT_CONNECTIONS',flush=True)
