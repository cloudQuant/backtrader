"""Record post-dependency verification and unchanged test selection."""
import json,os,subprocess,sys,time
from pathlib import Path
T=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv')
choices={'verify-dependency':'verify_msgpack.py','tests-msgpack':'run_tests_with_dependency.py','verify-final':'verify.py'}
if len(sys.argv)!=2 or sys.argv[1] not in choices:raise SystemExit('invalid stage')
stage=sys.argv[1];log=T/(stage+'.log')
if log.exists():raise RuntimeError('refuse overwrite')
argv=['/Users/yunjinqi/opt/anaconda3/bin/conda','run','--no-capture-output','-n','base','python','-I',str(T/choices[stage])]
env=os.environ.copy()
for k in tuple(env):
    if k.startswith(('CTP_','OKX_','BINANCE_','HTX_','IB_')):env.pop(k,None)
run_id=stage+'-'+str(os.getpid())+'-'+str(time.time_ns());env.update({'R22_ORIGIN_RUN':run_id,'TMPDIR':str(T/'tmp'),'PYTHONDONTWRITEBYTECODE':'1'})
started=time.time_ns()
with log.open('wb') as out:
    out.write(('RUN '+json.dumps({'argv':argv,'run_id':run_id},sort_keys=True)+'\n').encode());out.flush()
    result=subprocess.run(argv,cwd=T,env=env,stdout=out,stderr=subprocess.STDOUT,check=False)
    out.write(('EXIT '+str(result.returncode)+'\n').encode())
with (T/'supplement-executions.jsonl').open('a') as f:f.write(json.dumps({'stage':stage,'argv':argv,'run_id':run_id,'start_ns':started,'end_ns':time.time_ns(),'exit_code':result.returncode,'log':str(log)},sort_keys=True)+'\n')
print(stage,'exit',result.returncode,'run_id',run_id,'log',log,flush=True)
raise SystemExit(result.returncode)
