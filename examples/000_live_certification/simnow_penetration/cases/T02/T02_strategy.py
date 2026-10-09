"""T02 — open-then-close with real fills: crossing BUY open, reduce-only close.

PASS: the crossing BUY (price = AskPrice1) fully fills (status 0), the long
position is visible, the offset-1 SELL close at the crossing bid fully fills,
and the final position query shows the position back at zero.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "T02"
RISK = "WRITE"

_FILLED = {"0"}         # all traded
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


class T02Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        contract = ctx.contract
        scenario = ctx.scenario()
        instrument = contract["instrument"]
        exchange = contract["exchange"]
        hedge_flag = contract.get("hedge_flag") or "1"

        rows = client.query_instruments(instrument_id=instrument, exchange_id=exchange)["rows"]
        if not any(str(r.get("InstrumentID")) == instrument for r in rows):
            return CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"instrument": instrument})
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
        open_timeout = int(scenario.get("open_timeout_ms", 30000)) / 1000.0
        close_timeout = int(scenario.get("close_timeout_ms", 30000)) / 1000.0
        position_before, _rows_before = _long_position(client, instrument)

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
                                         order_ref=open_ref, timeout=close_timeout)
            if str(cancel.get("status") or "") in _TERMINAL:
                _settle(client, ctx, open_ref, str(cancel.get("order_sys_id") or ""))
            filled = int(cancel.get("volume_traded") or 0)
            return CaseResult(CASE_ID, "FAIL", exc.reason, {
                **exc.facts, "open": {"order_ref": open_ref, "cancel": cancel,
                                      "filled_volume": filled},
                "flatten": flatten_now(filled, close_timeout)})

        open_filled = int(open_row.get("VolumeTraded") or 0)
        open_sys_id = str(open_row.get("OrderSysID") or "")
        _settle(client, ctx, open_ref, open_sys_id)
        if open_filled != volume:
            return CaseResult(CASE_ID, "FAIL", "open_not_fully_filled", {
                "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                         "status": str(open_row.get("OrderStatus")),
                         "volume_traded": open_filled, "volume_total": volume},
                "flatten": flatten_now(open_filled, close_timeout)})

        long_now, rows_now = _probe_position(client, instrument)
        if long_now <= 0:
            return CaseResult(CASE_ID, "FAIL", "position_not_reflected", {
                "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                         "volume_traded": open_filled},
                "position_before": position_before, "position_rows": rows_now,
                "position_after_open": long_now,
                "flatten": flatten_now(open_filled, close_timeout)})

        close_depth = _depth_row(client, instrument)
        close_bid = float(close_depth.get("BidPrice1") or 0.0) if close_depth else 0.0
        if close_bid <= 0:
            return CaseResult(CASE_ID, "FAIL", "close_no_book", {
                "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                         "volume_traded": open_filled},
                "position_after_open": long_now, "bid": close_bid})

        close_volume = long_now  # reduce-only close of the visible position
        ctx.log(f"crossing SELL close {close_volume}@{close_bid} (offset 1)")
        try:
            closing = _place(client, ctx, instrument=instrument, exchange=exchange,
                             direction="1", offset_flag="1", price=close_bid,
                             volume=close_volume, hedge_flag=hedge_flag)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, {
                **exc.facts, "position_after_open": long_now,
                "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                         "volume_traded": open_filled}})
        close_ref = closing["order_ref"]

        try:
            close_row = client.wait_order_status(close_ref, _FILLED, instrument_id=instrument,
                                                 timeout=close_timeout)
        except SimNowSessionError as exc:
            cancel = _cancel_to_terminal(client, instrument=instrument, exchange=exchange,
                                         order_ref=close_ref, timeout=close_timeout)
            if str(cancel.get("status") or "") in _TERMINAL:
                _settle(client, ctx, close_ref, str(cancel.get("order_sys_id") or ""))
            remainder, _rows = _probe_position(client, instrument)
            if remainder > 0:
                retry = flatten_now(remainder, close_timeout)
            else:
                retry = {"skipped": "position_unknown" if remainder < 0 else "zero_volume"}
            return CaseResult(CASE_ID, "FAIL", exc.reason, {
                **exc.facts, "close": {"order_ref": close_ref, "cancel": cancel,
                                       "volume_total": close_volume},
                "position_before": position_before, "retry_close": retry})

        close_filled = int(close_row.get("VolumeTraded") or 0)
        close_sys_id = str(close_row.get("OrderSysID") or "")
        _settle(client, ctx, close_ref, close_sys_id)
        position_after, rows_after = _probe_position(client, instrument)
        if position_after != 0:
            retry = flatten_now(position_after, close_timeout)
            position_final, rows_final = _probe_position(client, instrument)
            return CaseResult(CASE_ID, "FAIL", "position_not_flat", {
                "open": {"order_ref": open_ref, "order_sys_id": open_sys_id,
                         "volume_traded": open_filled},
                "close": {"order_ref": close_ref, "order_sys_id": close_sys_id,
                          "status": str(close_row.get("OrderStatus")),
                          "volume_traded": close_filled, "volume_total": close_volume},
                "position_before": position_before, "position_after": position_after,
                "retry_close": retry, "position_final": position_final,
                "position_rows": rows_final})

        return CaseResult(CASE_ID, "PASS", "", {
            "open": {"order_ref": open_ref, "order_sys_id": open_sys_id, "direction": "0",
                     "offset_flag": "0", "price": ask, "volume": volume,
                     "status": str(open_row.get("OrderStatus")), "volume_traded": open_filled},
            "close": {"order_ref": close_ref, "order_sys_id": close_sys_id, "direction": "1",
                      "offset_flag": "1", "price": close_bid, "volume": close_volume,
                      "status": str(close_row.get("OrderStatus")), "volume_traded": close_filled},
            "position_before": position_before, "position_after_open": long_now,
            "position_after": position_after, "position_rows": rows_after,
            "position_flat": position_after == 0,
            "price_band": {"lower": lower, "upper": upper},
            "insert_evidence": {"open": opening["evidence"], "close": closing["evidence"]},
        })
