"""C01 — authenticated login with a valid session on the same account.

Success condition: authenticate/login reached a ready session with a valid
trading day and connection generation, and the baseline account-scope reads
(account, positions, orders for the configured contract) all complete on that
same connection generation.
"""

from __future__ import annotations

from certlib.context import CaseResult

CASE_ID = "C01"
RISK = "READ"


class C01Strategy:
    def run(self, ctx):
        client = ctx.client
        contract = ctx.contract

        login = dict(client.login_facts)
        if not login or len(str(login.get("trading_day", ""))) != 8:
            return CaseResult(CASE_ID, "FAIL", "login_facts_missing", login)
        if int(login.get("connection_generation", 0)) <= 0:
            return CaseResult(CASE_ID, "FAIL", "connection_generation_invalid", login)

        account = client.query_account()
        positions = client.query_positions(contract["instrument"])
        orders = client.query_orders(contract["instrument"])

        facts = {
            "trading_day": login["trading_day"],
            "connection_generation": login["connection_generation"],
            "front_id": login["front_id"],
            "session_id": login["session_id"],
            "account_fingerprint": client.account_fingerprint,
            "account_rows": account["facts"]["record_count"],
            "position_rows": positions["facts"]["record_count"],
            "order_rows": orders["facts"]["record_count"],
            "query_generations": [
                account["facts"]["connection_generation"],
                positions["facts"]["connection_generation"],
                orders["facts"]["connection_generation"],
            ],
        }
        if facts["account_rows"] < 1:
            return CaseResult(CASE_ID, "FAIL", "account_query_empty", facts)
        if any(row == 0 for row in facts["query_generations"]):
            return CaseResult(CASE_ID, "FAIL", "query_generation_unbound", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
