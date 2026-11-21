import sys,subprocess,json,statistics,platform,hashlib
from pathlib import Path
root=Path(r'D:/temp/iter71_clock_nocache_review_20261122')
roots={'head':root,'nocache':root/'candidate'};records={k:[] for k in roots};order=[]
for i in range(4):
 for name in (('head','nocache') if i%2==0 else ('nocache','head')):
  p=subprocess.run([sys.executable,'-B','bench_clock.py'],cwd=roots[name],capture_output=True,text=True,check=True);x=json.loads(p.stdout);records[name].append(x);order.append(name);print(i,name,x,flush=True)
result={'scope':'root sequential nonexclusive','head':'a2472f5b0baedf460de043847ab9f9189dc3a42f','python':sys.version,'platform':platform.platform(),'order':order,'records':records,'median':{n:statistics.median(x['seconds'] for x in vals) for n,vals in records.items()},'bench_sha256':hashlib.sha256((root/'bench_clock.py').read_bytes()).hexdigest()}
(root/'head_vs_nocache_root_serial_20261122.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print('summary',result['median'])
