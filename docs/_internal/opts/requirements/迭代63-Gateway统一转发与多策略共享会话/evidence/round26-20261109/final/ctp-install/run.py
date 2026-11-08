"""Execute one isolated CTP evidence stage and retain argv, rc and run id."""
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
T=Path('/tmp/iter63-r26-ctp-acceptance-20261109-7xzFjES1');C='/Users/yunjinqi/opt/anaconda3/bin/conda';PY=[C,'run','--no-capture-output','-n','base','python']
stages={'snapshot','tests','fixed','build-ctp','install','relocate','preflight','final-ctp','verify'}
if len(sys.argv)!=2 or sys.argv[1] not in stages:raise SystemExit('invalid stage')
if not (T/'SOURCE_FROZEN').is_file():raise SystemExit('CTP freeze required')
stage=sys.argv[1];log=T/(stage+'.log')
if log.exists():raise RuntimeError('refuse overwrite')
(T/'tmp').mkdir(exist_ok=True)
if stage in {'snapshot','tests','fixed'}:argv=PY+[str(T/'prepare.py'),stage]
elif stage=='build-ctp':
    if len(list((T/'wheels').glob('*.whl')))!=7:raise RuntimeError('expected seven R25 fixed wheels')
    argv=PY+['-I',str(T/'build_ctp_reuse.py')]
elif stage=='install':
    wheels=sorted((T/'wheels').glob('*.whl'))
    if len(wheels)!=8 or (T/'install/src').exists():raise RuntimeError('wheel count/target invalid')
    argv=PY+['-m','pip','install','--no-index','--no-deps','--target',str(T/'install/src'),*map(str,wheels)]
else:argv=PY+['-I',str(T/({'relocate':'relocate.py','preflight':'guard_preflight.py','final-ctp':'run_ctp.py','verify':'verify.py'}[stage]))]
env=os.environ.copy()
for k in tuple(env):
    if k.upper().startswith(('CTP_','OKX_','BINANCE_','HTX_','IB_','PIP_')):env.pop(k,None)
run_id=stage+'-'+str(os.getpid())+'-'+str(time.time_ns());env.update({'TMPDIR':str(T/'tmp'),'PIP_CONFIG_FILE':'/dev/null','PIP_NO_CACHE_DIR':'1','PYTHONDONTWRITEBYTECODE':'1','R26_ORIGIN_RUN':run_id})
if stage=='build-ctp':env['CC']=env['CXX']='/usr/bin/false'
start=time.time_ns();selector_sha=hashlib.sha256((T/'selectors.json').read_bytes()).hexdigest()
with log.open('wb') as out:
    out.write(('RUN_METADATA '+json.dumps({'run_id':run_id,'pid':os.getpid(),'ppid':os.getppid(),'selector_sha256':selector_sha,'argv':argv},sort_keys=True)+'\n').encode());out.flush()
    result=subprocess.run(argv,cwd=T,env=env,stdout=out,stderr=subprocess.STDOUT,check=False);out.write(('RUN_EXIT '+str(result.returncode)+'\n').encode())
record={'stage':stage,'run_id':run_id,'pid':os.getpid(),'ppid':os.getppid(),'selector_sha256':selector_sha,'argv':argv,'start_ns':start,'end_ns':time.time_ns(),'exit_code':result.returncode,'log':str(log)}
with (T/'executions.jsonl').open('a') as stream:stream.write(json.dumps(record,sort_keys=True)+'\n')
print(stage,'exit',result.returncode,'run_id',run_id,'log',log,flush=True)
raise SystemExit(result.returncode)
