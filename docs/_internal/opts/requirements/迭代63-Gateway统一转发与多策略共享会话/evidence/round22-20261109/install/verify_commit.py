"""Bind every frozen source/test path to the final Gateway Git commit blob."""
import hashlib,json,subprocess
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv');repo=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_gateway')
head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
if head!='091d72fcae1c6fe6ac3dacdf6db4619f2c5b87a6':raise RuntimeError(('unexpected Gateway HEAD',head))
rows=json.loads((T/'manifest.json').read_text())
for row in rows:
    for key in ('source','copy'):
        if hashlib.sha256(Path(row[key]).read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError(('source/copy drift',row[key]))
    blob=subprocess.run(['git','-C',str(repo),'show',head+':'+row['relative']],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,check=False)
    if blob.returncode or hashlib.sha256(blob.stdout).hexdigest()!=row['sha256']:raise RuntimeError(('commit mismatch',row['relative']))
parent=repo.parent.parent
link=subprocess.check_output(['git','-C',str(parent),'rev-parse','HEAD:bt_api/bt_api_gateway'],text=True).strip()
if link!=head:raise RuntimeError(('SDK gitlink mismatch',link,head))
print('COPY_WORKTREE_COMMIT_SHA_MATCH',len(rows),'GATEWAY_HEAD',head,'SDK_GITLINK_MATCH',link,flush=True)
