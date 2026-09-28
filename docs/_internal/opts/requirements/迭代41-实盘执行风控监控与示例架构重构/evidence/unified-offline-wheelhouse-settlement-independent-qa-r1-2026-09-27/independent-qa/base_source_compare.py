import hashlib,json,subprocess,zipfile
from pathlib import Path
cand=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1')
base=Path(r'D:\temp\bt_api_i9_store_broker_src_20260926\bt_api_base')
wheel=cand/'wheelhouse'/'bt_api_base-0.15.4-py3-none-any.whl'
def sha(b):return hashlib.sha256(b).hexdigest()
head=subprocess.run(['git','-C',str(base),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
status=subprocess.run(['git','-C',str(base),'status','--porcelain'],capture_output=True,text=True,check=True).stdout.strip()
src=base/'src'/'bt_api_base'
source={p.relative_to(base/'src').as_posix():p.read_bytes() for p in src.rglob('*.py')}
with zipfile.ZipFile(wheel) as z:
 packaged={n:z.read(n) for n in z.namelist() if n.startswith('bt_api_base/') and n.endswith('.py')}
rows=[]
for p in sorted(set(source)|set(packaged)):
 a=source.get(p); b=packaged.get(p)
 rows.append({'path':p,'source_sha256':sha(a) if a is not None else None,'wheel_sha256':sha(b) if b is not None else None,'exact_bytes_match':a==b})
obj={'schema':'iteration41.unified_offline_wheelhouse_settlement.base_source_comparison.r1.v1','git_head':head,'git_clean':not bool(status),'source_root':str(src),'wheel':wheel.name,'source_python_file_count':len(source),'wheel_python_file_count':len(packaged),'exact_matches':sum(r['exact_bytes_match'] for r in rows),'mismatches':[r for r in rows if not r['exact_bytes_match']],'files':rows}
qa=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927')
(qa/'evidence'/'base-source-comparison.json').write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in obj.items() if k not in ('files','mismatches')},indent=2))
if head!='3de0fa4f6cfe8d1973e9f4b9b47b01254259524f' or status or len(source)!=104 or len(packaged)!=104 or any(not x['exact_bytes_match'] for x in rows):raise SystemExit(1)
