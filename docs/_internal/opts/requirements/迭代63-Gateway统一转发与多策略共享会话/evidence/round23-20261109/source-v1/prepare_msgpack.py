"""Install the previously verified R22 msgpack wheel into a local source-test target."""
import hashlib,json,os,subprocess,time,zipfile
from pathlib import Path
T=Path('/tmp/iter63-r23-primary')
if not (T/'SOURCE_FROZEN').is_file():raise SystemExit('SOURCE_FREEZE required')
wheel=Path('/tmp/iter63-r22-e044-install-20261109-K3FbuXsv/dependency-wheels/msgpack-1.2.4-cp311-cp311-macosx_11_0_arm64.whl')
expected='a4b47ec7422bef149223786a87df80067ac65bfc7c0565e5cf1dfbdc40acee50'
if hashlib.sha256(wheel.read_bytes()).hexdigest()!=expected:raise RuntimeError('R22 msgpack wheel SHA mismatch')
target=T/'dependencies';log=T/'source-msgpack-install.log'
if target.exists() or log.exists():raise RuntimeError('refuse dependency target/log overwrite')
argv=['/Users/yunjinqi/opt/anaconda3/bin/conda','run','--no-capture-output','-n','base','python','-m','pip','install','--no-index','--no-deps','--no-cache-dir','--target',str(target),str(wheel)]
env=os.environ.copy()
for k in tuple(env):
    if k.upper().startswith(('PIP_','CTP_','OKX_','BINANCE_','HTX_','IB_')):env.pop(k,None)
env['PIP_CONFIG_FILE']='/dev/null'
start=time.time_ns()
with log.open('wb') as out:
    out.write(('RUN '+json.dumps({'argv':argv},sort_keys=True)+'\n').encode());out.flush()
    completed=subprocess.run(argv,cwd=T,env=env,stdout=out,stderr=subprocess.STDOUT,check=False)
    out.write(('EXIT '+str(completed.returncode)+'\n').encode())
rows=[]
if completed.returncode==0:
    with zipfile.ZipFile(wheel) as z:
        for n in (x for x in z.namelist() if x.startswith('msgpack/') and not x.endswith('/')):
            data=z.read(n)
            if not (target/n).is_file() or (target/n).read_bytes()!=data:raise RuntimeError(('source msgpack payload mismatch',n))
            rows.append({'relative':n,'sha256':hashlib.sha256(data).hexdigest()})
    if not rows:raise RuntimeError('empty msgpack package')
(T/'source-msgpack-manifest.json').write_text(json.dumps({'wheel':str(wheel),'wheel_sha256':expected,'version':'1.2.4','target':str(target),'argv':argv,'exit_code':completed.returncode,'start_ns':start,'end_ns':time.time_ns(),'members':rows},indent=2)+'\n')
print('SOURCE_MSGPACK_INSTALL',completed.returncode,'payload_files',len(rows),'log',log,flush=True)
raise SystemExit(completed.returncode)
