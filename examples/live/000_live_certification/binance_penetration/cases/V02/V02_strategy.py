"""V02 — misaligned price tick derived from the venue mark price.

Success condition: the venue symbol metadata provides a positive price tick,
the mark-price read provides a price, the price offset by half a tick from the
rounded mark is rejected locally as a price-tick mismatch, and no order write
was dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.validation import LocalReject, validate_order

CASE_ID = "V02"
RISK = "READ"

_WRITE_METHODS = ("POST", "PUT", "DELETE")
_MAX_LIMIT_ORDER_VOLUME = 1000


def _dispatch_absent(client):
    return not any(entry.get("method") in _WRITE_METHODS for entry in client.calls)


class V02Strategy:
    def run(self, ctx):
        client = ctx.client
        symbol = ctx.scenario()["symbol"]

        info = client.filters(symbol)
        tick = float(info.get("tick_size") or 0)
        if tick <= 0:
            return CaseResult(
                CASE_ID, "BLOCKED", "price_tick_invalid", {"symbol": symbol, "tick": tick}
            )
        row = {
            "PriceTick": tick,
            "MaxLimitOrderVolume": _MAX_LIMIT_ORDER_VOLUME,
            "MinLimitOrderVolume": float(info.get("min_qty") or 0),
        }

        mark = float(client.mark_price(symbol))
        if mark <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "mark_price_invalid", {"mark_price": mark})

        price = round(mark / tick) * tick + tick / 2.0
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
            "mark_price": mark,
            "symbol": symbol,
            "dispatch_absent": dispatch_absent,
        }
        if rule != "price_tick_mismatch":
            return CaseResult(CASE_ID, "FAIL", f"local_reject_unexpected:{rule or 'none'}", facts)
        if not dispatch_absent:
            return CaseResult(CASE_ID, "FAIL", "dispatch_not_absent", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
