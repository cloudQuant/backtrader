"""Typed read-only evidence contracts with a lazy offline smoke strategy."""
from __future__ import annotations

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "TH03"
PLAN = {
    "case_id": "TH03",
    "scenario_id": "RISK-THRESHOLD-03",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Record the configured combined submit-and-cancel warning threshold.",
    "actions": [
        "Start the approved sandbox runtime with submit_cancel_total_warn_threshold set to 10.",
        "Allow monitor initialization and one normal market-data bar without order activity.",
        "Collect the monitor summary and retain the effective threshold and cancellation-counter fields.",
    ],
    "evidence": [
        "Runtime-resolved combined threshold value.",
        "monitoring_summary event and its documented cancel threshold/count fields.",
        "Timestamped monitor log and runtime configuration identity.",
    ],
    "completion_criteria": [
        "The combined threshold is visible in runtime evidence and no order activity occurred."
    ],
}


def create_strategy(plan, scope, authenticator):
    """Build the no-I/O event state machine for an injected managed adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)


def _load_smoke_strategy():
    """TH03 strategy: inspect the local combined submit/cancel threshold setting."""

    import backtrader as bt

    class TH03Strategy(bt.Strategy):
        params = (("case_config", None), ("allow_orders", False))
        threshold_name = "submit_cancel_total_warn_threshold"
        threshold_metric = "submit_cancel_total"
        expected_threshold = 10

        def __init__(self):
            self.case_events = []
            self.case_observed = False
            self.case_reason = "waiting for local TradeLogger combined-threshold configuration"
            self.bars_seen = 0
            self.case_config = self.p.case_config
            self._setting_recorded = False
            config = self.case_config if isinstance(self.case_config, dict) else {}
            parameters = config.get("parameters", {})
            if isinstance(parameters, dict) and parameters.get("scenario") not in (None, "TH03"):
                self.case_reason = "case_config scenario does not match TH03"

        def _record(self, event):
            if len(self.case_events) < 100:
                self.case_events.append(event)

        def _observe_setting(self):
            if self._setting_recorded:
                return
            stats = getattr(self, "stats", None)
            for observer in getattr(stats, "items", ()):
                if observer.__class__.__name__ != "TradeLogger":
                    continue
                value = getattr(getattr(observer, "p", None), self.threshold_name, None)
                if value is None:
                    continue
                self._setting_recorded = True
                self._record(
                    {
                        "event_type": "local_threshold_setting",
                        "name": self.threshold_name,
                        "value": value,
                    }
                )
                if value == self.expected_threshold:
                    self.case_observed = True
                    self.case_reason = "TradeLogger combined threshold was observed locally; this is not certification evidence"
                else:
                    self.case_reason = (
                        "TradeLogger combined threshold differs from the TH03 planned value"
                    )
                return

        def notify_store(self, msg, *args, **kwargs):
            event = kwargs.get("event")
            if not isinstance(event, dict):
                return
            details = event.get("details") if isinstance(event.get("details"), dict) else {}
            thresholds = (
                details.get("thresholds") if isinstance(details.get("thresholds"), dict) else {}
            )
            value = event.get(
                self.threshold_name,
                details.get(self.threshold_name, thresholds.get(self.threshold_metric)),
            )
            if (
                event.get("event_type") not in ("risk_threshold_configured", "monitoring_summary")
                or value is None
            ):
                return
            self._record({"event_type": event.get("event_type"), "threshold": value})
            if value == self.expected_threshold:
                self.case_observed = True
                self.case_reason = "matching local threshold event was observed; this is not certification evidence"

        def next(self):
            self.bars_seen += 1
            self._observe_setting()

    return TH03Strategy


def __getattr__(name):
    if name == "TH03Strategy":
        strategy = _load_smoke_strategy()
        globals()[name] = strategy
        return strategy
    raise AttributeError(name)
