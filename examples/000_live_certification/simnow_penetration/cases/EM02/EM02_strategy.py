"""EM02 — strategy pause / resume around a terminal-canceled order cycle.

The session is armed for the configured contract.  A local operator pause
(recorded operator/authorization refs) must reject the next order with
write_paused; after resume, a resting LIMIT order at the band edge must be
accepted, visible in-queue, canceled, and reach the terminal canceled status.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "EM02"
RISK = "WRITE"

_IN_QUEUE = {"1", "3"}
_CANCELED = {"5"}


def _instrument_row(client, instrument, exchange):
    result = client.query_instruments(instrument_id=instrument, exchange_id=exchange)
    for row in result["rows"]:
        if str(row.get("InstrumentID")) == instrument:
            return row
    return None


def _depth_row(client, instrument):
    result = client.query_depth_market_data(instrument)
    for row in result["rows"]:
        if str(row.get("InstrumentID")) == instrument:
            return row
    return None


def _cancel_cycle(client, ctx, instrument, exchange, placement, scenario):
    """Confirm in-queue, cancel, confirm terminal canceled.  Raises SimNowSessionError."""
    order_ref = placement["order_ref"]
    ctx.track_order(instrument, order_ref, exchange_id=exchange)
    in_queue = client.wait_order_status(
        order_ref,
        _IN_QUEUE,
        instrument_id=instrument,
        timeout=int(scenario.get("accept_timeout_ms", 20000)) / 1000.0,
    )
    order_sys_id = str(in_queue.get("OrderSysID") or "")
    canceled = client.cancel_order(
        instrument_id=instrument,
        exchange_id=exchange,
        order_ref=order_ref,
        order_sys_id=order_sys_id,
    )
    final = client.wait_order_status(
        order_ref,
        _CANCELED,
        instrument_id=instrument,
        timeout=int(scenario.get("cancel_timeout_ms", 20000)) / 1000.0,
    )
    ctx.mark_order_closed(order_ref)
    client.mark_order_state(order_ref, "closed", order_sys_id)
    return {
        "order_ref": order_ref,
        "order_sys_id": order_sys_id,
        "in_queue_status": str(in_queue.get("OrderStatus")),
        "final_status": str(final.get("OrderStatus")),
        "cancel_submit_code": canceled.get("submit_code"),
    }


class EM02Strategy:
    def run(self, ctx):
        client = ctx.client
        contract = ctx.contract
        scenario = ctx.scenario()
        instrument = contract["instrument"]
        exchange = contract["exchange"]
        hedge_flag = contract.get("hedge_flag") or "1"
        operator_ref = str(scenario.get("operator_ref") or "operator-cert-em02")
        authorization_ref = str(scenario.get("authorization_ref") or "auth-cert-em02")

        row = _instrument_row(client, instrument, exchange)
        if row is None:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"instrument": instrument})
        tick = float(row.get("PriceTick") or 1.0)

        depth = _depth_row(client, instrument)
        if depth is None:
            return CaseResult(CASE_ID, "BLOCKED", "depth_unavailable", {"instrument": instrument})
        lower = float(depth["LowerLimitPrice"])
        upper = float(depth["UpperLimitPrice"])
        if not (0 < lower < upper):
            return CaseResult(CASE_ID, "BLOCKED", "price_band_invalid", {"lower": lower, "upper": upper})

        side = str(scenario.get("side", "buy")).lower()
        direction = "0" if side == "buy" else "1"
        price = round(lower + tick, 6) if side == "buy" else round(upper - tick, 6)
        volume = int(scenario.get("volume", 1))

        strategy_identity = hashlib.sha256(
            (CASE_ID + json.dumps(ctx.config, sort_keys=True, default=str)).encode()
        ).hexdigest()
        preflight = hashlib.sha256(
            json.dumps(
                {
                    "case": CASE_ID,
                    "instrument": instrument,
                    "exchange": exchange,
                    "pair_index": client.pair.index,
                    "generation": client.login_facts.get("connection_generation"),
                    "trading_day": client.login_facts.get("trading_day"),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        client.arm(
            instrument_id=instrument,
            exchange_id=exchange,
            strategy_identity_sha256=strategy_identity,
            execution_cycle_id=f"{CASE_ID}-{int(time.time())}",
            preflight_sha256=preflight,
        )

        pause_info = client.pause("operator_pause")
        ctx.log(f"paused ({pause_info.get('reason')}) by {operator_ref}; attempting write")
        pause_rejection = None
        paused_placement = None
        try:
            paused_placement = client.place_limit_order(
                instrument_id=instrument,
                exchange_id=exchange,
                direction=direction,
                offset_flag="0",
                price=price,
                volume=volume,
                hedge_flag=hedge_flag,
            )
        except SimNowSessionError as exc:
            if exc.reason != "write_paused":
                raise
            pause_rejection = {"reason": exc.reason, **dict(exc.facts)}

        if paused_placement is not None:
            # The pause was not enforced; do not leave that order open.
            try:
                cleanup = {"cleanup": _cancel_cycle(client, ctx, instrument, exchange, paused_placement, scenario)}
            except SimNowSessionError as exc:
                cleanup = {"cleanup_failed": exc.reason, **exc.facts}
            return CaseResult(
                CASE_ID,
                "FAIL",
                "write_pause_not_enforced",
                {"operator_ref": operator_ref, "authorization_ref": authorization_ref, **cleanup},
            )

        client.resume()
        ctx.log("resumed; placing post-resume order cycle")
        placement = client.place_limit_order(
            instrument_id=instrument,
            exchange_id=exchange,
            direction=direction,
            offset_flag="0",
            price=price,
            volume=volume,
            hedge_flag=hedge_flag,
        )
        try:
            cycle = _cancel_cycle(client, ctx, instrument, exchange, placement, scenario)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, {**exc.facts, "placement": placement})

        return CaseResult(
            CASE_ID,
            "PASS",
            "",
            {
                "pause_reason": pause_info.get("reason"),
                "operator_ref": operator_ref,
                "authorization_ref": authorization_ref,
                "pause_rejection": pause_rejection,
                "order_ref": cycle["order_ref"],
                "order_sys_id": cycle["order_sys_id"],
                "in_queue_status": cycle["in_queue_status"],
                "final_status": cycle["final_status"],
            },
        )
