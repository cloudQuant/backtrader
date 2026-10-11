"""L03 — monitor event capture over the signed session.

The OKX client has no session event hook, so the suite monitor records
directly: a monitor-start marker, an account-configuration read and a ticker
read.  Success condition: the monitor snapshot contains the start marker and
the observed query events, and the snapshot is retained as an artifact.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "L03"
RISK = "READ"


class L03Strategy:
    def run(self, ctx):
        client = ctx.client
        inst_id = ctx.scenario().get("inst_id", "BTC-USDT-SWAP")

        mon = Monitor({})
        mon.record("monitor_start", case=CASE_ID)
        config = client.account_config()
        mon.record("query", path="/api/v5/account/config", rows=1)
        ticker = client.ticker(inst_id)
        mon.record("query", path="/api/v5/market/ticker", rows=1)

        dump = mon.dump()
        ctx.record_artifact("monitor", dump)
        kinds = [entry["kind"] for entry in dump["events"]]
        facts = {
            "inst_id": inst_id,
            "event_count": len(dump["events"]),
            "event_kinds": kinds,
            "config_snapshot_id": dump["config_snapshot_id"],
            "acct_lv": config.get("acctLv"),
            "last": ticker.get("last"),
        }
        if "monitor_start" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_start_missing", facts)
        if "query" not in kinds:
            return CaseResult(CASE_ID, "FAIL", "monitor_query_missing", facts)
        if len(dump["events"]) < 2:
            return CaseResult(CASE_ID, "FAIL", "monitor_events_missing", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
