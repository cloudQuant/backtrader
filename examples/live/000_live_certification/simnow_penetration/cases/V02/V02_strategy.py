"""V02 — misaligned price tick derived from the venue last price.

Success condition: the venue-set instrument metadata provides a positive
price tick, the depth query provides a last price, the price offset by half
a tick from the rounded last price is rejected locally as a price-tick
mismatch, and no order insert or order action was dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.validation import LocalReject, validate_order

CASE_ID = "V02"
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


class V02Strategy:
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
        last = float(depth.get("LastPrice") or 0)
        if last <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "last_price_invalid", {"last_price": last})

        price = round(last / tick) * tick + tick / 2.0
        rule = ""
        try:
            validate_order(instrument_row=row, price=price, volume=1)
        except LocalReject as exc:
            rule = exc.rule

        dispatch_absent = _dispatch_absent(client)
        facts = {
            "rule": rule,
            "price": price,
            "tick": tick,
            "last_price": last,
            "dispatch_absent": dispatch_absent,
        }
        if rule != "price_tick_mismatch":
            return CaseResult(CASE_ID, "FAIL", f"local_reject_unexpected:{rule or 'none'}", facts)
        if not dispatch_absent:
            return CaseResult(CASE_ID, "FAIL", "dispatch_not_absent", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
