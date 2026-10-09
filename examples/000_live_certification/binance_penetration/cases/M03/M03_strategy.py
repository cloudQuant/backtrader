"""M03 — recovery to a fresh user-data-stream session (read-only).

A new listen key is created and proves usable by a successful renew; it is
then deleted so the run leaves no live user-data stream behind.  No order is
ever submitted.
"""

from __future__ import annotations

from certlib.binance_client import BinanceApiError
from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "M03"
RISK = "READ"


class M03Strategy:
    def run(self, ctx):
        client = ctx.client
        mon = Monitor({})

        started = client.listen_key_start()
        key = str(started.get("listenKey", ""))
        created = bool(key)
        mon.record("fresh_session_ready", created=created, key_chars=len(key))
        if not created:
            ctx.record_artifact("monitor", mon.dump())
            return CaseResult(
                CASE_ID, "FAIL", "listen_key_create_failed",
                {"reply_keys": sorted(started.keys()), "monitor_events": len(mon.events)},
            )

        renew_ok = False
        renew_error = ""
        try:
            renewed = client.listen_key_renew()
            renew_ok = bool(renewed.get("listenKey"))
        except BinanceApiError as exc:
            renew_error = f"{exc.code}:{exc.msg}"[:160]

        cleaned = False
        cleanup_error = ""
        try:
            client.listen_key_delete()
            cleaned = True
        except BinanceApiError as exc:
            cleanup_error = f"{exc.code}:{exc.msg}"[:160]

        mon.record("recovery_verified", renew_ok=renew_ok, cleaned=cleaned)
        ctx.record_artifact("monitor", mon.dump())
        facts = {
            "created": created,
            "key_chars": len(key),
            "renew_ok": renew_ok,
            "renew_error": renew_error,
            "cleaned": cleaned,
            "cleanup_error": cleanup_error,
            "monitor_event_kinds": [e.get("kind") for e in mon.events],
        }
        if not renew_ok:
            return CaseResult(CASE_ID, "FAIL", "fresh_session_renew_failed", facts)
        if not cleaned:
            return CaseResult(CASE_ID, "FAIL", "cleanup_failed", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
