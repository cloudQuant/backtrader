import hashlib, json, pathlib, sys, zipfile
root=pathlib.Path(sys.argv[1]); manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8')); zip_path=root/'evidence.zip'
checks=[]
for item in manifest['files']:
    rel=item['path'].replace('\\','/'); p=root.joinpath(*rel.split('/')); b=p.read_bytes()
    checks.append({'path':rel,'size_ok':len(b)==item['size_bytes'],'sha256_ok':hashlib.sha256(b).hexdigest()==item['sha256']})
with zipfile.ZipFile(zip_path) as z:
    bad=z.testzip(); names=sorted(z.namelist()); zip_checks=[]
    for name in names:
        expected=root.joinpath(*name.split('/'))
        actual=z.read(name)
        zip_checks.append({'path':name,'matches_frozen_file':expected.is_file() and actual==expected.read_bytes()})
result={'manifest_entries':len(checks),'manifest_payload_ok':all(x['size_ok'] and x['sha256_ok'] for x in checks),'zip_entries':len(names),'zip_test':bad,'zip_members_match_frozen_copy':all(x['matches_frozen_file'] for x in zip_checks),'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),'evidence_zip_sha256':hashlib.sha256(zip_path.read_bytes()).hexdigest(),'manifest_checks':checks,'zip_member_checks':zip_checks}
(root.parent/'frozen-zip-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('manifest_checks','zip_member_checks')},sort_keys=True))
if not(result['manifest_payload_ok'] and result['zip_test'] is None and result['zip_members_match_frozen_copy']): raise SystemExit(1)