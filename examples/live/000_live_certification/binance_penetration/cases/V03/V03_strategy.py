"""V03 — oversize volume rejected locally with no venue dispatch.

Success condition: one unit above the per-order volume cap (scenario
max_limit_order_volume, default 1000 — Binance symbol filters carry no
per-order maximum) at a tick-aligned mark price is rejected locally as above
the maximum, with no order write dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.validation import LocalReject, validate_order

CASE_ID = "V03"
RISK = "READ"

_WRITE_METHODS = ("POST", "PUT", "DELETE")
_MAX_LIMIT_ORDER_VOLUME = 1000


def _dispatch_absent(client):
    return not any(entry.get("method") in _WRITE_METHODS for entry in client.calls)


class V03Strategy:
    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        symbol = scenario["symbol"]

        info = client.filters(symbol)
        tick = float(info.get("tick_size") or 0)
        if tick <= 0:
            return CaseResult(
                CASE_ID, "BLOCKED", "price_tick_invalid", {"symbol": symbol, "tick": tick}
            )

        cap = int(scenario.get("max_limit_order_volume", _MAX_LIMIT_ORDER_VOLUME))
        row = {
            "PriceTick": tick,
            "MaxLimitOrderVolume": cap,
            "MinLimitOrderVolume": float(info.get("min_qty") or 0),
        }

        mark = float(client.mark_price(symbol))
        if mark <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "mark_price_invalid", {"mark_price": mark})
        price = round(mark / tick) * tick

        volume = cap + 1
        rule = ""
        try:
            validate_order(instrument_row=row, price=price, volume=volume)
        except LocalReject as exc:
            rule = exc.rule

        dispatch_absent = _dispatch_absent(client)
        facts = {
            "rule": rule,
            "price": price,
            "volume": volume,
            "max_limit_order_volume": cap,
            "tick": tick,
            "mark_price": mark,
            "symbol": symbol,
            "dispatch_absent": dispatch_absent,
        }
        if rule != "volume_above_max":
            return CaseResult(CASE_ID, "FAIL", f"local_reject_unexpected:{rule or 'none'}", facts)
        if not dispatch_absent:
            return CaseResult(CASE_ID, "FAIL", "dispatch_not_absent", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
