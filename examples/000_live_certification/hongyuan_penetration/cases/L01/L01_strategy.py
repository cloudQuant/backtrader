"""Correlate trade-log submissions and executions for case L01."""
import backtrader as bt


class L01Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting a logged submission and matching execution"
        self.bars_seen = 0
        self._submissions = {}

    @staticmethod
    def _capture(event):
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        row = {"event_type": event.get("event_type")}
        for key in ("timestamp", "order_ref", "trace_id", "trade_id", "dispatch_state"):
            value = event.get(key)
            if value is None:
                value = details.get(key)
            if isinstance(value, (str, int, float, bool)):
                row[key] = value
        return row

    def notify_store(self, msg, *args, **kwargs):
        event = kwargs.get("event")
        if msg != "runtime_event" or not isinstance(event, dict):
            return
        kind = event.get("event_type")
        if kind not in ("order_submit_request", "trade_execution"):
            return
        row = self._capture(event)
        self.case_events.append(row)
        if kind == "order_submit_request" and row.get("order_ref") and row.get("trace_id"):
            self._submissions[row["order_ref"]] = row["trace_id"]
        elif (
            kind == "trade_execution"
            and row.get("trade_id")
            and row.get("order_ref") in self._submissions
            and row.get("trace_id") == self._submissions[row["order_ref"]]
        ):
            self.case_observed = True
            self.case_reason = (
                "matching trade-log events observed; runner retains certification decision"
            )

    def next(self):
        self.bars_seen += 1
