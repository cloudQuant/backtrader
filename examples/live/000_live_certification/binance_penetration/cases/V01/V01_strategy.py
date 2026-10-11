"""V01 — unknown symbol rejected locally with no venue dispatch.

Success condition: the symbol query yields no row for the scenario-named
invalid symbol (default: configured symbol plus "ZZ"), the local pre-trade
check rejects the missing row as unknown, and the session log shows no order
write was dispatched.
"""

from __future__ import annotations

from certlib.binance_client import BinanceApiError, TransportFailure
from certlib.context import CaseResult
from certlib.validation import LocalReject, validate_order

CASE_ID = "V01"
RISK = "READ"

_WRITE_METHODS = ("POST", "PUT", "DELETE")


def _dispatch_absent(client):
    return not any(entry.get("method") in _WRITE_METHODS for entry in client.calls)


class V01Strategy:
    def run(self, ctx):
        client = ctx.client
        symbol = ctx.scenario()["symbol"]
        invalid = str(ctx.scenario().get("invalid_instrument") or f"{symbol}ZZ")

        visible = False
        query_error = ""
        try:
            visible = client.exchange_info(invalid) is not None
        except BinanceApiError as exc:
            query_error = f"{exc.code}:{exc.msg}"[:160]
        except TransportFailure as exc:
            return CaseResult(
                CASE_ID, "BLOCKED", "instrument_query_failed", {"error": str(exc)[:160]}
            )

        if visible:
            return CaseResult(
                CASE_ID, "FAIL", "invalid_instrument_visible", {"invalid_instrument": invalid}
            )

        rule = ""
        try:
            validate_order(instrument_row=None, price=1.0, volume=1)
        except LocalReject as exc:
            rule = exc.rule

        dispatch_absent = _dispatch_absent(client)
        facts = {
            "rule": rule,
            "invalid_instrument": invalid,
            "query_error": query_error,
            "dispatch_absent": dispatch_absent,
        }
        if rule != "unknown_instrument":
            return CaseResult(CASE_ID, "FAIL", f"local_reject_unexpected:{rule or 'none'}", facts)
        if not dispatch_absent:
            return CaseResult(CASE_ID, "FAIL", "dispatch_not_absent", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
