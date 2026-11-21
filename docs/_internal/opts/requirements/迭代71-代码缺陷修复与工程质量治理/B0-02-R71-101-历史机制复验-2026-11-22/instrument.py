import json,os,pathlib,subprocess,sys
p=pathlib.Path('.').resolve();env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1');rows=[]
for v in ('old','fixed'):
 r=subprocess.run(['C:/anaconda3/python.exe','-B',str(p/'worker.py'),v,'200','count'],cwd=p,env=env,text=True,capture_output=True,timeout=30,check=True)
 rows.append(json.loads(r.stdout));(p/(v+'.instrument.stderr')).write_text(r.stderr,encoding='utf-8')
(p/'instrument.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print(json.dumps(rows))
