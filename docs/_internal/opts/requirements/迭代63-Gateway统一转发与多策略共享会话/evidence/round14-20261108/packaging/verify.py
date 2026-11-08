"""Check R14 source, rebuilt wheels, target bytes and fixed wheel provenance."""
import hashlib
import importlib
import importlib.metadata
import json
import sys
import zipfile
from pathlib import Path

T = Path('/tmp/iter63-r14-packaging-B7Rre1rO')
if not (T/'SOURCE_FROZEN').is_file():
    raise SystemExit('R14 freeze marker absent')
TARGET = (T/'install/src').resolve()
sys.path[:0] = [str(TARGET), str(T/'bootstrap')]
from offline_guard import install as install_offline
install_offline()

for name, staged, runtime in (
    ('bt_api_base', 'base', 'src/bt_api_base'),
    ('bt_api_gateway', 'gateway', 'src/bt_api_gateway'),
    ('bt_api_py', 'sdk', 'bt_api_py'),
):
    module = importlib.import_module(name)
    distribution = importlib.metadata.distribution(name)
    wheels = list((T/'wheels').glob(name+'-*.whl'))
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
    print('REBUILT', name, module.__file__, distribution.version, 'PY_COUNT', len(wheel_py), 'README_SHA256', hashlib.sha256(readme).hexdigest(), flush=True)

fixed = json.loads((T/'fixed-wheels.json').read_text())
names = {'bt_api_ctp-':('bt_api_ctp','bt_api_ctp'), 'back_trader_python-':('backtrader','back-trader-python'),
         'bt_api_okx-':('bt_api_okx','bt_api_okx'), 'bt_api_binance-':('bt_api_binance','bt_api_binance')}
for row in fixed:
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
print('NO_FULL_RESOLVER_NO_ACCOUNT_CONNECTIONS', flush=True)
