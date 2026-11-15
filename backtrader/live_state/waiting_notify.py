"""Typed, bounded pause notices for waiting orders (iteration 67.07, D67-15/17).

A waiting order that cannot be resumed because its calendar binding cannot be
proven keeps its status, original target and identity (``waiting.py`` records
the reason as ``facts.calendar_disposition``).  This module builds one small
typed event per pause and hands it to the repository's existing notification
layer, :mod:`backtrader.notifications`.

The existing layer fits and is therefore reused unchanged instead of inventing
a channel:

* opt-in and silent by default - nothing is sent until
  ``bt.configure_notifications`` was called;
* asynchronous with one bounded queue per channel, so the enqueue path never
  blocks the caller;
* delivery problems are classified and returned in
  :class:`~backtrader.notifications.SendResult`, never raised into caller code;
* ``dedup_key`` is supported.

This module adds only what live state needs: a fixed payload shape, a bounded
text and a *finite* local status.  No SMTP/HTTP/WebSocket client is added here
and no delivery guarantee is claimed.

A pause notice is an operator hint, **not a trading authorization**: it never
changes an order's status, target, identity or sequence, and a successful send
does not clear a pause.  Pauses are only cleared by an explicit operator action
with current calendar evidence (``WaitingOrderStore.clear_calendar_pause``).
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Optional

__all__ = (
    "PAUSE_EVENT_KIND",
    "PAUSE_NOTIFICATION_STATUSES",
    "PAUSE_TEXT_LIMIT",
    "build_pause_event",
    "compose_pause_text",
    "notify_pause_event",
    "pause_dedup_key",
)

PAUSE_EVENT_KIND = "waiting_order_calendar_pause"
PAUSE_TEXT_LIMIT = 600
_TRUNCATION_MARK = "\n[truncated]"

#: The finite ``facts.pause_notification_status`` / return values of a pause
#: notice.  ``pending`` is stored before the send so a crash mid-send is
#: visible; it is not a delivery claim.
PAUSE_NOTIFICATION_STATUSES = frozenset(
    {
        "accepted",  # at least one configured channel accepted/queued the message
        "not_configured",  # notifications are opt-in and were never configured
        "no_channels",  # configured without any usable channel instance
        "queue_full",  # a channel queue dropped the message
        "worker_silent",  # a child process is not allowed to send
        "deduped",  # the notifier suppressed it inside its own cooldown
        "failed",  # a synchronous send failed
        "error",  # unexpected notifier problem (never raised to the caller)
        "pending",  # stored, send not yet attempted/finished (crash window)
    }
)


def pause_dedup_key(waiting_id: str, disposition: str, version: str) -> str:
    """Durable dedupe key: one notice per order + reason + calendar version."""
    token = hashlib.sha256(str(version).encode("utf-8")).hexdigest()[:16]
    return f"bt-waiting-pause:{waiting_id}:{disposition}:{token}"


def _target_version(order: Mapping[str, Any], disposition: str, observed: Optional[str]) -> str:
    """The calendar version a pause notice is *about*; never invented."""
    if observed is not None:
        return observed
    target = order.get("target_session") or {}
    reference = target.get("calendar_ref")
    if type(reference) is str and reference:
        return reference
    # No version was ever stored (legacy/unbound) or none is readable; the
    # disposition itself keeps the key finite and stable.
    return disposition


def build_pause_event(
    order: Mapping[str, Any],
    strategy_uuid: str,
    disposition: str,
    observed_calendar_ref: Optional[str],
) -> dict:
    """Return the fixed, JSON-safe pause event for one waiting order."""
    version = _target_version(order, disposition, observed_calendar_ref)
    return {
        "kind": PAUSE_EVENT_KIND,
        "strategy_uuid": strategy_uuid,
        "waiting_id": order["waiting_id"],
        "local_seq": order["local_seq"],
        "bt_ref": order.get("bt_ref"),
        "symbol": order["symbol"],
        "exchange_name": order["exchange_name"],
        "side": order["side"],
        "size": order["size"],
        "exectype": order["exectype"],
        "status": order["status"],
        "disposition": disposition,
        "observed_calendar_ref": observed_calendar_ref,
        "target_session": dict(order["target_session"]),
        "version": version,
        "dedup_key": pause_dedup_key(order["waiting_id"], disposition, version),
    }


def compose_pause_text(event: Mapping[str, Any]) -> str:
    """Bounded human-readable body; no account id or credential is added."""
    target = event.get("target_session") or {}
    reference = target.get("calendar_ref") or "unbound"
    observed = event.get("observed_calendar_ref") or "unavailable"
    text = (
        "waiting order paused: {disposition}\n"
        "order {waiting_id} local_seq={local_seq} {symbol} {exchange_name} "
        "{side} {size} {exectype} (status {status})\n"
        "original target {trading_day} {start}..{end} calendar_ref={reference}\n"
        "observed calendar_ref={observed}\n"
        "status kept, original target kept, not re-sent. Operator review "
        "required; this notice is not a trading authorization."
    ).format(
        disposition=event.get("disposition"),
        waiting_id=event.get("waiting_id"),
        local_seq=event.get("local_seq"),
        symbol=event.get("symbol"),
        exchange_name=event.get("exchange_name"),
        side=event.get("side"),
        size=event.get("size"),
        exectype=event.get("exectype"),
        status=event.get("status"),
        trading_day=target.get("trading_day"),
        start=target.get("continuous_start_utc"),
        end=target.get("session_end_utc"),
        reference=reference,
        observed=observed,
    )
    if len(text) <= PAUSE_TEXT_LIMIT:
        return text
    keep = PAUSE_TEXT_LIMIT - len(_TRUNCATION_MARK)
    return text[:keep] + _TRUNCATION_MARK


def status_from_result(result: Any) -> str:
    """Map a :class:`SendResult`-like object to a finite status."""
    if getattr(result, "accepted", False):
        return "accepted"
    outcomes = getattr(result, "outcomes", ()) or ()
    categories = [getattr(item, "error_category", None) for item in outcomes]
    if categories and all(category == "deduped" for category in categories):
        return "deduped"
    reason = getattr(result, "reason", None)
    if reason in PAUSE_NOTIFICATION_STATUSES and reason != "pending":
        return reason
    return "error"


def notify_pause_event(event: Mapping[str, Any]) -> str:
    """Send one pause event through the configured notification channels.

    Returns a member of :data:`PAUSE_NOTIFICATION_STATUSES`; never raises.  A
    not-configured notifier is silent by design and reports
    ``"not_configured"``, which is a fact, not a delivery claim.
    """
    try:
        from backtrader.notifications import send_message
    except Exception:  # pragma: no cover - import problems must not escape
        return "error"
    try:
        result = send_message(
            compose_pause_text(event),
            title="backtrader waiting order paused",
            level="warning",
            dedup_key=event["dedup_key"],
        )
    except Exception:
        # send_message itself is documented not to raise for delivery problems;
        # anything else stays inside this function.
        return "error"
    return status_from_result(result)
