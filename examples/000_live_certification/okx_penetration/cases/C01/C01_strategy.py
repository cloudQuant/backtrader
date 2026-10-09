"""C01 — authenticated demo session on the same account (read-only).

Success condition: the signed session is established (server time offset,
account configuration), and the account-scope reads (balance, positions,
pending orders) plus instrument/ticker metadata for the configured contract
all succeed under the same credentials.
"""

from __future__ import annotations

from certlib.context import CaseResult

CASE_ID = "C01"
RISK = "READ"


class C01Strategy:
    def run(self, ctx):
        client = ctx.client
        scenario = ctx.scenario()
        inst_id = scenario.get("inst_id", "BTC-USDT-SWAP")

        config = client.account_config()
        balance = client.balance()
        positions = client.positions(inst_id=inst_id)
        pending = client.pending_orders(inst_id=inst_id)
        instruments = client.instruments(inst_id)
        if not instruments:
            return CaseResult(CASE_ID, "FAIL", "instrument_unknown", {"inst_id": inst_id})
        ticker = client.ticker(inst_id)

        facts = {
            "inst_id": inst_id,
            "pos_mode": client.pos_mode,
            "acct_lv": config.get("acctLv"),
            "balance_rows": len(balance),
            "position_rows": len(positions),
            "pending_order_rows": len(pending),
            "instrument_state": instruments[0].get("state"),
            "last": ticker.get("last"),
            "time_offset_ms": client.time_offset_ms,
        }
        if not balance:
            return CaseResult(CASE_ID, "FAIL", "balance_query_empty", facts)
        if str(instruments[0].get("state")) != "live":
            return CaseResult(CASE_ID, "FAIL", f"instrument_state:{instruments[0].get('state')}", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
