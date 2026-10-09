"""M05 — the local monitor records submit and cancel.

Success condition: The session monitor records an order_insert event and an order_action
event carrying this order's reference, the order is visible in the venue
queue, and the venue reaches the terminal canceled state.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.context import CaseResult
from certlib.ctp_client import SimNowSessionError
from certlib.monitor import Monitor

CASE_ID = "M05"
RISK = "WRITE"


_IN_QUEUE = {"1", "3"}  # partial/no trade, still in queue
_CANCELED = {"5"}


def _instrument_row(client, instrument, exchange):
    result = client.query_instruments(instrument_id=instrument, exchange_id=exchange)
    for row in result["rows"]:
        if str(row.get("InstrumentID")) == instrument:
            return row
    return None


def _depth_row(client, instrument):
    result = client.query_depth_market_data(instrument)
    for row in result["rows"]:
        if str(row.get("InstrumentID")) == instrument:
            return row
    return None


def _prepare(client, ctx):
    """Resolve the traded contract from the venue and arm the session."""
    contract = ctx.contract
    instrument = contract["instrument"]
    exchange = contract["exchange"]
    row = _instrument_row(client, instrument, exchange)
    if row is None:
        return None, CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"instrument": instrument})
    depth = _depth_row(client, instrument)
    if depth is None:
        return None, CaseResult(CASE_ID, "BLOCKED", "depth_unavailable", {"instrument": instrument})
    lower = float(depth["LowerLimitPrice"])
    upper = float(depth["UpperLimitPrice"])
    if not (0 < lower < upper):
        return None, CaseResult(
            CASE_ID, "BLOCKED", "price_band_invalid", {"lower": lower, "upper": upper}
        )
    market = {
        "instrument": instrument,
        "exchange": exchange,
        "hedge_flag": contract.get("hedge_flag") or "1",
        "tick": float(row.get("PriceTick") or 1.0),
        "lower": lower,
        "upper": upper,
    }
    strategy_identity = hashlib.sha256(
        (CASE_ID + json.dumps(ctx.config, sort_keys=True, default=str)).encode()
    ).hexdigest()
    preflight = hashlib.sha256(
        json.dumps(
            {
                "case": CASE_ID,
                "instrument": instrument,
                "exchange": exchange,
                "pair_index": client.pair.index,
                "generation": client.login_facts.get("connection_generation"),
                "trading_day": client.login_facts.get("trading_day"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    client.arm(
        instrument_id=instrument,
        exchange_id=exchange,
        strategy_identity_sha256=strategy_identity,
        execution_cycle_id=f"{CASE_ID}-{int(time.time())}",
        preflight_sha256=preflight,
    )
    return market, None


def _edge_price(market, side):
    if side == "buy":
        return round(market["lower"] + market["tick"], 6)
    return round(market["upper"] - market["tick"], 6)


def _place_visible(client, ctx, market, side, price, volume, timeout_ms):
    """Place one resting order; wait until the venue query shows it in queue."""
    placement = client.place_limit_order(
        instrument_id=market["instrument"],
        exchange_id=market["exchange"],
        direction="0" if side == "buy" else "1",
        offset_flag="0",
        price=price,
        volume=volume,
        hedge_flag=market["hedge_flag"],
    )
    order_ref = placement["order_ref"]
    ctx.track_order(market["instrument"], order_ref, exchange_id=market["exchange"])
    row = client.wait_order_status(
        order_ref, _IN_QUEUE, instrument_id=market["instrument"], timeout=timeout_ms / 1000.0
    )
    return {
        "order_ref": order_ref,
        "order_sys_id": str(row.get("OrderSysID") or ""),
        "in_queue_status": str(row.get("OrderStatus")),
        "request_id": placement["request_id"],
        "insert_evidence": placement["evidence"],
    }


def _place_many(client, ctx, market, side, price, volume, count, timeout_ms, interval_ms):
    placed = []
    for index in range(count):
        if index and interval_ms > 0:
            time.sleep(interval_ms / 1000.0)
        placed.append(_place_visible(client, ctx, market, side, price, volume, timeout_ms))
    return placed


def _cancel_terminal(client, ctx, market, item, timeout_ms):
    """Cancel one tracked order; wait for the terminal canceled venue status."""
    cancel = client.cancel_order(
        instrument_id=market["instrument"],
        exchange_id=market["exchange"],
        order_ref=item["order_ref"],
        order_sys_id=item["order_sys_id"],
    )
    final = client.wait_order_status(
        item["order_ref"], _CANCELED,
        instrument_id=market["instrument"], timeout=timeout_ms / 1000.0,
    )
    ctx.mark_order_closed(item["order_ref"])
    client.mark_order_state(item["order_ref"], "closed", item["order_sys_id"])
    closed = {
        **item,
        "final_status": str(final.get("OrderStatus")),
        "cancel_submit_code": cancel.get("submit_code"),
    }
    return closed, final


def _cancel_many(client, ctx, market, placed, timeout_ms, interval_ms=0):
    orders = []
    for item in placed:
        if interval_ms > 0:
            time.sleep(interval_ms / 1000.0)
        orders.append(_cancel_terminal(client, ctx, market, item, timeout_ms)[0])
    return orders


def _residual_in_queue(client, market, refs):
    rows = client.query_orders(instrument_id=market["instrument"])["rows"]
    return [
        row
        for row in rows
        if str(row.get("OrderRef")) in refs and str(row.get("OrderStatus")) in _IN_QUEUE
    ]


class M05Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        market, blocked = _prepare(client, ctx)
        if blocked is not None:
            return blocked

        monitor = Monitor({})
        client.event_hook = monitor.record  # attached before placing: capture insert + cancel

        side = str(scenario.get("side", "buy")).lower()
        volume = int(scenario.get("volume", 1))
        accept_ms = int(scenario.get("accept_timeout_ms", 20000))
        cancel_ms = int(scenario.get("cancel_timeout_ms", 20000))
        price = _edge_price(market, side)
        ctx.log(f"armed; monitor attached; placing {side} {volume}@{price}")

        try:
            item = _place_visible(client, ctx, market, side, price, volume, accept_ms)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, exc.facts)

        inserts = [
            event
            for event in monitor.events
            if event.get("kind") == "order_insert"
            and str(event.get("order_ref")) == item["order_ref"]
        ]
        try:
            closed = _cancel_terminal(client, ctx, market, item, cancel_ms)[0]
        except SimNowSessionError as exc:
            return CaseResult(
                CASE_ID, "FAIL", exc.reason, {**exc.facts, "order_ref": item["order_ref"]}
            )
        actions = [
            event
            for event in monitor.events
            if event.get("kind") == "order_action"
            and str(event.get("order_ref")) == item["order_ref"]
        ]
        ctx.record_artifact("monitor", monitor.dump())

        residual = _residual_in_queue(client, market, {item["order_ref"]})
        facts = {
            **closed,
            "volume": volume,
            "in_queue_confirmed": True,
            "monitored_event_count": len(monitor.events),
            "matched_insert_events": len(inserts),
            "matched_cancel_events": len(actions),
        }
        if not inserts:
            return CaseResult(CASE_ID, "FAIL", "monitor_missing_order_insert_event", facts)
        if not actions:
            return CaseResult(CASE_ID, "FAIL", "monitor_missing_order_action_event", facts)
        if closed["final_status"] != "5":
            return CaseResult(CASE_ID, "FAIL", "order_not_terminal_canceled", facts)
        if residual:
            return CaseResult(CASE_ID, "FAIL", "order_still_open", {**facts, "residual": residual})
        return CaseResult(CASE_ID, "PASS", "", facts)
