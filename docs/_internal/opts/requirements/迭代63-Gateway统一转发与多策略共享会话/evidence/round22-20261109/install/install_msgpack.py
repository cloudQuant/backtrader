"""Install the downloaded binary dependency in the isolated target only."""
import hashlib,json,os,subprocess,time
from pathlib import Path
from packaging.utils import parse_wheel_filename
from packaging.version import Version
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv');wheels=list((T/'dependency-wheels').glob('msgpack*.whl'));log=T/'msgpack-install.log'
if len(wheels)!=1 or log.exists() or (T/'install/msgpack').exists():raise RuntimeError('missing/multiple wheel or target polluted')
wheel=wheels[0];name,version,_,_=parse_wheel_filename(wheel.name)
if str(name)!='msgpack' or version<Version('1.1'):raise RuntimeError('dependency version invalid')
digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
(T/'msgpack-wheel-manifest.json').write_text(json.dumps({'filename':wheel.name,'source':str(wheel),'sha256':digest,'version':str(version),'source_index':'https://pypi.org/simple'},indent=2)+'\n')
argv=['/Users/yunjinqi/opt/anaconda3/bin/conda','run','--no-capture-output','-n','base','python','-m','pip','install','--no-index','--no-deps','--no-cache-dir','--target',str(T/'install'),str(wheel)]
env=os.environ.copy()
for k in tuple(env):
    if k.upper().startswith(('PIP_','CTP_','OKX_','BINANCE_','HTX_','IB_')):env.pop(k,None)
env['PIP_CONFIG_FILE']='/dev/null';env['TMPDIR']=str(T/'tmp');start=time.time_ns()
with log.open('wb') as out:
    out.write(('RUN '+json.dumps({'argv':argv},sort_keys=True)+'\n').encode());out.flush()
    result=subprocess.run(argv,cwd=T,env=env,stdout=out,stderr=subprocess.STDOUT,check=False)
    out.write(('EXIT '+str(result.returncode)+'\n').encode())
with (T/'supplement-executions.jsonl').open('a') as f:f.write(json.dumps({'stage':'msgpack-install','argv':argv,'start_ns':start,'end_ns':time.time_ns(),'exit_code':result.returncode,'log':str(log)},sort_keys=True)+'\n')
print('msgpack-install exit',result.returncode,'version',version,'sha256',digest,flush=True)
raise SystemExit(result.returncode)
