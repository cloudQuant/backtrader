"""EM02 — strategy pause / resume around a terminal-canceled order cycle.

The case implements its own local write-pause guard: the operator (recorded
operator/authorization refs) sets the plain attribute ``client._cert_paused``
and every guarded write goes through the module-level ``_place_guarded``
helper, which raises ``RuntimeError("write_paused")`` before any dispatch when
the flag is set.  The paused attempt must be refused locally with no dispatch
(recorded via ``open_orders`` being unchanged and containing no order for this
run's clientOrderId).

After resume the same helper completes a real resting LIMIT order cycle:
accepted (NEW) -> canceled -> terminal CANCELED, with no residual order.
PASS = paused attempt refused locally + post-resume order cycle canceled +
no residual.
"""

from __future__ import annotations

import time

from certlib.binance_client import BinanceApiError, WriteOutcomeUnknown, format_decimal, round_step
from certlib.context import CaseResult

CASE_ID = "EM02"
RISK = "WRITE"

_OPEN_STATES = {"NEW", "PARTIALLY_FILLED"}
_TERMINAL_STATES = {"CANCELED", "FILLED", "EXPIRED", "REJECTED"}


def _place_guarded(client, **params):
    """Local write guard: refuse before dispatch while the pause flag is set."""
    if getattr(client, "_cert_paused", False):
        raise RuntimeError("write_paused")
    return client.place_order(**params)


def _wait_status(client, symbol, order_id, wanted, timeout_ms):
    """Bounded poll; returns (latest_snapshot, matched_wanted)."""
    deadline, last = time.monotonic() + timeout_ms / 1000.0, None
    while time.monotonic() < deadline:
        last = client.query_order(symbol, order_id=order_id)
        if last.get("status") in wanted:
            return last, True
        time.sleep(0.4)
    return last, False


class EM02Strategy:
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

        mark = float(client.mark_price(symbol))
        price = round_step(mark * (1.0 - float(scenario.get("price_offset_bps", 200)) / 10_000.0),
                           info["tick_size"])
        quantity = round_step(float(scenario["quantity"]), info["step_size"])
        client_order_id = f"{CASE_ID}-{int(time.time() * 1000)}"
        order_params = {
            "symbol": symbol,
            "side": scenario.get("side", "BUY"),
            "quantity": format_decimal(quantity),
            "price": format_decimal(price),
            "position_side": scenario.get("position_side", "LONG"),
            "time_in_force": scenario.get("time_in_force", "GTC"),
            "client_order_id": client_order_id,
        }

        operator_ref = str(scenario.get("operator_ref") or "operator-cert-em02")
        authorization_ref = str(scenario.get("authorization_ref") or "auth-cert-em02")
        baseline = client.open_orders(symbol)
        facts = {
            "operator_ref": operator_ref,
            "authorization_ref": authorization_ref,
            "pause_state": "write_paused",
            "clientOrderId": client_order_id,
            "symbol": symbol,
            "baseline_open_orders": len(baseline),
        }

        # ---- pause: the guarded write must be refused locally, no dispatch ----
        ctx.log(f"paused by {operator_ref}; attempting guarded write")
        client._cert_paused = True
        pause_rejection = None
        try:
            _place_guarded(client, **order_params)
        except RuntimeError as exc:
            pause_rejection = str(exc)
        finally:
            client._cert_paused = False
        facts["pause_rejection"] = pause_rejection
        facts["write_guard_active"] = True
        if pause_rejection != "write_paused":
            return CaseResult(CASE_ID, "FAIL", "write_pause_not_enforced", facts)

        after = [o for o in client.open_orders(symbol) if o.get("clientOrderId") == client_order_id]
        facts["dispatch_absent"] = not after and len(client.open_orders(symbol)) == len(baseline)
        if not facts["dispatch_absent"]:
            return CaseResult(CASE_ID, "FAIL", "paused_write_dispatched", facts)

        # ---- resume: real resting order cycle, then terminal cancel ----
        ctx.log("resumed; placing post-resume order cycle")
        try:
            order = _place_guarded(client, **order_params)
        except BinanceApiError as exc:
            facts.update({"code": exc.code, "msg": str(exc.msg)[:160]})
            return CaseResult(CASE_ID, "FAIL", "post_resume_order_rejected", facts)
        except WriteOutcomeUnknown:
            return CaseResult(CASE_ID, "UNKNOWN", "order_outcome_unknown", facts)

        order_id = order["orderId"]
        ctx.track_order(symbol, order_id, order.get("_client_order_id"))
        ctx.log(f"placed orderId={order_id} status={order.get('status')}")
        accepted, matched = _wait_status(
            client, symbol, order_id, _OPEN_STATES, int(scenario.get("accept_timeout_ms", 8000))
        )
        if not matched:
            status = (accepted or {}).get("status")
            if status in _TERMINAL_STATES:
                return CaseResult(CASE_ID, "FAIL",
                                  f"order_went_terminal_before_cancel:{status}",
                                  {**facts, "orderId": order_id})
            return CaseResult(CASE_ID, "FAIL", f"accept_timeout:{status}",
                              {**facts, "orderId": order_id})

        client.cancel_order(symbol, order_id=order_id)
        final, matched = _wait_status(
            client, symbol, order_id, {"CANCELED"}, int(scenario.get("cancel_confirm_timeout_ms", 8000))
        )
        ctx.mark_order_closed(order_id)
        if not matched:
            return CaseResult(CASE_ID, "FAIL",
                              f"cancel_confirm_timeout:{(final or {}).get('status')}",
                              {**facts, "orderId": order_id,
                               "cancel_status": (final or {}).get("status")})

        residual = [o for o in client.open_orders(symbol) if o.get("orderId") == order_id]
        if residual:
            return CaseResult(CASE_ID, "FAIL", "order_still_open_after_cancel",
                              {**facts, "orderId": order_id})

        facts.update({
            "orderId": order_id,
            "accepted_status": accepted.get("status"),
            "final_status": final.get("status"),
            "executedQty": final.get("executedQty"),
            "final_open_orders": len(client.open_orders(symbol)),
        })
        return CaseResult(CASE_ID, "PASS", "", facts)
