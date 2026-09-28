from __future__ import annotations
import csv,hashlib,io,json,zipfile
from pathlib import Path
root=Path(r'D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927')
inputs={
 'base_A':root/'build-a/wheelhouse/bt_api_base-0.15.5-py3-none-any.whl',
 'base_B':root/'build-b/wheelhouse/bt_api_base-0.15.5-py3-none-any.whl',
 'base_pinned':Path(r'D:\c41sdkf_audit\wheels\bt_api_base-0.15.5-py3-none-any.whl'),
 'ctp_A':root/'build-a/wheelhouse/bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl',
 'ctp_B':root/'build-b/wheelhouse/bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl',
 'ctp_pinned':Path(r'D:\c41sdki2_audit\wheels\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl'),
}
def inspect(path):
 raw=path.read_bytes()
 with zipfile.ZipFile(path) as z:
  entries=[]
  for info in z.infolist():
   data=z.read(info.filename)
   entries.append({'name':info.filename,'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'date_time':list(info.date_time),'compress_type':info.compress_type,'external_attr':info.external_attr})
  rec=[e for e in entries if e['name'].endswith('.dist-info/RECORD')]
  return {'path':str(path),'wheel_size':len(raw),'wheel_sha256':hashlib.sha256(raw).hexdigest(),'entries':entries,'record_sha256':hashlib.sha256(z.read(rec[0]['name'])).hexdigest() if rec else None}
results={key:inspect(path) for key,path in inputs.items()}
comparisons={}
for group in [('base_A','base_B'),('base_A','base_pinned'),('base_B','base_pinned'),('ctp_A','ctp_B'),('ctp_A','ctp_pinned'),('ctp_B','ctp_pinned')]:
 a={e['name']:e for e in results[group[0]]['entries']}; b={e['name']:e for e in results[group[1]]['entries']}
 names=sorted(set(a)|set(b))
 comparisons[' vs '.join(group)]={'same_names':set(a)==set(b),'count_a':len(a),'count_b':len(b),'different_payload':[{ 'name':n,'a_size':a.get(n,{}).get('size'),'b_size':b.get(n,{}).get('size'),'a_sha256':a.get(n,{}).get('sha256'),'b_sha256':b.get(n,{}).get('sha256'),'a_date_time':a.get(n,{}).get('date_time'),'b_date_time':b.get(n,{}).get('date_time')} for n in names if a.get(n,{}).get('size')!=b.get(n,{}).get('size') or a.get(n,{}).get('sha256')!=b.get(n,{}).get('sha256')], 'different_zip_metadata':[{'name':n,'a_date_time':a[n]['date_time'],'b_date_time':b[n]['date_time']} for n in names if n in a and n in b and a[n]['date_time']!=b[n]['date_time']]}
summary={'artifacts':{k:{key:v[key] for key in ('path','wheel_size','wheel_sha256','record_sha256')} for k,v in results.items()},'comparisons':comparisons}
out=root/'wheel-member-comparison.json'
out.write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
