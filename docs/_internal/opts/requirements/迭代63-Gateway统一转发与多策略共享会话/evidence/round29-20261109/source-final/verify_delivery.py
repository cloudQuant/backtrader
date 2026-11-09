import hashlib,json,subprocess,sys,zipfile
from pathlib import Path
S=Path('/Users/yunjinqi/Documents/new_projects/bt_api_py');T=Path('/tmp/iter63-r29-primary-v2');I=Path('/tmp/iter63-r29-sdk-install-20261109-pht8FUZ4')
sha=lambda b:hashlib.sha256(b).hexdigest()
mode=sys.argv[1]; assert mode in ('before-commit','committed')
head=subprocess.check_output(['git','-C',str(S),'rev-parse','HEAD'],text=True).strip()
plan=json.loads((T/'selectors.json').read_text()); assert len(plan['sdk'])==14 and plan==json.loads((I/'selectors.json').read_text())
frozen=json.loads((T/'sdk-frozen-inputs.json').read_text());assert len(frozen)==17
for row in frozen:assert sha((S/row['path']).read_bytes())==row['sha256'],row
allrows={}; counts={}
for name in ('source-manifest.json','test-manifest.json'):
 rows=json.loads((I/name).read_text());counts[name]=len(rows)
 for r in rows:
  for k in ('source','copy','original'):
   if k in r:assert sha(Path(r[k]).read_bytes())==r['sha256'],(name,k,r)
  original=Path(r.get('original',r['source'])).resolve()
  assert original.is_relative_to(S),str(original)
  assert original not in allrows or allrows[original]==r['sha256']
  allrows[original]=r['sha256']
  if mode=='committed':
   repository=Path(r['repo']);rel=original.relative_to(repository).as_posix()
   data=subprocess.check_output(['git','-C',str(repository),'show','HEAD:'+rel])
   assert sha(data)==r['sha256'],('git mismatch',str(repository),rel)
wheel,=(I/'wheels').glob('bt_api_py-*.whl')
with zipfile.ZipFile(wheel) as z:
 actual={n for n in z.namelist() if n.startswith('bt_api_py/') and not n.endswith('/')}
 expected={r['relative'] for r in json.loads((I/'source-manifest.json').read_text()) if r['relative'].startswith('bt_api_py/')}
 assert actual==expected,(actual-expected,expected-actual)
 for n in sorted(actual):
  payload=z.read(n)
  for p in (S/n,I/'source/sdk'/n,I/'install/src'/n):assert p.read_bytes()==payload,(n,str(p))
 metadata,=[n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
 assert (S/'README.md').read_bytes() in z.read(metadata)
for r in json.loads((I/'fixed-wheels.json').read_text()):
 for p in (Path(r['source']),I/'wheels'/r['filename']):assert sha(p.read_bytes())==r['sha256']
run=json.loads((T/'launcher-executions.jsonl').read_text().splitlines()[-1]);assert run['exit_code']==0
sourceaudit=subprocess.check_output([sys.executable,str(T/'audit_run.py'),run['run_id']],text=True)
(T/'sdk-origin-audit.json').write_text(sourceaudit)
sourceaudit=json.loads(sourceaudit);installaudit=json.loads((I/'sdk-origin-audit.json').read_text())
assert sourceaudit['files']==installaudit['files']==7
assert sourceaudit['missing_exit_audits']==installaudit['missing_exit_audits']==0
for p in (T/'sdk-source.log',I/'sdk-installed-v2.log'):assert '297 passed' in p.read_text() and 'RUN_EXIT 0' in p.read_text()
record={'mode':mode,'sdk_head':head,'selectors':14,'frozen_inputs':17,'manifest_rows':counts,'unique_paths':len(allrows),'sdk_payload_members':len(actual),'readme_raw_bytes_match':True,'sdk_wheel':str(wheel),'sdk_wheel_sha256':sha(wheel.read_bytes()),'source_recorded_processes':sourceaudit['files'],'install_recorded_processes':installaudit['files'],'missing_exit_audits':0,'all_bytes_verified':True,'git_verified':mode=='committed'}
(T/('primary-delivery-'+mode+'.json')).write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2))
