import hashlib, json, pathlib
snap=pathlib.Path(r'D:\temp\iteration41-store-account-actor-r2d-20260927\freeze-r2d-20260927')
qa=pathlib.Path(r'D:\temp\iteration41-store-account-actor-r2d-independent-qa-20260927')
m=json.loads((snap/'manifest.json').read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
rows=[]
for row in m['files']:
    if row['path'].startswith(('baseline/','candidate/','guard/')):
        p=qa/row['path']
        if not p.is_file(): raise SystemExit('COPY_MISSING '+row['path'])
        if p.stat().st_size != row['size'] or sha(p) != row['sha256']:
            raise SystemExit('COPY_HASH_MISMATCH '+row['path'])
        rows.append(row['path'])
sel=['tests/unit/stores/test_btapistore.py','tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py']
for rel in sel:
    bp=qa/'baseline'/rel; cp=qa/'candidate'/rel
    if bp.read_bytes()!=cp.read_bytes(): raise SystemExit('SELECTED_TESTS_DIFFER '+rel)
print('copied_tree_payloads_verified='+str(len(rows)))
print('selected_test_files_byte_identical=2/2')
