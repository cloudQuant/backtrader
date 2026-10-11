"""E02 — genuine venue rejection: close direction without a position.

The case intentionally bypasses local position validation — a SELL reduce
direction on positionSide LONG is submitted although the pre-flight
``position_risk`` query first confirms the LONG position amount is zero,
because the point is to let the venue itself reject the close.  One limit
order (resting inside the venue ±5% band, timeInForce GTC) is submitted
exactly once with an explicit clientOrderId; the expected outcome is
``BinanceApiError`` (the -2022 reduce-only / -4164 / -1106 family — whatever
code arrives is recorded).

Success condition: the venue rejects the insert with code/msg recorded
(truncated to 160 chars) and no order remains for this clientOrderId.  If the
order is unexpectedly accepted it is canceled to CANCELED first and the case
fails (``no_rejection_observed``).  If any position already exists the case
is BLOCKED (``existing_position_present``) so it can never leave a remainder.
"""

from __future__ import annotations

import time

from certlib.binance_client import BinanceApiError, WriteOutcomeUnknown, format_decimal, round_step
from certlib.context import CaseResult

CASE_ID = "E02"
RISK = "WRITE"


def _confirm_canceled(client, symbol, order_id, timeout_ms):
    deadline, last = time.monotonic() + timeout_ms / 1000.0, None
    while time.monotonic() < deadline:
        last = client.query_order(symbol, order_id=order_id)
        if last.get("status") == "CANCELED":
            return last, None
        time.sleep(0.4)
    return last, f"cancel_confirm_timeout:{(last or {}).get('status')}"


class E02Strategy:
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
        if not account.get("dualSidePosition"):
            return CaseResult(CASE_ID, "BLOCKED", "hedge_mode_not_active")

        info = client.filters(symbol)
        if info["status"] != "TRADING":
            return CaseResult(CASE_ID, "BLOCKED", f"symbol_status:{info['status']}")

        # Verify no position exists first, so this case can never leave a remainder.
        positions = client.position_risk(symbol)
        amounts = [float(row.get("positionAmt") or 0) for row in positions]
        if any(amount != 0 for amount in amounts):
            return CaseResult(CASE_ID, "BLOCKED", "existing_position_present", {
                "position_rows": len(positions),
                "max_abs_position_amt": max(abs(a) for a in amounts),
            })

        mark = float(client.mark_price(symbol))
        price = round_step(mark * (1.0 + float(scenario.get("price_offset_bps", 200)) / 10_000.0),
                           info["tick_size"])
        quantity = round_step(float(scenario["quantity"]), info["step_size"])
        client_order_id = f"{CASE_ID}-{int(time.time() * 1000)}"

        baseline = client.open_orders(symbol)
        ctx.log(f"baseline_open_orders={len(baseline)} positions={len(positions)} mark={mark} "
                f"submitting close-side {format_decimal(quantity)}@{format_decimal(price)}")
        facts = {
            "rule": "close_without_position",
            "clientOrderId": client_order_id,
            "symbol": symbol,
            "mark_price": mark,
            "limit_price": price,
            "quantity": format_decimal(quantity),
            "position_rows": len(positions),
            "baseline_open_orders": len(baseline),
            "expected_codes": list(scenario.get("expect_codes", [-2022, -4164, -1106])),
        }

        try:
            order = client.place_order(
                symbol,
                scenario.get("side", "SELL"),
                quantity=format_decimal(quantity),
                price=format_decimal(price),
                position_side=scenario.get("position_side", "LONG"),
                time_in_force=scenario.get("time_in_force", "GTC"),
                client_order_id=client_order_id,
            )
        except BinanceApiError as exc:
            facts["rejection_source"] = "venue_error"
            facts["code"] = exc.code
            facts["msg"] = str(exc.msg)[:160]
            residual = [o for o in client.open_orders(symbol)
                        if o.get("clientOrderId") == client_order_id]
            facts["residual_open_orders"] = len(residual)
            if residual:
                return CaseResult(CASE_ID, "FAIL", "residual_order_present", facts)
            return CaseResult(CASE_ID, "PASS", "", facts)
        except WriteOutcomeUnknown:
            return CaseResult(CASE_ID, "UNKNOWN", "order_outcome_unknown", facts)

        # Unexpected acceptance: the venue allowed a close with no position.
        order_id = order["orderId"]
        ctx.track_order(symbol, order_id, order.get("_client_order_id"))
        ctx.log(f"unexpectedly accepted orderId={order_id}; canceling before failing")
        client.cancel_order(symbol, order_id=order_id)
        final, error = _confirm_canceled(
            client, symbol, order_id, int(scenario.get("cancel_confirm_timeout_ms", 8000))
        )
        ctx.mark_order_closed(order_id)
        facts.update({
            "orderId": order_id,
            "accepted_status": order.get("status"),
            "cancel_final_status": (final or {}).get("status"),
            "cancel_confirm_error": error,
        })
        return CaseResult(CASE_ID, "FAIL", "no_rejection_observed", facts)
