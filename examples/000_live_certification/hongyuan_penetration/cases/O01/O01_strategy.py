"""Offline O01 strategy for bounded repeated open-order intents."""

import backtrader as bt


class O01Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = (
            "waiting for a local repeated open-order observation"
            if self.p.allow_orders is True
            else "offline order actions are disabled"
        )
        self.bars_seen = 0
        self.order_refs = []
        self.order_statuses = {}
        self._target = self._integer("repeat_count", 3, 2, 5)
        self._rounds_canceled = 0
        self._current_order = None
        self._current_ref = None
        self._cancel_requested = False
        self._fixed_price = None
        self._failed = False

    def _config_value(self, name, default):
        config = self.p.case_config
        if not hasattr(config, "get"):
            return default
        parameters = config.get("parameters", config)
        return parameters.get(name, default) if hasattr(parameters, "get") else default

    def _integer(self, name, default, minimum, maximum):
        value = self._config_value(name, default)
        try:
            if isinstance(value, bool):
                raise ValueError
            value = int(value)
        except (TypeError, ValueError):
            value = default
        return min(maximum, max(minimum, value))

    def _number(self, name, default):
        try:
            value = float(self._config_value(name, default))
        except (TypeError, ValueError):
            value = float(default)
        return value if value >= 0 else float(default)

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
        if order.ref != self._current_ref:
            return
        if status == "Canceled" and self._cancel_requested:
            if order.executed.size == 0:
                self._rounds_canceled += 1
                self.case_events.append(
                    {
                        "kind": "local_repeat_open_canceled",
                        "ref": order.ref,
                        "count": self._rounds_canceled,
                    }
                )
                self._current_order = None
                self._current_ref = None
                self._cancel_requested = False
                if self._rounds_canceled >= self._target:
                    self.case_observed = True
                    self.case_reason = (
                        "{} identical local open orders were accepted and canceled".format(
                            self._rounds_canceled
                        )
                    )
            else:
                self._failed = True
                self.case_reason = (
                    "a repeated local open order partially filled before cancellation"
                )
        elif status in ("Completed", "Rejected", "Margin", "Expired"):
            self._failed = True
            self.case_reason = "repeated local open order reached {}".format(status.lower())

    def notify_store(self, msg, *args, **kwargs):
        # This local smoke does not consume store notifications.
        pass

    def next(self):
        self.bars_seen += 1
        if self.p.allow_orders is not True or self.case_observed or self._failed:
            return
        if self._current_order is not None:
            status = self.order_statuses.get(self._current_ref)
            if status in ("Accepted", "Partial") and not self._cancel_requested:
                self._cancel_requested = True
                self.cancel(self._current_order)
                self.case_events.append(
                    {"kind": "local_cancel_requested", "ref": self._current_ref}
                )
                self.case_reason = (
                    "local repeated open order canceled; awaiting its terminal status"
                )
            return
        if self._rounds_canceled >= self._target:
            return
        size = self._integer("order_size", 1, 1, 5)
        if self._fixed_price is None:
            offset = self._number("price_offset", 20.0)
            self._fixed_price = max(float(self.data.close[0]) - offset, 0.01)
        self._current_order = self.buy(
            size=size,
            exectype=bt.Order.Limit,
            price=self._fixed_price,
            offset="open",
        )
        if self._current_order is not None:
            self._current_ref = self._current_order.ref
            self.order_refs.append(self._current_ref)
            self.case_events.append(
                {
                    "kind": "local_order_submitted",
                    "ref": self._current_ref,
                    "side": "buy_open",
                    "size": size,
                    "price": self._fixed_price,
                    "repeat_index": self._rounds_canceled + 1,
                }
            )
            self.case_reason = "local repeated open intent submitted; awaiting acceptance"
