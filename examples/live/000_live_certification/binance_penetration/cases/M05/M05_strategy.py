"""M05 — the local monitor records submit and cancel.

Success condition: the case-local monitor holds order_insert and order_action
events for this order's reference, the venue accepted the resting LIMIT order,
the order is canceled to terminal, and no order of this run remains open.
"""

from __future__ import annotations

import time

from certlib.binance_client import format_decimal, round_step
from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "M05"
RISK = "WRITE"

_OPEN_STATES = {"NEW", "PARTIALLY_FILLED"}
_TERMINAL_STATES = {"CANCELED", "FILLED", "EXPIRED", "REJECTED"}
_POLL_SECONDS = 0.4


def _plan(ctx):
    """Validate the policy/instrument and compute the bounded resting order plan."""
    scenario = ctx.scenario()
    policy = ctx.config.get("policy", {})
    client = ctx.client
    symbol = scenario["symbol"]
    if symbol not in policy.get("symbol_allowlist", []):
        return None, CaseResult(CASE_ID, "BLOCKED", "symbol_not_allowed")
    if not client.account_config().get("canTrade"):
        return None, CaseResult(CASE_ID, "BLOCKED", "account_cannot_trade")
    info = client.filters(symbol)
    if info["status"] != "TRADING":
        return None, CaseResult(CASE_ID, "BLOCKED", f"symbol_status:{info['status']}")
    mark = float(client.mark_price(symbol))
    side = str(scenario.get("side", "BUY")).upper()
    offset = float(scenario.get("price_offset_bps", 200)) / 10_000.0
    price = round_step(mark * (1.0 + (-1.0 if side == "BUY" else 1.0) * offset), info["tick_size"])
    quantity = round_step(float(scenario["quantity"]), info["step_size"])
    notional = price * quantity
    if notional < info["min_notional"]:
        return None, CaseResult(CASE_ID, "BLOCKED", "below_min_notional", {"notional": notional})
    if notional > float(policy.get("max_notional_usdt", 0)):
        return None, CaseResult(CASE_ID, "BLOCKED", "above_policy_notional", {"notional": notional})
    return {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "mark": mark,
        "position_side": scenario.get("position_side") or ("LONG" if side == "BUY" else "SHORT"),
        "time_in_force": scenario.get("time_in_force", "GTC"),
    }, None


def _place_resting(ctx, plan):
    """Place one resting LIMIT order and register it for the compensating cleanup."""
    order = ctx.client.place_order(
        plan["symbol"],
        plan["side"],
        quantity=format_decimal(plan["quantity"]),
        price=format_decimal(plan["price"]),
        position_side=plan["position_side"],
        time_in_force=plan["time_in_force"],
    )
    order_id = order["orderId"]
    ctx.track_order(plan["symbol"], order_id, order.get("_client_order_id"))
    return order_id


def _await_status(client, plan, order_id, phase, timeout_ms):
    """Poll query_order until acceptance (phase="accept") or CANCELED ("cancel")."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    snapshot = {}
    while time.monotonic() < deadline:
        snapshot = client.query_order(plan["symbol"], order_id=order_id)
        status = snapshot.get("status")
        if (phase == "accept" and status in _OPEN_STATES) or (
            phase == "cancel" and status == "CANCELED"
        ):
            return snapshot, None
        if status in _TERMINAL_STATES:
            token = (
                f"order_went_terminal_before_cancel:{status}"
                if phase == "accept"
                else f"terminal_state:{status}"
            )
            return None, CaseResult(
                CASE_ID,
                "FAIL",
                token,
                {"orderId": order_id, "executedQty": snapshot.get("executedQty")},
            )
        time.sleep(_POLL_SECONDS)
    token = "accept_timeout" if phase == "accept" else "cancel_confirm_timeout"
    return None, CaseResult(CASE_ID, "FAIL", token, {"orderId": order_id, "last": snapshot.get("status")})


def _residual(client, plan, order_ids):
    return [o for o in client.open_orders(plan["symbol"]) if o.get("orderId") in order_ids]


class M05Strategy:
    def run(self, ctx):
        plan, blocked = _plan(ctx)
        if blocked is not None:
            return blocked
        scenario = ctx.scenario()
        accept_ms = int(scenario.get("accept_timeout_ms", 8000))
        cancel_ms = int(scenario.get("cancel_timeout_ms", 8000))
        # BinanceDemoClient has no event hook: the case records the monitor
        # events itself around the client calls.
        monitor = Monitor({})
        baseline = ctx.client.open_orders(plan["symbol"])
        ctx.log(
            f"baseline_open_orders={len(baseline)} mark={plan['mark']} "
            f"plan={plan['quantity']}@{plan['price']}"
        )
        order_id = _place_resting(ctx, plan)
        monitor.record("order_insert", order_ref=str(order_id))
        ctx.log(f"placed orderId={order_id} monitor=order_insert")
        accepted, failed = _await_status(ctx.client, plan, order_id, "accept", accept_ms)
        if failed is not None:
            return failed
        ctx.log(f"accepted orderId={order_id} status={accepted.get('status')}")
        ctx.client.cancel_order(plan["symbol"], order_id=order_id)
        monitor.record("order_action", order_ref=str(order_id))
        final, failed = _await_status(ctx.client, plan, order_id, "cancel", cancel_ms)
        if failed is not None:
            return failed
        ctx.mark_order_closed(order_id)
        ctx.record_artifact("monitor", monitor.dump())
        inserts = [
            event
            for event in monitor.events
            if event.get("kind") == "order_insert" and event.get("order_ref") == str(order_id)
        ]
        actions = [
            event
            for event in monitor.events
            if event.get("kind") == "order_action" and event.get("order_ref") == str(order_id)
        ]
        residual = _residual(ctx.client, plan, {order_id})
        facts = {
            "orderId": order_id,
            "clientOrderId": final.get("clientOrderId"),
            "status": final.get("status"),
            "executedQty": final.get("executedQty"),
            "price": plan["price"],
            "quantity": plan["quantity"],
            "monitored_event_count": len(monitor.events),
            "matched_insert_events": len(inserts),
            "matched_cancel_events": len(actions),
            "baseline_open_orders": len(baseline),
            "final_open_orders": len(ctx.client.open_orders(plan["symbol"])),
        }
        if not inserts:
            return CaseResult(CASE_ID, "FAIL", "monitor_missing_order_insert_event", facts)
        if not actions:
            return CaseResult(CASE_ID, "FAIL", "monitor_missing_order_action_event", facts)
        if residual:
            return CaseResult(
                CASE_ID, "FAIL", "order_still_open_after_cancel", {**facts, "residual": residual}
            )
        return CaseResult(CASE_ID, "PASS", "", facts)
