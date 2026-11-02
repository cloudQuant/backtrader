import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

ROOT = Path('D:/source_code/backtrader')
OUT = Path('D:/temp/i51-nojoin-backtrader-20261027-r1')
PREFIX = Path('D:/temp/i51-ctp-nojoin-consumer-20261027-r1/consumer')
COMMIT = '9ecece9d9e80176de8cb9942ca187eb333a18137'
HOUSE = Path('D:/temp/ac51-r0-sdk-20261026-r2/offline-wheelhouse')
assert not OUT.exists()
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip() == COMMIT
OUT.mkdir()
state = {'status':'RUNNING','source_commit':COMMIT,'commands':[]}
env = os.environ.copy()
for name in ('PYTHONPATH','PYTHONHOME','PIP_FIND_LINKS','PIP_EXTRA_INDEX_URL'):
    env.pop(name,None)
env.update(PYTHONUTF8='1',PYTHONNOUSERSITE='1',PIP_CONFIG_FILE='NUL')
def pin(path):
    raw = path.read_bytes()
    return {'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def save():
    (OUT/'build-install.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
def run(label,command,cwd=OUT):
    save()
    with (OUT/(label+'.txt')).open('wb') as output:
        completed = subprocess.run(command,cwd=cwd,env=env,stdout=output,stderr=subprocess.STDOUT)
    state['commands'].append({'phase':label,'command':command,'exit_code':completed.returncode,'log':pin(OUT/(label+'.txt'))})
    save()
    assert completed.returncode == 0,label
try:
    archive = OUT/'source.zip'
    run('archive',['git','archive','--format=zip','--output='+str(archive),COMMIT,'setup.py','pyproject.toml','README.md','LICENSE','backtrader','backtrader_runtime'],ROOT)
    state['archive'] = pin(archive)
    source = OUT/'source'
    with zipfile.ZipFile(archive) as z:
        z.extractall(source)
    wheelhouse = OUT/'wheelhouse'
    wheelhouse.mkdir()
    run('build',['C:/anaconda3/python.exe','-I','-m','pip','wheel','--disable-pip-version-check','--no-deps','--no-build-isolation','--wheel-dir',str(wheelhouse),str(source)])
    wheels = list(wheelhouse.glob('*.whl'))
    assert len(wheels)==1
    wheel = wheels[0]
    state['wheel'] = pin(wheel)
    expected = {p.relative_to(source).as_posix():p.read_bytes() for package in ('backtrader','backtrader_runtime') for p in (source/package).rglob('*.py')}
    with zipfile.ZipFile(wheel) as z:
        actual = {n:z.read(n) for n in z.namelist() if n.startswith(('backtrader/','backtrader_runtime/')) and n.endswith('.py')}
    assert actual == expected,'Python source payload mismatch'
    state['python_payload_files_verified'] = len(actual)
    python = str(PREFIX/'Scripts/python.exe')
    run('install',[python,'-I','-m','pip','install','--disable-pip-version-check','--no-index','--find-links',str(HOUSE),str(wheel)])
    run('pip-check',[python,'-I','-m','pip','check'])
    state['status']='INSTALLED_PENDING_RUNTIME_CHECK'
    save()
    print(json.dumps({'status':state['status'],'wheel':state['wheel'],'python_files':len(actual)}))
except BaseException:
    state['status']='FAILED'
    save()
    raise
