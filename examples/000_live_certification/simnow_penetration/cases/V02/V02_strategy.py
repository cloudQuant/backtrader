"""V02 strategy: passively observe invalid-price-tick validation callbacks."""

import backtrader as bt


class V02Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = "waiting for a typed invalid-price-tick validation callback"
        self.bars_seen = 0
        self.case_config = self.p.case_config
        config = self.case_config if isinstance(self.case_config, dict) else {}
        parameters = config.get("parameters", {})
        if isinstance(parameters, dict) and parameters.get("scenario") not in (None, "V02"):
            self.case_reason = "case_config scenario does not match V02"

    def _record(self, event):
        if len(self.case_events) < 100:
            self.case_events.append(event)

    def notify_store(self, msg, *args, **kwargs):
        event = kwargs.get("event")
        if not isinstance(event, dict):
            return
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        code = event.get(
            "error_code",
            event.get("error_msg", details.get("error_code", details.get("error_msg", ""))),
        )
        code_text = str(code).lower()
        event_type = event.get("event_type")
        matched = event_type in (
            "order_validation_rejected",
            "order_reject_local",
            "order_rejected",
        ) and (
            "invalid_price_tick" in code_text
            or "price tick" in code_text
            or "tick mismatch" in code_text
        )
        if not matched:
            return
        self._record(
            {
                "event_type": event_type,
                "error_code": code,
                "price": event.get("price", details.get("price")),
                "min_price_tick": event.get("min_price_tick", details.get("min_price_tick")),
                "timestamp": event.get("timestamp"),
            }
        )
        self.case_observed = True
        self.case_reason = "local invalid-tick rejection callback was observed; validation provenance still needs review"

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
