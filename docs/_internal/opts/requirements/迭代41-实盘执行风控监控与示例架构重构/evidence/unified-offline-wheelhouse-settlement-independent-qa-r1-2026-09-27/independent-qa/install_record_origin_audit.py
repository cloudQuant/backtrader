import base64,csv,hashlib,json,re,sys,zipfile
from email.parser import Parser
from pathlib import Path,PurePosixPath
qa=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-independent-qa-20260927')
cand=Path(r'D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1')
venv=qa/'venv'; site=venv/'Lib'/'site-packages'; wh=cand/'wheelhouse'
def sha(b):return hashlib.sha256(b).hexdigest()
def norm(n):return n.lower().replace('_','-').replace('.','-')
errors=[]
if sys.version_info[:3] != (3,11,5): errors.append(f'Python version unexpected {sys.version}')
# Parse the lock and wheel manifest.
lock={}
for line in (cand/'requirements-hashes.txt').read_text(encoding='ascii').splitlines():
 m=re.fullmatch(r'(.+)==(.+) --hash=sha256:([0-9a-f]{64})',line.strip())
 if not m: errors.append('invalid hash lock line '+line); continue
 lock[norm(m.group(1))]=(m.group(2),m.group(3))
wman=json.loads((cand/'wheelhouse-manifest.json').read_text(encoding='utf-8'))
expected={norm(w['name']):w for w in wman['wheels']}
if len(lock)!=52 or len(expected)!=52: errors.append('expected 52 unique lock/manifest distributions')
# PIP initial no-index report proves the resolver's source URL and selected archive digest for each wheel.
report=json.loads((qa/'logs'/'pip-install-report.json').read_text(encoding='utf-8'))
report_entries=report.get('install',[])
report_rows=[]
for ent in report_entries:
 md=ent.get('metadata',{}); info=ent.get('download_info',{}); url=info.get('url',''); got=(info.get('archive_info') or {}).get('hashes',{}).get('sha256')
 name=norm(md.get('name',''))
 item=expected.get(name)
 if item is None: errors.append('unexpected pip report package '+md.get('name','')); continue
 expected_url='file:///'+str((wh/item['file']).as_posix()).replace(':','%3A',1) if False else None
 # Windows pip serializes local links as file:///D:/..., compare normalized path suffix and exact digest.
 if not url.lower().startswith('file:///d:/temp/iteration41-unified-offline-wheelhouse-settlement-20260927-r1/wheelhouse/'):
  errors.append('noncandidate wheel origin '+str(url))
 if got!=item['sha256']: errors.append('pip report archive hash mismatch '+name)
 if (md.get('version')!=item['version']) or lock.get(name)!=(item['version'],item['sha256']): errors.append('pip report/lock metadata mismatch '+name)
 report_rows.append({'name':md.get('name'),'version':md.get('version'),'url':url,'archive_sha256':got})
if len(report_rows)!=52: errors.append(f'pip install report has {len(report_rows)} install entries, expected 52')
# Exact installed wheel distribution, RECORD and payload audit.
installed_meta={}
for p in site.glob('*.dist-info/METADATA'):
 md=Parser().parsestr(p.read_text(encoding='utf-8',errors='replace'))
 installed_meta[norm(md.get('Name',''))]=(md.get('Version'),p.parent)
if not expected.keys() <= installed_meta.keys(): errors.append('one or more wheelhouse distributions are not installed')
all_record_rows=0; per_distribution=[]; pyd_payload=[]
def install_target(rel):
 for scheme in ('purelib','platlib','scripts','data','headers'):
  marker=f'.data/{scheme}/'
  if marker in rel:
   suffix=rel.split(marker,1)[1]; parts=PurePosixPath(suffix).parts
   if scheme in ('purelib','platlib'): base=site
   elif scheme=='scripts': base=venv/'Scripts'
   elif scheme=='headers': base=venv/'Include'/'site'/'python3.11'
   else: base=venv
   return (base.joinpath(*parts))
 return site.joinpath(*PurePosixPath(rel).parts)
for name,item in sorted(expected.items()):
 dist=installed_meta.get(name)
 if not dist: continue
 if dist[0]!=item['version']: errors.append(f'installed version mismatch {name} {dist[0]} != {item["version"]}')
 wheel=wh/item['file']
 with zipfile.ZipFile(wheel) as z:
  if z.testzip() is not None: errors.append('wheel CRC mismatch '+item['file'])
  meta_name=next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))
  wheel_rows=list(csv.reader(z.read(meta_name.split('/')[0]+'/RECORD').decode('utf-8').splitlines()))
  wmap={row[0]:row for row in wheel_rows}
  inst_record=dist[1]/'RECORD'
  if not inst_record.is_file(): errors.append('installed RECORD missing '+name); continue
  imap_rows=list(csv.reader(inst_record.read_text(encoding='utf-8').splitlines()))
  imap={row[0]:row for row in imap_rows}
  mismatches=[rel for rel,row in wmap.items() if imap.get(rel)!=row]
  if mismatches: errors.append(f'installed RECORD differs from wheel {name}: {mismatches[:3]}')
  extras=set(imap)-set(wmap)
  unexpected=[x for x in extras if not (x.endswith('/INSTALLER') or x.endswith('/REQUESTED') or x.endswith('/direct_url.json') or ('__pycache__/' in x and x.endswith('.pyc')) or (x.startswith('../../Scripts/') and x.endswith('.exe')))]
  if unexpected: errors.append(f'unexpected RECORD rows {name}: {sorted(unexpected)[:4]}')
  valid=0; payload=0
  for row in imap_rows:
   if len(row)<3: errors.append('malformed installed RECORD row '+name); continue
   rel,digest,size=row; target=install_target(rel)
   if not target.is_file(): errors.append(f'missing installed RECORD file {name}:{rel}'); continue
   data=target.read_bytes()
   if size and len(data)!=int(size): errors.append(f'installed RECORD size mismatch {name}:{rel}')
   if digest:
    algo,b64=digest.split('=',1); actual=base64.urlsafe_b64encode(hashlib.new(algo,data).digest()).decode().rstrip('=')
    if actual!=b64: errors.append(f'installed RECORD hash mismatch {name}:{rel}')
   valid+=1
  for rel,row in wmap.items():
   if rel.endswith('/RECORD') or not row[1] or rel not in z.namelist(): continue
   target=install_target(rel)
   if target.is_file():
    payload+=1
    if target.read_bytes()!=z.read(rel): errors.append(f'installed payload != wheel {name}:{rel}')
   if rel.lower().endswith('.pyd'): pyd_payload.append(f'{name}:{rel}')
  all_record_rows+=valid
  direct_path=dist[1]/'direct_url.json'
  direct=json.loads(direct_path.read_text(encoding='utf-8')) if direct_path.is_file() else None
  per_distribution.append({'name':item['name'],'version':dist[0],'wheel':item['file'],'wheel_sha256':item['sha256'],'wheel_record_rows':len(wheel_rows),'installed_record_rows':len(imap_rows),'installed_rows_hash_size_checked':valid,'wheel_payload_members_compared':payload,'extra_record_rows':len(extras),'direct_url':direct})
# PEP 610 roots, exact URL and archive hash.
root_names={'bt-api-base','bt-api-ctp','bt-api-execution','bt-api-py'}
pep610={}
for name in root_names:
 item=expected[name]; dist=installed_meta[name]; p=dist[1]/'direct_url.json'
 if not p.is_file(): errors.append('PEP610 direct_url.json missing '+name); continue
 direct=json.loads(p.read_text(encoding='utf-8')); url=direct.get('url',''); got=(direct.get('archive_info') or {}).get('hashes',{}).get('sha256')
 if not url.lower().startswith('file:///d:/temp/iteration41-unified-offline-wheelhouse-settlement-20260927-r1/wheelhouse/'):
  errors.append('PEP610 URL outside local candidate wheelhouse '+name)
 if got!=item['sha256']: errors.append('PEP610 archive hash mismatch '+name)
 pep610[name]={'url':url,'archive_sha256':got,'expected_sha256':item['sha256']}
# Wheel metadata/lock source availability, extras and no native imports in this audit process.
loaded_ctp=[x for x in sys.modules if x=='bt_api_ctp' or x.startswith('bt_api_ctp.')]
loaded_native=[x for x in sys.modules if x=='_ctp' or x=='bt_api_ctp.ctp._ctp' or x.startswith('bt_api_ctp.ctp._ctp.')]
if loaded_ctp or loaded_native: errors.append(f'CTP/native imported by QA audit process: {loaded_ctp}/{loaded_native}')
check=(qa/'logs'/'pip-check.log').read_text(encoding='utf-8').strip()
if check!='No broken requirements found.': errors.append('pip check not clean: '+check)
result={'schema':'iteration41.unified_offline_wheelhouse_settlement.install_qa.r1.v1','python':sys.version,'venv_path':str(venv),'isolated_no_system_site_packages':('include-system-site-packages = false' in (venv/'pyvenv.cfg').read_text(encoding='utf-8')),'pip_install_entries':len(report_rows),'expected_wheels':len(expected),'installed_distribution_count':len(per_distribution),'record_rows_checked':all_record_rows,'pep610_root_artifacts':pep610,'pip_check':check,'opaque_pyd_payloads_present_but_not_loaded':pyd_payload,'loaded_ctp_modules':loaded_ctp,'loaded_native_modules':loaded_native,'errors':errors,'distributions':per_distribution}
(qa/'evidence'/'install-record-origin-audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='distributions'},indent=2))
if errors: raise SystemExit(1)

