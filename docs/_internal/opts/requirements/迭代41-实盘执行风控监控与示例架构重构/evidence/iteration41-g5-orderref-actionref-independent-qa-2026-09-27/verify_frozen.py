from __future__ import annotations
import hashlib, json
from pathlib import Path
candidate=Path(r"D:\temp\iteration41-g5-order-authority-20260927-candidate")
qa=Path(r"D:\temp\iteration41-g5-order-authority-independent-qa-20260927")
expected_frozen="79bab5c0c0e136b722ef5f55c74f93aba2920f138a629b9ab8b4506d29003827"

def sha(p: Path) -> str: return hashlib.sha256(p.read_bytes()).hexdigest().lower()
fm=candidate/"frozen-input-manifest.json"
om=candidate/"evidence/final-output-manifest.json"
assert sha(fm)==expected_frozen, sha(fm)
inputs=json.loads(fm.read_text(encoding="utf-8"))
bad_inputs=[]
for item in inputs:
 p=candidate/Path(item["path"])
 if not p.is_file() or p.stat().st_size!=item["bytes"] or sha(p)!=item["sha256"].lower():
  bad_inputs.append(item["path"])
assert not bad_inputs, bad_inputs
out=json.loads(om.read_text(encoding="utf-8"))
assert out["frozen_input_manifest_sha256"].lower()==expected_frozen
bad_outputs=[]
for item in out["outputs"]:
 p=candidate/Path(item["path"])
 if not p.is_file() or p.stat().st_size!=item["bytes"] or sha(p)!=item["sha256"].lower():
  bad_outputs.append(item["path"])
assert not bad_outputs, bad_outputs
# Check isolated QA execution source/test files match the frozen candidate.
qa_paths=[
 ("implementation/sdk/src/bt_api_execution", "candidate/src/bt_api_execution"),
 ("implementation/backtrader_bridge", "candidate/backtrader_bridge"),
 ("implementation/tests", "candidate/tests"),
 ("implementation/main_repo_patch", "candidate/main_repo_patch"),
]
copy_mismatches=[]
for src_rel,dst_rel in qa_paths:
 src=candidate/src_rel; dst=qa/dst_rel
 for p in src.rglob("*"):
  if p.is_file():
   q=dst/p.relative_to(src)
   if not q.is_file() or sha(p)!=sha(q): copy_mismatches.append(str(q))
assert not copy_mismatches, copy_mismatches
print(json.dumps({
 "frozen_input_manifest_sha256":sha(fm).upper(),
 "frozen_inputs_verified":len(inputs),
 "output_manifest_sha256":sha(om).upper(),
 "output_entries_verified":len(out["outputs"]),
 "isolated_candidate_copy_files_verified":sum(1 for a,b in qa_paths for p in (candidate/a).rglob("*") if p.is_file()),
 "bad_inputs":len(bad_inputs),"bad_outputs":len(bad_outputs),"copy_mismatches":len(copy_mismatches),
},indent=2))
