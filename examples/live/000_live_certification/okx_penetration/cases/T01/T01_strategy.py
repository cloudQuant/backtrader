"""T01 — a bounded resting LIMIT order is accepted and finally canceled.

Success condition: the demo venue accepts the order (order id assigned), the
order is visible as live in the venue order query, the case cancels it, the
terminal state is canceled, and no order of this run remains pending.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult

CASE_ID = "T01"
RISK = "WRITE"

_OPEN_STATES = {"live", "partially_filled"}
_TERMINAL_STATES = {"canceled", "filled"}


def _round_to_step(value, step):
    step = float(step)
    return round(round(float(value) / step) * step, 10)


class T01Strategy:
    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        policy = ctx.config.get("policy", {})

        inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")
        if inst_id not in policy.get("symbol_allowlist", []):
            return CaseResult(CASE_ID, "BLOCKED", "symbol_not_allowed")

        instruments = client.instruments(inst_id)
        if not instruments:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_unknown", {"inst_id": inst_id})
        meta = instruments[0]
        tick = float(meta.get("tickSz") or 0.1)
        lot = float(meta.get("lotSz") or 1)

        ticker = client.ticker(inst_id)
        last = float(ticker["last"])
        price = _round_to_step(last * (1.0 - scenario.get("price_offset_bps", 200) / 10_000.0), tick)
        size = _round_to_step(float(scenario.get("size", 1)), lot)
        notional = price * size * float(meta.get("ctVal") or 0)
        if notional > float(policy.get("max_notional_usdt", 0)):
            return CaseResult(CASE_ID, "BLOCKED", "above_policy_notional", {"notional": notional})

        baseline = client.pending_orders(inst_id=inst_id)
        ctx.log(f"baseline_pending={len(baseline)} last={last} plan={size}@{price}")

        placement = client.place_order(
            inst_id, scenario.get("side", "buy"), sz=size, px=price, ord_type="limit"
        )
        ord_id = placement["ordId"]
        ctx.track_order(inst_id, ord_id, placement.get("_cl_ord_id"))
        ctx.log(f"placed ordId={ord_id}")

        deadline = time.monotonic() + scenario.get("accept_timeout_ms", 8000) / 1000.0
        accepted = None
        while time.monotonic() < deadline:
            rows = client.order_details(inst_id, ord_id=ord_id)
            state = str((rows[0] if rows else {}).get("state"))
            if state in _OPEN_STATES:
                accepted = rows[0]
                break
            if state in _TERMINAL_STATES:
                ctx.mark_order_closed(ord_id)
                return CaseResult(CASE_ID, "FAIL", f"order_went_terminal_before_cancel:{state}", {"ordId": ord_id})
            time.sleep(0.3)
        if accepted is None:
            return CaseResult(CASE_ID, "FAIL", "accept_timeout", {"ordId": ord_id})

        canceled = client.cancel_order(inst_id, ord_id=ord_id)
        ctx.log(f"cancel reply ordId={canceled.get('ordId')}")

        deadline = time.monotonic() + scenario.get("cancel_confirm_timeout_ms", 8000) / 1000.0
        final = None
        while time.monotonic() < deadline:
            rows = client.order_details(inst_id, ord_id=ord_id)
            state = str((rows[0] if rows else {}).get("state"))
            if state == "canceled":
                final = rows[0]
                break
            if state in _TERMINAL_STATES:
                return CaseResult(CASE_ID, "FAIL", f"terminal_state:{state}", {"ordId": ord_id})
            time.sleep(0.3)
        if final is None:
            return CaseResult(CASE_ID, "FAIL", "cancel_confirm_timeout", {"ordId": ord_id})

        residual = [o for o in client.pending_orders(inst_id=inst_id) if o.get("ordId") == ord_id]
        ctx.mark_order_closed(ord_id)
        if residual:
            return CaseResult(CASE_ID, "FAIL", "order_still_pending_after_cancel", {"ordId": ord_id})

        return CaseResult(
            CASE_ID,
            "PASS",
            "",
            {
                "ordId": ord_id,
                "clOrdId": placement.get("_cl_ord_id"),
                "state": final.get("state"),
                "accFillSz": final.get("accFillSz"),
                "avgPx": final.get("avgPx"),
                "baseline_pending": len(baseline),
                "final_pending": len(client.pending_orders(inst_id=inst_id)),
            },
        )
