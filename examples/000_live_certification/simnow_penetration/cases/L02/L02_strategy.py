"""L02 — session system log capture.

Success condition: the session log holds exactly one login event with a
positive connection generation, and every query event in the log carries that
same connection generation.
"""

from __future__ import annotations

from certlib.context import CaseResult

CASE_ID = "L02"
RISK = "READ"


class L02Strategy:
    def run(self, ctx):
        client = ctx.client
        calls = client.calls
        ctx.record_artifact("session_log", calls)

        login_events = [entry for entry in calls if entry.get("kind") == "login"]
        query_events = [entry for entry in calls if entry.get("kind") == "query"]
        generation = int(client.login_facts.get("connection_generation", 0) or 0)

        call_counts = {}
        for entry in calls:
            kind = str(entry.get("kind"))
            call_counts[kind] = call_counts.get(kind, 0) + 1

        facts = {
            "total_calls": len(calls),
            "call_counts": call_counts,
            "login_events": len(login_events),
            "query_events": len(query_events),
            "connection_generation": generation,
        }
        if len(login_events) != 1 or generation <= 0:
            return CaseResult(CASE_ID, "FAIL", "login_log_invalid", facts)
        for entry in query_events:
            if int(entry.get("connection_generation", 0) or 0) != generation:
                return CaseResult(CASE_ID, "FAIL", "query_generation_mismatch", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
