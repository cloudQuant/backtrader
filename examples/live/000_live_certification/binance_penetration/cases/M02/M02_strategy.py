"""M02 — user-data-stream disconnect observation (read-only).

The session's listen key is created, then invalidated server-side by the
operator through the venue's own delete endpoint; the follow-up renew must
then fail, which is the observed disconnect.  No order is ever submitted and
no account alias/UID is emitted.
"""

from __future__ import annotations

from certlib.binance_client import BinanceApiError
from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "M02"
RISK = "READ"


class M02Strategy:
    def run(self, ctx):
        client = ctx.client
        mon = Monitor({})

        started = client.listen_key_start()
        key = str(started.get("listenKey", ""))
        created = bool(key)
        mon.record("listen_key_active", created=created, key_chars=len(key))
        if not created:
            ctx.record_artifact("monitor", mon.dump())
            return CaseResult(
                CASE_ID, "FAIL", "listen_key_create_failed",
                {"reply_keys": sorted(started.keys()), "monitor_events": len(mon.events)},
            )

        delete_error = ""
        try:
            client.listen_key_delete()
        except BinanceApiError as exc:
            delete_error = f"{exc.code}:{exc.msg}"[:160]
        mon.record("listen_key_invalidated", delete_error=delete_error)

        renew_succeeded = False
        renew_error = ""
        try:
            renew = client.listen_key_renew()
            renew_succeeded = bool(renew.get("listenKey"))
        except BinanceApiError as exc:
            renew_error = f"{exc.code}:{exc.msg}"[:160]
        mon.record("disconnect_observed", created=created, renew_failed=bool(renew_error))

        ctx.record_artifact("monitor", mon.dump())
        facts = {
            "created": created,
            "key_chars": len(key),
            "delete_error": delete_error,
            "renew_succeeded": renew_succeeded,
            "renew_error": renew_error,
            "monitor_event_kinds": [e.get("kind") for e in mon.events],
        }
        if renew_succeeded:
            return CaseResult(CASE_ID, "FAIL", "listen_key_not_invalidated", facts)
        if not renew_error:
            return CaseResult(CASE_ID, "FAIL", "renew_outcome_unknown", facts)
        if delete_error:
            return CaseResult(CASE_ID, "FAIL", "listen_key_delete_failed", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
