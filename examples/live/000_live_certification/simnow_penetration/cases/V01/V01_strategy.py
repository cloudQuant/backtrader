"""V01 — unknown instrument rejected locally with no venue dispatch.

Success condition: the instrument query yields no row for the scenario-named
instrument (default: configured instrument plus "ZZ"), the local pre-trade
check rejects the missing row as unknown, and the session log shows no order
insert or order action was dispatched.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.ctp_client import SimNowSessionError
from certlib.validation import LocalReject, validate_order

CASE_ID = "V01"
RISK = "READ"


def _dispatch_absent(client):
    kinds = {str(entry.get("kind")) for entry in client.calls}
    return "order_insert" not in kinds and "order_action" not in kinds


class V01Strategy:
    def run(self, ctx):
        client = ctx.client
        contract = ctx.contract
        exchange = contract["exchange"]
        invalid = str(ctx.scenario().get("invalid_instrument") or f"{contract['instrument']}ZZ")

        try:
            result = client.query_instruments(instrument_id=invalid, exchange_id=exchange)
        except SimNowSessionError as exc:
            return CaseResult(
                CASE_ID, "BLOCKED", f"instrument_query_failed:{exc.reason}",
                {**exc.facts, "invalid_instrument": invalid},
            )

        matching = [row for row in result["rows"] if str(row.get("InstrumentID")) == invalid]
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
        facts = {"rule": rule, "invalid_instrument": invalid, "dispatch_absent": dispatch_absent}
        if rule != "unknown_instrument":
            return CaseResult(CASE_ID, "FAIL", f"local_reject_unexpected:{rule or 'none'}", facts)
        if not dispatch_absent:
            return CaseResult(CASE_ID, "FAIL", "dispatch_not_absent", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
