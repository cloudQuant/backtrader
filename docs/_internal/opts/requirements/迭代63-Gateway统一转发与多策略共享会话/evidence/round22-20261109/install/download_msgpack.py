"""Fetch one public dependency wheel only, with local pip config/cache disabled."""
import json,os,subprocess,time
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv');log=T/'msgpack-download.log';dest=T/'dependency-wheels'
if log.exists() or dest.exists():raise RuntimeError('refuse overwrite')
dest.mkdir()
argv=['/Users/yunjinqi/opt/anaconda3/bin/conda','run','--no-capture-output','-n','base','python','-m','pip','download','--index-url','https://pypi.org/simple','--no-input','--disable-pip-version-check','--no-cache-dir','--only-binary=:all:','--no-deps','--dest',str(dest),'msgpack>=1.1']
env=os.environ.copy()
for key in tuple(env):
    if key.upper().startswith(('PIP_','CTP_','OKX_','BINANCE_','HTX_','IB_')) or key.upper() in {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'}:env.pop(key,None)
env['PIP_CONFIG_FILE']='/dev/null';env['TMPDIR']=str(T/'tmp')
start=time.time_ns()
with log.open('wb') as output:
    output.write(('RUN '+json.dumps({'argv':argv},sort_keys=True)+'\n').encode());output.flush()
    result=subprocess.run(argv,cwd=T,env=env,stdout=output,stderr=subprocess.STDOUT,check=False)
    output.write(('EXIT '+str(result.returncode)+'\n').encode())
record={'stage':'msgpack-download','argv':argv,'start_ns':start,'end_ns':time.time_ns(),'exit_code':result.returncode,'log':str(log),'environment_policy':'public PyPI, no pip config/cache, proxy or credential environment'}
with (T/'supplement-executions.jsonl').open('a') as f:f.write(json.dumps(record,sort_keys=True)+'\n')
print('msgpack-download exit',result.returncode,'log',log,flush=True)
raise SystemExit(result.returncode)
