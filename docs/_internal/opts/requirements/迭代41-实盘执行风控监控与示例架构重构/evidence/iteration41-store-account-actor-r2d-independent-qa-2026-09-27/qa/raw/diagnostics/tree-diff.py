import hashlib, json, pathlib
root=pathlib.Path(r'D:\temp\iteration41-store-account-actor-r2d-independent-qa-20260927')
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def files(tree): return {p.relative_to(tree).as_posix():p for p in tree.rglob('*') if p.is_file() and not any(x in {'.ruff_cache','__pycache__','.pytest_cache'} for x in p.parts)}
b=files(root/'baseline'); c=files(root/'candidate')
keys=sorted(set(b)|set(c)); diffs=[]
for k in keys:
    if k not in b or k not in c: diffs.append({'path':k,'kind':'missing','baseline':k in b,'candidate':k in c})
    elif digest(b[k])!=digest(c[k]): diffs.append({'path':k,'kind':'content','baseline_sha256':digest(b[k]),'candidate_sha256':digest(c[k])})
print(json.dumps({'baseline_files':len(b),'candidate_files':len(c),'difference_count':len(diffs),'differences':diffs[:20]},sort_keys=True,indent=2))
