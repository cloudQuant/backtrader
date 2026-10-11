"""L02 — session system log capture.

Success condition: the session log shows exactly one connect (the server-time
probe) and every recorded call afterwards is a read; the recorded artifact is
the session log itself.  A read is performed so the log is not empty.
"""

from __future__ import annotations

from certlib.context import CaseResult

CASE_ID = "L02"
RISK = "READ"

_WRITE_METHODS = ("POST", "PUT", "DELETE")


class L02Strategy:
    def run(self, ctx):
        client = ctx.client
        account = client.account_config()
        calls = list(client.calls)
        ctx.record_artifact("session_log", calls)

        connect_events = 1 if client.server_time_ms is not None else 0
        reads = [entry for entry in calls if entry.get("method") == "GET"]
        writes = [entry for entry in calls if entry.get("method") in _WRITE_METHODS]
        call_counts = {}
        for entry in calls:
            kind = str(entry.get("method"))
            call_counts[kind] = call_counts.get(kind, 0) + 1

        facts = {
            "total_calls": len(calls),
            "call_counts": call_counts,
            "connect_events": connect_events,
            "read_events": len(reads),
            "write_events": len(writes),
            "server_time_ms": client.server_time_ms,
            "can_trade": bool(account.get("canTrade")),
        }
        if connect_events != 1:
            return CaseResult(CASE_ID, "FAIL", "connect_log_invalid", facts)
        if not reads or len(reads) != len(calls):
            return CaseResult(CASE_ID, "FAIL", "read_log_invalid", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
