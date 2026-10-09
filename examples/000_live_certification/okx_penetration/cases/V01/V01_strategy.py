"""V01 — unknown instrument rejected locally with no venue dispatch.

Success condition: the instrument query yields no row for the scenario-named
instrument (default: configured instrument plus "ZZ"), the local pre-trade
check rejects the missing row as unknown, and the session log shows no POST
(order) request was dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.okx_client import OkxApiError
from certlib.validation import LocalReject, validate_order

CASE_ID = "V01"
RISK = "READ"


def _dispatch_absent(client):
    methods = {str(entry.get("method")) for entry in client.calls}
    return "POST" not in methods


class V01Strategy:
    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")
        invalid = str(scenario.get("invalid_instrument") or f"{inst_id}ZZ")

        query_code = None
        try:
            rows = client.instruments(invalid)
        except OkxApiError as exc:
            # A venue-side rejection of the unknown instrument is equally
            # conclusive: no instrument row is visible for it.
            rows = []
            query_code = str(exc.code) if exc.code is not None else None

        matching = [row for row in rows if str(row.get("instId")) == invalid]
        if matching:
            return CaseResult(
                CASE_ID, "FAIL", "invalid_instrument_visible",
                {"invalid_instrument": invalid, "matching_rows": len(matching)},
            )

        rule = ""
        try:
            validate_order(instrument_row=None, price=1.0, volume=1)
        except LocalReject as exc:
            rule = exc.rule

        dispatch_absent = _dispatch_absent(client)
        facts = {
            "invalid_instrument": invalid,
            "rule": rule,
            "query_code": query_code,
            "instrument_rows": len(rows),
            "dispatch_absent": dispatch_absent,
        }
        if rule != "unknown_instrument":
            return CaseResult(CASE_ID, "FAIL", f"local_reject_unexpected:{rule or 'none'}", facts)
        if not dispatch_absent:
            return CaseResult(CASE_ID, "FAIL", "dispatch_not_absent", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
