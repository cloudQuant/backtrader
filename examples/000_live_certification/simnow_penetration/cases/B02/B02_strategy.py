"""Offline B02 strategy for canceling multiple accepted open orders."""

import backtrader as bt


class B02Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = (
            "waiting for local accepted orders before batch cancellation"
            if self.p.allow_orders is True
            else "offline order actions are disabled"
        )
        self.bars_seen = 0
        self.order_refs = []
        self.order_statuses = {}
        self._orders_by_ref = {}
        self._fills = {}
        self._target = self._integer("order_count", 3, 2, 5)
        self._cancel_refs = []
        self._cancel_requested = False
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

    def _maybe_finish(self):
        if not self._cancel_requested or not self._cancel_refs:
            return
        terminal = ("Canceled", "Completed", "Rejected", "Margin", "Expired")
        if not all(self.order_statuses.get(ref) in terminal for ref in self._cancel_refs):
            return
        if all(
            self.order_statuses.get(ref) == "Canceled" and self._fills.get(ref, 0) == 0
            for ref in self._cancel_refs
        ):
            self.case_observed = True
            self.case_reason = "{} locally accepted open orders were canceled with no fills".format(
                len(self._cancel_refs)
            )
        else:
            self._failed = True
            self.case_reason = "the local batch included a fill or a non-cancel terminal order"

    def notify_order(self, order):
        status = order.getstatusname()
        self.order_statuses[order.ref] = status
        self._fills[order.ref] = order.executed.size
        self.case_events.append(
            {
                "kind": "local_order_status",
                "ref": order.ref,
                "status": status,
                "executed_size": order.executed.size,
            }
        )
        if status in ("Completed", "Rejected", "Margin", "Expired") and not self._cancel_requested:
            self._failed = True
            self.case_reason = "local open order reached {} before batch cancellation".format(
                status.lower()
            )
        self._maybe_finish()

    def notify_store(self, msg, *args, **kwargs):
        # This local smoke does not consume store notifications.
        pass

    def next(self):
        self.bars_seen += 1
        if self.p.allow_orders is not True or self.case_observed or self._failed:
            return
        if not self.order_refs:
            size = self._integer("order_size", 1, 1, 5)
            offset = self._number("price_offset", 20.0)
            reference = float(self.data.close[0])
            for index in range(self._target):
                price = max(reference - offset - index, 0.01)
                order = self.buy(size=size, exectype=bt.Order.Limit, price=price, offset="open")
                if order is None:
                    continue
                self.order_refs.append(order.ref)
                self._orders_by_ref[order.ref] = order
                self._fills[order.ref] = 0
                self.case_events.append(
                    {
                        "kind": "local_order_submitted",
                        "ref": order.ref,
                        "side": "buy_open",
                        "size": size,
                        "price": price,
                    }
                )
            self.case_reason = "{} local open orders submitted; awaiting acceptance".format(
                len(self.order_refs)
            )
            return
        if self._cancel_requested:
            self._maybe_finish()
            return
        accepted = ("Accepted", "Partial")
        if len(self.order_refs) != self._target or not all(
            self.order_statuses.get(ref) in accepted for ref in self.order_refs
        ):
            return
        self._cancel_refs = list(self.order_refs)
        self._cancel_requested = True
        self.case_events.append(
            {"kind": "local_batch_cancel_requested", "refs": list(self._cancel_refs)}
        )
        batch_cancel = getattr(self.broker, "batch_cancel", None)
        if callable(batch_cancel):
            batch_cancel([self._orders_by_ref[ref] for ref in self._cancel_refs])
        else:
            for ref in self._cancel_refs:
                self.cancel(self._orders_by_ref[ref])
        self.case_reason = "local batch cancellation requested; awaiting terminal statuses"
