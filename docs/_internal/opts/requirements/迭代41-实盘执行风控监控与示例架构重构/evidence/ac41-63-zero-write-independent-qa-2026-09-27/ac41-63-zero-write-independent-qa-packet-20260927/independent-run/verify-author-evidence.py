import hashlib,json,pathlib,sys,zipfile
root=pathlib.Path(sys.argv[1]); m=json.loads((root/'manifest.json').read_text(encoding='utf-8')); bad=[]
for e in m['evidence_file_hashes']:
 p=root/e['path']; b=p.read_bytes()
 if len(b)!=e['bytes'] or hashlib.sha256(b).hexdigest()!=e['sha256']: bad.append(e['path'])
with zipfile.ZipFile(root/'evidence.zip') as z:
 zipbad=z.testzip(); names=z.namelist(); matches=[]
 for e in m['evidence_file_hashes']:
  possible=[e['path'],'evidence/'+e['path']]
  name=next((n for n in possible if n in names),None)
  matches.append({'path':e['path'],'member':name,'matches':name is not None and z.read(name)==(root/e['path']).read_bytes()})
result={'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),'manifest_companion':(root/'manifest.sha256').read_text().strip(),'evidence_zip_sha256':hashlib.sha256((root/'evidence.zip').read_bytes()).hexdigest(),'manifest_evidence_files':len(m['evidence_file_hashes']),'folder_file_mismatches':bad,'zip_entries':len(names),'zip_test':zipbad,'zip_members_match':all(x['matches'] for x in matches),'zip_member_mapping':matches,'candidate_source_rev':m['source_revision'],'runtime_files':len(m['loaded_runtime_source_hashes']),'candidate_inputs':len(m['candidate_and_test_inputs'])}
print(json.dumps(result,indent=2))
if bad or zipbad is not None or not result['zip_members_match']: raise SystemExit(1)