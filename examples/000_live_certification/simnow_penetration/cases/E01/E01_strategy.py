"""E01 — insufficient-funds rejection: bounded multi-attempt resting probe.

Funds are enforced only once accumulated resting margin exceeds Available,
so one resting buy (clamped to the instrument cap) can never provoke the
rejection: this case places up to ``scenario.max_attempts`` buys at a
strictly NON-crossing price inside the band (``lower + tick``) until the
venue rejects the insert (the genuine insufficient-funds rejection, PASS).

Attempts classify as rejected (native evidence → PASS), accepted in-queue
(continue) or not visible in the accept window (recorded, continue);
accepted orders are tracked immediately, all are canceled to terminal state
5, and a residual sweep runs before returning.  If all bounded attempts are
accepted — no rejection surfaced — the case returns an honest
BLOCKED(``insufficient_funds_rejection_not_reachable``) with account funds,
per-attempt notional observations (price*volume*ct_multiplier when known)
and the attempt list; facts never carry broker/user/account identity
strings.
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
_FINISHED = {"0", "2", "4", "5"}  # traded out, canceled, or no longer queueing
_SETTLED = _IN_QUEUE | _FINISHED


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


def _residual(client, instrument, order_refs):
    """In-queue venue rows for the given OrderRef(s); ``(None, error)`` when
    the venue query itself failed."""
    refs = {str(r) for r in ([order_refs] if isinstance(order_refs, str) else order_refs) if r}
    if not refs:
        return [], None
    try:
        rows = client.query_orders(instrument_id=instrument)["rows"]
    except SimNowSessionError as exc:
        return None, str(exc.reason)
    return ([_snapshot(row) for row in rows
             if str(row.get("OrderRef")) in refs
             and str(row.get("OrderStatus") or "") in _IN_QUEUE], None)


def _account_funds(ctx):
    """Balance/Available/CurrMargin from the account query; {} when unchecked."""
    try:
        rows = ctx.client.query_account()["rows"]
    except SimNowSessionError as exc:
        return {"error": str(exc.reason)}
    row = dict(rows[0]) if rows else {}
    return {**{k: row.get(k) for k in ("Balance", "Available", "CurrMargin")},
            "row_count": len(rows)}


def _flatten_position(ctx):
    """Best-effort bounded flatten of any position the attempts opened."""
    client, instrument = ctx.client, ctx.contract["instrument"]
    exchange = ctx.contract["exchange"]
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
        return {**facts, "skipped": "no_position"}
    depth = _row_of(client.query_depth_market_data(instrument), instrument) or {}
    direction = "1" if long_qty > 0 else "0"
    level = float(depth.get("BidPrice1" if long_qty > 0 else "AskPrice1") or 0)
    volume = long_qty or short_qty
    if level <= 0:
        return {**facts, "error": "no_book"}
    facts.update({"direction": direction, "offset_flag": "1", "price": level, "volume": volume})
    try:
        placement = client.place_limit_order(
            instrument_id=instrument, exchange_id=exchange, direction=direction,
            offset_flag="1", price=level, volume=volume,
            hedge_flag=ctx.contract.get("hedge_flag") or "1")
        ctx.track_order(instrument, placement["order_ref"], exchange_id=exchange)
        final = _poll(client, instrument, placement["order_ref"], timeout, _FINISHED)
        status = str((final or {}).get("OrderStatus") or "")
        facts.update({"order_ref": placement["order_ref"], "status": status or "not_visible",
                      "volume_traded": (final or {}).get("VolumeTraded")})
        if status in _FINISHED:
            ctx.mark_order_closed(placement["order_ref"])
            client.mark_order_state(placement["order_ref"], "closed",
                                    str((final or {}).get("OrderSysID") or ""))
    except SimNowSessionError as exc:
        facts["error"] = str(exc.reason)
    try:
        after = client.query_positions(instrument_id=instrument)["rows"]
        facts["position_after"] = sum(int(float(r.get("Position") or 0)) for r in after
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


def _arm(ctx):
    """Arm once for the whole probe: the engine allows one arm per instrument."""
    client = ctx.client
    instrument, exchange = ctx.contract["instrument"], ctx.contract["exchange"]
    identity = hashlib.sha256(
        (CASE_ID + json.dumps(ctx.config, sort_keys=True, default=str)).encode()).hexdigest()
    scope = {"case": CASE_ID, "instrument": instrument, "exchange": exchange,
             "pair_index": client.pair.index,
             "generation": client.login_facts.get("connection_generation"),
             "trading_day": client.login_facts.get("trading_day")}
    preflight = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()
    return client.arm(instrument_id=instrument, exchange_id=exchange,
                      strategy_identity_sha256=identity,
                      execution_cycle_id=f"{CASE_ID}-{int(time.time())}",
                      preflight_sha256=preflight)


def _submit_attempt(ctx, price, volume, timeout):
    """Place ONE resting buy; returns ``(entry, rejection)`` (record or None)."""
    client, instrument = ctx.client, ctx.contract["instrument"]
    exchange = ctx.contract["exchange"]
    entry = {"submit_code": None, "evidence_status": "none", "error_code": None,
             "error_message": "", "order_ref": "", "venue_status": "not_visible",
             "outcome": "not_visible"}
    try:
        placement = client.place_limit_order(
            instrument_id=instrument, exchange_id=exchange, direction="0",
            offset_flag="0", price=price, volume=volume,
            hedge_flag=ctx.contract.get("hedge_flag") or "1")
    except SimNowSessionError as exc:
        if exc.reason == "order_rejected":
            record = dict(exc.facts)
            evidence = record.get("evidence") or {}
            entry.update({"submit_code": record.get("submit_code"),
                          "evidence_status": str(evidence.get("status") or ""),
                          "error_code": evidence.get("error_code"),
                          "error_message": str(evidence.get("error_message") or "").strip()[:160],
                          "order_ref": str(record.get("order_ref") or ""),
                          "venue_status": "rejected", "outcome": "rejected"})
            return entry, record
        if exc.reason != "order_outcome_unknown":
            raise
        entry["place_error"] = str(exc.reason)
        order_ref = str(exc.facts.get("order_ref") or "")
        if not order_ref:
            entry["outcome"] = "order_outcome_unknown"
            return entry, None
    else:
        order_ref = str(placement.get("order_ref") or "")
        evidence = placement.get("evidence") or {}
        entry.update({"submit_code": placement.get("submit_code"),
                      "evidence_status": str(evidence.get("status") or "")})
        if entry["evidence_status"] == "rejected":
            entry.update({"error_code": evidence.get("error_code"),
                          "error_message": str(evidence.get("error_message") or "").strip()[:160],
                          "order_ref": order_ref, "venue_status": "rejected",
                          "outcome": "rejected"})
            return entry, dict(placement)
    entry["order_ref"] = order_ref
    # Track accepted orders immediately; a resting order must be cancelable.
    ctx.track_order(instrument, order_ref, exchange_id=exchange)
    row = _poll(client, instrument, order_ref, timeout, _SETTLED)
    if row is None:
        entry["outcome"] = "not_visible"
        return entry, None
    status = str(row.get("OrderStatus") or "")
    traded = int(float(row.get("VolumeTraded") or 0))
    entry.update({"venue_status": status, "volume_traded": traded,
                  "order_sys_id": str(row.get("OrderSysID") or "")})
    if status in _IN_QUEUE:
        entry["outcome"] = "accepted"
    else:
        entry["outcome"] = "accepted_filled" if traded > 0 else "terminal_without_trade"
        ctx.mark_order_closed(order_ref)
        client.mark_order_state(order_ref, "closed", entry["order_sys_id"])
    return entry, None


def _cancel_accepted(ctx, facts, attempts, timeout):
    """Cancel every non-terminal attempt order to terminal state, then sweep."""
    client, instrument = ctx.client, ctx.contract["instrument"]
    exchange = ctx.contract["exchange"]
    results = []
    for entry in attempts:
        if entry.get("outcome") not in ("accepted", "not_visible"):
            continue
        order_ref = str(entry.get("order_ref") or "")
        if not order_ref:
            continue
        item = {"order_ref": order_ref, "venue_status": entry.get("venue_status")}
        try:
            reply = client.cancel_order(
                instrument_id=instrument, exchange_id=exchange, order_ref=order_ref,
                order_sys_id=str(entry.get("order_sys_id") or ""))
            item["submit_code"] = reply.get("submit_code")
            final = _poll(client, instrument, order_ref, timeout, _FINISHED)
            status = str((final or {}).get("OrderStatus") or "")
            item["final_status"] = status or "timeout"
            if status in _FINISHED:
                ctx.mark_order_closed(order_ref)
                client.mark_order_state(order_ref, "closed",
                                        str((final or {}).get("OrderSysID") or ""))
        except SimNowSessionError as exc:
            item["error"] = str(exc.reason)
        results.append(item)
    facts["canceled_accepted"] = results
    residual, error = _residual(client, instrument, [e.get("order_ref") for e in attempts])
    facts["accepted_residual_in_queue"] = None if error else residual
    if error:
        facts["accepted_residual_check_error"] = error
    return residual


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

        attempt_volume = int(float(scenario.get("attempt_volume") or 1000))
        max_attempts = int(scenario.get("max_attempts", 5))
        max_volume = int(float(row.get("MaxLimitOrderVolume") or 0))
        volume = min(attempt_volume, max_volume) if max_volume > 0 else attempt_volume
        price = round(lower + tick, 6)
        multiple = float(row.get("VolumeMultiple") or 0)
        timeout = float(scenario.get("reject_timeout_ms") or 15000) / 1000.0
        unit_notional = round(price * (multiple if multiple > 0 else 1) * volume, 2)
        facts = {
            "rule": "insufficient_funds", "direction": "0", "offset_flag": "0",
            "dispatch_absent": False, "price_band": {"lower": lower, "upper": upper},
            "last_price": last, "max_limit_order_volume": row.get("MaxLimitOrderVolume"),
            "attempt_volume": attempt_volume, "attempt_price": price,
            "attempt_volume_placed": volume, "volume": volume, "price": price,
            "max_attempts": max_attempts, "ct_multiplier": multiple or None,
            "engine_observations": {
                "single_order_cap_lots": max_volume or None,
                "attempt_volume_requested": attempt_volume, "attempt_volume_placed": volume,
                "attempt_notional_yuan": unit_notional, "funds_enforcement": "not_observed",
                "note": "funds enforced only after accumulated resting margin exceeds Available"}}
        _arm(ctx)
        ctx.log(f"armed; up to {max_attempts} resting buys of {volume}@{price}")

        # Bounded probe: each accepted resting buy locks more margin; the
        # venue rejects the insert once Available is exhausted.
        attempts, available = [], []
        for index in range(1, max_attempts + 1):
            funds = _account_funds(ctx)
            available.append(funds)
            ctx.log(f"attempt {index}/{max_attempts}: funds={funds}")
            entry, rejection = _submit_attempt(ctx, price, volume, timeout)
            entry.update({"attempt": index, "available_before": funds,
                          "notional_yuan": unit_notional})
            attempts.append(entry)
            facts.update({"attempts": attempts, "available_before": available,
                          "attempts_used": len(attempts)})
            if rejection is not None:
                facts["rejection_attempt_index"] = index
                facts["engine_observations"].update({"funds_enforcement": "rejection_observed",
                                                     "outcome": "funds_rejection_reached"})
                ctx.log(f"attempt {index}: venue rejected the insert; canceling accepted orders")
                if _cancel_accepted(ctx, facts, attempts, timeout):
                    return CaseResult(CASE_ID, "FAIL", "cancel_residual_open", facts)
                if any(e.get("outcome") == "accepted_filled" for e in attempts):
                    facts["flatten"] = _flatten_position(ctx)  # fill safety guard
                return _native_result(ctx, facts, rejection)
            if entry["outcome"] == "order_outcome_unknown":
                _cancel_accepted(ctx, facts, attempts, timeout)
                return CaseResult(CASE_ID, "UNKNOWN", "order_outcome_unknown", facts)
            ctx.log(f"attempt {index}: {entry['outcome']} status={entry['venue_status']}")

        # Every bounded attempt was accepted: the probe accumulated the whole
        # allowed resting margin and the engine never surfaced a rejection.
        if _cancel_accepted(ctx, facts, attempts, timeout):
            return CaseResult(CASE_ID, "FAIL", "cancel_residual_open", facts)
        accepted = [e for e in attempts if e.get("outcome") == "accepted"]
        facts.update({"accepted_without_rejection": True, "account_funds": _account_funds(ctx),
                      "accepted_resting_orders": len(accepted), "flatten": _flatten_position(ctx),
                      "accepted_notional_yuan": round(unit_notional * len(accepted), 2)})
        facts["engine_observations"].update({"outcome": "accepted_without_funds_rejection",
                                             "funds_enforcement": "not_observed_bounded"})
        return CaseResult(CASE_ID, "BLOCKED", "insufficient_funds_rejection_not_reachable", facts)
