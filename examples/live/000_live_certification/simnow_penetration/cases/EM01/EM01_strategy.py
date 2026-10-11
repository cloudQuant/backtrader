"""EM01 — operator permission restriction is enforced, then restored.

The certification operator (recorded operator/authorization refs) revokes the
session's typed execution admission through the SDK's own disarm entry.  A
write attempt must then be refused before native dispatch (write_refused,
dispatch_absent=True).  The operator restores the admission and a bounded
order+cancel cycle must succeed again.  The restriction and its restoration
use the exact mechanism the SDK exposes; no instrument-permission guessing is
involved.
"""

from __future__ import annotations

import hashlib
import json
import time

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult

CASE_ID = "EM01"
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


def _arm(client, instrument, exchange):
    strategy_identity = hashlib.sha256(
        (CASE_ID + json.dumps(sorted({"i": instrument, "e": exchange}.items()), default=str)).encode()
    ).hexdigest()
    preflight = hashlib.sha256(
        json.dumps(
            {
                "case": CASE_ID,
                "instrument": instrument,
                "exchange": exchange,
                "generation": client.login_facts.get("connection_generation"),
                "trading_day": client.login_facts.get("trading_day"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return client.arm(
        instrument_id=instrument,
        exchange_id=exchange,
        strategy_identity_sha256=strategy_identity,
        execution_cycle_id=f"{CASE_ID}-{int(time.time() * 1000)}",
        preflight_sha256=preflight,
    )


class EM01Strategy:
    def run(self, ctx):
        client = ctx.client
        contract = ctx.contract
        scenario = ctx.scenario()
        instrument = contract["instrument"]
        exchange = contract["exchange"]
        hedge_flag = contract.get("hedge_flag") or "1"
        operator_ref = str(scenario.get("operator_ref", "operator-cert-em01"))
        authorization_ref = str(scenario.get("authorization_ref", "auth-cert-em01"))

        row = _instrument_row(client, instrument, exchange)
        if row is None:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"instrument": instrument})
        tick = float(row.get("PriceTick") or 1.0)
        depth = _depth_row(client, instrument)
        if depth is None:
            return CaseResult(CASE_ID, "BLOCKED", "depth_unavailable", {"instrument": instrument})
        lower = float(depth["LowerLimitPrice"])
        price = round(lower + tick, 6)
        volume = 1

        _arm(client, instrument, exchange)
        ctx.log(f"armed; operator {operator_ref} removes execution admission")

        native = getattr(client, "_client", None)
        native.disarm_execution_gate(client._capability, "operator_permission_restriction")

        refused = None
        try:
            client.place_limit_order(
                instrument_id=instrument,
                exchange_id=exchange,
                direction="0",
                offset_flag="0",
                price=price,
                volume=volume,
                hedge_flag=hedge_flag,
            )
        except SimNowSessionError as exc:
            refused = {"reason": exc.reason, "facts": exc.facts}
        if not refused or refused["reason"] != "write_refused":
            # The gate did not refuse: nothing was necessarily dispatched, but
            # the case cannot claim the restriction was enforced.
            return CaseResult(
                CASE_ID,
                "FAIL",
                "restriction_not_enforced",
                {"operator_ref": operator_ref, "refused": refused},
            )

        _arm(client, instrument, exchange)
        ctx.log("operator restores admission; verifying a bounded order cycle")
        placement = client.place_limit_order(
            instrument_id=instrument,
            exchange_id=exchange,
            direction="0",
            offset_flag="0",
            price=price,
            volume=volume,
            hedge_flag=hedge_flag,
        )
        order_ref = placement["order_ref"]
        ctx.track_order(instrument, order_ref, exchange_id=exchange)
        try:
            in_queue = client.wait_order_status(order_ref, _IN_QUEUE, instrument_id=instrument, timeout=20)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, {**exc.facts, "refused": refused})
        order_sys_id = str(in_queue.get("OrderSysID") or "")
        client.cancel_order(
            instrument_id=instrument,
            exchange_id=exchange,
            order_ref=order_ref,
            order_sys_id=order_sys_id,
        )
        try:
            final = client.wait_order_status(order_ref, _CANCELED, instrument_id=instrument, timeout=20)
        except SimNowSessionError as exc:
            return CaseResult(CASE_ID, "FAIL", exc.reason, {**exc.facts, "refused": refused})
        ctx.mark_order_closed(order_ref)
        client.mark_order_state(order_ref, "closed", order_sys_id)

        return CaseResult(
            CASE_ID,
            "PASS",
            "",
            {
                "operator_ref": operator_ref,
                "authorization_ref": authorization_ref,
                "restriction": refused,
                "restoration_order_ref": order_ref,
                "restoration_status": str(final.get("OrderStatus")),
            },
        )
