import json,os,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parent;exe='C:/anaconda3/python.exe';env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1');rows=[]
for round in range(3):
 for v in (('old','fixed') if round%2==0 else ('fixed','old')):
  p=subprocess.run([exe,'-B',str(root/'worker.py'),v,'30000','bench'],cwd=root,env=env,text=True,capture_output=True,timeout=120)
  if p.returncode:raise RuntimeError((v,p.returncode,p.stdout,p.stderr))
  r=json.loads(p.stdout);rows.append(r);print(json.dumps(r),flush=True)
(root/'benchmark.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
