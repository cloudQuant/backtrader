"""Execute one isolated stage with immutable log and precise argv/rc."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv'); C='/Users/yunjinqi/opt/anaconda3/bin/conda'
PY=[C,'run','--no-capture-output','-n','base','python']
if len(sys.argv)!=2 or sys.argv[1] not in {'snapshot','build','install','preflight','tests','verify'}:raise SystemExit('invalid stage')
if not (T/'SOURCE_FROZEN').is_file():raise SystemExit('SOURCE_FREEZE required')
stage=sys.argv[1];log=T/(stage+'.log')
if log.exists():raise RuntimeError('refuse overwrite')
(T/'tmp').mkdir(exist_ok=True)
if stage=='snapshot':argv=PY+[str(T/'prepare.py')]
elif stage=='build':argv=PY+['-m','pip','wheel','--no-index','--no-deps','--no-build-isolation','--wheel-dir',str(T/'wheels'),str(T/'source')]
elif stage=='install':
    wheels=sorted((T/'wheels').glob('*.whl'))
    if len(wheels)!=2 or (T/'install').exists():raise RuntimeError('unexpected wheel count or target exists')
    argv=PY+['-m','pip','install','--no-index','--no-deps','--target',str(T/'install'),*map(str,wheels)]
else:argv=PY+['-I',str(T/({'preflight':'preflight.py','tests':'run_tests.py','verify':'verify.py'}[stage]))]
env=os.environ.copy()
for k in tuple(env):
    if k.startswith(('CTP_','OKX_','BINANCE_','HTX_','IB_')):env.pop(k,None)
run_id=stage+'-'+str(os.getpid())+'-'+str(time.time_ns());env.update({'TMPDIR':str(T/'tmp'),'R22_ORIGIN_RUN':run_id,'PIP_NO_CACHE_DIR':'1','PYTHONDONTWRITEBYTECODE':'1'})
started=time.time_ns()
with log.open('wb') as out:
    out.write(('RUN '+json.dumps({'argv':argv,'run_id':run_id,'pid':os.getpid(),'ppid':os.getppid()},sort_keys=True)+'\n').encode());out.flush()
    result=subprocess.run(argv,cwd=T,env=env,stdout=out,stderr=subprocess.STDOUT,check=False)
    out.write(('EXIT '+str(result.returncode)+'\n').encode())
record={'stage':stage,'argv':argv,'run_id':run_id,'launcher_pid':os.getpid(),'launcher_ppid':os.getppid(),'start_ns':started,'end_ns':time.time_ns(),'exit_code':result.returncode,'log':str(log)}
with (T/'executions.jsonl').open('a') as stream:stream.write(json.dumps(record,sort_keys=True)+'\n')
print(stage,'exit',result.returncode,'run_id',run_id,'log',log,flush=True)
raise SystemExit(result.returncode)
