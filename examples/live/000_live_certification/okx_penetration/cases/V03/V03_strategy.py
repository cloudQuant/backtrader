"""V03 — oversize volume rejected locally with no venue dispatch.

Success condition: one lot above the instrument maximum limit order size (the
venue maxLmtSz when the instrument row carries it, otherwise the suite
fallback cap 1,000,000, i.e. volume 1,000,001) at a tick-aligned price is
rejected locally as above the maximum, with no POST (order) request
dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.validation import LocalReject, validate_order

CASE_ID = "V03"
RISK = "READ"

_FALLBACK_MAX_VOLUME = 1_000_000


def _instrument_meta(client, inst_id):
    rows = client.instruments(inst_id)
    return rows[0] if rows else None


def _dispatch_absent(client):
    methods = {str(entry.get("method")) for entry in client.calls}
    return "POST" not in methods


class V03Strategy:
    def run(self, ctx):
        client = ctx.client
        inst_id = ctx.scenario().get("inst_id", "BTC-USDT-SWAP")

        meta = _instrument_meta(client, inst_id)
        if meta is None:
            return CaseResult(CASE_ID, "BLOCKED", "instrument_not_found", {"inst_id": inst_id})
        tick = float(meta.get("tickSz") or 0)
        if tick <= 0:
            return CaseResult(
                CASE_ID, "BLOCKED", "price_tick_invalid", {"inst_id": inst_id, "tick": tick}
            )

        last = float(client.ticker(inst_id)["last"])
        if last <= 0:
            return CaseResult(CASE_ID, "BLOCKED", "last_price_invalid", {"last_price": last})
        price = round(last / tick) * tick

        venue_max = meta.get("maxLmtSz")
        cap_source = "venue_maxLmtSz" if venue_max else "fallback"
        cap = int(float(venue_max)) if venue_max else _FALLBACK_MAX_VOLUME
        volume = cap + 1
        row = {
            "PriceTick": tick,
            "MaxLimitOrderVolume": cap,
            "MinLimitOrderVolume": float(meta.get("minSz") or 1),
        }

        rule = ""
        try:
            validate_order(instrument_row=row, price=price, volume=volume)
        except LocalReject as exc:
            rule = exc.rule

        dispatch_absent = _dispatch_absent(client)
        facts = {
            "inst_id": inst_id,
            "rule": rule,
            "volume": volume,
            "max_volume": cap,
            "cap_source": cap_source,
            "price": price,
            "tick": tick,
            "dispatch_absent": dispatch_absent,
        }
        if rule != "volume_above_max":
            return CaseResult(CASE_ID, "FAIL", f"local_reject_unexpected:{rule or 'none'}", facts)
        if not dispatch_absent:
            return CaseResult(CASE_ID, "FAIL", "dispatch_not_absent", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
