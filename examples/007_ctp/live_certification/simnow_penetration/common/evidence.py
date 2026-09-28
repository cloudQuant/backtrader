"""Account, order, trade, and position reconciliation for certification cases."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from common.certification import (
    get_certification_scenario,
    get_reconciliation_expectation,
)


SNAPSHOT_FILE = "state_snapshots.json"
RECONCILIATION_FILE = "reconciliation.json"


def mask_account_id(account_id: Any) -> str:
    """Mask an account id to ``ab***yz`` for evidence redaction (short ids pass through)."""
    text = str(account_id or "")
    if len(text) <= 4:
        return text
    return f"{text[:2]}***{text[-2:]}"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _safe_call(label: str, fn):
    try:
        return _jsonable(fn()), ""
    except Exception as exc:
        return None, f"{label}: {type(exc).__name__}: {exc}"


def _snapshot_path(report_dir: str | Path) -> Path:
    return Path(report_dir) / SNAPSHOT_FILE


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def capture_store_snapshot(
    *,
    report_dir: str | Path,
    case_id: str,
    label: str,
    store: Any,
    env_key: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Query live account state and append it to state_snapshots.json."""

    config = dict(config or {})
    balance, balance_error = _safe_call("balance", store.get_balance)
    positions, positions_error = _safe_call("positions", store.get_positions)
    open_orders, open_orders_error = _safe_call(
        "open_orders",
        getattr(store, "get_open_orders", list),
    )
    snapshot = {
        "case_id": case_id,
        "label": label,
        "timestamp": datetime.now().isoformat(),
        "env": env_key,
        "connected": bool(getattr(store, "is_connected", False)),
        "account_id_masked": mask_account_id(
            config.get("investor_id") or config.get("user_id")
        ),
        "balance": balance,
        "positions": positions or [],
        "open_orders": open_orders or [],
        "errors": [
            item for item in (balance_error, positions_error, open_orders_error) if item
        ],
    }
    path = _snapshot_path(report_dir)
    rows = _read_json(path, [])
    rows.append(snapshot)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _collect_log_events(report_dir: Path) -> list[dict[str, Any]]:
    events = []
    for log_dir in (report_dir / "logs", report_dir):
        if not log_dir.exists():
            continue
        for path in sorted(log_dir.glob("*.log")):
            events.extend(_read_json_lines(path))
    return events


def _derive_runtime_evidence(
    result: Any,
    events: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return no certification claims from the unauthenticated legacy path.

    JSONL rows and result details are caller-forgeable.  Reconciliation still
    reads logs for diagnostics, but no provider/runtime/validator/control-plane
    adapter is wired into this path to authenticate required events or fields.
    """
    return {"observed_events": [], "field_names": set(), "values": {}}


def _missing_evidence_reason(missing_events: list[str], missing_fields: list[str]) -> str:
    missing_parts = []
    if missing_events:
        missing_parts.append("events=" + ",".join(missing_events))
    if missing_fields:
        missing_parts.append("fields=" + ",".join(missing_fields))
    return "Missing required certification evidence: " + "; ".join(missing_parts)


def _refresh_result_certification_state(
    result: Any,
    runtime_evidence: dict[str, Any],
) -> None:
    scenario = get_certification_scenario(str(getattr(result, "case_id", "") or ""))
    observed_events = list(runtime_evidence["observed_events"])
    field_names = set(runtime_evidence["field_names"])
    missing_events = [event for event in scenario.required_events if event not in observed_events]
    missing_fields = [field for field in scenario.evidence_fields if field not in field_names]

    was_missing_evidence_failure = str(getattr(result, "failure_reason", "")).startswith(
        "Missing required certification evidence"
    )
    result.observed_events = observed_events
    result.missing_required_events = missing_events
    result.required_events_present = not missing_events
    result.missing_evidence_fields = missing_fields
    result.evidence_fields_present = not missing_fields
    result.details = dict(getattr(result, "details", {}) or {})
    result.details["certification_evidence"] = dict(runtime_evidence["values"])

    if result.status == "PASS" and (missing_events or missing_fields):
        result.status = "FAIL"
        result.failure_reason = _missing_evidence_reason(missing_events, missing_fields)
    elif result.status == "FAIL" and was_missing_evidence_failure and not missing_events and not missing_fields:
        result.status = "PASS"
        result.failure_reason = ""
    elif result.status == "FAIL" and was_missing_evidence_failure:
        result.failure_reason = _missing_evidence_reason(missing_events, missing_fields)

    if result.audit_events:
        audit_event = result.audit_events[0]
        audit_event.update(
            {
                "status": result.status,
                "severity": "ERROR" if result.status == "FAIL" else "INFO",
                "message": result.failure_reason or (
                    "case passed" if result.status == "PASS" else result.status.lower()
                ),
                "observed_events": observed_events,
                "missing_required_events": missing_events,
                "missing_evidence_fields": missing_fields,
                "required_events_present": not missing_events,
                "evidence_fields_present": not missing_fields,
                "details": result.details,
            }
        )


def _failed_check_names(reconciliation: dict[str, Any]) -> list[str]:
    checks = reconciliation.get("checks")
    if not isinstance(checks, dict):
        return []
    return [
        str(name)
        for name, check in checks.items()
        if isinstance(check, dict) and check.get("passed") is not True
    ]


def _apply_strict_reconciliation_result(result: Any, reconciliation: dict[str, Any]) -> None:
    if result.status != "PASS" or reconciliation.get("strict_reconciliation_pass") is True:
        return
    failed = _failed_check_names(reconciliation)
    result.status = "FAIL"
    result.failure_reason = "Strict reconciliation failed"
    if failed:
        result.failure_reason += ": " + ",".join(failed)
    if result.audit_events:
        result.audit_events[0].update(
            {
                "status": result.status,
                "severity": "ERROR",
                "message": result.failure_reason,
                "details": result.details,
            }
        )


def _balance_changed(before: Any, after: Any) -> bool | None:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return None
    for key in ("cash", "value", "balance", "available", "equity", "total"):
        if key in before or key in after:
            try:
                if abs(float(before.get(key, 0.0) or 0.0) - float(after.get(key, 0.0) or 0.0)) > 1e-8:
                    return True
            except Exception:
                if before.get(key) != after.get(key):
                    return True
    return False


def _stable_positions(value: Any) -> Any:
    rows = value if isinstance(value, list) else []
    return sorted(json.dumps(_jsonable(row), ensure_ascii=False, sort_keys=True) for row in rows)


def _check(expected: str, observed: bool, *, allowed_values=("allowed", "allowed_if_trade")) -> dict[str, Any]:
    if expected == "required":
        return {"expected": expected, "observed": observed, "passed": observed}
    if expected == "none":
        return {"expected": expected, "observed": observed, "passed": not observed}
    if expected in allowed_values:
        return {"expected": expected, "observed": observed, "passed": True}
    return {"expected": expected or "not_specified", "observed": observed, "passed": True}


def _is_real_order_activity_event(event_type: str) -> bool:
    """Return whether an event means an order reached routing/cancel flow."""

    return event_type in {
        "order_submit_request",
        "order_submit_accepted",
        "order_status_submitted",
        "order_status_accepted",
        "order_status_partial",
        "order_status_completed",
        "order_cancel_request",
        "order_cancel_submitted",
        "order_status_canceled",
        "batch_cancel_requested",
        "batch_cancel_completed",
        "batch_cancel_failed",
    }


def build_reconciliation(result: Any, report_dir: str | Path) -> dict[str, Any]:
    """Build a strict reconciliation report from snapshots and log events."""

    report_dir = Path(report_dir)
    case_id = str(getattr(result, "case_id", "") or "")
    snapshots = _read_json(_snapshot_path(report_dir), [])
    events = _collect_log_events(report_dir)
    event_types = [str(event.get("event_type") or "") for event in events]
    details = getattr(result, "details", {}) or {}
    # Reconciliation activity must come from persisted event rows, never the
    # result's locally assembled observed-event list.
    all_event_types = event_types
    order_events = [
        event for event in all_event_types
        if _is_real_order_activity_event(event)
    ]
    trade_events = [
        event for event in all_event_types
        if event == "trade_execution" or event.startswith("trade_")
    ]
    before = snapshots[0] if snapshots else {}
    after = snapshots[-1] if len(snapshots) >= 2 else {}
    balance_changed = _balance_changed(before.get("balance"), after.get("balance"))
    positions_changed = (
        _stable_positions(before.get("positions")) != _stable_positions(after.get("positions"))
        if before and after else None
    )
    post_open_orders = after.get("open_orders") if isinstance(after, dict) else []
    expectation = get_reconciliation_expectation(case_id)
    order_seen = bool(order_events)
    trade_seen = bool(trade_events)
    checks = {
        "required_events": {
            "expected": list(getattr(result, "required_events", []) or []),
            "missing": list(getattr(result, "missing_required_events", []) or []),
            "passed": bool(getattr(result, "required_events_present", False)),
        },
        "order_activity": _check(str(expectation.get("order_activity", "")), order_seen),
        "trade_activity": _check(str(expectation.get("trade_activity", "")), trade_seen),
        "post_action_open_orders": {
            "expected": "none" if expectation.get("no_open_orders_after") else "not_specified",
            "observed_count": len(post_open_orders or []),
            "passed": (
                len(snapshots) >= 2
                and isinstance(after, dict)
                and isinstance(after.get("open_orders"), list)
                and not any(
                    str(error).startswith("open_orders:")
                    for error in (after.get("errors") or [])
                )
                and len(post_open_orders or []) == 0
            ) if expectation.get("no_open_orders_after") else True,
        },
    }
    if expectation.get("account_position_change") == "none":
        checks["account_position_unchanged"] = {
            "expected": "unchanged",
            "balance_changed": balance_changed,
            "positions_changed": positions_changed,
            "passed": balance_changed is False and positions_changed is False,
        }
    elif expectation.get("account_position_change") == "allowed_if_trade":
        unchanged_without_trade = (
            balance_changed is False and positions_changed is False
        )
        checks["account_position_change"] = {
            "expected": "allowed_if_trade",
            "balance_changed": balance_changed,
            "positions_changed": positions_changed,
            "trade_events": len(trade_events),
            "passed": trade_seen or unchanged_without_trade,
        }

    strict_pass = all(item.get("passed") is True for item in checks.values())
    return {
        "case_id": case_id,
        "scenario_id": getattr(result, "scenario_id", ""),
        "generated_at": datetime.now().isoformat(),
        "expectation": expectation,
        "snapshot_count": len(snapshots),
        "snapshots_file": str(_snapshot_path(report_dir)),
        "event_counts": {
            "total_events": len(events),
            "order_events": len(order_events),
            "trade_events": len(trade_events),
        },
        "event_types": sorted(set(all_event_types)),
        "account_delta": {
            "balance_changed": balance_changed,
            "positions_changed": positions_changed,
            "before_label": before.get("label", ""),
            "after_label": after.get("label", ""),
        },
        "post_action_open_orders": post_open_orders or [],
        "checks": checks,
        "strict_reconciliation_pass": strict_pass,
        "notes": details.get("reconciliation_notes", ""),
    }


def attach_reconciliation(result: Any, report_dir: str | Path):
    """Attach reconciliation evidence to a CaseResult and persist reconciliation.json."""

    report_dir = Path(report_dir)
    snapshots = _read_json(_snapshot_path(report_dir), [])
    events = _collect_log_events(report_dir)
    runtime_evidence = _derive_runtime_evidence(result, events, snapshots)
    _refresh_result_certification_state(result, runtime_evidence)
    reconciliation = build_reconciliation(result, report_dir)
    path = report_dir / RECONCILIATION_FILE
    path.write_text(json.dumps(reconciliation, ensure_ascii=False, indent=2), encoding="utf-8")
    result.details = dict(result.details or {})
    result.details["reconciliation"] = reconciliation
    _apply_strict_reconciliation_result(result, reconciliation)
    if result.audit_events:
        result.audit_events[0]["reconciliation"] = reconciliation
        result.audit_events[0]["details"] = result.details
    for evidence_path in (_snapshot_path(report_dir), path):
        text = str(evidence_path)
        if text not in result.evidence:
            result.evidence.append(text)
    return result
