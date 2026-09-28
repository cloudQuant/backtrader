from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOTS = {
    "proof_readme": Path(r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-g5-dual-actionref-collision-proof-2026-09-27\README.md"),
    "proof_script": Path(r"D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-g5-dual-actionref-collision-proof-2026-09-27\author\repro_actionref_collision.py"),
    "g5_authority": Path(r"D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py"),
    "g5_store": Path(r"D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\store.py"),
    "g5_worker": Path(r"D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\ctp_single_worker_candidate.py"),
    "g5_bridge": Path(r"D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\backtrader_bridge\ctp_order_action_bridge.py"),
    "g5_main_builder": Path(r"D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\main_repo_patch\backtrader\stores\ctp_i9_parent_request_builder.py"),
    "v21_store": Path(r"D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927\src\bt_api_execution\store.py"),
    "v21_worker": Path(r"D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927\src\bt_api_execution\ctp_single_worker_candidate.py"),
}
EXPECTED = {
    "proof_readme": "D83F57F483FF401AFD8DB17B8F2EE6C86A4BCBC24C8D4E20D4512ED610E5AEA5",
    "proof_script": "23033D685FF63B4D28F9FA9E3C306F9018B7424A0299F9F7EE7E7F9714315659",
    "g5_authority": "8E7ABDD2819F66B6EC3D5FF1D5A049FCBB91AE8E71327665EE925098D35F647D",
    "g5_store": "1DE4E83B9163B941E941E4ADB71B1C8D2DB5A92740D79B55B77AE5B7DD1B4BC4",
    "g5_worker": "5BFB2A6A12C5D7ECFBB589EC3FF9AF61CC7EC14AC9B5740675168DA4A926ABD1",
    "g5_bridge": "5F70CFE5CF70FCDE1008AB60D6CFEE09158F70E5D3D0CD70622F0D24C675E15A",
    "g5_main_builder": "ED00FC6AC6257700DE37D865B954EDD7AC4DCBABE532F48B1B143014CCEF78E2",
    "v21_store": "1F01EDA8466873B90359C25AAD2B61CB378D7A9FEB477FA8EC77A97FB2478E6A",
    "v21_worker": "5E378EE77AD5C6E640AD2ECA0DACF154849E6FCFE0D04D73E9DA6EB2554087B3",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def function_text(source: str, name: str) -> str:
    tree = ast.parse(source)
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise AssertionError(f"expected exactly one {name}, found {len(nodes)}")
    return ast.get_source_segment(source, nodes[0]) or ""


def method_parameters(source: str, name: str) -> set[str]:
    tree = ast.parse(source)
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise AssertionError(f"expected exactly one {name}, found {len(nodes)}")
    args = nodes[0].args
    return {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}


hashes = {}
for name, path in ROOTS.items():
    actual = sha(path)
    if actual != EXPECTED[name]:
        raise SystemExit(f"PREIMAGE_MISMATCH {name}: {actual} != {EXPECTED[name]}")
    hashes[name] = actual

g5_auth = ROOTS["g5_authority"].read_text(encoding="utf-8")
g5_store = ROOTS["g5_store"].read_text(encoding="utf-8")
g5_worker = ROOTS["g5_worker"].read_text(encoding="utf-8")
v21_store = ROOTS["v21_store"].read_text(encoding="utf-8")
v21_worker = ROOTS["v21_worker"].read_text(encoding="utf-8")

g5_allocator = function_text(g5_auth, "reserve_cancel_action_identity")
v21_allocator = function_text(v21_store, "_allocate_ctp_native_action_ref")
v21_stage = function_text(v21_store, "stage_ctp_dispatch_command")
v21_migration = function_text(v21_store, "_migrate_legacy_ctp_action_ref_accounts")
g5_stage = function_text(g5_auth, "stage_cancel_command")

assert "FROM ctp_action_identity_reservations" in g5_allocator
assert "legacy_seed.legacy_ledger_max_action_ref" in g5_allocator
assert "ctp_native_action_ref_allocations" not in g5_allocator
assert "ctp_native_action_ref_counters" not in g5_allocator
assert "ctp_native_action_ref_counters" in v21_allocator
assert "ctp_native_action_ref_allocations" in v21_allocator
assert "ctp_action_identity_reservations" not in v21_allocator
assert "ctp_action_ref_watermarks" not in v21_allocator
assert "if native_action_ref is not None" in v21_stage
assert "native ActionRef is allocated by the execution Store" in v21_stage
assert "_allocate_ctp_native_action_ref(" in v21_stage
assert 'logical["OrderActionRef"] = action.native_action_ref' in g5_stage
assert "ctp_action_identity_reservations" not in v21_migration
assert "ctp_action_ref_watermarks" not in v21_migration
assert "action_identity" in method_parameters(g5_worker, "stage_prepared_dispatch")
assert "action_identity" not in method_parameters(v21_worker, "stage_prepared_dispatch")
assert "_SCHEMA_VERSION = 5" in g5_store
assert "_SCHEMA_VERSION = 21" in v21_store

result = {
    "status": "STATIC_API_AND_MIGRATION_SPLIT_CONFIRMED",
    "scope": "read-only frozen source text and AST only; no SDK imports or execution",
    "checks": {
        "g5_allocator_uses_only_g5_reservation_rows": True,
        "v21_allocator_uses_only_v21_counter_and_allocation_tables": True,
        "g5_and_v21_worker_action_identity_signatures_differ": True,
        "g5_stages_action_ref_in_payload_but_v21_allocates_inside_store": True,
        "v21_legacy_actionref_migration_does_not_import_g5_action_rows": True,
        "schema_versions_are_g5_5_and_v21_21": True,
    },
    "preimage_sha256": hashes,
}
print(json.dumps(result, sort_keys=True, indent=2))
