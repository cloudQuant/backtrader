"""B01 — partial fill on an order sized above the top of book, then cancel.

PASS: two crossing BUY orders sized above the visible top-of-book depth are
accepted and visible in the venue order query, at least one shows
0 < VolumeTraded < VolumeTotalOriginal (partial fill) at some poll, every
remaining order reaches a terminal state, and the position opened by the
case is flattened back to its starting level.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "B01"
RISK = "DANGEROUS"

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


def _order_rows(client, instrument, refs):
    rows = {}
    for row in client.query_orders(instrument_id=instrument)["rows"]:
        ref = str(row.get("OrderRef") or "")
        if ref in refs:
            rows[ref] = row
    return rows


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
        row = client.wait_order_status(placement["order_ref"], {"0"},
                                       instrument_id=instrument, timeout=timeout)
        facts.update(order_ref=placement["order_ref"], status=str(row.get("OrderStatus")),
                     order_sys_id=str(row.get("OrderSysID") or ""),
                     volume_traded=row.get("VolumeTraded"))
        _settle(client, ctx, placement["order_ref"], facts["order_sys_id"])
    except SimNowSessionError as exc:
        facts["error"] = exc.reason
        facts.update(exc.facts)
    return facts


class B01Strategy:
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

        order_volume = int(scenario.get("order_volume", 20))
        order_count = int(scenario.get("order_count", 2))
        poll_timeout = int(scenario.get("fill_poll_timeout_ms", 20000)) / 1000.0
        cancel_timeout = int(scenario.get("cancel_timeout_ms", 20000)) / 1000.0
        flatten_timeout = int(scenario.get("flatten_timeout_ms", 30000)) / 1000.0
        position_before, _rows_before = _long_position(client, instrument)
        placements = []

        def flatten_now(flatten_volume):
            return _flatten(client, ctx, instrument=instrument, exchange=exchange,
                            hedge_flag=hedge_flag, volume=flatten_volume, timeout=flatten_timeout)

        def filled_so_far():
            final = _order_rows(client, instrument, {p["order_ref"] for p in placements})
            return sum(int(final.get(p["order_ref"], {}).get("VolumeTraded") or 0)
                       for p in placements)

        def reap_early(extra_facts):
            """Cancel every non-terminal placement and flatten what traded."""
            cleanup = []
            for placement in placements:
                ref = placement["order_ref"]
                row = _order_rows(client, instrument, {ref}).get(ref) or {}
                if str(row.get("OrderStatus")) in _TERMINAL:
                    _settle(client, ctx, ref, str(row.get("OrderSysID") or ""))
                    continue
                facts = _cancel_to_terminal(
                    client, instrument=instrument, exchange=exchange, order_ref=ref,
                    order_sys_id=str(row.get("OrderSysID") or ""), timeout=cancel_timeout)
                if str(facts.get("status") or "") in _TERMINAL:
                    _settle(client, ctx, ref, str(facts.get("order_sys_id") or ""))
                cleanup.append(facts)
            return {**extra_facts, "cleanup": cleanup, "flatten": flatten_now(filled_so_far())}

        _arm(client, ctx)
        for index in range(order_count):
            fresh = _depth_row(client, instrument)
            fresh_ask = float(fresh.get("AskPrice1") or 0.0) if fresh else 0.0
            if fresh_ask <= 0:
                facts = {"placed": placements, "bid": bid, "ask": fresh_ask}
                reason = reap_early(facts) if placements else facts
                return CaseResult(CASE_ID, "BLOCKED", "no_book", reason)
            try:
                placements.append(_place(
                    client, ctx, instrument=instrument, exchange=exchange, direction="0",
                    offset_flag="0", price=fresh_ask, volume=order_volume, hedge_flag=hedge_flag))
            except SimNowSessionError as exc:
                return CaseResult(CASE_ID, "FAIL", exc.reason,
                                  reap_early({"placed": placements, **exc.facts}))
            ctx.log(f"placed order {index + 1}/{order_count}: {order_volume}@{fresh_ask}")

        refs = {p["order_ref"] for p in placements}
        latest, partial_ref, seen = {}, "", set()
        deadline = time.monotonic() + poll_timeout
        while time.monotonic() < deadline:
            latest = _order_rows(client, instrument, refs)
            seen.update(latest)
            for ref, row in latest.items():
                traded = int(row.get("VolumeTraded") or 0)
                if not partial_ref and 0 < traded < int(row.get("VolumeTotalOriginal") or 0):
                    partial_ref = ref
            if partial_ref and seen >= refs:
                break
            if seen >= refs and all(str(r.get("OrderStatus")) in _TERMINAL for r in latest.values()):
                break
            time.sleep(0.5)

        per_order = []
        for placement in placements:
            ref = placement["order_ref"]
            row = latest.get(ref) or _order_rows(client, instrument, {ref}).get(ref) or {}
            status = str(row.get("OrderStatus") or "")
            record = {"order_ref": ref, "order_sys_id": str(row.get("OrderSysID") or ""),
                      "status": status, "volume_traded": int(row.get("VolumeTraded") or 0),
                      "volume_total": int(row.get("VolumeTotalOriginal") or order_volume),
                      "price": placement["price"]}
            if status not in _TERMINAL:
                facts = _cancel_to_terminal(client, instrument=instrument, exchange=exchange,
                                            order_ref=ref, order_sys_id=record["order_sys_id"],
                                            timeout=cancel_timeout)
                record["cancel"] = facts
                record["status"] = str(facts.get("status") or status)
            if record["status"] in _TERMINAL:
                _settle(client, ctx, ref, record["order_sys_id"])
            per_order.append(record)

        final = _order_rows(client, instrument, refs)
        residuals = [{"order_ref": r, "status": str(row.get("OrderStatus") or "")}
                     for r, row in final.items() if str(row.get("OrderStatus")) in _IN_QUEUE]
        for item in residuals:  # last bounded cancel pass, then re-check
            _cancel_to_terminal(client, instrument=instrument, exchange=exchange,
                                order_ref=item["order_ref"], timeout=cancel_timeout)
        final = _order_rows(client, instrument, refs)
        residuals = [{"order_ref": r, "status": str(row.get("OrderStatus") or "")}
                     for r, row in final.items() if str(row.get("OrderStatus")) in _IN_QUEUE]
        visible = [r for r in refs
                   if str(final.get(r, {}).get("OrderStatus") or "") in (_TERMINAL | _IN_QUEUE)]

        total_filled = sum(int(final.get(ref, {}).get("VolumeTraded") or 0) for ref in refs)
        flat = flatten_now(total_filled)
        position_after, rows_after = _probe_position(client, instrument)
        common = {"per_order": per_order, "partial_fill_observed": bool(partial_ref),
                  "partial_order_ref": partial_ref, "total_filled": total_filled,
                  "flatten": flat, "position_before": position_before,
                  "position_after": position_after, "position_rows": rows_after}
        if not partial_ref:
            return CaseResult(CASE_ID, "FAIL", "no_partial_fill_observed", common)
        if len(visible) < order_count:
            return CaseResult(CASE_ID, "FAIL", "order_not_visible",
                              {**common, "visible": sorted(visible)})
        if residuals:
            return CaseResult(CASE_ID, "FAIL", "residual_order_open",
                              {**common, "residuals": residuals})
        if flat.get("status") != "0" or position_after != position_before:
            return CaseResult(CASE_ID, "FAIL", "flatten_incomplete", common)
        return CaseResult(CASE_ID, "PASS", "", {
            **common, "price_band": {"lower": lower, "upper": upper},
            "insert_evidence": [p["evidence"] for p in placements]})
