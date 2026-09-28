from __future__ import annotations
import csv, hashlib, json, os, subprocess, sys, time
from pathlib import Path

base = Path(r'C:\anaconda3\python.exe')
wheel = Path(r'D:\temp\iteration41-coordinated-release-probe-independent-qa-20260927\wheelhouse\bt_api_py-0.15.7.dev0+r4r3r3.67e54513-py3-none-any.whl')
root = Path(r'D:\temp\iteration41-g4-parent-sdk-status-qa-20260927')
expected_wheel_sha = '5e6e846d26b5038c0916fa15d3ce3f7a1c1334fd0aa160cd263d2d0397c07b0f'

def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
def sha_file(p: Path) -> str:
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()
def run(label, args, logfile, env):
    p=subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    (root / logfile).write_text(p.stdout, encoding='utf-8')
    (root / (logfile+'.exit.txt')).write_text(str(p.returncode), encoding='ascii')
    if p.returncode:
        raise RuntimeError(f'{label} exit {p.returncode}: {p.stdout[-2000:]}')
    return p.stdout

assert sha_file(wheel)==expected_wheel_sha
base_version=subprocess.check_output([str(base),'-B','--version'],text=True).strip()
results=[]
for label in ('record-install-a','record-install-b'):
    venv=root/label/'venv'
    env=os.environ.copy()
    env['PIP_NO_INDEX']='1'
    env['PIP_DISABLE_PIP_VERSION_CHECK']='1'
    env['PYTHONPATH']=''
    venv_out=run(label+'-venv',[str(base),'-B','-m','venv',str(venv)],label+'-venv.log',env)
    py=venv/'Scripts'/'python.exe'
    pip_version=run(label+'-pip-version',[str(py),'-B','-m','pip','--version'],label+'-pip-version.log',env).strip()
    install_out=run(label+'-install',[str(py),'-B','-m','pip','install','--no-index','--no-deps','--disable-pip-version-check',str(wheel)],label+'-install.log',env)
    matches=list((venv/'Lib'/'site-packages').glob('bt_api_py-0.15.7.dev0+r4r3r3.67e54513.dist-info'))
    assert len(matches)==1,matches
    dist=matches[0]
    rec=dist/'RECORD'
    recbytes=rec.read_bytes()
    rows=list(csv.reader(recbytes.decode('utf-8').splitlines()))
    result={
      'label':label,
      'python_base_version':base_version,
      'pip_version':pip_version,
      'wheel_sha256':sha_file(wheel),
      'installed_record_sha256':sha_bytes(recbytes),
      'installed_record_rows':len(rows),
      'record_hashed_rows':sum(bool(r[1]) for r in rows),
      'record_blank_hash_rows':sum(not r[1] for r in rows),
      'blank_hash_suffix_counts':{},
      'venv_no_system_site_packages':True,
      'wheel_install_exit':0,
      'package_import_performed':False,
    }
    suffix_counts={}
    for r in rows:
        if not r[1]:
            suffix=Path(r[0]).suffix or '<none>'
            suffix_counts[suffix]=suffix_counts.get(suffix,0)+1
    result['blank_hash_suffix_counts']=suffix_counts
    results.append(result)
assert results[0]['installed_record_sha256']==results[1]['installed_record_sha256'],results
payload={'schema':'iteration41-g4-parent-record-repro-two-new-venvs-v1','results':results,'record_sha_match':results[0]['installed_record_sha256']==results[1]['installed_record_sha256']}
(root/'two-venv-installed-record-reproduction.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
print(json.dumps(payload,indent=2))
