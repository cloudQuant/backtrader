"""Read-only export of legacy path 5 ``state/execution_routing.sqlite`` & migration gate (T-039/D62S-07).

Hard invariants:
- Opens ONLY ``<strategy_dir>/state/execution_routing.sqlite`` using SQLite URI
  ``mode=ro`` (never mutates, never creates, never deletes the DB, and verifies
  DB SHA-256 is byte-identical before and after read).
- NEVER touches Gateway path 4's active ``state/gateway_execution_routing.sqlite``.
- Records ``approval_authority = "project_account_owner"`` (D62S-07b) when
  unresolved rows exist, requiring per-case written approval by the
  project/account owner before any mode migration proceeds.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import urllib.parse
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..stores._btapi_errors import LiveCompositionError
from ._common import StatePaths, is_text, utc_now_iso
from .atomic import LiveStateError, atomic_write_json
from .audit import append_audit, read_audit
from .identity import IDENTITY_MODES, load_identity

__all__ = (
    "APPROVAL_AUTHORITY",
    "GATEWAY_EXECUTION_ROUTING_DB_FILENAME",
    "LEGACY_EXECUTION_ROUTING_DB_FILENAME",
    "export_legacy_execution_routing",
    "verify_mode_migration_preconditions",
)

LEGACY_EXECUTION_ROUTING_DB_FILENAME = "execution_routing.sqlite"
GATEWAY_EXECUTION_ROUTING_DB_FILENAME = "gateway_execution_routing.sqlite"
APPROVAL_AUTHORITY = "project_account_owner"
_TERMINAL_RESULT_MARKERS = frozenset(
    {"COMPLETED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "FAILED", "TERMINAL"}
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_ro_uri(path: Path) -> str:
    resolved = path.resolve()
    posix = resolved.as_posix()
    encoded = urllib.parse.quote(posix, safe="/:")
    if not encoded.startswith("/"):
        encoded = "/" + encoded
    return f"file:{encoded}?mode=ro"


def _row_is_unresolved(table_name: str, row: Mapping[str, Any]) -> bool:
    if "result" in row:
        val = row["result"]
        if val is None or str(val).strip() == "":
            return True
        upper = str(val).upper()
        if any(tok in upper for tok in ("UNKNOWN", "PREPARED", "PENDING", "OPEN", "ACTIVE")):
            return True
        return not any(tok in upper for tok in _TERMINAL_RESULT_MARKERS)
    if "status" in row:
        val = str(row["status"] or "").upper()
        return val not in _TERMINAL_RESULT_MARKERS
    return table_name in {"execution_parent_requests_v1", "execution_route_candidates"}


def export_legacy_execution_routing(
    strategy_dir: Any,
    *,
    output_path: Optional[Any] = None,
    operator: Optional[str] = None,
    reason: Optional[str] = None,
    approval_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Read-only export of legacy ``state/execution_routing.sqlite`` with SHA-256 proof."""
    paths = StatePaths(strategy_dir)
    db_path = Path(paths.state_dir) / LEGACY_EXECUTION_ROUTING_DB_FILENAME
    if not db_path.is_file():
        raise LiveStateError("legacy_routing_export_failed", "legacy_db_missing")

    sha_before = _sha256_file(db_path)
    tables: Dict[str, List[Dict[str, Any]]] = {}
    unresolved_count = 0
    total_rows = 0

    conn = sqlite3.connect(_sqlite_ro_uri(db_path), uri=True)
    try:
        conn.row_factory = sqlite3.Row
        table_names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        for tname in table_names:
            quoted = '"' + tname.replace('"', '""') + '"'
            rows = [dict(r) for r in conn.execute(f"SELECT * FROM {quoted}").fetchall()]
            tables[tname] = rows
            total_rows += len(rows)
            for row in rows:
                if _row_is_unresolved(tname, row):
                    unresolved_count += 1
    except sqlite3.Error as exc:
        raise LiveStateError("legacy_routing_export_failed", type(exc).__name__) from None
    finally:
        conn.close()

    sha_after = _sha256_file(db_path)
    if sha_before != sha_after:
        raise LiveStateError("legacy_routing_export_failed", "db_mutated_during_readonly_export")

    exported_at = utc_now_iso()
    payload: Dict[str, Any] = {
        "schema": "backtrader.legacy_execution_routing_export/v1",
        "exported_at_utc": exported_at,
        "db_filename": LEGACY_EXECUTION_ROUTING_DB_FILENAME,
        "db_sha256": sha_after,
        "readonly_verified": True,
        "table_count": len(tables),
        "total_rows": total_rows,
        "unresolved_rows": unresolved_count,
        "approval_authority": APPROVAL_AUTHORITY,
        "owner_written_approval_required": unresolved_count > 0,
        "owner_approval_ref": approval_ref,
        "tables": tables,
    }

    if output_path is not None:
        out_str = os.fspath(output_path)
        atomic_write_json(out_str, payload)

    if os.path.isdir(paths.state_dir):
        audit_entry: Dict[str, Any] = {
            "event": "legacy_execution_routing_exported",
            "db_filename": LEGACY_EXECUTION_ROUTING_DB_FILENAME,
            "db_sha256": sha_after,
            "total_rows": total_rows,
            "unresolved_rows": unresolved_count,
            "approval_authority": APPROVAL_AUTHORITY,
            "owner_written_approval_required": unresolved_count > 0,
        }
        if is_text(operator, max_len=200):
            audit_entry["operator"] = operator
        if is_text(reason, max_len=2000):
            audit_entry["reason"] = reason
        if is_text(approval_ref, max_len=256):
            audit_entry["owner_approval_ref"] = approval_ref
        append_audit(paths.strategy_dir, audit_entry)

    return payload


def verify_mode_migration_preconditions(
    strategy_dir: Any,
    *,
    target_mode: str,
    open_positions: Iterable[Mapping[str, Any]] = (),
    owner_approval_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Enforce S-08 migration invariants (empty position, D62S-07b owner approval, R62S-11 mode)."""
    if type(target_mode) is not str or target_mode not in IDENTITY_MODES:
        raise LiveCompositionError("MODE_INVALID", detail="migration_target_mode")

    # 1. R62S-11: cross-mode reuse of a stamped directory is strictly forbidden.
    identity = load_identity(strategy_dir, check_host_path=True, expected_mode=target_mode)

    # 2. Empty-position migration gate: reject any non-zero exposure.
    for pos in open_positions:
        qty = pos.get("volume", pos.get("size", 0))
        if qty is not None and float(qty) != 0.0:
            raise LiveCompositionError(
                "MODE_CONFLICT", detail="non_empty_position_migration_forbidden"
            )

    # 3. D62S-07b: legacy state/execution_routing.sqlite unresolved rows require prior
    # read-only export audit AND explicit project/account owner written approval.
    paths = StatePaths(strategy_dir)
    legacy_db = Path(paths.state_dir) / LEGACY_EXECUTION_ROUTING_DB_FILENAME
    unresolved_rows = 0
    if legacy_db.is_file():
        db_sha = _sha256_file(legacy_db)
        exported_records = [
            entry
            for entry in read_audit(paths.strategy_dir)
            if entry.get("event") == "legacy_execution_routing_exported"
            and entry.get("db_sha256") == db_sha
        ]
        if not exported_records:
            raise LiveCompositionError(
                "LEGACY_EXECUTION_ROUTING_DB_UNEXPORTED", detail="export_audit_missing"
            )
        unresolved_rows = int(exported_records[-1].get("unresolved_rows", 0))
        if unresolved_rows > 0 and not is_text(owner_approval_ref, max_len=256):
            raise LiveCompositionError(
                "LEGACY_EXECUTION_ROUTING_DB_UNEXPORTED",
                detail="project_account_owner_written_approval_required",
            )

    return {
        "ok": True,
        "strategy_uuid": identity.strategy_uuid,
        "target_mode": target_mode,
        "legacy_db_present": legacy_db.is_file(),
        "legacy_unresolved_rows": unresolved_rows,
        "approval_authority": APPROVAL_AUTHORITY,
        "owner_approval_ref": owner_approval_ref,
    }
