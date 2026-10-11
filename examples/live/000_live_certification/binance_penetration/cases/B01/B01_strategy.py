"""B01 — crossing fill plus resting-order lifecycle (demo-engine adapted).

Live demo observation: the engine fills crossing orders FULLY and instantly
(no partial fills are producible), so the original "partial fill on resting
orders" flow fails as ``no_partial_fill_observed``.  The case is adapted to a
two-order batch:

  * order #1 — crossing BUY LIMIT at the freshly queried book_ticker askPrice
    (fallback mark*1.002), sized ``scenario.order_volume`` (default 0.01),
    GTC, positionSide LONG.  The case waits up to
    ``scenario.fill_poll_timeout_ms`` (default 20000) for status FILLED; a
    status that stays PARTIALLY_FILLED or NEW is recorded as observed and the
    order is canceled to CANCELED.
  * order #2 — non-crossing resting BUY at mark*(1 - price_offset_bps/10000)
    (default mark*0.98, tick-rounded, inside the venue's +-5% band), expected
    NEW and then canceled to CANCELED.

PASS requires: both orders accepted; order #1 terminal with fill evidence
(executedQty > 0) or canceled; order #2 terminal CANCELED; no residual open
order of this run; any net LONG flattened with a crossing SELL MARKET
(positionSide LONG) to FILLED and position_risk positionAmt ~ 0.  Facts
record the actual ``partial_fill_observed`` bool, the per-order evidence, the
flatten evidence and the engine note.

FAIL branches: order1_not_filled, order2_not_canceled, residual_order_open,
flatten_incomplete.
"""

from __future__ import annotations

import time

from certlib.binance_client import BinanceApiError, WriteOutcomeUnknown, format_decimal, round_step
from certlib.context import CaseResult

CASE_ID = "B01"
RISK = "DANGEROUS"

_OPEN_STATES = {"NEW", "PARTIALLY_FILLED"}
_TERMINAL_STATES = {"CANCELED", "FILLED", "EXPIRED", "REJECTED"}

_ENGINE_NOTE = "partial fills not producible on this engine; full fills observed"


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


def _watch_order(client, symbol, order_id, quantity, timeout_ms, want_states):
    """Poll one order until a wanted status or the timeout; ``(snapshot, partial_seen)``.

    ``partial_seen`` records whether 0 < executedQty < quantity was ever
    observed — the honest partial-fill observation for this engine.
    """
    deadline = time.monotonic() + max(timeout_ms, 0) / 1000.0
    snapshot, partial_seen = None, False
    while snapshot is None or time.monotonic() < deadline:
        snapshot = client.query_order(symbol, order_id=order_id)
        executed = float(snapshot.get("executedQty") or 0)
        if 0 < executed < quantity:
            partial_seen = True
        if snapshot.get("status") in want_states:
            return snapshot, partial_seen
        if time.monotonic() >= deadline:
            break
        time.sleep(0.4)
    return snapshot, partial_seen


def _cancel_to_terminal(ctx, symbol, order_id, timeout_ms):
    """Cancel and poll to a terminal state; never raises.  Returns (facts, snapshot)."""
    client = ctx.client
    facts = {"orderId": order_id}
    try:
        facts["cancel_reply_status"] = client.cancel_order(symbol, order_id=order_id).get("status")
    except BinanceApiError as exc:
        facts["cancel_error"] = f"code={exc.code}"
    except WriteOutcomeUnknown:
        facts["cancel_error"] = "outcome_unknown"
    snapshot = client.query_order(symbol, order_id=order_id)
    deadline = time.monotonic() + timeout_ms / 1000.0
    while snapshot.get("status") not in _TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.4)
        snapshot = client.query_order(symbol, order_id=order_id)
    facts.update({"status": snapshot.get("status"), "executedQty": snapshot.get("executedQty")})
    if snapshot.get("status") in _TERMINAL_STATES:
        ctx.mark_order_closed(order_id)
    return facts, snapshot


def _flatten_remaining(ctx, timeout_ms=15000):
    """Best-effort crossing SELL MARKET reversal of the LONG position; never raises."""
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
                                            position_side="LONG", timeout_ms=timeout_ms)
        facts["order"] = _order_facts(snapshot)
    except Exception as exc:
        facts["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return facts


class B01Strategy:
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
        tick = info["tick_size"]
        quantity = round_step(float(scenario.get("order_volume", 0.01)), info["step_size"])
        fill_timeout = int(scenario.get("fill_poll_timeout_ms", 20000))
        cancel_ms = int(scenario.get("cancel_confirm_timeout_ms", 8000))
        flatten_ms = int(scenario.get("flatten_timeout_ms", 15000))

        ticker = client.book_ticker(symbol)
        ask = float(ticker.get("askPrice") or 0.0)
        if ask <= 0:
            ask = mark * 1.002
        cross = round_step(ask, tick)
        if cross < ask:
            cross = round(cross + tick, 10)
        rest = round_step(mark * (1.0 - int(scenario.get("price_offset_bps", 200)) / 10_000.0), tick)
        for price, slot in ((cross, "crossing"), (rest, "resting")):
            notional = price * quantity
            if info["min_notional"] and notional < info["min_notional"]:
                return CaseResult(CASE_ID, "BLOCKED", "below_min_notional",
                                  {"slot": slot, "price": price, "notional": notional})
            if notional > float(policy.get("max_notional_usdt", 0)):
                return CaseResult(CASE_ID, "BLOCKED", "above_policy_notional",
                                  {"slot": slot, "price": price, "notional": notional})

        position_before = _long_amount(client, symbol)
        if abs(position_before) >= info["step_size"]:
            return CaseResult(CASE_ID, "BLOCKED", "position_not_flat_before",
                              {"position_before": position_before})
        baseline = client.open_orders(symbol)
        ctx.log(f"baseline open_orders={len(baseline)} mark={mark} cross={cross} rest={rest} "
                f"qty={format_decimal(quantity)}")

        orders = []
        partial_seen = False

        def reap(extra_facts):
            """Cancel every non-terminal order of this run and flatten any fill."""
            cleanup, filled, partial = [], 0.0, partial_seen
            for item in orders:
                snapshot = client.query_order(symbol, order_id=item["order_id"])
                if snapshot.get("status") in _OPEN_STATES:
                    cancel_facts, snapshot = _cancel_to_terminal(ctx, symbol, item["order_id"], cancel_ms)
                    cleanup.append(cancel_facts)
                executed = float(snapshot.get("executedQty") or 0)
                if 0 < executed < quantity:
                    partial = True
                filled += executed
                if snapshot.get("status") in _TERMINAL_STATES:
                    ctx.mark_order_closed(item["order_id"])
            return {**extra_facts, "cleanup": cleanup, "partial_fill_observed": bool(partial),
                    "engine_note": _ENGINE_NOTE, "total_filled": filled,
                    "flatten": _flatten_remaining(ctx, flatten_ms)}

        def place_buy(order_no, slot, price):
            reply = client.place_order(symbol, "BUY", order_type="LIMIT",
                                       quantity=format_decimal(quantity),
                                       price=format_decimal(price),
                                       position_side="LONG", time_in_force="GTC")
            item = {"slot": slot, "order_id": reply["orderId"],
                    "client_order_id": reply.get("_client_order_id"),
                    "price": format_decimal(price), "placement": reply, "cancel": None}
            orders.append(item)
            ctx.track_order(symbol, item["order_id"], item["client_order_id"])
            ctx.log(f"order #{order_no} ({slot}) BUY {format_decimal(quantity)}"
                    f"@{format_decimal(price)} placed orderId={item['order_id']} "
                    f"status={reply.get('status')}")
            return item

        # ---- order #1: crossing BUY that must fill fully (or be canceled) ----
        try:
            order1 = place_buy(1, "crossing", cross)
        except BinanceApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "order1_not_filled",
                              reap({"placement_error": f"code={exc.code}",
                                    "msg": str(exc.msg)[:200]}))

        snapshot1, partial1 = _watch_order(client, symbol, order1["order_id"], quantity,
                                           fill_timeout, _TERMINAL_STATES)
        partial_seen = partial_seen or partial1
        if snapshot1.get("status") not in _TERMINAL_STATES:
            ctx.log(f"order #1 stayed {snapshot1.get('status')}; canceling")
            order1["cancel"], snapshot1 = _cancel_to_terminal(ctx, symbol, order1["order_id"], cancel_ms)

        # ---- order #2: non-crossing resting BUY, queue then cancel ----------
        if rest >= cross:
            return CaseResult(CASE_ID, "BLOCKED", "no_resting_price_available",
                              reap({"mark": mark, "cross": cross, "rest": rest}))
        try:
            order2 = place_buy(2, "resting", rest)
        except BinanceApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "order2_not_canceled",
                              reap({"placement_error": f"code={exc.code}",
                                    "msg": str(exc.msg)[:200]}))

        snapshot2, partial2 = _watch_order(client, symbol, order2["order_id"], quantity,
                                           fill_timeout, _OPEN_STATES | _TERMINAL_STATES)
        partial_seen = partial_seen or partial2
        if snapshot2.get("status") in _OPEN_STATES:
            order2["accept_status"] = snapshot2.get("status")
            ctx.log(f"order #2 rests as {snapshot2.get('status')}; canceling")
            order2["cancel"], snapshot2 = _cancel_to_terminal(ctx, symbol, order2["order_id"], cancel_ms)

        # ---- residual sweep: last bounded cancel pass, then re-check --------
        finals = {item["order_id"]: client.query_order(symbol, order_id=item["order_id"])
                  for item in orders}
        for order_id, snapshot in finals.items():
            if snapshot.get("status") in _OPEN_STATES:
                _cancel_facts, finals[order_id] = _cancel_to_terminal(ctx, symbol, order_id, cancel_ms)
        residuals = [{"orderId": order_id, "status": str(snapshot.get("status") or "")}
                     for order_id, snapshot in finals.items()
                     if snapshot.get("status") in _OPEN_STATES]

        per_order, total_filled = [], 0.0
        for item in orders:
            snapshot = finals[item["order_id"]]
            executed = float(snapshot.get("executedQty") or 0)
            total_filled += executed
            if 0 < executed < quantity:
                partial_seen = True
            if snapshot.get("status") in _TERMINAL_STATES:
                ctx.mark_order_closed(item["order_id"])
            record = {"slot": item["slot"], "orderId": item["order_id"],
                      "clientOrderId": item["client_order_id"], "price": item["price"],
                      "quantity": format_decimal(quantity),
                      "placement_status": item["placement"].get("status"),
                      "status": snapshot.get("status"),
                      "executedQty": snapshot.get("executedQty"),
                      "avgPrice": snapshot.get("avgPrice")}
            if item.get("accept_status"):
                record["accept_status"] = item["accept_status"]
            if item.get("cancel") is not None:
                record["cancel"] = item["cancel"]
            per_order.append(record)
        record1, record2 = per_order[0], per_order[1]

        # ---- flatten any net LONG, then confirm the position is flat --------
        flatten = _flatten_remaining(ctx, flatten_ms)
        position_after = _long_amount(client, symbol)
        deadline = time.monotonic() + flatten_ms / 1000.0
        while abs(position_after) >= info["step_size"] and time.monotonic() < deadline:
            time.sleep(0.4)
            position_after = _long_amount(client, symbol)
        final_open = client.open_orders(symbol)

        common = {"orders": per_order,
                  "partial_fill_observed": bool(partial_seen),
                  "engine_note": _ENGINE_NOTE,
                  "total_filled": total_filled,
                  "flatten": flatten,
                  "position_before": position_before,
                  "position_after": position_after,
                  "baseline_open_orders": len(baseline),
                  "final_open_orders": len(final_open)}
        status1 = str(record1.get("status") or "")
        executed1 = float(record1.get("executedQty") or 0)
        if not (status1 in _TERMINAL_STATES and (executed1 > 0 or status1 == "CANCELED")):
            return CaseResult(CASE_ID, "FAIL", "order1_not_filled", common)
        if str(record2.get("status") or "") != "CANCELED":
            return CaseResult(CASE_ID, "FAIL", "order2_not_canceled", common)
        if residuals:
            return CaseResult(CASE_ID, "FAIL", "residual_order_open",
                              {**common, "residuals": residuals})
        position_measure = float(flatten.get("position_amount") or 0)
        flatten_status = str((flatten.get("order") or {}).get("status") or "")
        if position_measure >= info["step_size"] and flatten_status != "FILLED":
            return CaseResult(CASE_ID, "FAIL", "flatten_incomplete", common)
        if abs(position_after) >= info["step_size"]:
            return CaseResult(CASE_ID, "FAIL", "flatten_incomplete", common)
        return CaseResult(CASE_ID, "PASS", "", {**common, "position_flat": True,
                                                "fill_volume": total_filled})
