"""Thin injected driver for a caller-owned real SimNow mechanical session.

This module is deliberately not a CTP client, authorizer, preflight runner, or
strategy.  The caller must already have completed preflight and arming and must
provide a started ``SimNowMechanicalSession`` backed by a started broker.  The
driver only drains public broker notifications, forwards them to the session,
plans exits from caller-supplied fresh prices, and requires two final flat
reconciliation snapshots.  It never creates a client, reads credentials, or
simulates fills.  ``MECHANICAL_PASS`` is execution-path evidence only; it is
not strategy profitability evidence and does not admit Iter25 HFT activity.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable, Mapping


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _safe_reason(exc: BaseException) -> str:
    return type(exc).__name__ or "driver_error"


def _journal_projection(journal: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(journal, (list, tuple)):
        return ()
    result = []
    for row in journal:
        if not isinstance(row, Mapping):
            continue
        projected = {"status": str(row.get("status") or "UNKNOWN")}
        for key in ("intent_id_hash", "bt_ref_hash"):
            value = row.get(key)
            if isinstance(value, str) and len(value) == 64:
                projected[key] = value
        result.append(projected)
    return tuple(result)


def _notification_key(notification: Any) -> tuple[Any, ...]:
    """Build an internal duplicate key without exposing native identifiers."""
    ref = getattr(notification, "ref", None)
    info = getattr(notification, "info", None)
    values = []
    for key in ("trade_id", "TradeID", "order_sys_id", "OrderSysID"):
        value = getattr(notification, key, None)
        if value in (None, "") and info is not None:
            value = getattr(info, key, None)
            if value in (None, "") and hasattr(info, "get"):
                value = info.get(key)
        if value not in (None, ""):
            values.append((key, str(value)))
    if ref not in (None, ""):
        return ("ref", str(ref), *values)
    if values:
        return tuple(values)
    return ("object", id(notification))


def _result(
    *,
    status: str,
    phase: str,
    journal: Any,
    notifications: int,
    duplicate_notifications: int,
    cancel_requests: int,
    reason: str | None = None,
) -> dict[str, Any]:
    safe_journal = _journal_projection(journal)
    result = {
        "status": status,
        "phase": phase,
        "journal": [dict(row) for row in safe_journal],
        "journal_sha256": _hash(safe_journal),
        "journal_event_count": len(safe_journal),
        "notification_count": notifications,
        "duplicate_notification_count": duplicate_notifications,
        "cancel_request_count": cancel_requests,
        "native_fill_count": sum(row["status"] == "NATIVE_FILL_CONFIRMED" for row in safe_journal),
    }
    if reason:
        result["reason"] = reason
    return result


def drive_simnow_mechanical_session(
    *,
    broker: Any,
    session: Any,
    fresh_exit_prices: Callable[
        [], Mapping[str, Any] | tuple[Mapping[str, Any], Mapping[str, Any]]
    ],
    reconciliation_snapshot: Callable[[], Mapping[str, Any]],
    leg_timeout: float = 30.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    exit_intent_id: str = "simnow-mechanical-exit",
) -> dict[str, Any]:
    """Drive one already-armed, already-started three-leg mechanical session.

    ``fresh_exit_prices`` must return either ``prices`` or
    ``(prices, reference_snapshot)``.  The latter is passed to the public
    session ``plan_exit`` contract.  ``reconciliation_snapshot`` is called
    exactly twice only after all close fills are natively confirmed.
    """
    if not callable(getattr(broker, "next", None)) or not callable(
        getattr(broker, "get_notification", None)
    ):
        return _result(
            status="RECOVERY_REQUIRED",
            phase="UNKNOWN",
            journal=(),
            notifications=0,
            duplicate_notifications=0,
            cancel_requests=0,
            reason="BROKER_PUBLIC_NOTIFICATION_INTERFACE_REQUIRED",
        )
    for name in (
        "on_order_update",
        "plan_exit",
        "submit_next_exit",
        "timeout",
        "cancel_pending",
        "finalize_flat",
    ):
        if not callable(getattr(session, name, None)):
            return _result(
                status="RECOVERY_REQUIRED",
                phase="UNKNOWN",
                journal=(),
                notifications=0,
                duplicate_notifications=0,
                cancel_requests=0,
                reason=f"SESSION_PUBLIC_{name.upper()}_REQUIRED",
            )
    if not isinstance(leg_timeout, (int, float)) or leg_timeout <= 0:
        return _result(
            status="RECOVERY_REQUIRED",
            phase="UNKNOWN",
            journal=(),
            notifications=0,
            duplicate_notifications=0,
            cancel_requests=0,
            reason="LEG_TIMEOUT_INVALID",
        )

    seen_notifications: set[tuple[Any, ...]] = set()
    notifications = duplicate_notifications = cancel_requests = 0
    entry_fill_count = 0
    close_fill_count = 0
    phase = "OPEN"
    deadline = monotonic() + float(leg_timeout)
    exit_planned = False
    cancel_sent_for_deadline = False
    journal: tuple[dict[str, Any], ...] = ()

    def fail(reason: str) -> dict[str, Any]:
        return _result(
            status="RECOVERY_REQUIRED",
            phase=phase,
            journal=journal,
            notifications=notifications,
            duplicate_notifications=duplicate_notifications,
            cancel_requests=cancel_requests,
            reason=reason,
        )

    while True:
        try:
            broker.next()
            while True:
                notification = broker.get_notification()
                if notification is None:
                    break
                key = _notification_key(notification)
                if key in seen_notifications:
                    duplicate_notifications += 1
                    continue
                seen_notifications.add(key)
                notifications += 1
                status = session.on_order_update(notification)
                if not isinstance(status, Mapping):
                    return fail("SESSION_STATUS_INVALID")
                journal = _journal_projection(status.get("journal"))
                phase = str(status.get("phase") or phase)
                if str(status.get("status") or "").upper() == "RECOVERY_REQUIRED":
                    return fail("SESSION_RECOVERY_REQUIRED")
                fill_count = sum(row["status"] == "NATIVE_FILL_CONFIRMED" for row in journal)
                if phase == "OPEN":
                    entry_fill_count = fill_count
                elif phase == "CLOSE":
                    close_fill_count = max(close_fill_count, fill_count - entry_fill_count)
                if phase == "OPEN" and not status.get("pending") and entry_fill_count == 3:
                    if not exit_planned:
                        fresh = fresh_exit_prices()
                        if isinstance(fresh, tuple) and len(fresh) == 2:
                            prices, reference = fresh
                        else:
                            prices, reference = fresh, {}
                        if not isinstance(prices, Mapping) or not isinstance(reference, Mapping):
                            return fail("EXIT_PRICE_EVIDENCE_INVALID")
                        session.plan_exit(
                            prices,
                            intent_id=exit_intent_id,
                            reference_snapshot=reference,
                        )
                        session.submit_next_exit()
                        exit_planned = True
                        phase = "CLOSE"
                        deadline = monotonic() + float(leg_timeout)
                        cancel_sent_for_deadline = False
                elif phase == "CLOSE" and not status.get("pending") and close_fill_count >= 3:
                    first = reconciliation_snapshot()
                    second = reconciliation_snapshot()
                    final = session.finalize_flat(first, second)
                    if not isinstance(final, Mapping) or final.get("status") != "MECHANICAL_PASS":
                        return fail("FINAL_RECONCILIATION_NOT_PASS")
                    journal = _journal_projection(final.get("journal", journal))
                    return _result(
                        status="MECHANICAL_PASS",
                        phase="CLOSE",
                        journal=journal,
                        notifications=notifications,
                        duplicate_notifications=duplicate_notifications,
                        cancel_requests=cancel_requests,
                    )
                deadline = monotonic() + float(leg_timeout) if status.get("pending") else deadline
        except Exception as exc:
            return fail(_safe_reason(exc))

        now = monotonic()
        if now >= deadline:
            if not cancel_sent_for_deadline:
                try:
                    session.cancel_pending()
                    cancel_requests += 1
                except Exception:
                    pass
                cancel_sent_for_deadline = True
            try:
                session.timeout()
            except Exception:
                pass
            return fail("LEG_TIMEOUT_RECOVERY_REQUIRED")
        sleep(min(max(deadline - now, 0.0), 0.05))


__all__ = ["drive_simnow_mechanical_session"]
