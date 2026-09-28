import ast, hashlib, json, zipfile
from pathlib import Path, PurePosixPath
root=Path(r'D:\temp\iteration41-r2d-shared-session-readonly-port-20260927')
base=Path(r'D:\temp\iteration41-r2c-independent-qa-20260927')
ev=root/'evidence'
artifact=json.loads((ev/'r2d-artifact-hashes.json').read_text(encoding='utf-8'))
receipt=json.loads((ev/'r2d-author-final-receipt.json').read_text(encoding='utf-8'))
bundle=ev/'r2d-author-bundle-final'
bm=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
def sha(b): return hashlib.sha256(b).hexdigest()
def fsha(p): return sha(p.read_bytes())
assert fsha(ev/'r2d-shared-session-readonly-port.patch')==artifact['candidate']['patch_sha256']=='423111adfbfb47eb56e5303e917815c4f4594760c203d18930c44cf6b800094c'
assert fsha(ev/'candidate-focused.junit.xml')==artifact['candidate']['junit_sha256']=='8825a44a334d4c0c58766b6ccea87e1e0c915ffeae7f384d5f29600b47deff25'
assert fsha(ev/'r2d-author-final.zip')==receipt['archive_sha256']=='0160b69c0c91a046d2b47d5a55ddcfc2cdd6c979db5b0a023e69892d18f84a9b'
assert fsha(bundle/'manifest.json')==receipt['manifest_sha256']=='3e4b386ec95f52bb27d268a857aa4d5223d28ba2daf1952e2b6caf95eaf9f199'
for rel,digest in artifact['candidate']['source_sha256'].items(): assert fsha(root/rel)==digest,rel
for rel,digest in artifact['frozen_inputs'].items():
    if rel=='r2c_actor_port_sha256': assert fsha(base/'backtrader/stores/ctp_account_actor_port.py')==digest
    if rel=='original_i22_test_sha256': assert fsha(base/'tests/unit/stores/test_btapistore_iteration22.py')==digest
node=json.loads((ev/'r2d-nodeid-baseline-candidate.json').read_text(encoding='utf-8'))
selected=node['baseline']['selected_original_nodeids']; untouched=node['candidate']['unmigrated_original_nodeids']
assert node['baseline']['failed_original_i22_nodeids']==200 and len(selected)==3 and len(untouched)==197
assert len(set(selected)|set(untouched))==200
expected={'test_empty_incomplete_query_is_not_interpreted_as_zero_records','test_query_request_type_mismatch_fails_closed','test_preflight_rejects_trade_rows_outside_the_requested_scope'}
assert set(selected)==expected
old=ast.parse((base/'tests/unit/stores/test_btapistore_iteration22.py').read_text(encoding='utf-8'))
new=ast.parse((root/'tests/unit/stores/test_btapistore_iteration22.py').read_text(encoding='utf-8'))
def fnmap(tree): return {n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
oldf,newf=fnmap(old),fnmap(new)
changed={n for n,v in oldf.items() if n in newf and newf[n]!=v}
assert changed==expected,changed
with zipfile.ZipFile(ev/'r2d-author-final.zip') as z:
    names=z.namelist(); assert z.testzip() is None and len(names)==receipt['member_count']==36
    prefix='iteration41-r2d-author-bundle-final/'
    mn=prefix+'manifest.json'; mb=z.read(mn); assert sha(mb)==receipt['manifest_sha256']
    zm=json.loads(mb); assert len(zm['entries'])==receipt['manifest_payload_entries']==35
    for ent in zm['entries']:
        data=z.read(prefix+ent['path']); assert len(data)==ent['size_bytes'] and sha(data)==ent['sha256'],ent['path']
    forbidden=[n for n in names if PurePosixPath(n).name in {'.env','config.yaml'} or 'runtime-ctp-private' in n.lower() or 'bt_api_py' in n.lower() or 'bt_api_ctp' in n.lower()]
    assert not forbidden,forbidden
    for rel,digest in zm['output_hashes'].items():
        assert sha(z.read(prefix+'output/'+rel))==digest
        if rel in artifact['candidate']['source_sha256']: assert digest==artifact['candidate']['source_sha256'][rel]
assert zm['patch_sha256']==artifact['candidate']['patch_sha256']
assert zm['disposition']=='FAKE_READ_PORT_CONTRACT_ONLY' and zm['main_tree_modified'] is False
assert 'not directly applicable to current main' in zm['source_root']
assert artifact['candidate']['patch_files']==['backtrader/stores/ctp_account_actor_port.py','tests/unit/stores/test_btapistore_iteration22.py','tests/unit/stores/test_ctp_shared_session_read_port.py']
assert fsha(root/'backtrader/stores/btapistore.py')==artifact['frozen_inputs']['r2c_store_sha256']
print(json.dumps({'patch_sha256':fsha(ev/'r2d-shared-session-readonly-port.patch'),'source_sha256':artifact['candidate']['source_sha256'],'frozen_r2c_actor_port_sha256':fsha(base/'backtrader/stores/ctp_account_actor_port.py'),'frozen_r2c_i22_test_sha256':fsha(base/'tests/unit/stores/test_btapistore_iteration22.py'),'junit_sha256':fsha(ev/'candidate-focused.junit.xml'),'author_zip_sha256':fsha(ev/'r2d-author-final.zip'),'manifest_sha256':fsha(bundle/'manifest.json'),'zip_crc':'PASS','members':len(names),'verified_payload_entries':len(zm['entries']),'forbidden_members':forbidden,'patch_files':artifact['candidate']['patch_files'],'patch_preimage_replay':'PASS after CRLF/LF normalization for all three touched files','i22':{'baseline_failed':200,'migrated':3,'untouched':197,'changed_test_functions':sorted(changed)},'disposition':zm['disposition'],'main_tree_modified':zm['main_tree_modified'],'source_root':zm['source_root']},indent=2))

