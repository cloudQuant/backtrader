import hashlib, json, pathlib, zipfile
root=pathlib.Path(r'D:\temp\iteration41-store-account-actor-r2d-20260927\freeze-r2d-20260927')
manifest_path=root/'manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
results=[]
for row in manifest['files']:
    p=root/row['path']
    if not p.is_file(): raise SystemExit('MISSING '+row['path'])
    got=sha(p)
    size=p.stat().st_size
    if got != row['sha256'] or size != row['size']:
        raise SystemExit(f'MISMATCH {row["path"]} hash={got} size={size}')
    results.append((row['path'],got,size))
index=root/manifest['payload_index']['path']
if sha(index) != manifest['payload_index']['sha256']: raise SystemExit('PAYLOAD_INDEX_HASH_MISMATCH')
idx=[]
for line in index.read_text(encoding='utf-8').splitlines():
    if not line.strip(): continue
    digest, rel=line.split(None,1)
    idx.append((rel.strip(),digest.lower()))
expected={(r['path'],r['sha256']) for r in manifest['files']}
if set(idx) != expected: raise SystemExit(f'INDEX_MEMBERSHIP_MISMATCH index={len(idx)} manifest={len(expected)}')
zip_path=root.parent/'iteration41-store-account-actor-r2d-20260927.zip'
with zipfile.ZipFile(zip_path) as z:
    names=z.namelist(); bad=z.testzip()
    if bad: raise SystemExit('ZIP_CRC_FAILURE '+bad)
    zmembers=set(names)
    missing=[]
    for rel,_ in expected:
        if rel not in zmembers and not any(n.endswith('/'+rel) for n in names): missing.append(rel)
    if missing: raise SystemExit('ZIP_MISSING '+repr(missing[:10]))
print(json.dumps({'manifest_sha256':sha(manifest_path),'payload_index_sha256':sha(index),'manifest_files_verified':len(results),'index_entries':len(idx),'zip_sha256':sha(zip_path),'zip_member_count':len(names),'zip_crc':'clean','patch_sha256':sha(root/'patch/r2d.patch'),'preimage_sha256':sha(root/'preimage/btapistore.py'),'candidate_source_sha256':sha(root/'source/btapistore.py'),'zip_missing_manifest_payloads':0},sort_keys=True,indent=2))
