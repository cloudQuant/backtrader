"""Record public tracked editable Monitor and ZMQ bytes; do not import either package."""
import hashlib
import importlib.metadata
import importlib.util
import json
import subprocess
from pathlib import Path

T=Path('/tmp/iter63-r23-install-v2-20261109-vGLghOFU')
if not (T/'SOURCE_FROZEN').is_file(): raise SystemExit('SOURCE_FREEZE required')
manifest=T/'editable-deps-manifest.json'
if manifest.exists(): raise RuntimeError('editable dependency manifest already exists')
base=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api')
rows=[]
for package in ('bt_api_monitor','bt_api_transport_zmq'):
    repo=base/package; runtime='src/'+package
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    spec=importlib.util.find_spec(package)
    if spec is None or spec.origin is None or not Path(spec.origin).resolve().is_relative_to((repo/runtime).resolve()):
        raise RuntimeError(('unexpected editable origin',package))
    version=importlib.metadata.distribution(package).version
    paths=subprocess.check_output(['git','-C',str(repo),'ls-files','-z','--',runtime]).decode().split('\0')
    untracked=subprocess.check_output(['git','-C',str(repo),'ls-files','-z','--others','--exclude-standard','--',runtime]).decode().split('\0')
    if any(p.endswith('.py') for p in untracked): raise RuntimeError(('untracked runtime',package))
    files=[]
    for relative in sorted(filter(None,paths)):
        path=repo/relative
        if any(p.startswith('.env') or p in {'config.yaml','account_config.yaml'} for p in Path(relative).parts):
            raise RuntimeError(('private path in selection',relative))
        if not path.is_file() or path.is_symlink(): raise RuntimeError(('invalid source',str(path)))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        blob=subprocess.run(['git','-C',str(repo),'show',head+':'+relative],capture_output=True,check=False)
        if blob.returncode: raise RuntimeError(('editable commit blob unavailable',relative))
        clean_oid=subprocess.check_output(['git','-C',str(repo),'hash-object','--',relative],text=True).strip()
        head_oid=subprocess.check_output(['git','-C',str(repo),'rev-parse',head+':'+relative],text=True).strip()
        if clean_oid!=head_oid: raise RuntimeError(('editable working tree differs from commit after Git clean filters',relative))
        files.append({'source':str(path),'relative':relative,'sha256':digest,
                      'commit_blob_sha256':hashlib.sha256(blob.stdout).hexdigest(),'git_clean_blob_oid':clean_oid})
    if not files: raise RuntimeError(('empty runtime',package))
    rows.append({'package':package,'repo':str(repo),'head':head,'version':version,'origin':spec.origin,'files':files})
    print('EXTERNAL_EDITABLE_PUBLIC_RUNTIME',package,version,head,len(files),flush=True)
manifest.write_text(json.dumps(rows,indent=2)+'\n')
