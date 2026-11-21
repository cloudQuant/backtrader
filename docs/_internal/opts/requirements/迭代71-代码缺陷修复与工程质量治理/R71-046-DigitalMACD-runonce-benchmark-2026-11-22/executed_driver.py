import os,subprocess,json,statistics,pathlib,sys
root=pathlib.Path('D:/temp/i71_digital_prefix_opt')
exe=sys.argv[1];records=[]
for period in (5,256,1024):
 for pair in range(4):
  order=('baseline','candidate') if pair%2==0 else ('candidate','baseline')
  for name in order:
   folder=root/name;env=os.environ.copy();env['PYTHONPATH']=str(folder)
   raw=subprocess.check_output([exe,'-B','bench_worker.py',str(period),'1'],cwd=folder,env=env,text=True)
   row=json.loads(raw.strip().splitlines()[-1]); row.update(pair=pair,variant=name);records.append(row)
  a,b=records[-2:]
  assert a['output_sha256']==b['output_sha256'] and a['data_sha256']==b['data_sha256']
 print(period,[(round(r['seconds'],4),r['variant']) for r in records if r['period']==period],flush=True)
(root/('bench_root_serial_20261122_'+pathlib.Path(exe).parent.name+'.json')).write_text(json.dumps(records,indent=2)+'\n',encoding='utf-8')
