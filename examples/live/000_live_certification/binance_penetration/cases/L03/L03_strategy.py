"""L03 — monitor event capture.

Success condition: the monitor records its start marker plus the account read
and the mark-price read (attached through the client event hook when the
client provides one, recorded directly otherwise), and the monitor snapshot
is retained as an artifact.
"""

from __future__ import annotations

from certlib.binance_client import BinanceApiError
from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "L03"
RISK = "READ"


class L03Strategy:
    def run(self, ctx):
        client = ctx.client
        symbol = ctx.scenario()["symbol"]
        mon = Monitor({})
        hooked = hasattr(client, "event_hook")
        if hooked:
            client.event_hook = mon.record
        mon.record("monitor_start", case=CASE_ID)

        try:
            account = client.account_config()
            mon.record("query", family="account_config")
            mark = client.mark_price(symbol)
            mon.record("query", family="mark_price")
        except BinanceApiError as exc:
            ctx.record_artifact("monitor", mon.dump())
            return CaseResult(
                CASE_ID, "FAIL", f"query_failed:{exc.code}",
                {"error": str(exc.msg)[:160], "monitor_events": len(mon.events)},
            )

        ctx.record_artifact("monitor", mon.dump())
        dump = mon.dump()
        kinds = [entry["kind"] for entry in dump["events"]]
        facts = {
            "hook_attached": hooked,
            "event_count": len(dump["events"]),
            "event_kinds": kinds,
            "config_snapshot_id": dump["config_snapshot_id"],
            "symbol": symbol,
            "can_trade": bool(account.get("canTrade")),
            "mark_price": mark,
        }
        if len(dump["events"]) < 2:
            return CaseResult(CASE_ID, "FAIL", "monitor_events_missing", facts)
        if "monitor_start" not in kinds or "query" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_events_missing", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
