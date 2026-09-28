from __future__ import annotations
import hashlib,json,pathlib,re,zipfile
ZIP=pathlib.Path(r"D:\temp\ac41-63-writer-slice3-20260927-r2.zip")
EXPECTED="4d90d2e1abda09c44dfeb4845526b7a07b12d617bab9952de60d360832b37000"
MAIN=pathlib.Path(r"D:\source_code\backtrader")
SDK=pathlib.Path(r"D:\bt_api_py\bt_api\bt_api_ctp")
SDK_EXTRACT_ROOT=pathlib.Path(r"D:\bt_api_py")
OUT=pathlib.Path(r"D:\temp\ac41-63-writer-slice3-r2-independent-qa-20260927\verification.json")
def sha(b): return hashlib.sha256(b).hexdigest()
assert sha(ZIP.read_bytes())==EXPECTED
with zipfile.ZipFile(ZIP) as z:
    assert z.testzip() is None
    names=set(z.namelist()); manifest=json.loads(z.read("FREEZE-MANIFEST.json"))
    rows=manifest["files"]
    assert len(rows)==manifest["file_count_excluding_manifest"]==10
    assert names=={r["path"] for r in rows}|{"FREEZE-MANIFEST.json"}
    for r in rows:
        b=z.read(r["path"]); assert len(b)==r["bytes"] and sha(b).lower()==r["sha256"].lower(),r["path"]
    read=lambda n:z.read(n).decode("utf-8-sig")
    selected=json.loads(read("selected-candidates.json"))
    ledger=json.loads(read("coverage-ledger.json"))
    predecessor=json.loads(read("inputs/predecessor-slice2-selected-candidates.json"))
    inventory=json.loads(read("inputs/live-execution-inventory-candidates.json"))
    dispositions=json.loads(read("inputs/live-execution-writer-dispositions.json"))
    frozen=json.loads(read("inputs/frozen-source-manifest.json"))
    source_hashes=json.loads(read("source-hashes.json"))
    report=read("REPORT.md")
    main_extracts=read("source-extracts.txt")
    sdk_extracts=read("sdk-source-extracts.txt")

new=[x["candidate_id"] for x in selected["new_slice"]]
prior=selected["prior_reviewed_ids"]
prev2=predecessor["prior_reviewed_ids"]+[x["candidate_id"] for x in predecessor["new_slice"]]
assert len(new)==len(set(new))==21
assert len(prior)==len(set(prior))==22
assert len(prev2)==len(set(prev2))==22 and set(prior)==set(prev2)
assert not set(new)&set(prior)
all_ids={x["candidate_id"] for x in dispositions["entries"]}
assert len(all_ids)==389 and set(new)<=all_ids and set(prior)<=all_ids
identity_fields=("path","line","column","call","class_name","function_name","method","kind")
inventory_keys={tuple(x.get(k) for k in identity_fields) for x in inventory["writer_candidates"]+inventory["dynamic_execution_candidates"]}
assert all(tuple(x["source_candidate"].get(k) for k in identity_fields) in inventory_keys for x in selected["new_slice"])
assert len(inventory["writer_candidates"])==327 and len(inventory["dynamic_execution_candidates"])==62
assert (22,21,43,346)==(selected["prior_reviewed_count"],selected["new_slice_count"],selected["cumulative_examined_count_after_three_slices"],selected["unexamined_count_after_three_slices"])
assert 389-22-21==346
assert (22,21,43,346)==(ledger["previously_examined"],ledger["this_slice"],ledger["cumulative_examined"],ledger["residual_unexamined"])
assert ledger["inventory_candidates"]==389 and ledger["ids_do_not_overlap_previous_22"] is True
assert ledger["ids_all_exist_and_remain_review_required"] is True
assert selected["official_inventory_status"]=="NOT_CLOSED_STATIC_REVIEW_REQUIRED"
assert selected["all_inventory_dispositions_remain_review_required"] is True
assert dispositions["closure_status"]=="NOT_CLOSED_STATIC_REVIEW_REQUIRED"
assert dispositions["status"]=="REVIEW_REQUIRED" and len(dispositions["entries"])==389
entry_by_id={r["candidate_id"]:r for r in dispositions["entries"]}
assert all(r["disposition"]=="REVIEW_REQUIRED" and r["availability"]=="NOT_AVAILABLE" for r in dispositions["entries"])
assert all(entry_by_id[i]["disposition"]=="REVIEW_REQUIRED" and entry_by_id[i]["availability"]=="NOT_AVAILABLE" for i in new)
for row in selected["new_slice"]:
    c=row["source_candidate"]; p=MAIN/pathlib.Path(c["path"]); data=p.read_bytes(); lines=data.decode("utf-8").splitlines()
    assert 1<=c["line"]<=len(lines),c
    line=lines[c["line"]-1]
    assert line[c["column"]:].startswith(c["call"]),(c,line)

frozen_by_path={r["path"]:r for r in frozen["files"]}
actual_source_results={}; historical_mismatches=[]
for rel,row in source_hashes["selected_source_files"].items():
    data=(MAIN/pathlib.Path(rel)).read_bytes()
    actual=sha(data).upper()
    assert actual==row["sha256"].upper() and len(data)==row["bytes"],rel
    frozen_row=frozen_by_path.get(rel)
    assert frozen_row is not None,rel
    if frozen_row["sha256"].upper()!=actual:
        historical_mismatches.append({"path":rel,"frozen_manifest_sha256":frozen_row["sha256"],"current_sha256":actual})
        assert rel=="backtrader/stores/btapistore.py"
        assert frozen_row["sha256"].upper()==row["manifest_sha256"].upper()
    actual_source_results[rel]=actual
assert len(actual_source_results)==21 and len(historical_mismatches)==1
assert source_hashes["main_store_sha256_current"].upper()==actual_source_results["backtrader/stores/btapistore.py"]
assert source_hashes["main_simulation_execution_sha256_current"].upper()==actual_source_results["backtrader_runtime/ctp_simulation_execution.py"]

sdk_results={}
for rel,row in source_hashes["read_only_sdk"]["source_files"].items():
    data=(SDK/pathlib.Path(rel)).read_bytes(); actual=sha(data).upper()
    assert actual==row["sha256"].upper() and len(data)==row["bytes"],rel
    sdk_results[rel]=actual

def verify_extracts(txt, root, strip_prefix=""):
    lines=txt.splitlines(); verified=[]; i=0
    for i,line in enumerate(lines):
        m=re.match(r"^### (.+?):(\d+)-(\d+)(?:\s|$)",line)
        if not m: continue
        rel,lo,hi=m.group(1),int(m.group(2)),int(m.group(3))
        if strip_prefix and rel.startswith(strip_prefix): rel=rel[len(strip_prefix):]
        source=(root/pathlib.Path(rel)).read_text(encoding="utf-8").splitlines()
        body=[]; j=i+1
        while j<len(lines) and not lines[j].startswith("### "):
            q=re.match(r"^(\d+): (.*)$",lines[j])
            if q: body.append((int(q.group(1)),q.group(2)))
            j+=1
        expected=list(range(lo,hi+1)); got=[n for n,_ in body]
        assert got==expected,(m.group(1),lo,hi,len(body),got[:3],got[-3:])
        for n,text in body: assert source[n-1]==text,(m.group(1),n,source[n-1],text)
        verified.append(m.group(1))
    return verified
main_blocks=verify_extracts(main_extracts,MAIN)
sdk_blocks=verify_extracts(sdk_extracts,SDK_EXTRACT_ROOT)
assert len(main_blocks)>0 and len(sdk_blocks)>0

required_report=["Decision: NO_WRITE / LIVE_NO_GO","REVIEW_REQUIRED / NOT_AVAILABLE","dirty working tree","not a released artifact","no account, config, provider, native SDK, or network was accessed","does not close the public direct arm route"]
assert all(s.lower() in report.lower() for s in required_report)
assert "real order was accepted" not in report.lower()
assert "route is closed" not in report.lower()
assert "NO_WRITE / LIVE_NO_GO" in report
result={"verdict":"PASS_STATIC_QA_SCOPE_ONLY","zip_sha256":EXPECTED,"zip_crc":"clean","zip_members":11,"manifest_payloads_verified":10,"new_ids":21,"prior_ids":22,"overlap":0,"cumulative":43,"residual":346,"inventory_ids":389,"all_official_dispositions":"REVIEW_REQUIRED / NOT_AVAILABLE","main_selected_source_hashes_verified":len(actual_source_results),"historical_manifest_mismatches":historical_mismatches,"sdk_working_source_hashes_verified":sdk_results,"main_extract_blocks_verified":len(main_blocks),"sdk_extract_blocks_verified":len(sdk_blocks),"candidate_locations_verified":len(new),"static_only_no_import_test_network_credentials_account":True,"decision":"NO_WRITE / LIVE_NO_GO retained"}
OUT.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
print(json.dumps(result,sort_keys=True))
