import hashlib,json,os,subprocess,sys,time
from pathlib import Path
T=Path('/tmp/iter63-r26-sdk-install-20261109-xAIrOrDl');PY=['/Users/yunjinqi/opt/anaconda3/bin/conda','run','--no-capture-output','-n','base','python']; stage=sys.argv[1]; log=T/(stage+'.log')
if log.exists():raise RuntimeError('refusing log overwrite')
if stage in ('freeze','snapshot','tests','fixed'):cmd=PY+[str(T/'setup_harness.py'),stage]
elif stage=='build':cmd=PY+['-m','pip','wheel','--no-index','--no-deps','--no-build-isolation','--wheel-dir',str(T/'wheels'),str(T/'source/sdk')]
elif stage=='install':
 wheels=sorted((T/'wheels').glob('*.whl'));assert len(wheels)==8 and not (T/'install/src').exists();cmd=PY+['-m','pip','install','--no-index','--no-deps','--target',str(T/'install/src'),*map(str,wheels)]
elif stage in ('preflight','sdk-installed','sdk-installed-v2','verify','verify-final'):cmd=PY+['-I',str(T/({'preflight':'guard_preflight.py','sdk-installed':'run_sdk.py','sdk-installed-v2':'run_sdk_v2.py','verify':'verify.py','verify-final':'verify.py'}[stage]))]
else:raise SystemExit('unknown stage')
env=os.environ.copy()
for k in tuple(env):
 if k.upper().startswith(('CTP_','OKX_','BINANCE_','HTX_','IB_','PIP_')):env.pop(k,None)
(T/'tmp').mkdir(exist_ok=True);runid=stage+'-'+str(os.getpid())+'-'+str(time.time_ns());env.update({'TMPDIR':str(T/'tmp'),'PIP_CONFIG_FILE':'/dev/null','PIP_NO_CACHE_DIR':'1','PYTHONDONTWRITEBYTECODE':'1','R26_ORIGIN_RUN':runid,'CC':'/usr/bin/false','CXX':'/usr/bin/false'})
start=time.time_ns();sel=T/'selectors.json';selection=hashlib.sha256(sel.read_bytes()).hexdigest() if sel.exists() else None
with log.open('wb') as out:
 out.write(('RUN_METADATA '+json.dumps({'stage':stage,'run_id':runid,'pid':os.getpid(),'ppid':os.getppid(),'selector_sha256':selection,'argv':cmd},sort_keys=True)+'\n').encode());out.flush();result=subprocess.run(cmd,cwd=T,env=env,stdout=out,stderr=subprocess.STDOUT);out.write(('RUN_EXIT '+str(result.returncode)+'\n').encode())
record={'stage':stage,'run_id':runid,'pid':os.getpid(),'ppid':os.getppid(),'selector_sha256':selection,'argv':cmd,'start_ns':start,'end_ns':time.time_ns(),'exit_code':result.returncode,'log':str(log)}
with (T/'executions.jsonl').open('a') as f:f.write(json.dumps(record,sort_keys=True)+'\n')
print(stage,'exit',result.returncode,'run_id',runid,'log',log,flush=True);raise SystemExit(result.returncode)
