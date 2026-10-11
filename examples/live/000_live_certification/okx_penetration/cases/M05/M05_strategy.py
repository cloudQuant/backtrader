"""M05 — the local monitor records submit and cancel.

Success condition: the local monitor records an order_insert event and an
order_action event carrying this order's id, the order is visible as live in
the venue queue, the venue reaches the terminal canceled state, and no order
of this run remains pending.
"""

from __future__ import annotations

import time

from certlib.context import CaseResult
from certlib.monitor import Monitor
from certlib.okx_client import OkxError

CASE_ID = "M05"
RISK = "WRITE"

_OPEN_STATES = {"live", "partially_filled"}
_TERMINAL_STATES = {"canceled", "filled"}


class _Abort(Exception):
    """Internal signal: stop the case and return this outcome."""

    def __init__(self, status, reason, facts=None):
        self.status = status
        self.reason = reason
        self.facts = dict(facts or {})
        super().__init__(reason)


def _round_to_step(value, step):
    step = float(step)
    return round(round(float(value) / step) * step, 10)


def _prepare(ctx):
    """Resolve the instrument plan from venue metadata; enforce policy."""
    client = ctx.client
    scenario = ctx.scenario()
    policy = ctx.config.get("policy", {})
    inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")
    if inst_id not in policy.get("symbol_allowlist", []):
        raise _Abort("BLOCKED", "symbol_not_allowed")
    instruments = client.instruments(inst_id)
    if not instruments:
        raise _Abort("BLOCKED", "instrument_unknown", {"inst_id": inst_id})
    meta = instruments[0]
    tick = float(meta.get("tickSz") or 0.1)
    lot = float(meta.get("lotSz") or 1)
    last = float(client.ticker(inst_id)["last"])
    price = _round_to_step(last * (1.0 - scenario.get("price_offset_bps", 200) / 10_000.0), tick)
    size = _round_to_step(float(scenario.get("size", 1)), lot)
    notional = price * size * float(meta.get("ctVal") or 0)
    if notional > float(policy.get("max_notional_usdt", 0)):
        raise _Abort("BLOCKED", "above_policy_notional", {"notional": notional})
    return {
        "inst_id": inst_id,
        "side": str(scenario.get("side", "buy")).lower(),
        "size": size,
        "price": price,
        "last": last,
    }


def _place_live(client, ctx, market, timeout_ms, monitor=None):
    """Place one resting LIMIT order; wait until the venue shows it live."""
    placement = client.place_order(
        market["inst_id"], market["side"], sz=market["size"], px=market["price"], ord_type="limit"
    )
    ord_id = placement["ordId"]
    ctx.track_order(market["inst_id"], ord_id, placement.get("_cl_ord_id"))
    if monitor is not None:
        monitor.record("order_insert", order_ref=str(ord_id))
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        rows = client.order_details(market["inst_id"], ord_id=ord_id)
        state = str((rows[0] if rows else {}).get("state"))
        if state in _OPEN_STATES:
            return {"ordId": ord_id, "clOrdId": placement.get("_cl_ord_id"), "live_state": state}
        if state in _TERMINAL_STATES:
            ctx.mark_order_closed(ord_id)
            raise _Abort("FAIL", f"order_went_terminal_before_cancel:{state}", {"ordId": ord_id})
        time.sleep(0.3)
    raise _Abort("FAIL", "accept_timeout", {"ordId": ord_id})


def _cancel_terminal(client, ctx, market, ord_id, timeout_ms, monitor=None):
    """Cancel one live order; wait for the terminal canceled venue state."""
    client.cancel_order(market["inst_id"], ord_id=ord_id)
    if monitor is not None:
        monitor.record("order_action", order_ref=str(ord_id))
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        rows = client.order_details(market["inst_id"], ord_id=ord_id)
        state = str((rows[0] if rows else {}).get("state"))
        if state == "canceled":
            ctx.mark_order_closed(ord_id)
            return {"ordId": ord_id, "state": state}
        if state in _TERMINAL_STATES:
            ctx.mark_order_closed(ord_id)
            raise _Abort("FAIL", f"terminal_state:{state}", {"ordId": ord_id})
        time.sleep(0.3)
    raise _Abort("FAIL", "cancel_confirm_timeout", {"ordId": ord_id})


def _residual_pending(client, inst_id, ord_ids):
    wanted = {str(x) for x in ord_ids}
    return [o for o in client.pending_orders(inst_id=inst_id) if str(o.get("ordId")) in wanted]


class M05Strategy:
    RISK = RISK  # class-level alias so certlib.runner's risk gate sees it

    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        monitor = Monitor({})
        try:
            market = _prepare(ctx)
            accept_ms = int(scenario.get("accept_timeout_ms", 8000))
            cancel_ms = int(scenario.get("cancel_confirm_timeout_ms", 8000))

            ctx.log(f"monitor attached; plan={market['size']}@{market['price']}")
            placed = _place_live(client, ctx, market, accept_ms, monitor)
            inserts = [
                event
                for event in monitor.events
                if event.get("kind") == "order_insert"
                and str(event.get("order_ref")) == placed["ordId"]
            ]
            closed = _cancel_terminal(client, ctx, market, placed["ordId"], cancel_ms, monitor)
            actions = [
                event
                for event in monitor.events
                if event.get("kind") == "order_action"
                and str(event.get("order_ref")) == placed["ordId"]
            ]
        except _Abort as abort:
            return CaseResult(CASE_ID, abort.status, abort.reason, abort.facts)
        except OkxError as exc:
            return CaseResult(
                CASE_ID, "FAIL", f"client_error:{type(exc).__name__}", {"error": str(exc)[:200]}
            )
        ctx.record_artifact("monitor", monitor.dump())

        residual = _residual_pending(client, market["inst_id"], {placed["ordId"]})
        facts = {
            **placed,
            **closed,
            "price": market["price"],
            "size": market["size"],
            "monitored_event_count": len(monitor.events),
            "matched_insert_events": len(inserts),
            "matched_action_events": len(actions),
        }
        if not inserts:
            return CaseResult(CASE_ID, "FAIL", "monitor_missing_order_insert_event", facts)
        if not actions:
            return CaseResult(CASE_ID, "FAIL", "monitor_missing_order_action_event", facts)
        if residual:
            return CaseResult(CASE_ID, "FAIL", "order_still_pending_after_cancel", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
