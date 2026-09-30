"""E02 strategy: passively observe supplied remote order-rejection events."""

import backtrader as bt


class E02Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = "waiting for a supplied remote position-rejection event"
        self.bars_seen = 0
        self.case_config = self.p.case_config
        config = self.case_config if isinstance(self.case_config, dict) else {}
        parameters = config.get("parameters", {})
        if isinstance(parameters, dict) and parameters.get("scenario") not in (None, "E02"):
            self.case_reason = "case_config scenario does not match E02"

    def _record(self, event):
        if len(self.case_events) < 100:
            self.case_events.append(event)

    def notify_store(self, msg, *args, **kwargs):
        event = kwargs.get("event")
        if not isinstance(event, dict) or event.get("event_type") != "order_reject_remote":
            return
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        error_id = event.get(
            "ErrorID", event.get("error_code", details.get("ErrorID", details.get("ErrorId")))
        )
        error_msg = event.get("ErrorMsg", event.get("error_msg", details.get("ErrorMsg", "")))
        status_msg = event.get(
            "StatusMsg", event.get("status_msg", details.get("StatusMsg", error_msg))
        )
        if error_id in (None, "") and error_msg in (None, "") and status_msg in (None, ""):
            return
        self._record(
            {
                "event_type": "order_reject_remote",
                "order_ref": event.get("order_ref", details.get("order_ref")),
                "ErrorID": error_id,
                "ErrorMsg": str(error_msg)[:500],
                "StatusMsg": str(status_msg)[:500],
                "timestamp": event.get("timestamp"),
            }
        )
        self.case_observed = True
        self.case_reason = "remote rejection notification was observed; position classification and provider evidence still require review"

    def notify_order(self, order):
        self._record(
            {
                "event_type": "local_order_status",
                "ref": getattr(order, "ref", None),
                "status": order.getstatusname(),
            }
        )

    def next(self):
        self.bars_seen += 1
