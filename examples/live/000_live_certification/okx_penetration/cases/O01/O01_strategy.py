"""O01 — repeated open submissions are accepted and canceled.

Success condition: several resting LIMIT orders are placed with the configured
interval, the local monitor records exactly one order_insert event per
submission, every order reaches the terminal canceled state, no order of this
run remains pending, and the monitor artifact carries the events.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult
from certlib.monitor import Monitor
from certlib.okx_client import OkxError

CASE_ID = "O01"
RISK = "DANGEROUS"

_OPEN_STATES = {"live", "partially_filled"}
_TERMINAL_STATES = {"canceled", "filled"}


class _Abort(Exception):
    """Internal signal: stop the case and return this outcome."""

    def __init__(self, status, reason, facts=None):
        self.status = status
        self.reason = reason
        self.facts = dict(facts or {})
        super().__init__(reason)


def _round_to_step(value, step):
    step = float(step)
    return round(round(float(value) / step) * step, 10)


def _prepare(ctx):
    """Resolve the instrument plan from venue metadata; enforce policy."""
    client = ctx.client
    scenario = ctx.scenario()
    policy = ctx.config.get("policy", {})
    inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")
    if inst_id not in policy.get("symbol_allowlist", []):
        raise _Abort("BLOCKED", "symbol_not_allowed")
    instruments = client.instruments(inst_id)
    if not instruments:
        raise _Abort("BLOCKED", "instrument_unknown", {"inst_id": inst_id})
    meta = instruments[0]
    tick = float(meta.get("tickSz") or 0.1)
    lot = float(meta.get("lotSz") or 1)
    last = float(client.ticker(inst_id)["last"])
    price = _round_to_step(last * (1.0 - scenario.get("price_offset_bps", 200) / 10_000.0), tick)
    size = _round_to_step(float(scenario.get("size", 1)), lot)
    notional = price * size * float(meta.get("ctVal") or 0)
    if notional > float(policy.get("max_notional_usdt", 0)):
        raise _Abort("BLOCKED", "above_policy_notional", {"notional": notional})
    return {
        "inst_id": inst_id,
        "side": str(scenario.get("side", "buy")).lower(),
        "size": size,
        "price": price,
        "last": last,
    }


def _place_live(client, ctx, market, timeout_ms, monitor=None):
    """Place one resting LIMIT order; wait until the venue shows it live."""
    placement = client.place_order(
        market["inst_id"], market["side"], sz=market["size"], px=market["price"], ord_type="limit"
    )
    ord_id = placement["ordId"]
    ctx.track_order(market["inst_id"], ord_id, placement.get("_cl_ord_id"))
    if monitor is not None:
        monitor.record("order_insert", order_ref=str(ord_id))
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        rows = client.order_details(market["inst_id"], ord_id=ord_id)
        state = str((rows[0] if rows else {}).get("state"))
        if state in _OPEN_STATES:
            return {"ordId": ord_id, "clOrdId": placement.get("_cl_ord_id"), "live_state": state}
        if state in _TERMINAL_STATES:
            ctx.mark_order_closed(ord_id)
            raise _Abort("FAIL", f"order_went_terminal_before_cancel:{state}", {"ordId": ord_id})
        time.sleep(0.3)
    raise _Abort("FAIL", "accept_timeout", {"ordId": ord_id})


def _cancel_terminal(client, ctx, market, ord_id, timeout_ms):
    """Cancel one live order; wait for the terminal canceled venue state."""
    client.cancel_order(market["inst_id"], ord_id=ord_id)
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        rows = client.order_details(market["inst_id"], ord_id=ord_id)
        state = str((rows[0] if rows else {}).get("state"))
        if state == "canceled":
            ctx.mark_order_closed(ord_id)
            return {"ordId": ord_id, "state": state}
        if state in _TERMINAL_STATES:
            ctx.mark_order_closed(ord_id)
            raise _Abort("FAIL", f"terminal_state:{state}", {"ordId": ord_id})
        time.sleep(0.3)
    raise _Abort("FAIL", "cancel_confirm_timeout", {"ordId": ord_id})


def _residual_pending(client, inst_id, ord_ids):
    wanted = {str(x) for x in ord_ids}
    return [o for o in client.pending_orders(inst_id=inst_id) if str(o.get("ordId")) in wanted]


class O01Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        monitor = Monitor({})
        try:
            market = _prepare(ctx)
            count = max(1, int(scenario.get("repeat_count", 3)))
            interval_ms = int(scenario.get("order_interval_ms", 800))
            accept_ms = int(scenario.get("accept_timeout_ms", 8000))
            cancel_ms = int(scenario.get("cancel_confirm_timeout_ms", 8000))

            ctx.log(f"monitor attached; placing {count} resting orders (repeat_count={count})")
            placed = []
            for index in range(count):
                if index and interval_ms > 0:
                    time.sleep(interval_ms / 1000.0)
                placed.append(_place_live(client, ctx, market, accept_ms, monitor))
            orders = []
            for item in placed:
                closed = _cancel_terminal(client, ctx, market, item["ordId"], cancel_ms)
                orders.append({**item, **closed})
        except _Abort as abort:
            return CaseResult(CASE_ID, abort.status, abort.reason, abort.facts)
        except OkxError as exc:
            return CaseResult(
                CASE_ID, "FAIL", f"client_error:{type(exc).__name__}", {"error": str(exc)[:200]}
            )
        ctx.record_artifact("monitor", monitor.dump())

        refs = {item["ordId"] for item in placed}
        inserts = [event for event in monitor.events if event.get("kind") == "order_insert"]
        own_inserts = [event for event in inserts if str(event.get("order_ref")) in refs]
        residual = _residual_pending(client, market["inst_id"], refs)
        facts = {
            "repeat_count": count,
            "order_insert_events": len(inserts),
            "own_order_insert_events": len(own_inserts),
            "order_ids": sorted(refs),
            "orders": orders,
            "terminal_count": sum(1 for order in orders if order["state"] == "canceled"),
            "price": market["price"],
            "size": market["size"],
        }
        if len(inserts) != count or len(own_inserts) != count:
            return CaseResult(CASE_ID, "FAIL", "repeat_insert_count_mismatch", facts)
        if facts["terminal_count"] != count:
            return CaseResult(CASE_ID, "FAIL", "not_all_canceled_terminal", facts)
        if residual:
            return CaseResult(CASE_ID, "FAIL", "order_still_pending_after_cancel", {**facts, "residual": residual})
        return CaseResult(CASE_ID, "PASS", "", facts)
