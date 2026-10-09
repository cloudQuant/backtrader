"""L02 — signed-session system log capture.

OKX REST is stateless, so the "session" is the signed credential context and
the session log is the client's call journal for this run.  Success condition:
the log holds exactly one unsigned server-time anchor call (measured at
connect), at least one successful signed read, and no failed call.  Facts
carry no account identifiers.
"""

from __future__ import annotations

from certlib.context import CaseResult

CASE_ID = "L02"
RISK = "READ"

_TIME_PATH = "/api/v5/public/time"


class L02Strategy:
    def run(self, ctx):
        client = ctx.client
        inst_id = ctx.scenario().get("inst_id", "BTC-USDT-SWAP")

        balance = client.balance()
        calls = list(client.calls)
        ctx.record_artifact("session_log", calls)

        time_calls = [e for e in calls if e.get("path") == _TIME_PATH]
        signed_reads = [e for e in calls if e.get("path") != _TIME_PATH]
        failures = [
            e for e in calls
            if e.get("error") or not (200 <= int(e.get("status") or 0) < 300)
        ]
        call_counts = {}
        for entry in calls:
            path = str(entry.get("path"))
            call_counts[path] = call_counts.get(path, 0) + 1

        facts = {
            "inst_id": inst_id,
            "total_calls": len(calls),
            "call_counts": call_counts,
            "time_calls": len(time_calls),
            "signed_reads": len(signed_reads),
            "failed_calls": len(failures),
            "time_offset_ms": client.time_offset_ms,
            "balance_rows": len(balance),
        }
        if len(time_calls) != 1:
            return CaseResult(CASE_ID, "FAIL", "time_anchor_invalid", facts)
        if not signed_reads:
            return CaseResult(CASE_ID, "FAIL", "signed_reads_missing", facts)
        if failures:
            return CaseResult(CASE_ID, "FAIL", "session_log_has_failures", facts)
        if not balance:
            return CaseResult(CASE_ID, "FAIL", "balance_query_empty", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
