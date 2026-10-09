"""O02 — resting reduce flow: the MARKET BUY open fills, a non-crossing reduce
SELL LIMIT is accepted as NEW, canceled to the terminal CANCELED state, then
the position is flattened flat again.

PASS: position existed, reduce order rested NEW, final state CANCELED, flat.
"""

from __future__ import annotations

import time

from certlib.binance_client import BinanceApiError, format_decimal, round_step
from certlib.context import CaseResult

CASE_ID = "O02"
RISK = "DANGEROUS"

_TERMINAL_STATES = {"CANCELED", "FILLED", "EXPIRED", "REJECTED"}


def _long_amount(client, symbol):
    """Signed positionAmt of the hedge-mode LONG side; 0.0 when absent."""
    for row in client.position_risk(symbol):
        if row.get("positionSide") == "LONG":
            return float(row.get("positionAmt") or 0.0)
    return 0.0


def _order_facts(s):
    return {"orderId": s.get("orderId"), "clientOrderId": s.get("clientOrderId"),
            "status": s.get("status"), "executedQty": s.get("executedQty"), "avgPrice": s.get("avgPrice")}


def _place_market(ctx, symbol, side, quantity, *, position_side, timeout_ms):
    """Crossing MARKET order: tracked, then polled to a terminal state."""
    client = ctx.client
    order = client.place_order(symbol, side, order_type="MARKET", quantity=quantity,
                               position_side=position_side)
    order_id = order["orderId"]
    ctx.track_order(symbol, order_id, order.get("_client_order_id"))
    ctx.log(f"placed {side} MARKET {quantity} orderId={order_id} status={order.get('status')}")
    deadline = time.monotonic() + timeout_ms / 1000.0
    snapshot = order
    while snapshot.get("status") not in _TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.4)
        snapshot = client.query_order(symbol, order_id=order_id)
    if snapshot.get("status") in _TERMINAL_STATES:
        ctx.mark_order_closed(order_id)
    return order_id, snapshot


def _wait_amount(client, symbol, step, timeout_ms, *, target):
    """Bounded poll for a flat (|amt| < step) or positive LONG position."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    amount = _long_amount(client, symbol)
    while time.monotonic() < deadline:
        if (target == "flat" and abs(amount) < step) or (target == "positive" and amount > 0):
            return amount
        time.sleep(0.4)
        amount = _long_amount(client, symbol)
    return amount


def _flatten_remaining(ctx):
    """Best-effort MARKET reversal of the LONG position; never raises."""
    client = ctx.client
    symbol = ctx.scenario().get("symbol")
    facts = {"symbol": symbol}
    try:
        info = client.filters(symbol)
        amount = _long_amount(client, symbol)
        facts["position_amount"] = amount
        if abs(amount) < info["step_size"]:
            facts["skipped"] = "already_flat"
            return facts
        side = "SELL" if amount > 0 else "BUY"
        quantity = format_decimal(round_step(abs(amount), info["step_size"]))
        _order_id, snapshot = _place_market(ctx, symbol, side, quantity,
                                            position_side="LONG", timeout_ms=15000)
        facts["order"] = _order_facts(snapshot)
    except Exception as exc:
        facts["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return facts


def _cancel_to_terminal(ctx, symbol, order_id, timeout_ms):
    """Cancel and poll to a terminal state; never raises. Returns (facts, snapshot)."""
    client = ctx.client
    facts = {"orderId": order_id}
    try:
        facts["cancel_reply_status"] = client.cancel_order(symbol, order_id=order_id).get("status")
    except BinanceApiError as exc:
        facts["cancel_error"] = f"code={exc.code}"
    snapshot = client.query_order(symbol, order_id=order_id)
    deadline = time.monotonic() + timeout_ms / 1000.0
    while snapshot.get("status") not in _TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.4)
        snapshot = client.query_order(symbol, order_id=order_id)
    facts.update({"status": snapshot.get("status"), "executedQty": snapshot.get("executedQty")})
    if snapshot.get("status") in _TERMINAL_STATES:
        ctx.mark_order_closed(order_id)
    return facts, snapshot


class O02Strategy:
    def run(self, ctx):
        try:
            return self._flow(ctx)
        except Exception as exc:
            return CaseResult(CASE_ID, "FAIL", f"exception:{type(exc).__name__}",
                              {"error": f"{type(exc).__name__}: {exc}"[:300],
                               "flatten": _flatten_remaining(ctx)})

    def _flow(self, ctx):
        scenario = ctx.scenario()
        policy = ctx.config.get("policy", {})
        client = ctx.client

        symbol = scenario["symbol"]
        if symbol not in policy.get("symbol_allowlist", []):
            return CaseResult(CASE_ID, "BLOCKED", "symbol_not_allowed")
        account = client.account_config()
        if not account.get("canTrade"):
            return CaseResult(CASE_ID, "BLOCKED", "account_cannot_trade")
        if str(account.get("dualSidePosition", "")).lower() not in ("true", "1"):
            return CaseResult(CASE_ID, "BLOCKED", "hedge_mode_required")
        info = client.filters(symbol)
        if info["status"] != "TRADING":
            return CaseResult(CASE_ID, "BLOCKED", f"symbol_status:{info['status']}")
        mark = float(client.mark_price(symbol))
        quantity = round_step(float(scenario.get("quantity", 0.001)), info["step_size"])
        price = round_step(mark * (1.0 + int(scenario.get("reduce_price_offset_bps", 200)) / 10_000.0),
                           info["tick_size"])
        notional = mark * quantity
        if info["min_notional"] and notional < info["min_notional"]:
            return CaseResult(CASE_ID, "BLOCKED", "below_min_notional", {"notional": notional})
        if notional > float(policy.get("max_notional_usdt", 0)):
            return CaseResult(CASE_ID, "BLOCKED", "above_policy_notional", {"notional": notional})
        if price <= mark:
            return CaseResult(CASE_ID, "BLOCKED", "no_resting_price", {"mark": mark, "price": price})

        position_before = _long_amount(client, symbol)
        if abs(position_before) >= info["step_size"]:
            return CaseResult(CASE_ID, "BLOCKED", "position_not_flat_before",
                              {"position_before": position_before})
        baseline = client.open_orders(symbol)
        ctx.log(f"baseline open_orders={len(baseline)} mark={mark} quantity={quantity} "
                f"resting_reduce={price}")

        try:
            open_id, open_snapshot = _place_market(
                ctx, symbol, "BUY", format_decimal(quantity), position_side="LONG",
                timeout_ms=int(scenario.get("open_timeout_ms", 15000)))
        except BinanceApiError as exc:
            return CaseResult(CASE_ID, "FAIL", f"open_rejected:{exc.code}",
                              {"msg": str(exc.msg)[:200]})
        if open_snapshot.get("status") != "FILLED":
            return CaseResult(CASE_ID, "FAIL", f"open_not_filled:{open_snapshot.get('status')}",
                              {"open": _order_facts(open_snapshot),
                               "flatten": _flatten_remaining(ctx)})
        executed = round_step(float(open_snapshot.get("executedQty") or 0), info["step_size"])
        if executed <= 0:
            return CaseResult(CASE_ID, "FAIL", "open_executed_quantity_zero",
                              {"open": _order_facts(open_snapshot), "flatten": _flatten_remaining(ctx)})

        position_after_open = _wait_amount(client, symbol, info["step_size"],
                                           int(scenario.get("position_reflect_timeout_ms", 5000)),
                                           target="positive")
        if position_after_open <= 0:
            return CaseResult(CASE_ID, "FAIL", "position_not_reflected",
                              {"open": _order_facts(open_snapshot),
                               "position_after_open": position_after_open,
                               "flatten": _flatten_remaining(ctx)})

        try:
            reply = client.place_order(symbol, "SELL", order_type="LIMIT",
                                       quantity=format_decimal(executed), price=format_decimal(price),
                                       position_side="LONG", time_in_force="GTC")
        except BinanceApiError as exc:
            return CaseResult(CASE_ID, "FAIL", f"reduce_rejected:{exc.code}",
                              {"open": _order_facts(open_snapshot),
                               "position_after_open": position_after_open,
                               "msg": str(exc.msg)[:200], "flatten": _flatten_remaining(ctx)})
        reduce_id = reply["orderId"]
        ctx.track_order(symbol, reduce_id, reply.get("_client_order_id"))
        ctx.log(f"placed resting reduce SELL orderId={reduce_id} status={reply.get('status')} "
                f"price={price}")

        deadline = time.monotonic() + int(scenario.get("accept_timeout_ms", 8000)) / 1000.0
        while time.monotonic() < deadline and reply.get("status") not in _TERMINAL_STATES | {"NEW"}:
            time.sleep(0.3)
            reply = client.query_order(symbol, order_id=reduce_id)
        accept_status = reply.get("status")

        cancel_facts, final = _cancel_to_terminal(ctx, symbol, reduce_id,
                                                  int(scenario.get("cancel_confirm_timeout_ms", 8000)))
        flatten = _flatten_remaining(ctx)
        position_after = _wait_amount(client, symbol, info["step_size"],
                                      int(scenario.get("flatten_timeout_ms", 15000)), target="flat")
        facts = {"open": _order_facts(open_snapshot), "position_after_open": position_after_open,
                 "reduce": {"orderId": reduce_id, "price": format_decimal(price),
                            "quantity": format_decimal(executed), "accept_status": accept_status,
                            "terminal_status": final.get("status"),
                            "executedQty": final.get("executedQty"), "cancel": cancel_facts},
                 "flatten": flatten, "position_before": position_before,
                 "position_after": position_after,
                 "position_flat": abs(position_after) < info["step_size"],
                 "baseline_open_orders": len(baseline),
                 "final_open_orders": len(client.open_orders(symbol))}
        if accept_status != "NEW":
            return CaseResult(CASE_ID, "FAIL", f"reduce_not_resting:{accept_status}", facts)
        if str(final.get("status")) != "CANCELED":
            return CaseResult(CASE_ID, "FAIL", f"reduce_terminal_not_canceled:{final.get('status')}", facts)
        if not facts["position_flat"]:
            return CaseResult(CASE_ID, "FAIL", "position_not_flat", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
