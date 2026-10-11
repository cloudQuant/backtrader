"""T01 — a bounded resting LIMIT order is accepted and finally canceled.

Success condition: the venue accepts the order with an open status, the case
cancels it, the terminal state is CANCELED, and no order of this run remains.
"""

from __future__ import annotations

import time

from certlib.binance_client import format_decimal, round_step
from certlib.context import CaseResult

CASE_ID = "T01"
RISK = "WRITE"

_OPEN_STATES = {"NEW", "PARTIALLY_FILLED"}
_TERMINAL_STATES = {"CANCELED", "FILLED", "EXPIRED", "REJECTED"}


class T01Strategy:
    def run(self, ctx):
        scenario = ctx.scenario()
        policy = ctx.config.get("policy", {})
        client = ctx.client

        symbol = scenario["symbol"]
        if symbol not in policy.get("symbol_allowlist", []):
            return CaseResult(CASE_ID, "BLOCKED", "symbol_not_allowed")

        account = client.account_config()
        if not account.get("canTrade"):
            return CaseResult(CASE_ID, "BLOCKED", "account_cannot_trade")

        info = client.filters(symbol)
        if info["status"] != "TRADING":
            return CaseResult(CASE_ID, "BLOCKED", f"symbol_status:{info['status']}")

        mark = float(client.mark_price(symbol))
        price = round_step(mark * (1.0 - scenario["price_offset_bps"] / 10_000.0), info["tick_size"])
        quantity = round_step(float(scenario["quantity"]), info["step_size"])
        notional = price * quantity
        if notional < info["min_notional"]:
            return CaseResult(CASE_ID, "BLOCKED", "below_min_notional", {"notional": notional})
        if notional > float(policy.get("max_notional_usdt", 0)):
            return CaseResult(CASE_ID, "BLOCKED", "above_policy_notional", {"notional": notional})

        baseline = client.open_orders(symbol)
        ctx.log(f"baseline_open_orders={len(baseline)} mark={mark} plan={quantity}@{price}")

        order = client.place_order(
            symbol,
            scenario["side"],
            quantity=format_decimal(quantity),
            price=format_decimal(price),
            position_side=scenario.get("position_side"),
            time_in_force=scenario.get("time_in_force", "GTC"),
        )
        order_id = order["orderId"]
        ctx.track_order(symbol, order_id, order.get("_client_order_id"))
        ctx.log(f"placed orderId={order_id} status={order.get('status')}")

        deadline = time.monotonic() + scenario.get("accept_timeout_ms", 8000) / 1000.0
        accepted = None
        while time.monotonic() < deadline:
            snapshot = client.query_order(symbol, order_id=order_id)
            if snapshot.get("status") in _OPEN_STATES:
                accepted = snapshot
                break
            if snapshot.get("status") in _TERMINAL_STATES:
                return CaseResult(
                    CASE_ID,
                    "FAIL",
                    f"order_went_terminal_before_cancel:{snapshot.get('status')}",
                    {"orderId": order_id, "executedQty": snapshot.get("executedQty")},
                )
            time.sleep(0.4)
        if accepted is None:
            return CaseResult(
                CASE_ID, "FAIL", "accept_timeout", {"orderId": order_id, "last": snapshot.get("status")}
            )

        canceled = client.cancel_order(symbol, order_id=order_id)
        ctx.log(f"cancel reply status={canceled.get('status')}")

        deadline = time.monotonic() + scenario.get("cancel_confirm_timeout_ms", 8000) / 1000.0
        final = None
        while time.monotonic() < deadline:
            snapshot = client.query_order(symbol, order_id=order_id)
            status = snapshot.get("status")
            if status == "CANCELED":
                final = snapshot
                break
            if status in _TERMINAL_STATES:
                return CaseResult(CASE_ID, "FAIL", f"terminal_state:{status}", {"orderId": order_id})
            time.sleep(0.4)
        if final is None:
            return CaseResult(CASE_ID, "FAIL", "cancel_confirm_timeout", {"orderId": order_id})

        executed = float(final.get("executedQty", "0") or 0)
        residual = [o for o in client.open_orders(symbol) if o.get("orderId") == order_id]
        if residual:
            return CaseResult(CASE_ID, "FAIL", "order_still_open_after_cancel", {"orderId": order_id})

        if executed > 0:
            # The resting order should not fill; if it did, flatten the residual position.
            close = client.place_order(
                symbol,
                "SELL",
                order_type="MARKET",
                quantity=format_decimal(round_step(executed, info["step_size"])),
                position_side=scenario.get("position_side", "LONG"),
            )
            ctx.track_order(symbol, close["orderId"], close.get("_client_order_id"))
            ctx.mark_order_closed(close["orderId"])
            ctx.log(f"unexpected fill {executed}; market-close orderId={close['orderId']}")
        ctx.mark_order_closed(order_id)

        return CaseResult(
            CASE_ID,
            "PASS",
            "",
            {
                "orderId": order_id,
                "clientOrderId": final.get("clientOrderId"),
                "status": final.get("status"),
                "executedQty": final.get("executedQty"),
                "avgPrice": final.get("avgPrice"),
                "baseline_open_orders": len(baseline),
                "final_open_orders": len(client.open_orders(symbol)),
            },
        )
