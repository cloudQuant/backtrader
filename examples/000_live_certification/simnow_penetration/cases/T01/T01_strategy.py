"""T01 — a bounded resting LIMIT order is accepted and finally canceled.

Success condition: the venue accepts the order (native insert evidence and an
in-queue venue status), the order is visible in the venue order query, the
case cancels it, the terminal venue status is canceled (5), and no order of
this run remains open.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "T01"
RISK = "WRITE"

_IN_QUEUE = {"1", "3"}  # partial/no trade, still in queue
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


class T01Strategy:
    def run(self, ctx):
        client = ctx.client
        contract = ctx.contract
        scenario = ctx.scenario()
        instrument = contract["instrument"]
        exchange = contract["exchange"]
        hedge_flag = contract.get("hedge_flag") or "1"

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
        ctx.log(f"armed; placing {side} {volume}@{price} ({instrument}.{exchange})")

        placement = client.place_limit_order(
            instrument_id=instrument,
            exchange_id=exchange,
            direction=direction,
            offset_flag="0",
            price=price,
            volume=volume,
            hedge_flag=hedge_flag,
        )
        order_ref = placement["order_ref"]
        ctx.track_order(instrument, order_ref, exchange_id=exchange)

        try:
            in_queue = client.wait_order_status(
                order_ref, _IN_QUEUE,
                instrument_id=instrument,
                timeout=int(scenario.get("accept_timeout_ms", 20000)) / 1000.0,
            )
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, {**exc.facts, "placement": placement})

        order_sys_id = str(in_queue.get("OrderSysID") or "")
        canceled = client.cancel_order(
            instrument_id=instrument,
            exchange_id=exchange,
            order_ref=order_ref,
            order_sys_id=order_sys_id,
        )
        try:
            final = client.wait_order_status(
                order_ref, _CANCELED,
                instrument_id=instrument,
                timeout=int(scenario.get("cancel_timeout_ms", 20000)) / 1000.0,
            )
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, {**exc.facts, "cancel": canceled})
        ctx.mark_order_closed(order_ref)
        client.mark_order_state(order_ref, "closed", order_sys_id)

        residual = [
            r for r in client.query_orders(instrument_id=instrument)["rows"]
            if str(r.get("OrderRef")) == order_ref and str(r.get("OrderStatus")) in _IN_QUEUE
        ]
        if residual:
            return CaseResult(CASE_ID, "FAIL", "order_still_open", {"residual": residual})

        return CaseResult(
            CASE_ID,
            "PASS",
            "",
            {
                "order_ref": order_ref,
                "order_sys_id": order_sys_id,
                "direction": direction,
                "price": price,
                "volume": volume,
                "in_queue_status": str(in_queue.get("OrderStatus")),
                "final_status": str(final.get("OrderStatus")),
                "volume_traded": final.get("VolumeTraded"),
                "price_band": {"lower": lower, "upper": upper},
                "insert_evidence": placement["evidence"],
            },
        )
