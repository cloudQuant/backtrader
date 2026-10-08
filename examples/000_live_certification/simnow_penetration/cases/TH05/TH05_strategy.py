"""Typed read-only evidence contracts with a lazy offline smoke strategy."""
from __future__ import annotations

from common.read_only_case_strategy import create_read_only_strategy

CASE_ID = "TH05"
PLAN = {
    "case_id": "TH05",
    "scenario_id": "RISK-THRESHOLD-05",
    "evidence_mode": "REAL",
    "status": "PLANNED",
    "objective": "Record the configured repeated-order threshold and its observation window.",
    "actions": [
        "Start the approved sandbox runtime with duplicate_order_warn_threshold set to 3.",
        "Allow monitor initialization and one normal market-data bar without submitting or cancelling orders.",
        "Collect the monitor summary and retain the threshold and repeat-window values.",
    ],
    "evidence": [
        "Runtime-resolved repeat threshold value.",
        "monitoring_summary event containing the repeat threshold and repeat window.",
        "Timestamped monitor log and runtime configuration identity.",
    ],
    "completion_criteria": [
        "The threshold and observation window are visible in runtime evidence; no order activity occurred."
    ],
}


def create_strategy(plan, scope, authenticator):
    """Build the no-I/O event state machine for an injected managed adapter."""

    return create_read_only_strategy(CASE_ID, plan, scope, authenticator)


def _load_smoke_strategy():
    """TH05 strategy: inspect the local repeated-order threshold and window."""

    import backtrader as bt

    class TH05Strategy(bt.Strategy):
        params = (("case_config", None), ("allow_orders", False))
        threshold_name = "duplicate_order_warn_threshold"
        threshold_metric = "duplicate_order"
        expected_threshold = 3
        window_name = "duplicate_order_window_seconds"
        expected_window = 60.0

        def __init__(self):
            self.case_events = []
            self.case_observed = False
            self.case_reason = "waiting for local TradeLogger repeated-order threshold and window"
            self.bars_seen = 0
            self.case_config = self.p.case_config
            self._setting_recorded = False
            config = self.case_config if isinstance(self.case_config, dict) else {}
            parameters = config.get("parameters", {})
            if isinstance(parameters, dict) and parameters.get("scenario") not in (None, "TH05"):
                self.case_reason = "case_config scenario does not match TH05"

        def _record(self, event):
            if len(self.case_events) < 100:
                self.case_events.append(event)

        def _window_matches(self, value):
            try:
                return float(value) == self.expected_window
            except (TypeError, ValueError):
                return False

        def _observe_setting(self):
            if self._setting_recorded:
                return
            stats = getattr(self, "stats", None)
            for observer in getattr(stats, "items", ()):
                if observer.__class__.__name__ != "TradeLogger":
                    continue
                params = getattr(observer, "p", None)
                threshold = getattr(params, self.threshold_name, None)
                window = getattr(params, self.window_name, None)
                if threshold is None or window is None:
                    continue
                self._setting_recorded = True
                self._record(
                    {
                        "event_type": "local_threshold_setting",
                        "name": self.threshold_name,
                        "value": threshold,
                        "window_seconds": window,
                    }
                )
                if threshold == self.expected_threshold and self._window_matches(window):
                    self.case_observed = True
                    self.case_reason = "TradeLogger repeat threshold and window were observed locally; this is not certification evidence"
                else:
                    self.case_reason = (
                        "TradeLogger repeat threshold or window differs from the TH05 planned value"
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
            window = details.get("repeat_window_sec", details.get(self.window_name))
            if (
                event.get("event_type") not in ("risk_threshold_configured", "monitoring_summary")
                or value is None
            ):
                return
            self._record(
                {
                    "event_type": event.get("event_type"),
                    "threshold": value,
                    "window_seconds": window,
                }
            )
            if value == self.expected_threshold and self._window_matches(window):
                self.case_observed = True
                self.case_reason = "matching local threshold and window event was observed; this is not certification evidence"

        def next(self):
            self.bars_seen += 1
            self._observe_setting()

    return TH05Strategy


def __getattr__(name):
    if name == "TH05Strategy":
        strategy = _load_smoke_strategy()
        globals()[name] = strategy
        return strategy
    raise AttributeError(name)
