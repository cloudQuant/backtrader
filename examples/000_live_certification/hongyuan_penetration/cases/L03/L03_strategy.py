"""Observe a correlated monitor-log record for case L03."""
import backtrader as bt


class L03Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting monitor event with trace and digest"
        self.bars_seen = 0

    def notify_store(self, msg, *args, **kwargs):
        event = kwargs.get("event")
        if msg != "runtime_event" or not isinstance(event, dict):
            return
        if event.get("event_type") != "risk_monitor_event":
            return
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        row = {"event_type": "risk_monitor_event"}
        for key in ("timestamp", "trace_id", "metric", "monitor_digest"):
            value = event.get(key)
            if value is None:
                value = details.get(key)
            if isinstance(value, (str, int, float, bool)):
                row[key] = value
        self.case_events.append(row)
        if row.get("trace_id") and row.get("metric") and row.get("monitor_digest"):
            self.case_observed = True
            self.case_reason = "monitor event observed; runner retains certification decision"
        else:
            self.case_reason = "monitor event lacks trace, metric, or integrity digest"

    def next(self):
        self.bars_seen += 1
