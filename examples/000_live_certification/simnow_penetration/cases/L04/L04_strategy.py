"""Observe a local validation rejection record for case L04."""
import backtrader as bt


class L04Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting a logged local validation rejection"
        self.bars_seen = 0

    def notify_store(self, msg, *args, **kwargs):
        event = kwargs.get("event")
        if msg != "runtime_event" or not isinstance(event, dict):
            return
        if event.get("event_type") != "order_validation_rejected":
            return
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        row = {"event_type": "order_validation_rejected"}
        for key in (
            "timestamp",
            "trace_id",
            "error_code",
            "error_msg",
            "validation_rule",
            "dispatch_absent",
        ):
            value = event.get(key)
            if value is None:
                value = details.get(key)
            if isinstance(value, (str, int, float, bool)):
                row[key] = value
        self.case_events.append(row)
        if (
            row.get("trace_id")
            and row.get("error_code")
            and row.get("error_msg")
            and row.get("validation_rule")
            and row.get("dispatch_absent") is True
        ):
            self.case_observed = True
            self.case_reason = "local rejection log observed; runner retains certification decision"

    def next(self):
        self.bars_seen += 1
