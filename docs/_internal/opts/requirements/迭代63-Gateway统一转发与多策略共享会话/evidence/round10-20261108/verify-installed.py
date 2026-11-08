"""Offline source, wheel, installed target and metadata agreement."""
import hashlib
import importlib
import importlib.metadata
import json
import sys
import zipfile
from pathlib import Path

T = Path('/tmp/iter63-r10-packaging-Zc9un7t2')
TARGET = (T/'install/src').resolve()
sys.path.insert(0, str(TARGET))
SDK = Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
for module, sub, runtime, repo in (
    ('bt_api_ctp','ctp','src/bt_api_ctp',SDK/'bt_api/bt_api_ctp'),
    ('bt_api_py','sdk','bt_api_py',SDK),
):
    mod = importlib.import_module(module)
    distribution = importlib.metadata.distribution(module)
    assert Path(mod.__file__).resolve().is_relative_to(TARGET)
    assert Path(distribution._path).resolve().is_relative_to(TARGET)
    wheels = list((T/'wheels').glob(module+'-*.whl'))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        prefix = module+'/'
        members = {Path(x[len(prefix):]) for x in wheel.namelist() if x.startswith(prefix) and x.endswith('.py')}
        roots = (TARGET/module, T/'source'/sub/runtime, repo/runtime)
        sets = [{p.relative_to(root) for p in root.rglob('*.py')} for root in roots]
        assert members == sets[0] == sets[1] == sets[2], (module,'python module set mismatch')
        for rel in members:
            assert wheel.read(prefix+rel.as_posix()) == (roots[0]/rel).read_bytes() == (roots[1]/rel).read_bytes() == (roots[2]/rel).read_bytes(), (module,rel)
    readme = (repo/'README.md').read_bytes()
    assert (T/'source'/sub/'README.md').read_bytes() == readme
    assert distribution.metadata.get_payload().rstrip('\n') == readme.decode('utf-8').rstrip('\n')
    print('REBUILT',module,mod.__file__,distribution.version,'PY_COUNT',len(members),'README_SHA256',hashlib.sha256(readme).hexdigest(),flush=True)
prior = Path('/tmp/iter63-r09-packaging-ySGAYCmv/final')
hashes = {r['filename']:r['sha256'] for r in json.loads((prior/'artifact.json').read_text())['wheels']}
for module, distribution_name, prefix in (
    ('backtrader','back-trader-python','back_trader_python'),
    ('bt_api_base','bt_api_base','bt_api_base'),
    ('bt_api_gateway','bt_api_gateway','bt_api_gateway'),
    ('bt_api_okx','bt_api_okx','bt_api_okx'),
    ('bt_api_binance','bt_api_binance','bt_api_binance'),
):
    mod = importlib.import_module(module)
    distribution = importlib.metadata.distribution(distribution_name)
    wheel_path, = (T/'wheels').glob(prefix+'-*.whl')
    digest = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    assert digest == hashes[wheel_path.name]
    assert Path(mod.__file__).resolve().is_relative_to(TARGET)
    assert Path(distribution._path).resolve().is_relative_to(TARGET)
    with zipfile.ZipFile(wheel_path) as wheel:
        root = module+'/'
        members = {Path(x[len(root):]) for x in wheel.namelist() if x.startswith(root) and x.endswith('.py')}
        installed = {p.relative_to(TARGET/module) for p in (TARGET/module).rglob('*.py')}
        assert members == installed
        for rel in members: assert wheel.read(root+rel.as_posix()) == (TARGET/module/rel).read_bytes()
    print('R09_FIXED',module,mod.__file__,distribution.version,len(members),digest,flush=True)
for kind in ('source','test'):
    rows = json.loads((T/(kind+'-manifest.json')).read_text())
    for row in rows:
        fields = ('source','snapshot') if kind == 'source' else ('source','copy')
        for field in fields:
            assert hashlib.sha256(Path(row[field]).read_bytes()).hexdigest() == row['sha256'],(kind,row[field])
    print(kind.upper()+'_MANIFEST_SHA_MATCH',len(rows),flush=True)
import bt_api_transport_zmq
print('EXTERNAL_EDITABLE_TRANSPORT',bt_api_transport_zmq.__file__,flush=True)
for wheel in sorted((T/'wheels').glob('*.whl')):
    print('WHEEL_SHA256',wheel.name,hashlib.sha256(wheel.read_bytes()).hexdigest(),flush=True)
print('FULL_RESOLVER_AND_ACCOUNT_CALL_NOT_RUN',flush=True)
