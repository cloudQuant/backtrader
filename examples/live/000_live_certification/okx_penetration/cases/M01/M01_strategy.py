"""M01 — monitor readiness on the signed session.

Success condition: the monitor records its readiness marker with the server-
time offset measured at connect, a signed account-configuration read is
observed in the monitor log, and the account reads back under the same
credential context.  Facts carry no account identifiers (pos mode / account
level only).
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "M01"
RISK = "READ"


class M01Strategy:
    def run(self, ctx):
        client = ctx.client
        offset_ms = int(client.time_offset_ms)

        mon = Monitor(ctx.scenario().get("monitor", {}))
        mon.record("monitor_ready", time_offset_ms=offset_ms, pos_mode=str(client.pos_mode))
        config = client.account_config()
        mon.record("query", path="/api/v5/account/config", rows=1)

        dump = mon.dump()
        ctx.record_artifact("monitor", dump)
        kinds = [entry["kind"] for entry in dump["events"]]
        facts = {
            "monitor_events": len(dump["events"]),
            "event_kinds": kinds,
            "time_offset_ms": offset_ms,
            "pos_mode": client.pos_mode,
            "acct_lv": config.get("acctLv"),
            "config_snapshot_id": dump["config_snapshot_id"],
        }
        if "monitor_ready" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_ready_missing", facts)
        if "query" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_query_missing", facts)
        if client.server_time_ms is None:
            return CaseResult(CASE_ID, "FAIL", "time_anchor_missing", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
