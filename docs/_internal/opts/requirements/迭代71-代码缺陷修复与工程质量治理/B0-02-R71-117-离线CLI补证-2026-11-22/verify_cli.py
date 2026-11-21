import csv,hashlib,io,json,os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
exe=Path('C:/anaconda3/python.exe')
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
report={}
for version in ('old','fixed'):
 r=subprocess.run([str(exe),'-B',str(root/'bootstrap.py'),version],cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
 (root/(version+'.stdout')).write_bytes(r.stdout);(root/(version+'.stderr')).write_bytes(r.stderr)
 text=r.stdout.decode('utf-8',errors='strict');err=r.stderr.decode('utf-8',errors='strict')
 csvrows=[]
 for line in text.splitlines():
  if line and line[0].isdigit() and ',bars.csv,' in line:csvrows.append(next(csv.reader([line])))
 report[version]={'exit':r.returncode,'missing_yahoo_module':"No module named 'backtrader.feeds.yahoounreversed'" in err,'rows':len(csvrows),'closes':[float(row[7]) for row in csvrows],'strategy_lengths':[int(row[11]) for row in csvrows],'blocked_categories':next((line for line in text.splitlines() if line.startswith('PUBLIC_BLOCKED_CATEGORIES ')),None),'stdout_sha256':hashlib.sha256(r.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(r.stderr).hexdigest()}
(root/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
assert report['old']['exit']!=0 and report['old']['missing_yahoo_module'] and report['old']['rows']==0
assert report['fixed']['exit']==0 and report['fixed']['rows']==6 and report['fixed']['closes']==[10.,11.,12.,13.,14.,15.] and report['fixed']['strategy_lengths']==[1,2,3,4,5,6]
