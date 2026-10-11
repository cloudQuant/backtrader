"""L04 — local validation rejection with no venue dispatch.

Success condition: a price offset by half a price tick from the venue mark
price is rejected by the local pre-trade check as a price-tick mismatch, and
the session log shows no order write was dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.validation import LocalReject, validate_order

CASE_ID = "L04"
RISK = "READ"

_WRITE_METHODS = ("POST", "PUT", "DELETE")
_MAX_LIMIT_ORDER_VOLUME = 1000


def _instrument_row(info, cap=_MAX_LIMIT_ORDER_VOLUME):
    """Map Binance symbol filters into the normalized local rule shape."""
    tick = float(info.get("tick_size") or 0)
    if tick <= 0:
        return None, tick
    return {
        "PriceTick": tick,
        "MaxLimitOrderVolume": int(cap),
        "MinLimitOrderVolume": float(info.get("min_qty") or 0),
    }, tick


def _misaligned_price(base, tick):
    """Half-tick offset from the tick-aligned mark (realign if the mark drifted)."""
    price = float(base) + tick / 2.0
    ratio = price / tick
    if abs(ratio - round(ratio)) <= 1e-6:
        price = round(float(base) / tick) * tick + tick / 2.0
    return price


def _dispatch_absent(client):
    return not any(entry.get("method") in _WRITE_METHODS for entry in client.calls)


class L04Strategy:
    def run(self, ctx):
        client = ctx.client
        symbol = ctx.scenario()["symbol"]

        row, tick = _instrument_row(client.filters(symbol))
        if row is None:
            return CaseResult(
                CASE_ID, "BLOCKED", "price_tick_invalid", {"symbol": symbol, "tick": tick}
            )

        mark = float(client.mark_price(symbol))
        if mark <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "mark_price_invalid", {"mark_price": mark})
        price = _misaligned_price(mark, tick)

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
