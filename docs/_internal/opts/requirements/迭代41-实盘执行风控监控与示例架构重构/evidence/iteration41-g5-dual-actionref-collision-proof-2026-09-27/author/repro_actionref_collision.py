from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
sys.dont_write_bytecode = True

V21_SRC = Path(r"D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927\src")
V21_STORE = V21_SRC / "bt_api_execution" / "store.py"
V21_MANIFEST = V21_SRC.parent / "SOURCE-MANIFEST.json"
G5_AUTHORITY = Path(r"D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py")
EXPECTED = {
    "v21_manifest_sha256": "B3A614D62B2A4CF1B0DBDFEFEE463015157DEE38BF4C9C5119C64EF2D71D6D24",
    "v21_store_sha256": "1F01EDA8466873B90359C25AAD2B61CB378D7A9FEB477FA8EC77A97FB2478E6A",
    "g5_authority_sha256": "8E7ABDD2819F66B6EC3D5FF1D5A049FCBB91AE8E71327665EE925098D35F647D",
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


actual = {
    "v21_manifest_sha256": file_sha256(V21_MANIFEST),
    "v21_store_sha256": file_sha256(V21_STORE),
    "g5_authority_sha256": file_sha256(G5_AUTHORITY),
}
if actual != EXPECTED:
    raise SystemExit("frozen source hash mismatch; refusing to run")

sys.path.insert(0, str(V21_SRC))
from bt_api_execution.contracts import ExecutionScope, payload_sha256
from bt_api_execution.store import CtpOrderRefSeedProof, SqliteExecutionStore

module_name = "bt_api_execution.ctp_identity_authority"
spec = importlib.util.spec_from_file_location(module_name, G5_AUTHORITY)
if spec is None or spec.loader is None:
    raise SystemExit("unable to load frozen G5 authority")
g5 = importlib.util.module_from_spec(spec)
sys.modules[module_name] = g5
spec.loader.exec_module(g5)

# All identifiers and watermarks below are synthetic. The DB exists only in
# memory and no CTP/native/provider module, socket, credential, or sender is used.
account_ref = "ctp-account-ref.v1:" + hashlib.sha256(b"synthetic fake account").hexdigest()
scope = ExecutionScope("ctp", "simulation", account_ref, "strategy.fake", "20260927")
store = SqliteExecutionStore(":memory:")
try:
    account_owner = store.acquire_ctp_account_family_owner(scope)
    writer_lease = store.acquire_or_renew_lease(
        scope, "fake-writer", ctp_account_family_owner=account_owner
    )
    authority = g5.CtpUnifiedOrderActionAuthority(store)

    source_digest = hashlib.sha256(b"synthetic empty legacy ledger source").hexdigest()
    source_digests = {
        "backtrader_prototype": source_digest,
        "sdk_jsonl": source_digest,
    }
    order_seed = CtpOrderRefSeedProof(
        trading_day=scope.trading_day,
        native_max_order_ref="000000000000",
        legacy_ledger_max_order_ref="000000000000",
        legacy_ledger_sha256=payload_sha256(source_digests),
        account_key=scope.account_key,
        scope_key=scope.key,
        session_generation_id="fake-session-1",
        native_front_id=1,
        native_session_id=1,
        existing_native_order_refs=(),
        legacy_source_sha256=tuple(sorted(source_digests.items())),
        legacy_mappings=(),
    )
    managed_intent_id = "fake-intent-1"
    runtime_order_id = "bt-managed-v1:" + hashlib.sha256(b"synthetic fake order").hexdigest()
    order_identity = authority.reserve_submit_order_identity(
        scope,
        order_seed,
        managed_intent_id,
        runtime_order_id,
        writer_lease=writer_lease,
    )
    action_seed = g5.CtpActionRefSeedProof(
        trading_day=scope.trading_day,
        legacy_ledger_max_action_ref=0,
        legacy_ledger_sha256=hashlib.sha256(b"synthetic zero action floor").hexdigest(),
    )
    g5_action = authority.reserve_cancel_action_identity(
        scope,
        "fake-g5-cancel",
        managed_intent_id,
        runtime_order_id,
        order_identity.order_ref,
        legacy_seed=action_seed,
        writer_lease=writer_lease,
    )

    with store._transaction() as cursor:
        v21_action_ref = SqliteExecutionStore._allocate_ctp_native_action_ref(
            cursor,
            account_key=scope.account_key,
            scope_key=scope.key,
            command_id="fake-v21-cancel-command",
            managed_action_id="fake-v21-cancel",
            allocated_at_ns=1,
        )
        schemas = {
            str(row["name"]): str(row["sql"])
            for row in cursor.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'table' AND name IN (?, ?, ?) ORDER BY name",
                ("ctp_action_identity_reservations", "ctp_native_action_ref_counters", "ctp_native_action_ref_allocations"),
            ).fetchall()
        }
        action_rows = {
            "g5": [dict(row) for row in cursor.execute(
                "SELECT account_key, native_action_ref, managed_action_id "
                "FROM ctp_action_identity_reservations ORDER BY managed_action_id"
            ).fetchall()],
            "v21_counter": [dict(row) for row in cursor.execute(
                "SELECT account_key, last_action_ref "
                "FROM ctp_native_action_ref_counters ORDER BY account_key"
            ).fetchall()],
            "v21_command_mappings": [dict(row) for row in cursor.execute(
                "SELECT account_key, native_action_ref, command_id, managed_action_id "
                "FROM ctp_native_action_ref_allocations ORDER BY command_id"
            ).fetchall()],
        }

    if g5_action.native_action_ref != v21_action_ref:
        raise SystemExit(
            "collision did not reproduce: "
            f"G5={g5_action.native_action_ref}, V21={v21_action_ref}"
        )
    if (
        len(action_rows["g5"]) != 1
        or len(action_rows["v21_counter"]) != 1
        or action_rows["v21_counter"][0]["last_action_ref"] != v21_action_ref
        or action_rows["v21_command_mappings"]
    ):
        raise SystemExit("unexpected row count/state in in-memory authority tables")
    forbidden_roots = {"bt_api_ctp", "bt_api_py", "ctp", "vnpy", "tqsdk"}
    loaded_forbidden = sorted(
        name for name in sys.modules
        if name.split(".", 1)[0] in forbidden_roots
    )
    if loaded_forbidden:
        raise SystemExit(f"unexpected native/provider modules loaded: {loaded_forbidden}")

    print(json.dumps({
        "result": "STRUCTURAL_COLLISION_REPRODUCED",
        "scope_account_key": scope.account_key,
        "scope_key": scope.key,
        "order_ref_reserved_by_shared_order_api": order_identity.order_ref,
        "g5_action_ref": g5_action.native_action_ref,
        "v21_action_ref": v21_action_ref,
        "action_refs_equal": g5_action.native_action_ref == v21_action_ref,
        "sqlite_db": ":memory:",
        "native_or_provider_modules_loaded": loaded_forbidden,
        "native_sdk_or_provider_send": False,
        "credentials_used": False,
        "network_used": False,
        "source_hashes": actual,
        "table_schemas": schemas,
        "authority_rows": action_rows,
        "v21_command_mapping_created": False,
        "v21_allocation_scope": (
            "The Store allocator primitive was called in its own committed SQLite transaction; "
            "full cancel command staging and the command-to-ActionRef mapping insert were not called."
        ),
        "interpretation": (
            "Two independent durable ActionRef allocators in one SQLite database "
            "both issue 1 for the same synthetic account. This is a structural "
            "single-authority blocker, not evidence that a provider received or "
            "observed a duplicate."
        ),
    }, sort_keys=True, indent=2))
finally:
    store.close()






