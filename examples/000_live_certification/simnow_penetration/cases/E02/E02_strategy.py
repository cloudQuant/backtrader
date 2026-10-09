"""E02 — genuine venue rejection: insufficient position (close without position).

The case intentionally bypasses local validation — a close-direction order is
submitted although the pre-flight query first confirms there is no open
position, because the point is to let the venue itself reject the request (and
to prove no remainder is left behind).  One order is submitted once; its
rejection is recorded (PASS), or the accepted outcome is resolved bounded and
the case fails (``no_rejection_observed``).  No in-queue row may remain for
this OrderRef.

On engines without the position check the insert is accepted, and the
bid-priced close can even fill; that accepted/filled path now flattens any
resulting position back to zero (crossing opposite direction, offset 1,
bounded, marked closed) and reports the position after cleanup before
returning FAIL.

Success condition: the venue rejects the insert with error detail recorded
(native insert evidence or a venue order-query row) and no residual remains.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "E02"
RISK = "WRITE"

_IN_QUEUE = {"1", "3"}  # partial/no trade, still resting in the venue queue
_SETTLED = _IN_QUEUE | {"2", "4", "5"}


def _row_of(result, instrument):
    return next((row for row in result["rows"]
                 if str(row.get("InstrumentID")) == instrument), None)


def _quotes(ctx):
    """Query the instrument + depth rows and validate the price band."""
    client, instrument = ctx.client, ctx.contract["instrument"]
    row = _row_of(client.query_instruments(instrument_id=instrument,
                                           exchange_id=ctx.contract["exchange"]), instrument)
    if row is None:
        return None, CaseResult(CASE_ID, "BLOCKED", "instrument_not_found",
                                {"instrument": instrument})
    depth = _row_of(client.query_depth_market_data(instrument), instrument)
    if depth is None:
        return None, CaseResult(CASE_ID, "BLOCKED", "depth_unavailable",
                                {"instrument": instrument})
    lower = float(depth.get("LowerLimitPrice") or 0)
    upper = float(depth.get("UpperLimitPrice") or 0)
    if not (0 < lower < upper):
        return None, CaseResult(CASE_ID, "BLOCKED", "price_band_invalid",
                                {"lower": lower, "upper": upper})
    return (row, depth, float(row.get("PriceTick") or 1.0), lower, upper), None


def _snapshot(row):
    keys = ("OrderStatus", "VolumeTraded", "VolumeTotal", "LimitPrice", "VolumeTotalOriginal")
    out = {k: row[k] for k in keys if row.get(k) is not None}
    msg = str(row.get("StatusMsg") or "").strip()[:160]
    return {**out, "StatusMsg": msg} if msg else out


def _poll(client, instrument, order_ref, timeout, statuses):
    deadline, latest = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        for row in client.query_orders(instrument_id=instrument)["rows"]:
            if str(row.get("OrderRef")) == str(order_ref):
                latest = row
        if latest is not None and str(latest.get("OrderStatus") or "") in statuses:
            return latest
        time.sleep(0.5)
    return latest


def _residual(client, instrument, order_ref):
    """In-queue venue rows for our OrderRef; ``(None, error)`` if unchecked."""
    try:
        rows = client.query_orders(instrument_id=instrument)["rows"]
    except SimNowSessionError as exc:
        return None, str(exc.reason)
    return ([_snapshot(row) for row in rows
             if str(row.get("OrderRef")) == str(order_ref)
             and str(row.get("OrderStatus") or "") in _IN_QUEUE], None)


def _position_breakdown(client, instrument):
    """(long, short, rows) for the instrument; raises SimNowSessionError."""
    rows = client.query_positions(instrument_id=instrument)["rows"]
    long_qty = sum(int(float(r.get("Position") or 0)) for r in rows
                   if str(r.get("PosiDirection")) == "2")
    short_qty = sum(int(float(r.get("Position") or 0)) for r in rows
                    if str(r.get("PosiDirection")) == "3")
    return long_qty, short_qty, rows


def _flatten_position(ctx):
    """Bounded flatten of any position the accepted attempt left behind.

    If long: crossing SELL (offset 1) at BidPrice1; if short: crossing BUY
    (offset 1) at AskPrice1, for the full position size.  Waits terminal,
    marks the order closed and confirms Position == 0.  Never raises.
    """
    client = ctx.client
    instrument = ctx.contract["instrument"]
    exchange = ctx.contract["exchange"]
    hedge_flag = ctx.contract.get("hedge_flag") or "1"
    timeout = max(float(ctx.scenario().get("reject_timeout_ms") or 15000) / 1000.0, 20.0)
    try:
        long_qty, short_qty, _rows = _position_breakdown(client, instrument)
    except SimNowSessionError as exc:
        return {"position_check_error": str(exc.reason)}
    facts = {"long": long_qty, "short": short_qty}
    if long_qty <= 0 and short_qty <= 0:
        facts["skipped"] = "no_position"
        return facts
    depth = _row_of(client.query_depth_market_data(instrument), instrument)
    if depth is None:
        facts["error"] = "no_book"
        return facts
    if long_qty > 0:
        direction, level, volume = "1", float(depth.get("BidPrice1") or 0), long_qty
    else:
        direction, level, volume = "0", float(depth.get("AskPrice1") or 0), short_qty
    if level <= 0:
        facts["error"] = "no_book"
        return facts
    facts.update({"direction": direction, "offset_flag": "1",
                  "price": level, "volume": volume})
    try:
        placement = client.place_limit_order(
            instrument_id=instrument, exchange_id=exchange, direction=direction,
            offset_flag="1", price=level, volume=volume, hedge_flag=hedge_flag)
        ctx.track_order(instrument, placement["order_ref"], exchange_id=exchange)
        final = _poll(client, instrument, placement["order_ref"], timeout, {"0", "2", "4", "5"})
        status = str((final or {}).get("OrderStatus") or "")
        facts.update({"order_ref": placement["order_ref"], "status": status or "not_visible",
                      "volume_traded": (final or {}).get("VolumeTraded")})
        if status in {"0", "2", "4", "5"}:
            ctx.mark_order_closed(placement["order_ref"])
            client.mark_order_state(placement["order_ref"], "closed",
                                    str((final or {}).get("OrderSysID") or ""))
    except SimNowSessionError as exc:
        facts["error"] = str(exc.reason)
    try:
        long_after, short_after, _rows_after = _position_breakdown(client, instrument)
        facts["position_after"] = {"long": long_after, "short": short_after}
        facts["position_flat"] = long_after == 0 and short_after == 0
    except SimNowSessionError as exc:
        facts["position_after_error"] = str(exc.reason)
    return facts


def _cleanup_facts(ctx, facts):
    """Attach the bounded flatten + the post-cleanup position to facts."""
    facts["flatten"] = _flatten_position(ctx)
    try:
        long_qty, short_qty, _rows = _position_breakdown(ctx.client, ctx.contract["instrument"])
        facts["position_after_cleanup"] = {"long": long_qty, "short": short_qty}
    except SimNowSessionError as exc:
        facts["position_after_cleanup_error"] = str(exc.reason)
    return facts


def _native_result(ctx, facts, record):
    """PASS path: the venue deterministically rejected the insert."""
    evidence = record.get("evidence") or {}
    code = evidence.get("error_code")
    message = str(evidence.get("error_message") or "").strip()[:160]
    facts.update({"rejection_source": "native_evidence",
                  "evidence_status": str(evidence.get("status") or ""),
                  "error_code": code, "error_message": message,
                  "order_ref": facts.get("order_ref") or record.get("order_ref"),
                  "submit_code": record.get("submit_code"),
                  "callback_received": bool(evidence.get("callback_received"))})
    if code in (None, 0) and not message:
        return CaseResult(CASE_ID, "FAIL", "rejection_evidence_incomplete", facts)
    residual, residual_error = _residual(ctx.client, ctx.contract["instrument"],
                                         str(facts.get("order_ref") or ""))
    facts["residual_in_queue"] = None if residual_error else residual
    if residual_error:
        facts["residual_check_error"] = residual_error
    if residual:
        return CaseResult(CASE_ID, "FAIL", "cancel_residual_open", facts)
    return CaseResult(CASE_ID, "PASS", "", facts)


def _rejection_probe(ctx, *, rule, direction, offset_flag, price, volume, extra):
    """Arm, submit exactly once, and resolve the venue outcome of that order."""
    client = ctx.client
    instrument = ctx.contract["instrument"]
    exchange = ctx.contract["exchange"]
    timeout = float(ctx.scenario().get("reject_timeout_ms") or 15000) / 1000.0
    facts = dict(extra)
    facts.update({"rule": rule, "direction": direction, "offset_flag": offset_flag,
                  "price": float(price), "volume": int(volume), "dispatch_absent": False})

    identity = hashlib.sha256(
        (CASE_ID + json.dumps(ctx.config, sort_keys=True, default=str)).encode()).hexdigest()
    scope = {"case": CASE_ID, "instrument": instrument, "exchange": exchange,
             "pair_index": client.pair.index,
             "generation": client.login_facts.get("connection_generation"),
             "trading_day": client.login_facts.get("trading_day")}
    preflight = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    client.arm(instrument_id=instrument, exchange_id=exchange, strategy_identity_sha256=identity,
               execution_cycle_id=f"{CASE_ID}-{int(time.time())}", preflight_sha256=preflight)
    ctx.log(f"armed; submitting one {direction}/{offset_flag} {volume}@{price}")

    try:
        placement = client.place_limit_order(
            instrument_id=instrument, exchange_id=exchange, direction=direction,
            offset_flag=offset_flag, price=price, volume=volume,
            hedge_flag=ctx.contract.get("hedge_flag") or "1")
    except SimNowSessionError as exc:
        if exc.reason == "order_rejected":
            return _native_result(ctx, facts, dict(exc.facts))
        if exc.reason != "order_outcome_unknown":
            raise
        facts["place_error"] = str(exc.reason)
        order_ref = str(exc.facts.get("order_ref") or "")
        if not order_ref:
            return CaseResult(CASE_ID, "UNKNOWN", "order_outcome_unknown", facts)
    else:
        order_ref = str(placement.get("order_ref") or "")
        facts["submit_code"] = placement.get("submit_code")
        if str((placement.get("evidence") or {}).get("status") or "") == "rejected":
            return _native_result(ctx, facts, dict(placement))
    facts["order_ref"] = order_ref
    ctx.track_order(instrument, order_ref, exchange_id=exchange)
    ctx.log(f"order {order_ref} was not deterministically rejected; confirming at the venue")

    row = _poll(client, instrument, order_ref, timeout, _SETTLED)
    status = str((row or {}).get("OrderStatus") or "")
    facts["venue_status"] = status or "not_visible"
    if row is not None:
        facts["venue_row"] = _snapshot(row)
    order_sys_id = str((row or {}).get("OrderSysID") or "")
    terminal = status in {"2", "4", "5"}
    if row is not None and status in _IN_QUEUE:
        cancel = {"order_sys_id": order_sys_id}
        try:
            reply = client.cancel_order(instrument_id=instrument, exchange_id=exchange,
                                        order_ref=order_ref, order_sys_id=order_sys_id)
            cancel["submit_code"] = reply.get("submit_code")
            final = _poll(client, instrument, order_ref, max(timeout, 20.0), {"2", "4", "5"})
            final_status = str((final or {}).get("OrderStatus") or "")
            cancel["final_status"] = final_status or "timeout"
            terminal = final_status in {"2", "4", "5"}
        except SimNowSessionError as exc:
            cancel["error"] = str(exc.reason)
        facts["cancel"] = cancel
    traded = int(float((row or {}).get("VolumeTraded") or 0))
    residual, residual_error = _residual(client, instrument, order_ref)
    facts["residual_in_queue"] = None if residual_error else residual
    if residual_error:
        facts["residual_check_error"] = residual_error
    if residual:
        return CaseResult(CASE_ID, "FAIL", "cancel_residual_open", facts)
    if terminal:
        ctx.mark_order_closed(order_ref)
        client.mark_order_state(order_ref, "closed", order_sys_id)
    if row is None:
        return CaseResult(CASE_ID, "UNKNOWN", "order_outcome_unknown", facts)
    if status in _IN_QUEUE:
        return CaseResult(CASE_ID, "FAIL", "no_rejection_observed", _cleanup_facts(ctx, facts))
    if status == "5" and traded == 0:
        facts.update({"rejection_source": "venue_query",
                      "evidence_status": "canceled_without_trade", "error_code": None,
                      "error_message": str(row.get("StatusMsg") or "").strip()[:160]})
        return CaseResult(CASE_ID, "PASS", "", facts)
    if traded > 0 or status in {"2", "4"}:
        # The accepted attempt opened a position (unexpected without the
        # position check): flatten it before returning FAIL.
        return CaseResult(CASE_ID, "FAIL", "no_rejection_observed", _cleanup_facts(ctx, facts))
    return CaseResult(CASE_ID, "UNKNOWN", "order_outcome_unknown", facts)


class E02Strategy:
    def run(self, ctx):
        quotes, blocked = _quotes(ctx)
        if blocked is not None:
            return blocked
        _, depth, tick, lower, upper = quotes

        # A close-direction order (offset flag 1) needs an open position.
        # Verify none exists first, so this case can never leave a remainder.
        positions = ctx.client.query_positions(ctx.contract["instrument"])
        held = [r for r in positions["rows"] if float(r.get("Position") or 0) > 0]
        if held:
            return CaseResult(CASE_ID, "BLOCKED", "existing_position_present",
                              {"position_rows": len(held),
                               "max_position": max(float(r.get("Position") or 0) for r in held)})

        # Deliberately invalid-for-position request: sell-to-close with no
        # position.  The price rests at BidPrice1 (or the band center when no
        # market data is available); no local position check intervenes.
        bid = float(depth.get("BidPrice1") or 0)
        base = bid if bid > 0 else (lower + upper) / 2
        price = round(base / tick) * tick if tick > 0 else base
        price = round(max(lower, min(upper, price)), 6)

        return _rejection_probe(
            ctx, rule="insufficient_position", direction="1", offset_flag="1",
            price=price, volume=1,
            extra={"price_band": {"lower": lower, "upper": upper}, "bid_price1": bid,
                   "price_source": "bid_price1" if bid > 0 else "band_center"})
