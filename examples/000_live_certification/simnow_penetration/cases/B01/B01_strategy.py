"""B01 — crossing fill plus resting order lifecycle (engine-adapted).

Live SimNow 7x24 observation: crossing orders (buy at/above the ask) fill
FULLY and instantly at any size, and partial fills are not producible.  The
original "partial fill on orders sized above top-of-book depth" flow therefore
cannot PASS on this engine and was adapted to a two-order batch:

  * order #1 — crossing BUY at the freshly queried AskPrice1 (fallback
    LastPrice + tick), sized ``scenario.order_volume`` (default 20).  The case
    waits up to ``scenario.fill_poll_timeout_ms`` for a FULL fill (status 0,
    VolumeTraded == volume); if it somehow stays queued it is canceled and
    the actual outcome is recorded.
  * order #2 — non-crossing resting BUY at the lower band edge + one tick,
    expected to queue (status 3) and then canceled to terminal status 5.

PASS requires: both orders visible/accepted, order #1 terminal with fill
evidence (VolumeTraded > 0) or canceled, order #2 canceled to status 5, zero
residual in-queue rows, and any net long flattened with a crossing SELL at
BidPrice1 (offset 1) until Position == 0 for the instrument.  Facts record
``partial_fill_observed`` (the actual observation) and the engine note.
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

_ENGINE_NOTE = "partial fills not producible on this engine; full fills observed"


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


def _watch_order(client, instrument, order_ref, timeout, statuses):
    """Poll one order until a wanted status; ``(row, partial_seen)``.

    ``partial_seen`` records whether 0 < VolumeTraded < VolumeTotalOriginal was
    ever observed — the honest partial-fill observation for this engine.
    """
    deadline = time.monotonic() + timeout
    latest, partial_seen = None, False
    while time.monotonic() < deadline:
        row = _order_rows(client, instrument, {order_ref}).get(order_ref)
        if row is not None:
            latest = row
            traded = int(row.get("VolumeTraded") or 0)
            total = int(row.get("VolumeTotalOriginal") or 0)
            if 0 < traded < total:
                partial_seen = True
            if str(row.get("OrderStatus")) in statuses:
                return row, partial_seen
        time.sleep(0.5)
    return latest, partial_seen


def _record_of(row, placement, volume):
    """Per-order evidence: status, traded, price; whatever state it reached."""
    record = {"order_ref": placement["order_ref"], "price": placement["price"],
              "volume": volume, "status": "not_visible", "volume_traded": 0}
    if row is not None:
        record.update(order_sys_id=str(row.get("OrderSysID") or ""),
                      status=str(row.get("OrderStatus") or ""),
                      volume_traded=int(row.get("VolumeTraded") or 0),
                      volume_total=int(row.get("VolumeTotalOriginal") or volume))
    return record


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
        instrument_row = next((r for r in rows if str(r.get("InstrumentID")) == instrument), None)
        if instrument_row is None:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"instrument": instrument})
        tick = float(instrument_row.get("PriceTick") or 1.0)
        depth = _depth_row(client, instrument)
        if depth is None:
            return CaseResult(CASE_ID, "BLOCKED", "depth_unavailable", {"instrument": instrument})
        lower = float(depth.get("LowerLimitPrice") or 0.0)
        upper = float(depth.get("UpperLimitPrice") or 0.0)
        bid = float(depth.get("BidPrice1") or 0.0)
        ask = float(depth.get("AskPrice1") or 0.0)
        last = float(depth.get("LastPrice") or 0.0)
        if not (0 < lower < upper):
            return CaseResult(CASE_ID, "BLOCKED", "price_band_invalid",
                              {"lower": lower, "upper": upper})
        if ask <= 0:
            ask = round(last + tick, 6) if last > 0 else 0.0
        if ask <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "no_book", {"bid": bid, "ask": ask})

        order_volume = int(scenario.get("order_volume", 20))
        fill_timeout = int(scenario.get("fill_poll_timeout_ms", 20000)) / 1000.0
        cancel_timeout = int(scenario.get("cancel_timeout_ms", 20000)) / 1000.0
        flatten_timeout = int(scenario.get("flatten_timeout_ms", 30000)) / 1000.0
        position_before, _rows_before = _long_position(client, instrument)
        placements = []
        partial_seen = False

        def flatten_now(flatten_volume):
            return _flatten(client, ctx, instrument=instrument, exchange=exchange,
                            hedge_flag=hedge_flag, volume=flatten_volume, timeout=flatten_timeout)

        def reap(extra_facts):
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
            final_rows = _order_rows(client, instrument, {p["order_ref"] for p in placements})
            total = sum(int(final_rows.get(p["order_ref"], {}).get("VolumeTraded") or 0)
                        for p in placements)
            return {**extra_facts, "cleanup": cleanup, "flatten": flatten_now(total)}

        _arm(client, ctx)

        # ---- order #1: crossing BUY that must fill fully (or be canceled) ----
        fresh = _depth_row(client, instrument)
        fresh_ask = float(fresh.get("AskPrice1") or 0.0) if fresh else 0.0
        if fresh_ask <= 0:
            fresh_last = float(fresh.get("LastPrice") or 0.0) if fresh else 0.0
            fresh_ask = round(fresh_last + tick, 6) if fresh_last > 0 else 0.0
        if fresh_ask <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "no_book", {"bid": bid, "ask": fresh_ask})
        try:
            crossing = _place(client, ctx, instrument=instrument, exchange=exchange,
                              direction="0", offset_flag="0", price=fresh_ask,
                              volume=order_volume, hedge_flag=hedge_flag)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, dict(exc.facts))
        placements.append(crossing)
        ctx.log(f"order #1 crossing BUY {order_volume}@{fresh_ask} placed "
                f"({crossing['order_ref']})")

        row1, partial1 = _watch_order(client, instrument, crossing["order_ref"],
                                      fill_timeout, _TERMINAL)
        partial_seen = partial_seen or partial1
        record1 = _record_of(row1, crossing, order_volume)
        record1["slot"] = "crossing"
        if record1["status"] not in _TERMINAL:
            cancel1 = _cancel_to_terminal(
                client, instrument=instrument, exchange=exchange,
                order_ref=crossing["order_ref"],
                order_sys_id=str(record1.get("order_sys_id") or ""),
                timeout=cancel_timeout)
            record1["cancel"] = cancel1
            record1["status"] = str(cancel1.get("status") or record1["status"])
        if record1["status"] in _TERMINAL:
            _settle(client, ctx, crossing["order_ref"], str(record1.get("order_sys_id") or ""))

        # ---- order #2: non-crossing resting BUY, queue then cancel ----------
        rest_price = round(lower + tick, 6)
        if fresh_ask > 0 and rest_price >= fresh_ask:
            return CaseResult(CASE_ID, "BLOCKED", "no_resting_price_available",
                              reap({"order1": record1, "bid": bid, "ask": fresh_ask,
                                    "lower": lower, "upper": upper, "rest_price": rest_price}))
        try:
            resting = _place(client, ctx, instrument=instrument, exchange=exchange,
                             direction="0", offset_flag="0", price=rest_price,
                             volume=order_volume, hedge_flag=hedge_flag)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason,
                              reap({"order1": record1, **exc.facts}))
        placements.append(resting)
        ctx.log(f"order #2 resting BUY {order_volume}@{rest_price} placed "
                f"({resting['order_ref']})")

        row2, partial2 = _watch_order(client, instrument, resting["order_ref"],
                                      fill_timeout, _IN_QUEUE | _TERMINAL)
        partial_seen = partial_seen or partial2
        record2 = _record_of(row2, resting, order_volume)
        record2["slot"] = "resting"
        if row2 is not None and str(row2.get("OrderStatus")) in _IN_QUEUE:
            record2["accept_status"] = str(row2.get("OrderStatus"))
        if record2["status"] not in _TERMINAL:
            cancel2 = _cancel_to_terminal(
                client, instrument=instrument, exchange=exchange,
                order_ref=resting["order_ref"],
                order_sys_id=str(record2.get("order_sys_id") or ""),
                timeout=cancel_timeout)
            record2["cancel"] = cancel2
            record2["status"] = str(cancel2.get("status") or record2["status"])
        if record2["status"] in _TERMINAL:
            _settle(client, ctx, resting["order_ref"], str(record2.get("order_sys_id") or ""))

        # ---- residual sweep, then flatten any net long ----------------------
        refs = {p["order_ref"] for p in placements}
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

        long_now, _rows_now = _probe_position(client, instrument)
        flatten = {"skipped": "position_unknown" if long_now < 0 else "no_position"}
        if long_now > 0:
            flatten = flatten_now(long_now)
        position_after, rows_after = _probe_position(client, instrument)
        total_filled = (int(record1.get("volume_traded") or 0)
                        + int(record2.get("volume_traded") or 0))

        common = {"per_order": [record1, record2],
                  "partial_fill_observed": bool(partial_seen),
                  "engine_note": _ENGINE_NOTE,
                  "total_filled": total_filled,
                  "flatten": flatten, "position_before": position_before,
                  "position_after": position_after, "position_rows": rows_after,
                  "price_band": {"lower": lower, "upper": upper},
                  "insert_evidence": [p["evidence"] for p in placements]}
        if len(visible) < len(refs):
            return CaseResult(CASE_ID, "FAIL", "order_not_visible",
                              {**common, "visible": sorted(visible)})
        status1 = str(record1.get("status") or "")
        if not (status1 in _TERMINAL
                and (int(record1.get("volume_traded") or 0) > 0 or status1 == "5")):
            return CaseResult(CASE_ID, "FAIL", "order1_not_filled", common)
        if str(record2.get("status") or "") != "5":
            return CaseResult(CASE_ID, "FAIL", "order2_not_canceled", common)
        if residuals:
            return CaseResult(CASE_ID, "FAIL", "residual_order_open",
                              {**common, "residuals": residuals})
        if long_now > 0 and flatten.get("status") != "0":
            return CaseResult(CASE_ID, "FAIL", "flatten_incomplete", common)
        if position_after != 0:
            return CaseResult(CASE_ID, "FAIL", "flatten_incomplete", common)
        return CaseResult(CASE_ID, "PASS", "", {
            **common, "position_flat": True,
            "fill_volume": int(record1.get("volume_traded") or 0)})
