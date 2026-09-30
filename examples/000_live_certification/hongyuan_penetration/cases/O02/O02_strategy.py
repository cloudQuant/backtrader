"""Offline O02 strategy for bounded repeated close-order intents."""

import backtrader as bt


class O02Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = (
            "waiting for a local repeated close-order observation"
            if self.p.allow_orders is True
            else "offline order actions are disabled"
        )
        self.bars_seen = 0
        self.order_refs = []
        self.order_statuses = {}
        self._target = self._integer("repeat_count", 3, 2, 5)
        self._rounds_canceled = 0
        self._seed_order = None
        self._current_order = None
        self._current_ref = None
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
        if order.ref == getattr(self._seed_order, "ref", None):
            if status == "Completed":
                self.case_reason = (
                    "bounded local setup position filled; awaiting repeated close requests"
                )
            elif status in ("Rejected", "Margin", "Expired", "Canceled"):
                self._failed = True
                self.case_reason = "bounded local setup position reached {}".format(status.lower())
            return
        if order.ref != self._current_ref:
            return
        if status == "Canceled" and self._cancel_requested:
            if order.executed.size == 0:
                self._rounds_canceled += 1
                self.case_events.append(
                    {
                        "kind": "local_repeat_close_canceled",
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
                        "{} identical local close orders were accepted and canceled".format(
                            self._rounds_canceled
                        )
                    )
            else:
                self._failed = True
                self.case_reason = "a repeated local close order filled before cancellation"
        elif status in ("Completed", "Rejected", "Margin", "Expired"):
            self._failed = True
            self.case_reason = "repeated local close order reached {}".format(status.lower())

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
                    "local repeated close order canceled; awaiting its terminal status"
                )
            return
        if self._rounds_canceled >= self._target:
            return
        position = float(self.getposition(self.data).size)
        if position == 0:
            if self._seed_order is None:
                seed_size = self._integer("seed_position_size", 1, 1, 5)
                self._seed_order = self.buy(size=seed_size, exectype=bt.Order.Market)
                if self._seed_order is not None:
                    self.order_refs.append(self._seed_order.ref)
                    self.case_events.append(
                        {
                            "kind": "local_setup_position_submitted",
                            "ref": self._seed_order.ref,
                            "side": "buy_market",
                            "size": seed_size,
                            "offline_only": True,
                        }
                    )
                    self.case_reason = (
                        "bounded local setup order submitted; awaiting fill before repeated closes"
                    )
                else:
                    self._failed = True
                    self.case_reason = "offline broker did not return a local setup order"
            return
        size = min(abs(position), self._number("close_size", 1.0))
        if size <= 0:
            self.case_reason = "configured close size is not positive"
            return
        reference = float(self.data.close[0])
        offset = self._number("price_offset", 20.0)
        if position > 0:
            side = "sell_close"
            price = max(reference + offset, 0.01)
            self._current_order = self.sell(
                size=size, exectype=bt.Order.Limit, price=price, offset="close"
            )
        else:
            side = "buy_close"
            price = max(reference - offset, 0.01)
            self._current_order = self.buy(
                size=size, exectype=bt.Order.Limit, price=price, offset="close"
            )
        if self._current_order is not None:
            self._current_ref = self._current_order.ref
            self.order_refs.append(self._current_ref)
            self.case_events.append(
                {
                    "kind": "local_close_order_submitted",
                    "ref": self._current_ref,
                    "side": side,
                    "size": size,
                    "position_before": position,
                    "repeat_index": self._rounds_canceled + 1,
                }
            )
            self.case_reason = "local repeated close intent submitted; awaiting acceptance"
