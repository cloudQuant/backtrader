"""TH06 strategy: bounded local repeated-order threshold probe."""

import backtrader as bt


class TH06Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))
    threshold_name = "duplicate_order_warn_threshold"
    threshold_metric = "duplicate_order"
    expected_threshold = 2
    max_submit_requests = 3

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = "waiting for bars and a local repeated-order threshold observation"
        self.bars_seen = 0
        self.case_config = self.p.case_config
        self.submit_count = 0
        self.order_attempts = 0
        self.cancel_request_count = 0
        self.orders = []
        self._case_price = None
        self._setting_recorded = False
        config = self.case_config if isinstance(self.case_config, dict) else {}
        parameters = config.get("parameters", {})
        self._config_ok = not (
            isinstance(parameters, dict) and parameters.get("scenario") not in (None, "TH06")
        )
        if not self._config_ok:
            self.case_reason = "case_config scenario does not match TH06"

    def _record(self, event):
        if len(self.case_events) < 100:
            self.case_events.append(event)

    def _inspect_logger(self):
        stats = getattr(self, "stats", None)
        for observer in getattr(stats, "items", ()):
            if observer.__class__.__name__ != "TradeLogger":
                continue
            params = getattr(observer, "p", None)
            threshold = getattr(params, self.threshold_name, None)
            if threshold is not None and not self._setting_recorded:
                self._setting_recorded = True
                self._record(
                    {
                        "event_type": "local_threshold_setting",
                        "name": self.threshold_name,
                        "value": threshold,
                    }
                )
            if threshold != self.expected_threshold:
                continue
            counts = getattr(observer, "_monitoring", {})
            observed_count = (
                int(counts.get("duplicate_order_count", 0)) if hasattr(counts, "get") else 0
            )
            if observed_count >= self.expected_threshold:
                self.case_observed = True
                self.case_reason = "TradeLogger duplicate-order threshold was reached locally; this is not certification evidence"

    def _limit_price(self):
        if self._case_price is not None:
            return self._case_price
        try:
            close = float(self.data.close[0])
        except (TypeError, ValueError, IndexError):
            return None
        if close <= 0 or close != close or close > 1.0e300:
            return None
        self._case_price = max(close * 0.000001, 1.0e-8)
        return self._case_price

    def _request_one(self):
        if self.order_attempts >= self.max_submit_requests:
            return
        if not isinstance(getattr(self, "broker", None), bt.brokers.BackBroker):
            self.case_reason = "order requests are disabled unless the broker is BackBroker"
            return
        price = self._limit_price()
        if price is None:
            self.case_reason = (
                "no finite positive bar price is available for the bounded local probe"
            )
            return
        self.order_attempts += 1
        try:
            order = self.buy(size=1, exectype=bt.Order.Limit, price=price)
            if order is None:
                self._record({"event_type": "local_submit_unavailable"})
                self.case_reason = "offline broker did not return an order object"
                return
            self.orders.append(order)
            self.submit_count += 1
            self._record(
                {
                    "event_type": "local_submit_request",
                    "ref": getattr(order, "ref", None),
                    "size": 1,
                    "price": price,
                }
            )
            self.cancel_request_count += 1
            self.cancel(order)
            self._record({"event_type": "local_cancel_request", "ref": getattr(order, "ref", None)})
            self.case_reason = "identical local order and cancel requests were counted; a monitor warning remains unverified"
        except Exception as exc:
            self._record({"event_type": "local_order_error", "message": str(exc)[:160]})
            self.case_reason = "bounded local order probe could not be issued"

    def notify_order(self, order):
        self._record(
            {
                "event_type": "local_order_status",
                "ref": getattr(order, "ref", None),
                "status": order.getstatusname(),
            }
        )

    def notify_store(self, msg, *args, **kwargs):
        event = kwargs.get("event")
        if not isinstance(event, dict):
            return
        event_type = event.get("event_type")
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        if event_type in (
            "duplicate_order_threshold_reached",
            "risk_threshold_triggered",
        ) and details.get("counter", self.threshold_metric) in (
            self.threshold_metric,
            "duplicate_order_count",
        ):
            self._record({"event_type": event_type, "details": dict(details)})
            self.case_observed = True
            self.case_reason = "matching local duplicate threshold event was received; this is not certification evidence"

    def next(self):
        self.bars_seen += 1
        self._inspect_logger()
        if (
            self.p.allow_orders is True
            and self._config_ok
            and self.order_attempts < self.max_submit_requests
        ):
            self._request_one()
