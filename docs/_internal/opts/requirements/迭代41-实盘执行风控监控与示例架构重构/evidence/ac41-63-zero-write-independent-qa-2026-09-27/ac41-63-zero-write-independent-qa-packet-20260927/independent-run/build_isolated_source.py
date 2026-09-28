import hashlib,json,pathlib,sys
source=pathlib.Path(sys.argv[1]); dest=pathlib.Path(sys.argv[2]); evidence=source/'docs'/'_internal'/'opts'/'requirements'/'迭代41-实盘执行风控监控与示例架构重构'/'evidence'/'ac41-63-zero-write-runtime-trace-2026-09-27'
manifest=json.loads((evidence/'manifest.json').read_text(encoding='utf-8'))
expected={}
for e in manifest['candidate_and_test_inputs']:
    if e.get('sha256') and not e['path'].endswith('/'): expected[e['path']]=e['sha256']
for e in manifest['loaded_runtime_source_hashes']: expected[e['path']]=e['sha256']
for e in manifest['changed_files']:
    if e.get('sha256') and len(e['sha256'])==64: expected[e['path']]=e['sha256']
paths=set(expected)
for folder in ('backtrader','backtrader_runtime'):
    for p in (source/folder).rglob('*.py'):
        if '__pycache__' not in p.parts: paths.add(p.relative_to(source).as_posix())
paths.add('pytest.ini')
paths={rel for rel in paths if source.joinpath(*rel.split('/')).is_file()}
fail=[]; entries=[]
for rel in sorted(paths):
    src=source.joinpath(*rel.split('/')); raw=src.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
    if rel in expected and digest!=expected[rel]: fail.append({'path':rel,'error':'source_hash_mismatch','expected':expected[rel],'actual':digest}); continue
    out=dest.joinpath(*rel.split('/')); out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(raw)
    out_hash=hashlib.sha256(out.read_bytes()).hexdigest()
    if out_hash!=digest: fail.append({'path':rel,'error':'copy_hash_mismatch'}); continue
    entries.append({'path':rel,'size_bytes':len(raw),'sha256':digest,'expected_from_author_manifest':expected.get(rel)})
if fail:
    print(json.dumps({'copy_failures':fail},indent=2)); raise SystemExit(1)
(dest/'isolated-source-manifest.json').write_text(json.dumps({'schema':'ac41-63.isolated_source_copy.v1','author_source_revision':manifest['source_revision'],'copied_file_count':len(entries),'files':entries},indent=2)+'\n',encoding='utf-8')
print(json.dumps({'copied_file_count':len(entries),'manifest_input_count':len(expected),'loaded_runtime_file_count':len(manifest['loaded_runtime_source_hashes']),'pytest_ini_sha256':hashlib.sha256((dest/'pytest.ini').read_bytes()).hexdigest(),'source_revision':manifest['source_revision'],'unread_private_config':True},sort_keys=True))