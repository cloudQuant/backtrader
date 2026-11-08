"""Copy five tracked public YAML example fixtures omitted from first test snapshot."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
T=Path('/tmp/iter63-r18-install-20261109-GvDCI8TF')
repo=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py')
names=['unconfigured-client.yaml','strategy-readonly.yaml','portfolio-analysis-client.yaml','account-service.yaml','portfolio-analysis-service.yaml']
manifest=T/'test-manifest.json'
backup=T/'test-manifest-before-public-examples.json'
if backup.exists(): raise RuntimeError('do not overwrite original manifest')
shutil.copyfile(manifest,backup)
rows=json.loads(manifest.read_text())
head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
added=[]
for name in names:
    relative='examples/services/'+name
    if subprocess.run(['git','-C',str(repo),'ls-files','--error-unmatch','--',relative],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
        raise RuntimeError(('example is not tracked',relative))
    source=repo/relative; destination=T/'sdk-tests'/relative
    if source.is_symlink() or not source.is_file() or destination.exists(): raise RuntimeError(('invalid source/destination',relative))
    data=source.read_bytes(); destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(data)
    added.append({'source':str(source),'copy':str(destination),'sha256':hashlib.sha256(data).hexdigest(),'repo':str(repo),'relative':relative,'snapshot_head':head})
rows.extend(added)
manifest.write_text(json.dumps(rows,indent=2)+'\n')
(T/'public-example-fixtures-manifest.json').write_text(json.dumps(added,indent=2)+'\n')
print('tracked public example fixture count',len(added),'total test manifest count',len(rows))
