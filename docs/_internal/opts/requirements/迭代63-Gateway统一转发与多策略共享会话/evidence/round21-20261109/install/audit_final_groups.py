"""Audit only each explicitly selected final test run, retaining per-run logs."""
import json
import subprocess
from pathlib import Path
T=Path('/tmp/iter63-r21-install-20261109-QD2dgx3G')
records=[json.loads(line) for line in (T/'executions.jsonl').read_text().splitlines()]
report=[]
for kind in ('gateway','ctp','sdk'):
    found=[row for row in records if row['stage']==kind+'-frozen-final']
    if len(found)!=1 or found[0]['exit_code']!=0: raise RuntimeError(('final test stage not uniquely passed',kind))
    run_id=found[0]['run_id']; log=T/(kind+'-origin-audit.log')
    if log.exists(): raise RuntimeError('refuse overwrite audit')
    argv=['/Users/yunjinqi/opt/anaconda3/bin/conda','run','--no-capture-output','-n','base','python','-I',str(T/'audit_run.py'),run_id]
    with log.open('wb') as out: result=subprocess.run(argv,cwd=T,stdout=out,stderr=subprocess.STDOUT,check=False)
    if result.returncode: raise RuntimeError(('run audit failed',kind,run_id,str(log)))
    data=json.loads(log.read_text());report.append({'kind':kind,'run_id':run_id,'argv':argv,'exit_code':result.returncode,'stdout_stderr':str(log),'files':data['files'],'missing_exit_audits':data['missing_exit_audits']})
    print('RUN_AUDIT',kind,run_id,'recorded',data['files'],'missing_exit',data['missing_exit_audits'],flush=True)
(T/'group-audit-results.json').write_text(json.dumps(report,indent=2)+'\n')
