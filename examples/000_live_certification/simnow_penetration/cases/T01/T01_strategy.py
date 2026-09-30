"""Offline T01 strategy for a bounded open-order request and cleanup."""

import backtrader as bt


class T01Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = (
            "waiting for a local open-order observation"
            if self.p.allow_orders is True
            else "offline order actions are disabled"
        )
        self.bars_seen = 0
        self.order_refs = []
        self.order_statuses = {}
        self.order = None
        self._accepted = False
        self._cancel_requested = False

    def _config_value(self, name, default):
        config = self.p.case_config
        if not hasattr(config, "get"):
            return default
        parameters = config.get("parameters", config)
        return parameters.get(name, default) if hasattr(parameters, "get") else default

    def _number(self, name, default):
        try:
            value = float(self._config_value(name, default))
        except (TypeError, ValueError):
            value = float(default)
        return value if value >= 0 else float(default)

    def _integer(self, name, default, minimum, maximum):
        value = self._config_value(name, default)
        try:
            if isinstance(value, bool):
                raise ValueError
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return min(maximum, max(minimum, value))

    def _record_order(self, order, side, size):
        self.order_refs.append(order.ref)
        self.case_events.append(
            {"kind": "local_order_submitted", "ref": order.ref, "side": side, "size": size}
        )

    def notify_order(self, order):
        status = order.getstatusname()
        self.order_statuses[order.ref] = status
        self.case_events.append(
            {
                "kind": "local_order_status",
                "ref": order.ref,
                "status": status,
                "executed_size": order.executed.size,
            }
        )
        if order.ref != getattr(self.order, "ref", None):
            return
        if status in ("Accepted", "Partial"):
            self._accepted = True
        elif status == "Canceled" and self._accepted and self._cancel_requested:
            self.case_observed = True
            self.case_reason = "local open order was accepted and canceled"
        elif status in ("Completed", "Rejected", "Margin", "Expired"):
            self.case_reason = "local open order reached {} before cleanup".format(status.lower())

    def notify_store(self, msg, *args, **kwargs):
        # This local smoke does not consume store notifications.
        pass

    def next(self):
        self.bars_seen += 1
        if self.p.allow_orders is not True or self.case_observed:
            return
        if self.order is None:
            size = self._integer("order_size", 1, 1, 5)
            offset = self._number("price_offset", 20.0)
            price = max(float(self.data.close[0]) - offset, 0.01)
            self.order = self.buy(size=size, exectype=bt.Order.Limit, price=price, offset="open")
            if self.order is not None:
                self._record_order(self.order, "buy_open", size)
                self.case_reason = "local open order submitted; awaiting acceptance"
            return
        status = self.order_statuses.get(self.order.ref)
        if status in ("Accepted", "Partial") and not self._cancel_requested:
            self._accepted = True
            self._cancel_requested = True
            self.cancel(self.order)
            self.case_events.append({"kind": "local_cancel_requested", "ref": self.order.ref})
            self.case_reason = "local open order cancel requested; awaiting terminal status"
        elif status == "Canceled" and self._accepted and self._cancel_requested:
            self.case_observed = True
            self.case_reason = "local open order was accepted and canceled"
