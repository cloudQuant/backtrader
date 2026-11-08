from pathlib import Path
import hashlib,json,os,subprocess,sys,time
root=Path('/Users/yunjinqi/Documents/new_projects/backtrader')
out=Path('/tmp/iter63-r25-primary')
paths=['backtrader/brokers/_btapi_gateway_projection.py','tests/unit/brokers/test_iter63_gateway_framework_projection.py','tests/unit/live_state/test_gateway_framework_checkpoint.py']
def hashes(): return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}
before=hashes()
selectors=json.loads((out/'selectors.json').read_text())
command=[sys.executable,'-m','pytest','--import-mode=importlib','-q','--junitxml='+str(out/'bt-source.xml'),*selectors]
start=time.time()
with (out/'bt-source.log').open('w') as log:
 result=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
after=hashes()
record={'command':command,'cwd':str(root),'returncode':result.returncode,'duration_seconds':round(time.time()-start,3),'before':before,'after':after,'source_unchanged':before==after}
(out/'source-execution.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
print('\n'.join((out/'bt-source.log').read_text().splitlines()[-14:]))
raise SystemExit(result.returncode or (0 if before==after else 2))
