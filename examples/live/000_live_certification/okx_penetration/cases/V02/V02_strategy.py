"""V02 — misaligned price tick derived from the venue last price.

Success condition: the venue instrument metadata provides a positive price
tick, the ticker provides a last price, a price offset by half a tick from
the tick-aligned last price is rejected locally as a price-tick mismatch, and
no POST (order) request was dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.validation import LocalReject, validate_order

CASE_ID = "V02"
RISK = "READ"


def _instrument_meta(client, inst_id):
    rows = client.instruments(inst_id)
    return rows[0] if rows else None


def _dispatch_absent(client):
    methods = {str(entry.get("method")) for entry in client.calls}
    return "POST" not in methods


class V02Strategy:
    def run(self, ctx):
        client = ctx.client
        inst_id = ctx.scenario().get("inst_id", "BTC-USDT-SWAP")

        meta = _instrument_meta(client, inst_id)
        if meta is None:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"inst_id": inst_id})
        row = {
            "PriceTick": float(meta.get("tickSz") or 0),
            "MaxLimitOrderVolume": None,
            "MinLimitOrderVolume": float(meta.get("minSz") or 1),
        }
        tick = row["PriceTick"]
        if tick <= 0:
            return CaseResult(
                CASE_ID, "BLOCKED", "price_tick_invalid", {"inst_id": inst_id, "tick": tick}
            )

        last = float(client.ticker(inst_id)["last"])
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
            "inst_id": inst_id,
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
