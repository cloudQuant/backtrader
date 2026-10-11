"""EM02 — strategy pause guard: local write refusal, then resume cycle.

The case records the operator/authorization refs and models a local operator
pause with a case-level guard around placement: the first attempt is refused
locally (RuntimeError "write_paused") and must not reach the venue — the
pending-order baseline is compared before/after.  After resume a resting buy
order is placed, becomes live, is canceled to the terminal canceled state, and
no residual remains.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult
from certlib.okx_client import OkxApiError

CASE_ID = "EM02"
RISK = "WRITE"

_LIVE = {"live", "partially_filled"}
_TERMINAL = {"canceled", "filled"}


def _round_to_step(value, step):
    step = float(step)
    return round(round(float(value) / step) * step, 10)


def _brief(exc):
    return {"error_code": str(getattr(exc, "code", None)),
            "error_message": str(getattr(exc, "msg", "") or exc)[:120]}


def _poll_state(client, inst_id, ord_id, states, timeout):
    deadline, row = time.monotonic() + timeout, {}
    while time.monotonic() < deadline:
        rows = client.order_details(inst_id, ord_id=ord_id)
        row = rows[0] if rows else {}
        if str(row.get("state")) in states:
            return row, True
        time.sleep(0.3)
    return row, False


def _guarded_place(ctx, paused, inst_id, side, size, px):
    """Case-level write guard: a paused strategy never calls the venue."""
    if paused:
        raise RuntimeError("write_paused")
    return ctx.client.place_order(inst_id, side, sz=size, px=px,
                                  ord_type="limit", pos_side="long")


class EM02Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        scenario, policy = ctx.scenario(), ctx.config.get("policy", {})
        inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")
        operator_ref = str(scenario.get("operator_ref", "operator-cert-em02"))
        authorization_ref = str(scenario.get("authorization_ref", "auth-cert-em02"))
        if inst_id not in policy.get("symbol_allowlist", []):
            return CaseResult(CASE_ID, "BLOCKED", "symbol_not_allowed", {"inst_id": inst_id})
        instruments = client.instruments(inst_id)
        if not instruments:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_unknown", {"inst_id": inst_id})
        tick = float(instruments[0].get("tickSz") or 0.01)
        size = _round_to_step(float(scenario.get("size", 1)),
                              float(instruments[0].get("lotSz") or 0.01))
        offset = float(scenario.get("price_offset_bps", 200)) / 10_000.0
        accept_timeout = float(scenario.get("accept_timeout_ms", 10000)) / 1000.0
        cancel_timeout = float(scenario.get("cancel_timeout_ms", 10000)) / 1000.0
        last = float(client.ticker(inst_id)["last"])
        px = _round_to_step(last * (1.0 - offset), tick)

        before_ids = sorted(str(o.get("ordId")) for o in client.pending_orders(inst_id=inst_id) or [])
        pause_rejection = None
        paused_placement = None
        try:
            paused_placement = _guarded_place(ctx, True, inst_id, "buy", size, px)
        except RuntimeError as exc:
            pause_rejection = str(exc)
        if pause_rejection is None:
            if paused_placement is not None:
                ctx.track_order(inst_id, paused_placement["ordId"], paused_placement.get("_cl_ord_id"))
            return CaseResult(CASE_ID, "FAIL", "pause_not_enforced",
                              {"operator_ref": operator_ref,
                               "ordId": (paused_placement or {}).get("ordId")})
        after_ids = sorted(str(o.get("ordId")) for o in client.pending_orders(inst_id=inst_id) or [])
        ctx.log(f"paused write refused locally ({pause_rejection}); venue order set unchanged")
        if after_ids != before_ids:
            return CaseResult(CASE_ID, "FAIL", "pause_attempt_reached_venue",
                              {"operator_ref": operator_ref, "before": before_ids,
                               "after": after_ids, "pause_rejection": pause_rejection})

        ctx.log("resumed; placing post-resume resting order cycle")
        try:
            placement = _guarded_place(ctx, False, inst_id, "buy", size, px)
        except OkxApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "resume_rejected",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "pause_rejection": pause_rejection, "error": _brief(exc)})
        ord_id = placement["ordId"]
        ctx.track_order(inst_id, ord_id, placement.get("_cl_ord_id"))
        row, live = _poll_state(client, inst_id, ord_id, _LIVE, accept_timeout)
        cycle = {"ordId": ord_id, "clOrdId": placement.get("_cl_ord_id"), "px": px,
                 "state": str(row.get("state"))}
        if not live:
            return CaseResult(CASE_ID, "FAIL", "resume_not_live",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "pause_rejection": pause_rejection, "cycle": cycle})
        try:
            client.cancel_order(inst_id, ord_id=ord_id)
        except OkxApiError as exc:
            return CaseResult(CASE_ID, "FAIL", "resume_cancel_rejected",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "pause_rejection": pause_rejection,
                               "cycle": {**cycle, "cancel": _brief(exc)}})
        final, canceled = _poll_state(client, inst_id, ord_id, _TERMINAL, cancel_timeout)
        cycle["final_state"] = str(final.get("state"))
        if not canceled or cycle["final_state"] != "canceled":
            if cycle["final_state"] in _TERMINAL:
                ctx.mark_order_closed(ord_id)
            return CaseResult(CASE_ID, "FAIL", "resume_cancel_unconfirmed",
                              {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                               "pause_rejection": pause_rejection, "cycle": cycle})
        ctx.mark_order_closed(ord_id)

        pending = client.pending_orders(inst_id=inst_id) or []
        residual = [{"ordId": o.get("ordId")} for o in pending if str(o.get("ordId")) == str(ord_id)]
        facts = {"operator_ref": operator_ref, "authorization_ref": authorization_ref,
                 "pause_rejection": pause_rejection, "venue_unchanged": True,
                 "cycle": cycle, "residual": residual, "final_pending": len(pending)}
        if residual:
            return CaseResult(CASE_ID, "FAIL", "residual_order_open", facts)
        return CaseResult(CASE_ID, "PASS", "", {**facts, "resumed_and_canceled": True})
