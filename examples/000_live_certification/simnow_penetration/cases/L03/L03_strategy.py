"""L03 — monitor event-hook capture.

Success condition: after the monitor is attached to the session event hook
(login has already happened, so a synthetic monitor-start marker is recorded),
an account query is observed by the monitor and the monitor snapshot is kept.
"""

from __future__ import annotations

from certlib.ctp_client import SimNowSessionError
from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "L03"
RISK = "READ"


class L03Strategy:
    def run(self, ctx):
        client = ctx.client
        mon = Monitor({})
        client.event_hook = mon.record
        mon.record("monitor_start", case=CASE_ID)

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
            "event_count": len(dump["events"]),
            "event_kinds": kinds,
            "config_snapshot_id": dump["config_snapshot_id"],
            "account_rows": account["facts"]["record_count"],
        }
        if "monitor_start" not in kinds or "query" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_events_missing", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
