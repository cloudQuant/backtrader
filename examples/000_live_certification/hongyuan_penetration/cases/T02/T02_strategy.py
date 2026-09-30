"""Offline T02 strategy for a close request against an existing position."""

import backtrader as bt


class T02Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = (
            "waiting for a local close-order observation"
            if self.p.allow_orders is True
            else "offline order actions are disabled"
        )
        self.bars_seen = 0
        self.order_refs = []
        self.order_statuses = {}
        self.order = None
        self.seed_order = None
        self._seed_attempted = False
        self._seed_completed = False
        self._position_before = 0.0
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
            if order.ref == getattr(self.seed_order, "ref", None):
                if status == "Completed":
                    self._seed_completed = True
                    self.case_reason = "bounded local setup position filled; awaiting close request"
                elif status in ("Rejected", "Margin", "Expired", "Canceled"):
                    self.case_reason = "bounded local setup position reached {}".format(
                        status.lower()
                    )
            return
        if status in ("Accepted", "Partial"):
            self._accepted = True
        elif status == "Canceled" and self._accepted and self._cancel_requested:
            self.case_observed = True
            self.case_reason = (
                "local close order against an existing position was accepted and canceled"
            )
        elif status == "Completed" and self._accepted:
            self.case_observed = True
            self.case_reason = "local close order against an existing position completed"
        elif status in ("Rejected", "Margin", "Expired"):
            self.case_reason = "local close order reached {}".format(status.lower())

    def notify_store(self, msg, *args, **kwargs):
        # This local smoke does not consume store notifications.
        pass

    def next(self):
        self.bars_seen += 1
        if self.p.allow_orders is not True or self.case_observed:
            return
        if self.order is not None:
            status = self.order_statuses.get(self.order.ref)
            if status in ("Accepted", "Partial") and not self._cancel_requested:
                self._accepted = True
                self._cancel_requested = True
                self.cancel(self.order)
                self.case_events.append({"kind": "local_cancel_requested", "ref": self.order.ref})
                self.case_reason = "local close order cancel requested; awaiting terminal status"
            elif status == "Canceled" and self._accepted and self._cancel_requested:
                self.case_observed = True
                self.case_reason = (
                    "local close order against an existing position was accepted and canceled"
                )
            return

        position = float(self.getposition(self.data).size)
        if position == 0:
            if self.seed_order is None and not self._seed_attempted:
                size = self._integer("seed_position_size", 1, 1, 5)
                self.seed_order = self.buy(size=size, exectype=bt.Order.Market)
                self._seed_attempted = True
                if self.seed_order is not None:
                    self.order_refs.append(self.seed_order.ref)
                    self.case_events.append(
                        {
                            "kind": "local_setup_position_submitted",
                            "ref": self.seed_order.ref,
                            "side": "buy_market",
                            "size": size,
                            "offline_only": True,
                        }
                    )
                    self.case_reason = (
                        "bounded local setup order submitted; awaiting fill before close request"
                    )
                else:
                    self.case_reason = "offline broker did not return a local setup order"
            elif self._seed_attempted and not self._seed_completed:
                self.case_reason = "waiting for the bounded local setup position to fill"
            else:
                self.case_reason = "no local broker position is available to close"
            return
        configured_size = self._number("close_size", 1.0)
        size = min(abs(position), configured_size)
        if size <= 0:
            self.case_reason = "configured close size is not positive"
            return
        offset = self._number("price_offset", 20.0)
        reference = float(self.data.close[0])
        if position > 0:
            side = "sell_close"
            price = max(reference + offset, 0.01)
            self.order = self.sell(size=size, exectype=bt.Order.Limit, price=price, offset="close")
        else:
            side = "buy_close"
            price = max(reference - offset, 0.01)
            self.order = self.buy(size=size, exectype=bt.Order.Limit, price=price, offset="close")
        if self.order is not None:
            self._position_before = position
            self.order_refs.append(self.order.ref)
            self.case_events.append(
                {
                    "kind": "local_close_order_submitted",
                    "ref": self.order.ref,
                    "side": side,
                    "size": size,
                    "position_before": position,
                }
            )
            self.case_reason = "local close order submitted; awaiting acceptance"
