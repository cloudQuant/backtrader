import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

OUT = Path('D:/temp/i51-ctp-nojoin-consumer-20261027-r1')
HOUSE = Path('D:/temp/ac51-r0-sdk-20261026-r2/offline-wheelhouse')
BUILD = Path('D:/temp/i51-ctp-nojoin-wheel-20261027-r1')
WHEEL = BUILD / 'wheelhouse/bt_api_ctp-2.0.4+iteration41.i9-cp311-cp311-win_amd64.whl'
BASE = HOUSE / 'bt_api_base-0.15.8-py3-none-any.whl'
PY = 'C:/anaconda3/python.exe'

def pin(p):
    raw = p.read_bytes()
    return {'path': str(p), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

assert not OUT.exists(), 'fresh output required'
assert pin(WHEEL)['sha256'] == '32811ab303cd875274fc9d69ee3ca3f29d83c33d9d5217f4eadd037cb07123d7'
assert pin(BASE)['sha256'] == 'b579a73531281d74f6e1630d447717b9f87e38bf507d82178d9ad46745017f39'
inventory = json.loads(Path('D:/source_code/backtrader/.codex-tmp/r0_dependency_inventory_20261025.json').read_text(encoding='utf-8-sig'))
dependencies = [row for row in inventory['wheels'] if row['name'] not in ('back-trader-python', 'bt_api_base')]
assert len(dependencies) == 49
for row in dependencies:
    actual = pin(HOUSE / row['filename'])
    assert actual['sha256'] == row['sha256'] and actual['size_bytes'] == row['size_bytes']
with zipfile.ZipFile(WHEEL) as z:
    payload = {n: z.read(n) for n in z.namelist() if n.startswith('bt_api_ctp/') and n.endswith('.py')}
    source = BUILD / 'source/src'
    expected = {p.relative_to(source).as_posix(): p.read_bytes() for p in (source / 'bt_api_ctp').rglob('*.py')}
    assert payload == expected, 'source to wheel Python mismatch'
OUT.mkdir()
state = {'status': 'RUNNING', 'sdk_commit': '574cd2dd495a3c675d7cd23fcbf23a797a08c04d', 'wheel': pin(WHEEL), 'base': pin(BASE), 'source_python_count': len(payload), 'source_to_wheel_exact': True, 'pinned_available_dependency_count': len(dependencies), 'commands': []}
def save():
    (OUT / 'preparation.json').write_text(json.dumps(state, indent=2)+'\n', encoding='utf-8')
env = os.environ.copy()
for key in ('PYTHONPATH', 'PYTHONHOME', 'PIP_EXTRA_INDEX_URL', 'PIP_FIND_LINKS'):
    env.pop(key, None)
env.update(PYTHONUTF8='1', PYTHONNOUSERSITE='1', PIP_CONFIG_FILE='NUL')
def run(label, args):
    save()
    with (OUT / (label+'.txt')).open('wb') as log:
        result = subprocess.run(args, cwd=OUT, env=env, stdout=log, stderr=subprocess.STDOUT)
    state['commands'].append({'phase': label, 'args': args, 'exit_code': result.returncode, 'log': pin(OUT / (label+'.txt'))})
    save()
    assert result.returncode == 0, label
try:
    run('venv', [PY, '-I', '-m', 'venv', str(OUT / 'consumer')])
    consumer = str(OUT / 'consumer/Scripts/python.exe')
    run('install', [consumer, '-I', '-m', 'pip', 'install', '--disable-pip-version-check', '--no-index', '--find-links', str(HOUSE), str(BASE), str(WHEEL)])
    run('pip-check', [consumer, '-I', '-m', 'pip', 'check'])
    state['status'] = 'INSTALLED_PENDING_RECORD_VERIFICATION'
    save()
    print(json.dumps({'status': state['status'], 'source_python_count': len(payload), 'consumer': consumer}))
except BaseException:
    state['status'] = 'FAILED'
    save()
    raise
