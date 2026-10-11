"""O02 — reduce order final state: resting non-crossing reduce, accepted then canceled.

PASS: the crossing BUY open fills and the long position is visible, the
offset-1 SELL reduce rests ABOVE the market (``min(upper - tick, ask + N
ticks)``), the venue accepts it into the queue, a cancel drives it to the
terminal canceled state (5), and the position is then flattened back to zero.

Live SimNow 7x24 observation drove this rule: a reduce SELL placed at/under the
market bid crosses and fills instantly (the previous below-bid resting price
filled instead of queueing).  A resting SELL must therefore sit above the ask,
``scenario.rest_ticks`` (default 20) above it and capped one tick under the
band ceiling.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "O02"
RISK = "DANGEROUS"

_FILLED = {"0"}         # all traded
_IN_QUEUE = {"1", "3"}  # partially/no traded, still in queue
_TERMINAL = {"0", "5"}  # all traded / canceled


def _depth_row(client, instrument):
    result = client.query_depth_market_data(instrument)
    for row in result["rows"]:
        if str(row.get("InstrumentID")) == instrument:
            return row
    return None


def _long_position(client, instrument):
    rows = [r for r in client.query_positions(instrument_id=instrument)["rows"]
            if str(r.get("PosiDirection")) == "2"]
    return sum(int(r.get("Position") or 0) for r in rows), rows


def _probe_position(client, instrument):
    try:
        return _long_position(client, instrument)
    except SimNowSessionError as exc:
        return -1, [{"error": exc.reason, **exc.facts}]


def _arm(client, ctx):
    identity = hashlib.sha256(
        (CASE_ID + json.dumps(ctx.config, sort_keys=True, default=str)).encode()).hexdigest()
    preflight = hashlib.sha256(json.dumps({
        "case": CASE_ID, "instrument": ctx.contract["instrument"],
        "exchange": ctx.contract["exchange"], "pair_index": client.pair.index,
        "generation": client.login_facts.get("connection_generation"),
        "trading_day": client.login_facts.get("trading_day"),
    }, sort_keys=True).encode()).hexdigest()
    client.arm(
        instrument_id=ctx.contract["instrument"], exchange_id=ctx.contract["exchange"],
        strategy_identity_sha256=identity, preflight_sha256=preflight,
        execution_cycle_id=f"{CASE_ID}-{int(time.time())}")


def _place(client, ctx, *, instrument, exchange, direction, offset_flag, price, volume, hedge_flag):
    placement = client.place_limit_order(
        instrument_id=instrument, exchange_id=exchange, direction=direction,
        offset_flag=offset_flag, price=price, volume=volume, hedge_flag=hedge_flag)
    ctx.track_order(instrument, placement["order_ref"], exchange_id=exchange)
    return placement


def _settle(client, ctx, order_ref, order_sys_id=""):
    ctx.mark_order_closed(order_ref)
    client.mark_order_state(order_ref, "closed", order_sys_id)


def _cancel_to_terminal(client, *, instrument, exchange, order_ref, order_sys_id="", timeout=20.0):
    """Bounded cancel; never raises.  Returns the last observed order state."""
    facts = {"order_ref": order_ref}
    try:
        facts["cancel"] = client.cancel_order(
            instrument_id=instrument, exchange_id=exchange, order_ref=order_ref,
            order_sys_id=order_sys_id)
        row = client.wait_order_status(order_ref, _TERMINAL, instrument_id=instrument, timeout=timeout)
        facts.update(status=str(row.get("OrderStatus")), volume_traded=row.get("VolumeTraded"),
                     order_sys_id=str(row.get("OrderSysID") or order_sys_id))
    except SimNowSessionError as exc:
        facts["error"] = exc.reason
        latest = exc.facts.get("latest") if isinstance(exc.facts, dict) else None
        if isinstance(latest, dict):
            facts.update(status=str(latest.get("OrderStatus") or ""),
                         volume_traded=latest.get("VolumeTraded"))
    return facts


def _flatten(client, ctx, *, instrument, exchange, hedge_flag, volume, timeout):
    """Best-effort bounded crossing SELL (offset 1) reduce; never raises."""
    volume = int(volume)
    if volume <= 0:
        return {"volume": volume, "skipped": "zero_volume"}
    depth = _depth_row(client, instrument)
    bid = float(depth.get("BidPrice1") or 0.0) if depth else 0.0
    if bid <= 0:
        return {"volume": volume, "error": "no_book"}
    facts = {"volume": volume, "price": bid}
    try:
        placement = _place(client, ctx, instrument=instrument, exchange=exchange,
                           direction="1", offset_flag="1", price=bid,
                           volume=volume, hedge_flag=hedge_flag)
        row = client.wait_order_status(placement["order_ref"], _FILLED,
                                       instrument_id=instrument, timeout=timeout)
        facts.update(order_ref=placement["order_ref"], status=str(row.get("OrderStatus")),
                     order_sys_id=str(row.get("OrderSysID") or ""),
                     volume_traded=row.get("VolumeTraded"))
        _settle(client, ctx, placement["order_ref"], facts["order_sys_id"])
    except SimNowSessionError as exc:
        facts["error"] = exc.reason
        facts.update(exc.facts)
    return facts


class O02Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        contract = ctx.contract
        scenario = ctx.scenario()
        instrument = contract["instrument"]
        exchange = contract["exchange"]
        hedge_flag = contract.get("hedge_flag") or "1"

        instrument_rows = client.query_instruments(instrument_id=instrument,
                                                   exchange_id=exchange)["rows"]
        if not any(str(r.get("InstrumentID")) == instrument for r in instrument_rows):
            return CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"instrument": instrument})
        tick = float(instrument_rows[0].get("PriceTick") or 1.0)
        depth = _depth_row(client, instrument)
        if depth is None:
            return CaseResult(CASE_ID, "BLOCKED", "depth_unavailable", {"instrument": instrument})
        lower = float(depth.get("LowerLimitPrice") or 0.0)
        upper = float(depth.get("UpperLimitPrice") or 0.0)
        bid = float(depth.get("BidPrice1") or 0.0)
        ask = float(depth.get("AskPrice1") or 0.0)
        if not (0 < lower < upper):
            return CaseResult(CASE_ID, "BLOCKED", "price_band_invalid",
                              {"lower": lower, "upper": upper})
        if ask <= 0 or bid <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "no_book", {"bid": bid, "ask": ask})

        volume = int(scenario.get("volume", 1))
        rest_ticks = int(scenario.get("rest_ticks", 20))
        open_timeout = int(scenario.get("open_timeout_ms", 30000)) / 1000.0
        accept_timeout = int(scenario.get("accept_timeout_ms", 20000)) / 1000.0
        cancel_timeout = int(scenario.get("cancel_timeout_ms", 20000)) / 1000.0
        flatten_timeout = int(scenario.get("flatten_timeout_ms", 30000)) / 1000.0
        position_before, rows_before = _long_position(client, instrument)

        def flatten_now(flatten_volume, timeout):
            return _flatten(client, ctx, instrument=instrument, exchange=exchange,
                            hedge_flag=hedge_flag, volume=flatten_volume, timeout=timeout)

        _arm(client, ctx)
        ctx.log(f"armed; crossing BUY open {volume}@{ask} ({instrument}.{exchange})")
        try:
            opening = _place(client, ctx, instrument=instrument, exchange=exchange,
                             direction="0", offset_flag="0", price=ask,
                             volume=volume, hedge_flag=hedge_flag)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, dict(exc.facts))
        open_ref = opening["order_ref"]

        try:
            open_row = client.wait_order_status(open_ref, _FILLED, instrument_id=instrument,
                                                timeout=open_timeout)
        except SimNowSessionError as exc:
            cancel = _cancel_to_terminal(client, instrument=instrument, exchange=exchange,
                                         order_ref=open_ref, timeout=flatten_timeout)
            filled = int(cancel.get("volume_traded") or 0)
            return CaseResult(CASE_ID, "FAIL", exc.reason, {
                **exc.facts, "open": {"order_ref": open_ref, "cancel": cancel,
                                      "filled_volume": filled},
                "flatten": flatten_now(filled, flatten_timeout)})

        open_filled = int(open_row.get("VolumeTraded") or 0)
        open_sys_id = str(open_row.get("OrderSysID") or "")
        _settle(client, ctx, open_ref, open_sys_id)
        if open_filled != volume:
            return CaseResult(CASE_ID, "FAIL", "open_not_fully_filled", {
                "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                         "status": str(open_row.get("OrderStatus")),
                         "volume_traded": open_filled, "volume_total": volume},
                "flatten": flatten_now(open_filled, flatten_timeout)})

        long_now, rows_now = _probe_position(client, instrument)
        if long_now <= 0:
            return CaseResult(CASE_ID, "FAIL", "position_not_reflected", {
                "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                         "volume_traded": open_filled},
                "position_before": position_before, "position_rows": rows_now,
                "position_after_open": long_now,
                "flatten": flatten_now(open_filled, flatten_timeout)})

        fresh = _depth_row(client, instrument)
        rest_bid = float(fresh.get("BidPrice1") or 0.0) if fresh else 0.0
        rest_ask = float(fresh.get("AskPrice1") or 0.0) if fresh else 0.0
        if rest_ask <= 0:
            rest_last = float(fresh.get("LastPrice") or 0.0) if fresh else 0.0
            rest_ask = round(rest_last + rest_ticks * tick, 6) if rest_last > 0 else 0.0
        if rest_ask <= 0:
            return CaseResult(CASE_ID, "FAIL", "reduce_no_book", {
                "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                         "volume_traded": open_filled},
                "position_after_open": long_now,
                "flatten": flatten_now(long_now, flatten_timeout)})
        # A resting SELL must sit ABOVE the market: selling at/under the bid
        # crosses and fills instantly (observed live), so rest above the ask
        # and cap one tick under the band ceiling.
        rest_price = round(min(upper - tick, rest_ask + rest_ticks * tick), 6)
        if rest_bid > 0 and rest_price <= rest_bid:
            return CaseResult(CASE_ID, "BLOCKED", "no_resting_price_available", {
                "bid": rest_bid, "ask": rest_ask, "lower": lower, "upper": upper,
                "tick": tick, "rest_price": rest_price,
                "position_after_open": long_now,
                "flatten": flatten_now(long_now, flatten_timeout)})

        reduce_volume = long_now  # reduce the visible position
        ctx.log(f"resting reduce SELL {reduce_volume}@{rest_price} "
                f"(offset 1, {rest_ticks} ticks above ask)")
        try:
            reducing = _place(client, ctx, instrument=instrument, exchange=exchange,
                              direction="1", offset_flag="1", price=rest_price,
                              volume=reduce_volume, hedge_flag=hedge_flag)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, {
                **exc.facts, "position_after_open": long_now,
                "flatten": flatten_now(long_now, flatten_timeout)})
        reduce_ref = reducing["order_ref"]

        try:
            accept_row = client.wait_order_status(reduce_ref, _IN_QUEUE, instrument_id=instrument,
                                                  timeout=accept_timeout)
        except SimNowSessionError as exc:
            latest = exc.facts.get("latest") if isinstance(exc.facts, dict) else None
            filled_early = str((latest or {}).get("OrderStatus") or "") == "0"
            cancel = _cancel_to_terminal(client, instrument=instrument, exchange=exchange,
                                         order_ref=reduce_ref, timeout=cancel_timeout)
            if str(cancel.get("status") or "") in _TERMINAL:
                _settle(client, ctx, reduce_ref, str(cancel.get("order_sys_id") or ""))
            remainder, _rows = _probe_position(client, instrument)
            if remainder > 0:
                flat = flatten_now(remainder, flatten_timeout)
            else:
                flat = {"skipped": "position_unknown" if remainder < 0 else "zero_volume"}
            reason = "reduce_filled_before_accept" if filled_early else exc.reason
            return CaseResult(CASE_ID, "FAIL", reason, {
                **exc.facts, "reduce": {"order_ref": reduce_ref, "cancel": cancel,
                                        "volume_total": reduce_volume},
                "position_after_open": long_now, "flatten": flat})
        accept_status = str(accept_row.get("OrderStatus"))
        accept_sys_id = str(accept_row.get("OrderSysID") or "")

        cancel_facts = _cancel_to_terminal(client, instrument=instrument, exchange=exchange,
                                           order_ref=reduce_ref, order_sys_id=accept_sys_id,
                                           timeout=cancel_timeout)
        reduce_terminal = str(cancel_facts.get("status") or "")
        if reduce_terminal in _TERMINAL:
            _settle(client, ctx, reduce_ref, str(cancel_facts.get("order_sys_id") or accept_sys_id))

        remainder, rows_remainder = _probe_position(client, instrument)
        if remainder > 0:
            flat = flatten_now(remainder, flatten_timeout)
        else:
            flat = {"skipped": "position_unknown" if remainder < 0 else "zero_volume"}
        position_after, rows_after = _probe_position(client, instrument)
        common = {
            "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                     "volume_traded": open_filled, "price": ask},
            "position_before": position_before, "position_after_open": long_now,
            "reduce": {"order_ref": reduce_ref, "order_sys_id": accept_sys_id,
                       "price": rest_price, "bid": rest_bid, "ask": rest_ask,
                       "volume": reduce_volume,
                       "accept_status": accept_status, "terminal_status": reduce_terminal,
                       "cancel": cancel_facts},
            "flatten": flat, "position_after": position_after, "position_rows": rows_after,
            "price_band": {"lower": lower, "upper": upper},
            "insert_evidence": {"open": opening["evidence"], "reduce": reducing["evidence"]},
        }
        if reduce_terminal != "5":
            return CaseResult(CASE_ID, "FAIL", "reduce_terminal_not_canceled", common)
        if flat.get("status") != "0" or position_after != 0:
            return CaseResult(CASE_ID, "FAIL", "flatten_incomplete", common)
        return CaseResult(CASE_ID, "PASS", "", {
            **common, "position_flat": True, "position_rows_before": rows_before,
            "position_rows_remainder": rows_remainder})
