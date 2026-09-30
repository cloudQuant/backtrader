"""Observe order-submit monitor events for case M04."""
import backtrader as bt


class M04Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_config = self.p.case_config
        self.case_events = []
        self.case_observed = False
        self.case_reason = "awaiting an order-submit monitor event"
        self.bars_seen = 0
        self._probe_order = None
        self._probe_sent = False
        self._cancel_sent = False

    @staticmethod
    def _capture(event):
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        row = {"event_type": event.get("event_type")}
        for key in (
            "timestamp",
            "order_ref",
            "trace_id",
            "dispatch_state",
            "submitted_order_count",
        ):
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
        if event.get("event_type") != "order_submit_request":
            return
        row = self._capture(event)
        self.case_events.append(row)
        if (
            row.get("order_ref")
            and row.get("trace_id")
            and row.get("dispatch_state") == "submitted"
        ):
            self.case_observed = True
            self.case_reason = "submit request observed; monitor count and provider reconciliation remain runner evidence"

    def notify_order(self, order):
        status = order.getstatusname() if hasattr(order, "getstatusname") else str(order.status)
        self.case_events.append({"source": "backtrader_order_callback", "status": status})
        if (
            self.p.allow_orders is True
            and self._probe_order is not None
            and not self._cancel_sent
            and order.ref == self._probe_order.ref
            and order.status == bt.Order.Accepted
        ):
            self._cancel_sent = True
            self.cancel(order)

    def next(self):
        self.bars_seen += 1
        if self.p.allow_orders is not True or self._probe_sent or self.data is None:
            return
        close = float(self.data.close[0])
        if not (close > 0 and close == close and close < float("inf")):
            return
        self._probe_sent = True
        self._probe_order = self.buy(
            size=1, exectype=bt.Order.Limit, price=max(round(close * 0.25, 2), 0.01)
        )
