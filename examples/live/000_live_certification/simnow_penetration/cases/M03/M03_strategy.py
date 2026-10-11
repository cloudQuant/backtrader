"""M03 — recovery to a fresh session (read-only).

The runner connects exactly one fresh session for the account.  The case
verifies the login facts (8-digit trading day, positive connection
generation), records the recovery fact for that new generation, and reads the
account baseline bound to the same connection generation.  No second session
and no write action are used.
"""

from __future__ import annotations

from certlib.context import CaseResult

CASE_ID = "M03"
RISK = "READ"


class M03Strategy:
    def run(self, ctx):
        client = ctx.client

        login = dict(client.login_facts)
        if not login or len(str(login.get("trading_day", ""))) != 8:
            return CaseResult(CASE_ID, "FAIL", "login_facts_missing", login)
        generation = int(login.get("connection_generation", 0) or 0)
        if generation <= 0:
            return CaseResult(CASE_ID, "FAIL", "connection_generation_invalid", login)

        native = getattr(client, "_client", None)
        ready = bool(getattr(native, "is_read_only_ready", False))
        account = client.query_account()

        facts = {
            "generation": generation,
            "trading_day": login["trading_day"],
            "account_fingerprint": client.account_fingerprint,
            "ready": ready,
            "account_rows": account["facts"]["record_count"],
            "query_generation": account["facts"]["connection_generation"],
        }
        if facts["account_rows"] < 1:
            return CaseResult(CASE_ID, "FAIL", "account_query_empty", facts)
        if facts["query_generation"] != generation:
            return CaseResult(CASE_ID, "FAIL", "query_generation_unbound", facts)
        if not ready:
            return CaseResult(CASE_ID, "BLOCKED", "session_not_ready", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
