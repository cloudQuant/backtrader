"""M01 — monitor readiness on a valid trading day.

Success condition: the monitor records its readiness marker with the session
connection generation, the monitor observes the account query event through
the session event hook, and the login trading day is an 8-character day.
"""

from __future__ import annotations

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "M01"
RISK = "READ"


class M01Strategy:
    def run(self, ctx):
        client = ctx.client
        login = dict(client.login_facts)
        generation = int(login.get("connection_generation", 0) or 0)
        trading_day = str(login.get("trading_day", ""))

        mon = Monitor(ctx.scenario().get("monitor", {}))
        client.event_hook = mon.record
        mon.record("monitor_ready", generation=generation)

        try:
            account = client.query_account()
        except SimNowSessionError as exc:
            ctx.record_artifact("monitor", mon.dump())
            return CaseResult(
                CASE_ID, "FAIL", exc.reason,
                {**exc.facts, "monitor_events": len(mon.events)},
            )

        ctx.record_artifact("monitor", mon.dump())
        dump = mon.dump()
        kinds = [entry["kind"] for entry in dump["events"]]
        facts = {
            "monitor_events": len(dump["events"]),
            "event_kinds": kinds,
            "connection_generation": generation,
            "trading_day": trading_day,
            "account_rows": account["facts"]["record_count"],
            "config_snapshot_id": dump["config_snapshot_id"],
        }
        if "monitor_ready" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_ready_missing", facts)
        if "query" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_query_missing", facts)
        if len(trading_day) != 8:
            return CaseResult(CASE_ID, "FAIL", "trading_day_invalid", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
