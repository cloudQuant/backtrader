"""Account, order, trade, and position reconciliation for certification cases."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from common.certification import (
    get_certification_scenario,
    get_reconciliation_expectation,
)
from common.result import _collect_evidence_field_names, _collect_observed_events


SNAPSHOT_FILE = "state_snapshots.json"
RECONCILIATION_FILE = "reconciliation.json"


def mask_account_id(account_id: Any) -> str:
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
        getattr(store, "get_open_orders", lambda: []),
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


def _field_names(value: Any) -> set[str]:
    fields: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            fields.add(str(key))
            fields.update(_field_names(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            fields.update(_field_names(item))
    return fields


def _put_value(values: dict[str, Any], key: str, value: Any) -> None:
    if key in values:
        return
    if value in (None, ""):
        return
    values[key] = _jsonable(value)


def _first_value(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _event_details(event: dict[str, Any]) -> dict[str, Any]:
    details = event.get("details")
    return dict(details) if isinstance(details, dict) else {}


def _is_remote_counter_order_reject(event: dict[str, Any]) -> bool:
    """Return whether an order rejection carries counter-side CTP evidence."""

    event_type = str(event.get("event_type") or "")
    if event_type == "order_reject_remote":
        return True
    if event_type != "order_rejected":
        return False

    details = _event_details(event)
    error_code = str(
        _first_value(event.get("error_code"), details.get("ErrorID"), details.get("ErrorId"))
        or ""
    ).strip()
    error_msg = str(
        _first_value(event.get("error_msg"), details.get("ErrorMsg"), details.get("StatusMsg"))
        or ""
    )
    provider = str(event.get("provider") or details.get("provider") or "").lower()

    if error_code.isdigit():
        return True
    return provider == "ctp" and ("CTP:" in error_msg or "CTP" in error_msg)


def _derive_order_status_event(event: dict[str, Any]) -> str:
    status = str(event.get("status") or "").strip().lower()
    if status in {"accepted"}:
        return "order_status_accepted"
    if status in {"canceled", "cancelled"}:
        return "order_status_canceled"
    if status in {"partial", "partialfilled", "partial_filled"}:
        return "order_status_partial"
    if status in {"completed", "filled"}:
        return "order_status_completed"
    return ""


def _event_aliases(event: dict[str, Any]) -> set[str]:
    event_type = str(event.get("event_type") or "")
    aliases = set()
    if event_type == "session_stopped":
        aliases.add("store_disconnected")
    if _is_remote_counter_order_reject(event):
        aliases.add("order_reject_remote")
    if event_type == "order_submit_accepted":
        aliases.add("order_status_accepted")
    order_log_row = not event_type and any(
        key in event for key in ("ref", "order_type", "external_order_id")
    )
    if event_type.startswith("order_") or order_log_row:
        status_event = _derive_order_status_event(event)
        if status_event:
            aliases.add(status_event)
    if not event_type and ("trade_id" in event or "tradeid" in event) and event.get("status") in {
        "Completed",
        "completed",
        "Filled",
        "filled",
    }:
        aliases.add("trade_execution")
    return aliases


def _parse_numeric(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return int(value) if value.is_integer() else value


def _derive_threshold_values(details: dict[str, Any], values: dict[str, Any]) -> None:
    thresholds = details.get("thresholds")
    if isinstance(thresholds, dict):
        if "submit_count" in thresholds:
            _put_value(values, "order_threshold", thresholds.get("submit_count"))
        if "cancel_count" in thresholds:
            _put_value(values, "cancel_threshold", thresholds.get("cancel_count"))
        if "submit_cancel_total" in thresholds:
            _put_value(values, "cancel_threshold", thresholds.get("submit_cancel_total"))
        if "duplicate_order" in thresholds:
            _put_value(values, "repeat_threshold", thresholds.get("duplicate_order"))

    counter = str(details.get("counter") or "")
    threshold = details.get("threshold")
    value = details.get("value")
    if counter == "submit_count":
        _put_value(values, "order_threshold", threshold)
        _put_value(values, "submitted_order_count", value)
    elif counter in {"cancel_count", "submit_cancel_total"}:
        _put_value(values, "cancel_threshold", threshold)
        _put_value(values, "cancel_order_count", value)
    elif counter == "duplicate_order":
        _put_value(values, "repeat_threshold", threshold)
        _put_value(values, "repeat_count", value)

    _put_value(values, "repeat_window_sec", details.get("repeat_window_sec"))


def _derive_runtime_evidence(
    result: Any,
    events: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    observed_events = set(getattr(result, "observed_events", []) or [])
    observed_events.update(_collect_observed_events(getattr(result, "details", {}) or {}))
    field_names = set(_collect_evidence_field_names(getattr(result, "details", {}) or {}))
    values: dict[str, Any] = {"trace_id": getattr(result, "trace_id", "")}
    order_refs: list[Any] = []
    cancel_refs: list[Any] = []
    submit_count = 0
    cancel_count = 0

    for snapshot in snapshots:
        field_names.update(_field_names(snapshot))
        _put_value(values, "account_id_masked", snapshot.get("account_id_masked"))
        _put_value(values, "gateway_key", snapshot.get("env"))

    for event in events:
        event_type = str(event.get("event_type") or "")
        details = _event_details(event)
        if event_type:
            observed_events.add(event_type)
        observed_events.update(_event_aliases(event))
        field_names.update(_field_names(event))

        timestamp = _first_value(event.get("event_time"), event.get("log_time"), event.get("timestamp"))
        _put_value(values, "timestamp", timestamp)
        _put_value(values, "gateway_key", _first_value(event.get("gateway_key"), event.get("provider")))
        _put_value(values, "account_id_masked", event.get("account_id_masked"))
        _put_value(values, "strategy_id", event.get("strategy_name"))
        _put_value(values, "reason", details.get("reason"))
        _put_value(values, "metric", details.get("metric"))

        order_ref = _first_value(
            event.get("order_ref"),
            event.get("ref"),
            details.get("order_ref"),
            details.get("bt_order_ref"),
            details.get("OrderRef"),
        )
        if order_ref not in (None, ""):
            order_refs.append(order_ref)
            if event_type.startswith("order_cancel"):
                cancel_refs.append(order_ref)
        _put_value(values, "order_ref", order_ref)
        _put_value(
            values,
            "external_order_id",
            _first_value(
                event.get("external_order_id"),
                details.get("external_order_id"),
                details.get("OrderSysID"),
            ),
        )
        _put_value(values, "trade_id", _first_value(event.get("trade_id"), details.get("trade_id")))
        _put_value(
            values,
            "instrument",
            _first_value(
                event.get("data_name"),
                event.get("symbol"),
                details.get("data_name"),
                details.get("symbol"),
                details.get("InstrumentID"),
            ),
        )
        _put_value(values, "price", _first_value(event.get("price"), details.get("price")))
        _put_value(values, "size", _first_value(event.get("size"), details.get("size")))
        error_id = _first_value(
            details.get("ErrorID"),
            details.get("ErrorId"),
            event.get("error_code"),
        )
        error_msg_value = _first_value(
            details.get("ErrorMsg"),
            event.get("error_msg"),
        )
        status_msg = _first_value(
            details.get("StatusMsg"),
            event.get("status_msg"),
            event.get("status_message"),
            error_msg_value if _is_remote_counter_order_reject(event) else None,
        )
        _put_value(values, "error_msg", error_msg_value)
        _put_value(values, "error_code", error_id)
        _put_value(values, "ErrorID", error_id)
        _put_value(values, "ErrorMsg", error_msg_value)
        _put_value(values, "StatusMsg", status_msg)

        if event_type == "order_submit_request":
            submit_count += 1
        elif event_type.startswith("order_cancel"):
            cancel_count += 1
        if event_type == "market_data_subscribe_request":
            _put_value(values, "market_connection", True)
        if event_type in {"store_login_success", "store_ready", "store_connected"}:
            _put_value(values, "trade_connection", True)

        if event_type == "monitoring_summary":
            _put_value(values, "submitted_order_count", details.get("submit_count"))
            _put_value(values, "cancel_order_count", details.get("cancel_count"))
            _put_value(values, "open_order_count", details.get("open_order_count"))
        if event_type in {"risk_threshold_configured", "risk_threshold_triggered"}:
            _derive_threshold_values(details, values)
        if event_type in {"risk_repeat_order_detected", "risk_repeat_cancel_detected"}:
            _put_value(values, "repeat_key", details.get("repeat_key"))
            _put_value(values, "repeat_count", details.get("repeat_count"))
        if event_type == "batch_cancel_requested":
            requested = details.get("orders")
            if isinstance(requested, list):
                refs = [
                    item.get("external_order_id") or item.get("order_ref")
                    for item in requested
                    if isinstance(item, dict)
                ]
                refs = [ref for ref in refs if ref not in (None, "")]
                _put_value(values, "order_refs", refs)
                _put_value(values, "open_order_count", len(refs))

        error_msg = str(_first_value(event.get("error_msg"), details.get("error_msg")) or "")
        if "tick size" in error_msg:
            _put_value(values, "price_tick", _parse_numeric(r"tick size ([0-9.]+)", error_msg))
        if "max allowed size" in error_msg:
            _put_value(values, "max_order_size", _parse_numeric(r"max allowed size ([0-9.]+)", error_msg))

    if "market_connection" not in values and any(
        event in observed_events for event in ("data_status", "tick")
    ):
        values["market_connection"] = True
    if "trade_connection" not in values and any(
        event in observed_events for event in ("store_login_success", "store_ready")
    ):
        values["trade_connection"] = True
    _put_value(values, "submitted_order_count", submit_count)
    _put_value(values, "cancel_order_count", cancel_count)
    if "order_refs" not in values and order_refs:
        values["order_refs"] = [_jsonable(ref) for ref in order_refs]
    if "open_order_count" not in values and order_refs:
        values["open_order_count"] = len(order_refs)
    if "partial_count" not in values:
        partial_count = sum(1 for event in observed_events if event == "order_status_partial")
        values["partial_count"] = partial_count

    field_names.update(values.keys())
    return {
        "observed_events": sorted(event for event in observed_events if event),
        "field_names": field_names,
        "values": values,
    }


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
    observed_events = list(getattr(result, "observed_events", []) or [])
    all_event_types = event_types + observed_events
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
    account_or_position_changed = bool(balance_changed) or bool(positions_changed)

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
            "passed": (len(post_open_orders or []) == 0) if expectation.get("no_open_orders_after") else True,
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
        checks["account_position_change"] = {
            "expected": "allowed_if_trade",
            "balance_changed": balance_changed,
            "positions_changed": positions_changed,
            "trade_events": len(trade_events),
            "passed": True,
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
