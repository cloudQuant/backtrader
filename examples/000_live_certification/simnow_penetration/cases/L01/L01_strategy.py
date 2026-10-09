"""L01 — trade-log correlation: a crossing BUY fill matched by OrderRef, then flat.

PASS: the crossing BUY (price = AskPrice1) trades, >=1 venue trade row carries
our OrderRef (TradeID/OrderSysID/Price/Volume recorded), a crossing SELL
(price = BidPrice1) flattens the fill, and the position query is back at its
starting level.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "L01"
RISK = "WRITE"

_TRADED = {"0", "1"}  # all traded / partially traded
_FILLED = {"0"}       # all traded


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
        (CASE_ID + json.dumps(ctx.config, sort_keys=True, default=str)).encode()
    ).hexdigest()
    preflight = hashlib.sha256(json.dumps({
        "case": CASE_ID,
        "instrument": ctx.contract["instrument"],
        "exchange": ctx.contract["exchange"],
        "pair_index": client.pair.index,
        "generation": client.login_facts.get("connection_generation"),
        "trading_day": client.login_facts.get("trading_day"),
    }, sort_keys=True).encode()).hexdigest()
    client.arm(
        instrument_id=ctx.contract["instrument"], exchange_id=ctx.contract["exchange"],
        strategy_identity_sha256=identity, preflight_sha256=preflight,
        execution_cycle_id=f"{CASE_ID}-{int(time.time())}",
    )


def _place(client, ctx, *, instrument, exchange, direction, offset_flag, price, volume, hedge_flag):
    placement = client.place_limit_order(
        instrument_id=instrument, exchange_id=exchange, direction=direction,
        offset_flag=offset_flag, price=price, volume=volume, hedge_flag=hedge_flag)
    ctx.track_order(instrument, placement["order_ref"], exchange_id=exchange)
    return placement


def _settle(client, ctx, order_ref, order_sys_id=""):
    ctx.mark_order_closed(order_ref)
    client.mark_order_state(order_ref, "closed", order_sys_id)


def _filled_volume(client, order_ref, instrument):
    try:
        for row in client.query_orders(instrument_id=instrument)["rows"]:
            if str(row.get("OrderRef") or "") == str(order_ref):
                return int(row.get("VolumeTraded") or 0)
    except SimNowSessionError:
        pass
    return 0


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
        facts.update({
            "order_ref": placement["order_ref"], "status": str(row.get("OrderStatus")),
            "order_sys_id": str(row.get("OrderSysID") or ""),
            "volume_traded": row.get("VolumeTraded"),
        })
        _settle(client, ctx, placement["order_ref"], facts["order_sys_id"])
    except SimNowSessionError as exc:
        facts["error"] = exc.reason
        facts.update(exc.facts)
    return facts


class L01Strategy:
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
        if ask <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "no_book", {"bid": bid, "ask": ask})

        volume = int(scenario.get("volume", 1))
        fill_timeout = int(scenario.get("fill_timeout_ms", 30000)) / 1000.0
        trade_timeout = int(scenario.get("trade_timeout_ms", 30000)) / 1000.0
        flatten_timeout = int(scenario.get("flatten_timeout_ms", 30000)) / 1000.0
        position_before, _before_rows = _long_position(client, instrument)

        def flatten_now(filled_volume):
            return _flatten(client, ctx, instrument=instrument, exchange=exchange,
                            hedge_flag=hedge_flag, volume=filled_volume, timeout=flatten_timeout)

        _arm(client, ctx)
        ctx.log(f"armed; crossing BUY {volume}@{ask} ({instrument}.{exchange})")
        try:
            opening = _place(client, ctx, instrument=instrument, exchange=exchange,
                             direction="0", offset_flag="0", price=ask,
                             volume=volume, hedge_flag=hedge_flag)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, dict(exc.facts))
        open_ref = opening["order_ref"]

        try:
            filled_row = client.wait_order_status(open_ref, _TRADED, instrument_id=instrument,
                                                  timeout=fill_timeout)
        except SimNowSessionError as exc:
            filled = _filled_volume(client, open_ref, instrument)
            return CaseResult(CASE_ID, "FAIL", exc.reason, {
                **exc.facts, "order_ref": open_ref, "filled_volume": filled,
                "flatten": flatten_now(filled)})

        open_sys_id = str(filled_row.get("OrderSysID") or "")
        filled = int(filled_row.get("VolumeTraded") or 0)
        if str(filled_row.get("OrderStatus")) != "0":
            try:  # cancel anything still working before flattening
                client.cancel_order(instrument_id=instrument, exchange_id=exchange,
                                    order_ref=open_ref, order_sys_id=open_sys_id)
                client.wait_order_status(open_ref, {"0", "5"}, instrument_id=instrument, timeout=10.0)
            except SimNowSessionError:
                pass
            filled = _filled_volume(client, open_ref, instrument)
            return CaseResult(CASE_ID, "FAIL", "opening_not_fully_filled", {
                "order_ref": open_ref, "status": str(filled_row.get("OrderStatus")),
                "filled_volume": filled, "flatten": flatten_now(filled)})
        _settle(client, ctx, open_ref, open_sys_id)

        matched = []
        deadline = time.monotonic() + trade_timeout
        try:
            while time.monotonic() < deadline:
                trades = client.query_trades(instrument_id=instrument)["rows"]
                matched = [r for r in trades if str(r.get("OrderRef") or "") == open_ref]
                if matched:
                    break
                time.sleep(0.5)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason,
                              {"order_ref": open_ref, "flatten": flatten_now(filled), **exc.facts})
        if not matched:
            return CaseResult(CASE_ID, "FAIL", "trade_not_found", {
                "order_ref": open_ref, "order_sys_id": open_sys_id, "filled_volume": filled,
                "flatten": flatten_now(filled)})

        flat = flatten_now(filled)
        position_after, rows_after = _probe_position(client, instrument)
        if flat.get("status") != "0" or position_after != position_before:
            return CaseResult(CASE_ID, "FAIL", "flatten_incomplete", {
                "flatten": flat, "position_before": position_before,
                "position_after": position_after, "position_rows": rows_after})
        return CaseResult(CASE_ID, "PASS", "", {
            "order_ref": open_ref, "order_sys_id": open_sys_id, "direction": "0",
            "price": ask, "volume": volume, "filled_volume": filled,
            "trade_rows": matched[:5], "trade_ids": [r.get("TradeID") for r in matched][:5],
            "flatten": flat, "position_before": position_before,
            "position_after": position_after, "position_flat": position_after == 0,
            "price_band": {"lower": lower, "upper": upper},
            "insert_evidence": opening["evidence"],
        })
