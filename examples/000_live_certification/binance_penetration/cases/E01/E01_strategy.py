"""E01 — genuine venue rejection: insufficient margin (deliberately oversized).

The case intentionally bypasses local margin/notional validation — the
oversized BTC quantity ("50" by default, several million USDT) is never
pre-checked locally, because the point is to let the venue itself reject the
request.  One BUY limit order (resting inside the venue ±5% band,
positionSide LONG, timeInForce GTC) is submitted exactly once with an explicit
clientOrderId.  The expected outcome is ``BinanceApiError`` (typically code
-2019 insufficient margin; whatever code arrives is recorded).

Success condition: the venue rejects the insert with code/msg recorded
(truncated to 160 chars) AND no order was created — the symbol's open orders
must contain no order with this run's clientOrderId.  If the order is
unexpectedly accepted it is canceled to CANCELED first and the case fails
(``no_rejection_observed``).
"""

from __future__ import annotations

import time

from certlib.binance_client import BinanceApiError, WriteOutcomeUnknown, format_decimal, round_step
from certlib.context import CaseResult

CASE_ID = "E01"
RISK = "WRITE"


def _residual(client, symbol, client_order_id):
    """Open orders carrying this run's clientOrderId; the venue must have none."""
    return [o for o in client.open_orders(symbol) if o.get("clientOrderId") == client_order_id]


def _confirm_canceled(client, symbol, order_id, timeout_ms):
    """Bounded poll until CANCELED; returns (snapshot, error_reason)."""
    deadline, last = time.monotonic() + timeout_ms / 1000.0, None
    while time.monotonic() < deadline:
        last = client.query_order(symbol, order_id=order_id)
        if last.get("status") == "CANCELED":
            return last, None
        time.sleep(0.4)
    return last, f"cancel_confirm_timeout:{(last or {}).get('status')}"


class E01Strategy:
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
        price = round_step(mark * (1.0 - float(scenario.get("price_offset_bps", 200)) / 10_000.0),
                           info["tick_size"])
        # Deliberately oversized: no local balance/margin check intervenes.
        quantity = round_step(float(scenario["oversize_quantity"]), info["step_size"])
        client_order_id = f"{CASE_ID}-{int(time.time() * 1000)}"

        baseline = client.open_orders(symbol)
        ctx.log(f"baseline_open_orders={len(baseline)} mark={mark} "
                f"submitting oversize {format_decimal(quantity)}@{format_decimal(price)}")
        facts = {
            "rule": "insufficient_margin",
            "clientOrderId": client_order_id,
            "symbol": symbol,
            "mark_price": mark,
            "limit_price": price,
            "quantity": format_decimal(quantity),
            "notional_usdt": round(price * quantity, 2),
            "baseline_open_orders": len(baseline),
            "expected_codes": list(scenario.get("expect_codes", [-2019])),
        }

        try:
            order = client.place_order(
                symbol,
                scenario.get("side", "BUY"),
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
            residual = _residual(client, symbol, client_order_id)
            facts["residual_open_orders"] = len(residual)
            if residual:
                return CaseResult(CASE_ID, "FAIL", "residual_order_present", facts)
            return CaseResult(CASE_ID, "PASS", "", facts)
        except WriteOutcomeUnknown:
            return CaseResult(CASE_ID, "UNKNOWN", "order_outcome_unknown", facts)

        # Unexpected acceptance: the venue did not reject the oversized order.
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
