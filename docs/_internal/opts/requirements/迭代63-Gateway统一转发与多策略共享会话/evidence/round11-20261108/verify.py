"""Verify source snapshots, fixed wheel hashes, installed bytes and editable transport."""
import hashlib
import importlib
import importlib.metadata
import json
import sys
import zipfile
from pathlib import Path

T = Path('/tmp/iter63-r11-packaging-CoU48Q7B')
TARGET = (T/'install/src').resolve()
sys.path[:0] = [str(TARGET), str(T/'bootstrap')]
from offline_guard import install as install_offline
install_offline()
for name, repo, runtime in (
    ('bt_api_base', 'base', 'src/bt_api_base'),
    ('bt_api_gateway', 'gateway', 'src/bt_api_gateway'),
):
    module = importlib.import_module(name)
    distribution = importlib.metadata.distribution(name)
    wheel, = (T/'wheels').glob(name+'-*.whl')
    if not Path(module.__file__).resolve().is_relative_to(TARGET) or not Path(distribution._path).resolve().is_relative_to(TARGET):
        raise RuntimeError(('wrong installed origin', name))
    with zipfile.ZipFile(wheel) as archive:
        prefix = name+'/'
        wheel_py = {Path(x[len(prefix):]) for x in archive.namelist() if x.startswith(prefix) and x.endswith('.py')}
        snapshot = T/'source'/repo/runtime
        installed = TARGET/name
        snap_py = {p.relative_to(snapshot) for p in snapshot.rglob('*.py')}
        inst_py = {p.relative_to(installed) for p in installed.rglob('*.py')}
        if wheel_py != snap_py or wheel_py != inst_py:
            raise RuntimeError(('python module set mismatch', name))
        for rel in wheel_py:
            if archive.read(prefix+rel.as_posix()) != (snapshot/rel).read_bytes() or (snapshot/rel).read_bytes() != (installed/rel).read_bytes():
                raise RuntimeError(('installed module mismatch', name, str(rel)))
    readme = (T/'source'/repo/'README.md').read_bytes()
    if distribution.metadata.get_payload().rstrip('\n') != readme.decode('utf-8').rstrip('\n'):
        raise RuntimeError(('wheel README mismatch', name))
    print('REBUILT', name, module.__file__, distribution.version, 'PY_COUNT', len(wheel_py), 'README_SHA256', hashlib.sha256(readme).hexdigest(), flush=True)
fixed = json.loads((T/'fixed-wheels.json').read_text())
modules = {'back_trader_python-': ('backtrader', 'back-trader-python'), 'bt_api_py-': ('bt_api_py','bt_api_py'),
           'bt_api_ctp-': ('bt_api_ctp','bt_api_ctp'), 'bt_api_okx-': ('bt_api_okx','bt_api_okx'),
           'bt_api_binance-': ('bt_api_binance','bt_api_binance')}
for row in fixed:
    wheel = T/'wheels'/row['filename']
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != row['sha256']:
        raise RuntimeError(('fixed wheel mismatch', wheel.name))
    prefix, = [x for x in modules if wheel.name.startswith(x)]
    name, distribution_name = modules[prefix]
    module, distribution = importlib.import_module(name), importlib.metadata.distribution(distribution_name)
    if not Path(module.__file__).resolve().is_relative_to(TARGET) or not Path(distribution._path).resolve().is_relative_to(TARGET):
        raise RuntimeError(('wrong fixed origin', name))
    with zipfile.ZipFile(wheel) as archive:
        root = name+'/'
        members = [x for x in archive.namelist() if x.startswith(root) and not x.endswith('/')]
        for item in members:
            installed = TARGET/item
            if not installed.is_file() or archive.read(item) != installed.read_bytes():
                raise RuntimeError(('fixed installed file mismatch', item))
    print('R10_FIXED', name, module.__file__, distribution.version, len(members), row['sha256'], flush=True)
for manifest in ('source-manifest.json', 'test-manifest.json'):
    rows = json.loads((T/manifest).read_text())
    for row in rows:
        for name in ('source', 'copy'):
            if hashlib.sha256(Path(row[name]).read_bytes()).hexdigest() != row['sha256']:
                raise RuntimeError(('source or copy drift', name, row[name]))
    print('MANIFEST_SHA_MATCH', manifest, len(rows), flush=True)
import bt_api_transport_zmq
print('EXTERNAL_EDITABLE_TRANSPORT', bt_api_transport_zmq.__file__, flush=True)
for wheel in sorted((T/'wheels').glob('*.whl')):
    print('WHEEL_SHA256', wheel.name, hashlib.sha256(wheel.read_bytes()).hexdigest(), flush=True)
print('NO_FULL_RESOLVER_NO_ACCOUNT_NO_NATIVE_CTP', flush=True)
