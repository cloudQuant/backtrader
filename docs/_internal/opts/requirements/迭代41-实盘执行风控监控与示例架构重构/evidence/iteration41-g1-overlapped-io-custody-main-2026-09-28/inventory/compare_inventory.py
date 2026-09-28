from pathlib import Path
import hashlib
import json

repo = Path(r"D:\source_code\backtrader")
archive = Path(r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-g1-overlapped-io-custody-main-2026-09-28")
relative_inventory = Path("docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/live-execution-inventory-candidates.json")
baseline_path = repo / relative_inventory
fresh_path = archive / "inventory/fresh-collection.json"
source_path = repo / "scripts/ctp_i13_i15_worker_output_channel.py"
test_path = repo / "tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py"

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

baseline = load(baseline_path)
fresh = load(fresh_path)
writer_same = baseline["writer_candidates"] == fresh["writer_candidates"]
dynamic_same = baseline["dynamic_execution_candidates"] == fresh["dynamic_execution_candidates"]
changed_script_rows = [
    row
    for category in ("writer_candidates", "dynamic_execution_candidates")
    for row in fresh[category]
    if row["path"] == "scripts/ctp_i13_i15_worker_output_channel.py"
]
result = {
    "status": "NO_CHANGE" if writer_same and dynamic_same else "DIFF",
    "boundary": "STATIC_INVENTORY_ONLY_NOT_WRITER_CLOSURE_OR_ROUTE_AUTHORITY",
    "baseline_inventory": {
        "path_from_repo_root": str(relative_inventory).replace("\\", "/"),
        "sha256": sha(baseline_path),
    },
    "fresh_collection": {
        "path": "inventory/fresh-collection.json",
        "sha256": sha(fresh_path),
        "counts": fresh["counts"],
        "status": fresh.get("status"),
        "source_path_coverage_status": fresh.get("source_path_coverage", {}).get("status"),
    },
    "comparison": {
        "writer_rows_exact_and_ordered": writer_same,
        "dynamic_rows_exact_and_ordered": dynamic_same,
        "counts_equal": baseline["counts"] == fresh["counts"],
        "writer_rows_added_removed_moved": 0 if writer_same else None,
        "dynamic_rows_added_removed_moved": 0 if dynamic_same else None,
        "changed_channel_script_candidate_rows": changed_script_rows,
    },
    "source_hashes": {
        "channel_source_sha256": sha(source_path),
        "channel_test_sha256": sha(test_path),
    },
}
output = archive / "inventory/no-change-result.json"
output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps(result, indent=2))
if result["status"] != "NO_CHANGE" or not result["comparison"]["counts_equal"]:
    raise SystemExit(2)