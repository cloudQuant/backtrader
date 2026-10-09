"""E01 — insufficient-funds rejection: SAFE bounded attempt, honest BLOCKED.

Live SimNow 7x24 observation: the engine does not enforce funds within the
reachable order sizes — the single-order cap (``MaxLimitOrderVolume``) keeps
the margin well below the account's Available balance, and oversized
accumulation crosses and fills instantly — so an insufficient-funds rejection
is NOT producible within bounded safety.

The case therefore runs one SAFE bounded attempt: ONE buy for
``scenario.attempt_volume`` (clamped to the instrument cap) at a NON-crossing
resting price (``lower + tick``), which queues without fill churn, is recorded
and then canceled to terminal state 5.  The PASS path is unchanged for
environments that DO reject: the venue's insert evidence or the venue-query
canceled-without-trade row is recorded.  Otherwise the case returns
BLOCKED(``insufficient_funds_rejection_not_reachable``) with the queried
account funds row (Balance/Available/CurrMargin), the attempt details and the
engine observations.  No in-queue row may remain for this OrderRef.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "E01"
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


def _account_funds(ctx):
    """Balance/Available/CurrMargin from the account query; {} when unchecked."""
    try:
        rows = ctx.client.query_account()["rows"]
    except SimNowSessionError as exc:
        return {"error": str(exc.reason)}
    row = dict(rows[0]) if rows else {}
    funds = {k: row.get(k) for k in ("Balance", "Available", "CurrMargin")}
    funds["row_count"] = len(rows)
    return funds


def _flatten_position(ctx):
    """Best-effort bounded flatten of any position the attempt opened.

    The bounded attempt rests at the band floor, so a fill is not expected;
    this guard only matters on engines that fill it anyway.  Never raises.
    """
    client = ctx.client
    instrument = ctx.contract["instrument"]
    exchange = ctx.contract["exchange"]
    hedge_flag = ctx.contract.get("hedge_flag") or "1"
    timeout = max(float(ctx.scenario().get("reject_timeout_ms") or 15000) / 1000.0, 20.0)
    try:
        rows = client.query_positions(instrument_id=instrument)["rows"]
    except SimNowSessionError as exc:
        return {"position_check_error": str(exc.reason)}
    long_qty = sum(int(float(r.get("Position") or 0)) for r in rows
                   if str(r.get("PosiDirection")) == "2")
    short_qty = sum(int(float(r.get("Position") or 0)) for r in rows
                    if str(r.get("PosiDirection")) == "3")
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
        rows_after = client.query_positions(instrument_id=instrument)["rows"]
        facts["position_after"] = sum(int(float(r.get("Position") or 0)) for r in rows_after
                                      if str(r.get("PosiDirection")) in ("2", "3"))
    except SimNowSessionError as exc:
        facts["position_after_error"] = str(exc.reason)
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
        # The bounded resting attempt was accepted and canceled without any
        # venue funds rejection: the rejection is not reachable this way.
        facts.update({"accepted_without_rejection": True, "attempt_status": status,
                      "attempt_volume_traded": traded,
                      "cancel_terminal_status": str(
                          (facts.get("cancel") or {}).get("final_status") or "")})
        facts["engine_observations"] = {
            **facts.get("engine_observations", {}),
            "outcome": "accepted_without_funds_rejection"}
        return CaseResult(CASE_ID, "BLOCKED", "insufficient_funds_rejection_not_reachable", facts)
    if status == "5" and traded == 0:
        facts.update({"rejection_source": "venue_query",
                      "evidence_status": "canceled_without_trade", "error_code": None,
                      "error_message": str(row.get("StatusMsg") or "").strip()[:160]})
        return CaseResult(CASE_ID, "PASS", "", facts)
    if traded > 0:
        # An unexpected fill on the resting price: flatten it before reporting.
        facts.update({"accepted_without_rejection": True, "attempt_status": status,
                      "attempt_volume_traded": traded,
                      "flatten": _flatten_position(ctx)})
        facts["engine_observations"] = {
            **facts.get("engine_observations", {}),
            "outcome": "filled_without_funds_rejection"}
        return CaseResult(CASE_ID, "BLOCKED", "insufficient_funds_rejection_not_reachable", facts)
    if status in {"2", "4"}:
        facts.update({"accepted_without_rejection": True, "attempt_status": status,
                      "attempt_volume_traded": traded})
        facts["engine_observations"] = {
            **facts.get("engine_observations", {}),
            "outcome": "accepted_without_funds_rejection"}
        return CaseResult(CASE_ID, "BLOCKED", "insufficient_funds_rejection_not_reachable", facts)
    return CaseResult(CASE_ID, "UNKNOWN", "order_outcome_unknown", facts)


class E01Strategy:
    def run(self, ctx):
        scenario = ctx.scenario()
        quotes, blocked = _quotes(ctx)
        if blocked is not None:
            return blocked
        row, depth, tick, lower, upper = quotes

        last = float(depth.get("LastPrice") or 0)
        if last <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "last_price_unavailable", {"last_price": last})

        # SAFE bounded attempt: the live engine draws no funds rejection inside
        # the reachable order size (the single-order cap keeps the margin well
        # below Available; oversized accumulation fills instantly).  The ONE
        # buy is sized to the attempt volume (clamped to the instrument cap)
        # and rests at a NON-crossing price (lower band + one tick): it draws a
        # genuine venue rejection when one exists (PASS, unchanged), otherwise
        # it queues without fill churn until canceled and the case reports an
        # honest BLOCKED with the observed account funds and engine facts.
        attempt_volume = int(float(scenario.get("attempt_volume") or 1000))
        max_volume = int(float(row.get("MaxLimitOrderVolume") or 0))
        volume = min(attempt_volume, max_volume) if max_volume > 0 else attempt_volume
        price = round(lower + tick, 6)
        multiple = float(row.get("VolumeMultiple") or 0)
        observations = {
            "single_order_cap_lots": max_volume or None,
            "attempt_volume_requested": attempt_volume,
            "attempt_volume_placed": volume,
            "attempt_notional_yuan": (round(price * multiple * volume, 2)
                                      if multiple > 0 else None),
            "funds_enforcement": "not_observed",
            "note": ("single-order cap bounds the attempt; acceptance without a funds "
                     "rejection is recorded when observed"),
        }

        return _rejection_probe(
            ctx, rule="insufficient_funds", direction="0", offset_flag="0",
            price=price, volume=volume,
            extra={"price_band": {"lower": lower, "upper": upper}, "last_price": last,
                   "max_limit_order_volume": row.get("MaxLimitOrderVolume"),
                   "attempt_volume": attempt_volume, "attempt_price": price,
                   "account_funds": _account_funds(ctx),
                   "engine_observations": observations})
