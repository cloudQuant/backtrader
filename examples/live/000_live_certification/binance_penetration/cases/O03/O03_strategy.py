"""O03 — a repeated cancel is either rejected or leaves the order terminal.

Success condition: two resting LIMIT orders are canceled to the terminal
CANCELED state, a repeated cancel of the first order either raises a venue
error or leaves the query status CANCELED (no resurrection), and no order of
this run remains open.
"""

from __future__ import annotations

import time

from certlib.binance_client import BinanceApiError, format_decimal, round_step
from certlib.context import CaseResult

CASE_ID = "O03"
RISK = "DANGEROUS"

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


class O03Strategy:
    def run(self, ctx):
        plan, blocked = _plan(ctx)
        if blocked is not None:
            return blocked
        scenario = ctx.scenario()
        count = max(2, int(scenario.get("order_count", 2)))
        accept_ms = int(scenario.get("accept_timeout_ms", 8000))
        cancel_ms = int(scenario.get("cancel_timeout_ms", 8000))
        interval_ms = int(scenario.get("order_interval_ms", 800))
        repeat_wait_ms = int(scenario.get("repeat_cancel_wait_ms", 1000))
        baseline = ctx.client.open_orders(plan["symbol"])
        ctx.log(
            f"baseline_open_orders={len(baseline)} mark={plan['mark']} "
            f"plan={count}x{plan['quantity']}@{plan['price']}"
        )
        placed = []
        for index in range(count):
            if index and interval_ms > 0:
                time.sleep(interval_ms / 1000.0)
            order_id = _place_resting(ctx, plan)
            accepted, failed = _await_status(ctx.client, plan, order_id, "accept", accept_ms)
            if failed is not None:
                return failed
            placed.append({"orderId": order_id, "in_queue_status": accepted.get("status")})
            ctx.log(f"accepted orderId={order_id} status={accepted.get('status')}")
        for item in placed:
            order_id = item["orderId"]
            ctx.client.cancel_order(plan["symbol"], order_id=order_id)
            final, failed = _await_status(ctx.client, plan, order_id, "cancel", cancel_ms)
            if failed is not None:
                return failed
            ctx.mark_order_closed(order_id)
            item["final_status"] = final.get("status")
            ctx.log(f"canceled orderId={order_id} status={final.get('status')}")
        first_id = placed[0]["orderId"]
        outcome, outcome_facts = "", {}
        try:
            reply = ctx.client.cancel_order(plan["symbol"], order_id=first_id)
        except BinanceApiError as exc:
            outcome = "repeat_cancel_rejected"
            outcome_facts = {"repeat_error_code": exc.code, "repeat_error_msg": str(exc.msg)[:200]}
        else:
            if repeat_wait_ms > 0:
                time.sleep(repeat_wait_ms / 1000.0)
            latest = ctx.client.query_order(plan["symbol"], order_id=first_id)
            outcome_facts = {
                "repeat_reply_status": reply.get("status"),
                "repeat_query_status": latest.get("status"),
            }
            if latest.get("status") == "CANCELED":
                outcome = "repeat_cancel_terminal_unchanged"
            else:
                return CaseResult(
                    CASE_ID,
                    "FAIL",
                    "repeat_cancel_resurrected",
                    {"firstOrderId": first_id, "orders": placed, **outcome_facts},
                )
        residual = _residual(ctx.client, plan, {item["orderId"] for item in placed})
        facts = {
            "order_count": count,
            "orders": placed,
            "firstOrderId": first_id,
            "terminal_count": sum(1 for o in placed if o.get("final_status") == "CANCELED"),
            "repeat_cancel_outcome": outcome,
            "price": plan["price"],
            "quantity": plan["quantity"],
            "baseline_open_orders": len(baseline),
            "final_open_orders": len(ctx.client.open_orders(plan["symbol"])),
            **outcome_facts,
        }
        if residual:
            return CaseResult(
                CASE_ID, "FAIL", "order_still_open_after_cancel", {**facts, "residual": residual}
            )
        if facts["terminal_count"] != count:
            return CaseResult(CASE_ID, "FAIL", "not_all_canceled_terminal", facts)
        return CaseResult(CASE_ID, "PASS", outcome, facts)
