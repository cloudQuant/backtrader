"""Integration simulation tests for legacy path retirement, read-only SQLite export CLI, and mode migration (T-039/T-040/S-08).

Verifies:
- Path 5 retired on both compat BtApiStore and DirectBtApiStore (LEGACY_HYBRID_ROUTING_RETIRED)
- Path 2/3/6 retired / rejected on DirectBtApiStore and live composition root
- CLI `python -m backtrader.live_state export-legacy-execution-routing` reads
  `state/execution_routing.sqlite` strictly via SQLite `mode=ro` URI, proves
  byte-identical DB SHA-256 before/after, leaves Gateway's
  `state/gateway_execution_routing.sqlite` untouched, and appends an audit record
- D62S-07b: unresolved rows in legacy DB block migration until read-only export
  AND project/account owner written approval ref are both present
- R62S-11: identity.json mode mismatch blocks cross-mode reuse
- Empty-position migration passes; non-empty position migration fails closed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from backtrader.live_state import (
    APPROVAL_AUTHORITY,
    GATEWAY_EXECUTION_ROUTING_DB_FILENAME,
    LEGACY_EXECUTION_ROUTING_DB_FILENAME,
    LiveStateModeMismatch,
    StrategyStateDir,
    export_legacy_execution_routing,
    read_audit,
    verify_mode_migration_preconditions,
)
from backtrader.stores import (
    BtApiStore,
    DirectBtApiStore,
    LiveCompositionError,
    ProcessModeFence,
    create_direct_store,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _reset_fence():
    ProcessModeFence._reset_for_tests()
    yield
    ProcessModeFence._reset_for_tests()


def _create_legacy_db(path: Path, *, unresolved: bool = True) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE execution_parent_requests_v1 ("
            "account TEXT, strategy TEXT, request_key TEXT, request_id TEXT, result TEXT)"
        )
        conn.execute(
            "INSERT INTO execution_parent_requests_v1 VALUES (?, ?, ?, ?, ?)",
            ("acc-1", "strat-1", "rk-1", "req-1", None if unresolved else "COMPLETED"),
        )
        conn.commit()
    finally:
        conn.close()
    return path.read_bytes()


def test_s08_path5_retired_on_btapistore_and_direct_store():
    for kw in (
        {"service_client_config": object()},
        {"gateway_client_config": object()},
        {"execution_parent_port": object()},
    ):
        with pytest.raises(LiveCompositionError) as exc1:
            BtApiStore(config={"exchange_kwargs": {"CTP___FUTURE": {}}}, **kw)
        assert exc1.value.code == "LEGACY_HYBRID_ROUTING_RETIRED"

        with pytest.raises(LiveCompositionError) as exc2:
            create_direct_store(
                config={"mode": "direct", "exchange_kwargs": {"CTP___FUTURE": {}}}, **kw
            )
        assert exc2.value.code == "LEGACY_HYBRID_ROUTING_RETIRED"

    # Path 6 keys refused directly on DirectBtApiStore
    for key in ("market_runtime_factory", "forwarding_config", "transport_mode"):
        with pytest.raises(LiveCompositionError) as exc6:
            DirectBtApiStore(config={"exchange_kwargs": {"CTP___FUTURE": {}}, key: "v"})
        assert exc6.value.code == "DIRECT_SERVICE_KEY_FORBIDDEN"


def test_s08_readonly_legacy_sqlite_export_cli_preserves_bytes_and_leaves_gateway_db_untouched(
    tmp_path,
):
    sdir = tmp_path / "legacy_strat"
    sdir.mkdir()
    StrategyStateDir.initialize(sdir, mode="gateway")

    legacy_db = sdir / "state" / LEGACY_EXECUTION_ROUTING_DB_FILENAME
    gateway_db = sdir / "state" / GATEWAY_EXECUTION_ROUTING_DB_FILENAME
    legacy_before = _create_legacy_db(legacy_db, unresolved=True)
    gateway_before = _create_legacy_db(gateway_db, unresolved=False)
    expected_sha = hashlib.sha256(legacy_before).hexdigest()
    out_json = tmp_path / "exported_legacy.json"

    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "backtrader.live_state",
            "export-legacy-execution-routing",
            str(sdir),
            "--output",
            str(out_json),
            "--operator",
            "project-owner",
            "--reason",
            "split04-readonly-audit",
            "--approval-ref",
            "OWNER-APPROVAL-2026-11-23-001",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, res.stderr
    body = json.loads(res.stdout)
    assert body["ok"] is True
    assert body["db_filename"] == "execution_routing.sqlite"
    assert body["db_sha256"] == expected_sha
    assert body["readonly_verified"] is True
    assert body["unresolved_rows"] == 1
    assert body["approval_authority"] == APPROVAL_AUTHORITY == "project_account_owner"
    assert body["owner_written_approval_required"] is True
    assert body["owner_approval_ref"] == "OWNER-APPROVAL-2026-11-23-001"
    assert out_json.is_file()
    assert json.loads(out_json.read_text(encoding="utf-8"))["db_sha256"] == expected_sha

    # Byte-identical proof on BOTH DBs (never deleted, never modified!)
    assert legacy_db.read_bytes() == legacy_before
    assert gateway_db.read_bytes() == gateway_before

    # Audit log recorded export
    audit_events = [row for row in read_audit(sdir) if row.get("event") == "legacy_execution_routing_exported"]
    assert len(audit_events) == 1
    assert audit_events[0]["db_sha256"] == expected_sha


def test_s08_migration_gate_enforces_owner_approval_empty_position_and_mode_stamp(tmp_path):
    sdir = tmp_path / "mig_strat"
    sdir.mkdir()
    StrategyStateDir.initialize(sdir, mode="gateway")
    legacy_db = sdir / "state" / LEGACY_EXECUTION_ROUTING_DB_FILENAME
    _create_legacy_db(legacy_db, unresolved=True)

    # 1. Cross-mode target refused by R62S-11 identity.json mode stamp
    with pytest.raises(LiveStateModeMismatch):
        verify_mode_migration_preconditions(sdir, target_mode="direct", open_positions=[])

    # 2. Non-empty position refused
    with pytest.raises(LiveCompositionError) as exc_pos:
        verify_mode_migration_preconditions(
            sdir,
            target_mode="gateway",
            open_positions=[{"symbol": "SA701", "volume": 2}],
        )
    assert exc_pos.value.code == "MODE_CONFLICT"

    # 3. Unexported legacy DB refused (D62S-07b)
    with pytest.raises(LiveCompositionError) as exc_unexp:
        verify_mode_migration_preconditions(sdir, target_mode="gateway", open_positions=[])
    assert exc_unexp.value.code == "LEGACY_EXECUTION_ROUTING_DB_UNEXPORTED"

    # 4. Exported, but unresolved rows WITHOUT project/account owner written approval still refused!
    export_legacy_execution_routing(sdir, operator="owner", reason="audit")
    with pytest.raises(LiveCompositionError) as exc_no_appr:
        verify_mode_migration_preconditions(sdir, target_mode="gateway", open_positions=[])
    assert exc_no_appr.value.code == "LEGACY_EXECUTION_ROUTING_DB_UNEXPORTED"

    # 5. Exported + flat positions + explicit project/account owner written approval PASSES!
    result = verify_mode_migration_preconditions(
        sdir,
        target_mode="gateway",
        open_positions=[{"symbol": "SA701", "volume": 0}],
        owner_approval_ref="WRITTEN-APPROVAL-USER-001",
    )
    assert result["ok"] is True
    assert result["approval_authority"] == "project_account_owner"
    assert result["owner_approval_ref"] == "WRITTEN-APPROVAL-USER-001"
