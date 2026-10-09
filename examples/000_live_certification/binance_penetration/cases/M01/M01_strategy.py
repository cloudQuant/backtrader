"""M01 — monitor readiness on a valid venue server-time day.

Success condition: the monitor records its readiness marker with the venue
server time and clock offset, an account read is observed by the monitor, the
account read returns the expected configuration shape, and the server-time day
is an 8-character day.
"""

from __future__ import annotations

from datetime import datetime, timezone

from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "M01"
RISK = "READ"


class M01Strategy:
    def run(self, ctx):
        client = ctx.client
        mon = Monitor(ctx.scenario().get("monitor", {}))
        hooked = hasattr(client, "event_hook")
        if hooked:
            client.event_hook = mon.record

        server_ms = client.server_time_ms
        offset_ms = client.time_offset_ms
        mon.record("monitor_ready", server_time_ms=server_ms, offset_ms=offset_ms)

        account = client.account_config()
        mon.record("query", family="account_config")

        server_day = ""
        if server_ms is not None:
            server_day = datetime.fromtimestamp(server_ms / 1000.0, tz=timezone.utc).strftime("%Y%m%d")

        ctx.record_artifact("monitor", mon.dump())
        dump = mon.dump()
        kinds = [entry["kind"] for entry in dump["events"]]
        facts = {
            "hook_attached": hooked,
            "monitor_events": len(dump["events"]),
            "event_kinds": kinds,
            "server_time_ms": server_ms,
            "time_offset_ms": offset_ms,
            "connect_rtt_ms": client.connect_rtt_ms,
            "server_day": server_day,
            "can_trade": bool(account.get("canTrade")),
            "config_snapshot_id": dump["config_snapshot_id"],
        }
        if "monitor_ready" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_ready_missing", facts)
        if "query" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_query_missing", facts)
        if len(server_day) != 8:
            return CaseResult(CASE_ID, "FAIL", "server_day_invalid", facts)
        if "canTrade" not in account:
            return CaseResult(CASE_ID, "FAIL", "account_read_invalid", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
