"""Launch one frozen source suite and record exact non-sensitive execution metadata."""
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

T=Path('/tmp/iter63-r26-primary')
if len(sys.argv)!=2 or sys.argv[1] not in {'gateway','ctp','sdk'}:
    raise SystemExit('usage: run_source.py gateway|ctp|sdk')
if not (T/'SOURCE_FROZEN').is_file(): raise SystemExit('SOURCE_FREEZE required')
kind=sys.argv[1];plan=T/'selectors.json';log=T/(kind+'-source.log')
if not plan.is_file() or log.exists(): raise RuntimeError('missing selector or refusing to overwrite log')
native=None
if kind in {'ctp','sdk'}:
    source=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/ctp')/('_ctp'+sysconfig.get_config_var('EXT_SUFFIX'))
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if digest!='b49b009529b197025afe6561285fda428959240b9de515fa76bfa165719971f5': raise RuntimeError('source CTP native differs from R19 wheel')
    native={'source':str(source),'sha256':digest,'provenance':'R19 validated native wheel payload; source bytes read without importing'}
    native_manifest=T/(kind+'-source-native.json')
    if native_manifest.exists(): raise RuntimeError('refusing native manifest overwrite')
    native_manifest.write_text(json.dumps(native,indent=2)+'\n')
selector_sha=hashlib.sha256(plan.read_bytes()).hexdigest()
command=['/Users/yunjinqi/opt/anaconda3/bin/conda','run','--no-capture-output','-n','base','python','-I',str(T/'run.py')]
env=os.environ.copy()
for key in tuple(env):
    if key.startswith(('CTP_','OKX_','BINANCE_','HTX_','IB_')): env.pop(key,None)
env['R26_KIND']=kind;env['R26_SELECTORS']=str(plan);env.pop('R26_ORIGIN_RUN',None)
start=time.time_ns()
with log.open('wb') as output:
    completed=subprocess.run(command,cwd=T,env=env,stdout=output,stderr=subprocess.STDOUT,check=False)
end=time.time_ns()
metadata=[]
for line in log.read_text(errors='replace').splitlines():
    if line.startswith('RUN_METADATA '): metadata.append(json.loads(line[len('RUN_METADATA '):]))
if len(metadata)!=1 or metadata[0]['selector_sha256']!=selector_sha:
    print('RUN_METADATA_MISSING_OR_MISMATCH',flush=True);metadata=[]
record={'kind':kind,'launcher_pid':os.getpid(),'launcher_ppid':os.getppid(),'argv':command,
        'selector_sha256':selector_sha,'run_id':metadata[0]['run_id'] if metadata else None,
        'source_pid':metadata[0]['pid'] if metadata else None,'start_ns':start,'finish_ns':end,
        'exit_code':completed.returncode,'source_native':native,'stdout_stderr':str(log)}
with (T/'launcher-executions.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps(record,sort_keys=True)+'\n')
print('SOURCE_RUN_COMPLETE',json.dumps(record,sort_keys=True),flush=True)
raise SystemExit(completed.returncode if metadata else 1)
