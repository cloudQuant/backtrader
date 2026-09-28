from __future__ import annotations
import hashlib, json
from pathlib import Path
root=Path(r'D:\temp\iteration41-g5-order-authority-independent-qa-20260927')
items=[]
for p in sorted((root/'evidence').rglob('*')):
    if p.is_file(): items.append(p)
for rel in ['README.md','frozen-input-manifest.json','final-output-manifest.json','verify_frozen.py','qa_main_input_compare.py','qa_multiprocess.py','qa_worker_action_identity.py','qa_author_archive_verify.py','qa-receipt.md','make_qa_manifest.py','verify_qa_manifest.py']:
    p=root/rel
    if p.is_file(): items.append(p)
# De-duplicate and keep paths relative to the independent QA root.
unique=sorted(set(items),key=lambda p:p.as_posix().lower())
entries=[]
for p in unique:
    entries.append({'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest().upper()})
data={'schema':'iteration41-g5-independent-qa-manifest.v1','candidate_root':r'D:\temp\iteration41-g5-order-authority-20260927-candidate','candidate_frozen_input_manifest_sha256':'79BAB5C0C0E136B722EF5F55C74F93ABA2920F138A629B9AB8B4506D29003827','candidate_output_manifest_sha256':'6DB92F8FD9700EF9BC903C41FCAD0C34BD3012830370B37AFA50E37FAB11450F','independent_qa_root':str(root),'files':entries}
out=root/'qa-manifest.json'; out.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8')
digest=hashlib.sha256(out.read_bytes()).hexdigest().upper()
(root/'qa-manifest.sha256').write_text(f'{digest}  qa-manifest.json\n',encoding='ascii')
print(json.dumps({'manifest':str(out),'manifest_sha256':digest,'files':len(entries)},indent=2))


