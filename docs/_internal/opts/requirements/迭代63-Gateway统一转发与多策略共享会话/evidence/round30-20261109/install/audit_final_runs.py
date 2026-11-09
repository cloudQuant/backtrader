from pathlib import Path
import json,subprocess
T=Path('/tmp/iter63-r30-install-20261109-ySExhdil');PY=['/Users/yunjinqi/opt/anaconda3/bin/conda','run','--no-capture-output','-n','base','python'];results=[]
for kind in ('base','gateway','ctp','sdk','bt'):
 path=T/f'{kind}-frozen-final.log';prefix='RUN_METADATA ';lines=[x[len(prefix):] for x in path.read_text().splitlines() if x.startswith(prefix)]
 if len(lines)!=1:raise RuntimeError(('metadata count',kind))
 metadata=json.loads(lines[0]);run=metadata['run_id'];proc=subprocess.run(PY+[str(T/'audit_run.py'),run],text=True,capture_output=True);out=T/f'{kind}-origin-audit.json'
 if out.exists():raise RuntimeError('audit overwrite')
 out.write_text(proc.stdout)
 if proc.returncode:raise RuntimeError(('audit failed',kind,proc.stderr))
 item=json.loads(proc.stdout);results.append({'kind':kind,'run_id':run,'processes':item['files'],'missing_exit':item['missing_exit_audits']})
 print('AUDIT',kind,run,item['files'],'MISSING_EXIT',item['missing_exit_audits'],flush=True)
(T/'audit-summary.json').write_text(json.dumps(results,indent=2)+'\n')
