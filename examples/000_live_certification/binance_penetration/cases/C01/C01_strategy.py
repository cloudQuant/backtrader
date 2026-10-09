"""C01 — authenticated session with baseline account-scope reads.

Success condition: the demo session is established (server-time offset
measured), the account is in hedge mode and allowed to trade, and the
baseline balances, position-risk and open-order reads all complete.
Facts stay sanitized: no account alias, UID or balance values are emitted.
"""

from __future__ import annotations

from certlib.context import CaseResult

CASE_ID = "C01"
RISK = "READ"


class C01Strategy:
    def run(self, ctx):
        client = ctx.client
        symbol = ctx.scenario()["symbol"]

        connect = {
            "host": client.host,
            "server_time_ms": client.server_time_ms,
            "time_offset_ms": client.time_offset_ms,
            "rtt_ms": client.connect_rtt_ms,
        }
        if client.server_time_ms is None:
            return CaseResult(CASE_ID, "BLOCKED", "connect_facts_missing", connect)

        account = client.account_config()
        if not account.get("canTrade"):
            return CaseResult(CASE_ID, "BLOCKED", "account_cannot_trade", connect)

        balances = client.balances()
        risks = client.position_risk(symbol)
        orders = client.open_orders(symbol)
        if not isinstance(balances, list) or not isinstance(risks, list) or not isinstance(orders, list):
            return CaseResult(CASE_ID, "FAIL", "read_shape_invalid", connect)

        facts = {
            "host": client.host,
            "server_time_ms": client.server_time_ms,
            "time_offset_ms": client.time_offset_ms,
            "rtt_ms": client.connect_rtt_ms,
            "symbol": symbol,
            "can_trade": bool(account.get("canTrade")),
            "can_deposit": bool(account.get("canDeposit")),
            "can_withdraw": bool(account.get("canWithdraw")),
            "dual_side_position": account.get("dualSidePosition"),
            "balance_rows": len(balances),
            "position_rows": len(risks),
            "open_order_rows": len(orders),
        }
        if len(balances) < 1:
            return CaseResult(CASE_ID, "FAIL", "balances_empty", facts)
        if account.get("dualSidePosition") is not True:
            return CaseResult(CASE_ID, "FAIL", "hedge_mode_not_enabled", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
