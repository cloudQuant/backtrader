"""L04 — local validation rejection with no venue dispatch.

Success condition: a deliberately misaligned price tick derived from the
venue lower band price is rejected by the local pre-trade check, and the
session log shows no order insert or order action was dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.validation import LocalReject, validate_order

CASE_ID = "L04"
RISK = "READ"


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


def _dispatch_absent(client):
    kinds = {str(entry.get("kind")) for entry in client.calls}
    return "order_insert" not in kinds and "order_action" not in kinds


class L04Strategy:
    def run(self, ctx):
        client = ctx.client
        contract = ctx.contract
        instrument = contract["instrument"]
        exchange = contract["exchange"]

        row = _instrument_row(client, instrument, exchange)
        if row is None:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"instrument": instrument})
        tick = float(row.get("PriceTick") or 0)
        if tick <= 0:
            return CaseResult(
                CASE_ID, "BLOCKED", "price_tick_invalid",
                {"instrument": instrument, "tick": tick},
            )

        depth = _depth_row(client, instrument)
        if depth is None:
            return CaseResult(CASE_ID, "BLOCKED", "depth_unavailable", {"instrument": instrument})
        lower = float(depth.get("LowerLimitPrice") or 0)
        if lower <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "price_band_invalid", {"lower": lower})

        price = lower + tick / 2.0
        rule = ""
        try:
            validate_order(instrument_row=row, price=price, volume=1)
        except LocalReject as exc:
            rule = exc.rule

        dispatch_absent = _dispatch_absent(client)
        facts = {"rule": rule, "dispatch_absent": dispatch_absent, "price": price, "tick": tick}
        if rule != "price_tick_mismatch":
            return CaseResult(CASE_ID, "FAIL", f"local_reject_unexpected:{rule or 'none'}", facts)
        if not dispatch_absent:
            return CaseResult(CASE_ID, "FAIL", "dispatch_not_absent", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
