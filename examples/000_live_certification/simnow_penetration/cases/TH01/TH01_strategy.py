"""TH01 — threshold configuration snapshot (submit threshold).

Success condition: the monitor's effective configuration snapshot equals the
configured threshold set and the snapshot identity has the expected
16-character form.  No orders are placed.
"""

from __future__ import annotations

from certlib.context import CaseResult
from certlib.monitor import Monitor

CASE_ID = "TH01"
RISK = "READ"

_THRESHOLD_KEYS = (
    "submit_threshold",
    "combined_threshold",
    "repeated_threshold",
    "window_seconds",
)


class TH01Strategy:
    def run(self, ctx):
        monitor_config = dict(ctx.scenario().get("monitor", {}))
        mon = Monitor(monitor_config)
        snapshot = mon.snapshot_config()
        ctx.record_artifact("threshold_snapshot", snapshot)

        observed = dict(snapshot.get("config", {}))
        snapshot_id = str(snapshot.get("config_snapshot_id", ""))
        thresholds = {k: v for k, v in observed.items() if k in _THRESHOLD_KEYS}
        facts = {"snapshot_id": snapshot_id, "thresholds": thresholds}
        if not thresholds:
            return CaseResult(CASE_ID, "FAIL", "thresholds_missing", facts)
        if observed != monitor_config:
            return CaseResult(CASE_ID, "FAIL", "snapshot_config_mismatch", facts)
        if len(snapshot_id) != 16:
            return CaseResult(CASE_ID, "FAIL", "snapshot_id_invalid", facts)
        return CaseResult(CASE_ID, "PASS", "", facts)
