"""Offline B01 strategy for partial fills followed by batch cancellation."""

import backtrader as bt


class B01Strategy(bt.Strategy):
    params = (("case_config", None), ("allow_orders", False))

    def __init__(self):
        self.case_events = []
        self.case_observed = False
        self.case_reason = (
            "waiting for local partial fills before batch cancellation"
            if self.p.allow_orders is True
            else "offline order actions are disabled"
        )
        self.bars_seen = 0
        self.order_refs = []
        self.order_statuses = {}
        self._orders_by_ref = {}
        self._requested_sizes = {}
        self._fills = {}
        self._target = self._integer("order_count", 3, 2, 5)
        self._minimum_partials = self._integer("partial_min_count", 2, 1, self._target)
        self._max_wait_bars = self._integer("max_wait_bars", 3, 1, 10)
        self._submitted_bar = None
        self._cancel_refs = []
        self._partial_refs_at_cancel = []
        self._cancel_requested = False

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

    def _partial_refs(self):
        return [
            ref
            for ref in self.order_refs
            if self.order_statuses.get(ref) == "Partial"
            and 0 < abs(self._fills.get(ref, 0)) < self._requested_sizes.get(ref, 0)
        ]

    def _maybe_finish(self):
        if not self._cancel_requested or not self._cancel_refs:
            return
        terminal = ("Canceled", "Completed", "Rejected", "Margin", "Expired")
        if not all(self.order_statuses.get(ref) in terminal for ref in self._cancel_refs):
            return
        all_canceled = all(self.order_statuses.get(ref) == "Canceled" for ref in self._cancel_refs)
        partials_still_partial = all(
            0 < abs(self._fills.get(ref, 0)) < self._requested_sizes.get(ref, 0)
            for ref in self._partial_refs_at_cancel
        )
        if (
            all_canceled
            and len(self._partial_refs_at_cancel) >= self._minimum_partials
            and partials_still_partial
        ):
            self.case_observed = True
            self.case_reason = (
                "{} locally partial orders were included in batch cancellation".format(
                    len(self._partial_refs_at_cancel)
                )
            )
        elif all_canceled:
            self.case_reason = (
                "local orders were cleaned up without the required partial-fill count"
            )
        else:
            self.case_reason = "local batch cleanup ended with a fill or non-cancel terminal status"

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
        self._maybe_finish()

    def notify_store(self, msg, *args, **kwargs):
        # This local smoke does not consume store notifications.
        pass

    def next(self):
        self.bars_seen += 1
        if self.p.allow_orders is not True or self.case_observed:
            return
        if not self.order_refs:
            size = self._integer("order_size", 3, 2, 20)
            offset = self._number("price_offset", 0.5)
            reference = float(self.data.close[0])
            for index in range(self._target):
                price = max(reference - offset - index * 0.01, 0.01)
                order = self.buy(size=size, exectype=bt.Order.Limit, price=price, offset="open")
                if order is None:
                    continue
                self.order_refs.append(order.ref)
                self._orders_by_ref[order.ref] = order
                self._requested_sizes[order.ref] = size
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
            self._submitted_bar = self.bars_seen
            self.case_reason = "{} local orders submitted; waiting for partial fills".format(
                len(self.order_refs)
            )
            return
        if self._cancel_requested:
            self._maybe_finish()
            return
        if len(self.order_refs) != self._target or not all(
            self.order_statuses.get(ref) is not None for ref in self.order_refs
        ):
            return
        partial_refs = self._partial_refs()
        timed_out = self.bars_seen - self._submitted_bar >= self._max_wait_bars
        if len(partial_refs) < self._minimum_partials and not timed_out:
            self.case_reason = "waiting for at least {} local partial fills".format(
                self._minimum_partials
            )
            return
        self._cancel_refs = [
            ref
            for ref in self.order_refs
            if self.order_statuses.get(ref) in ("Accepted", "Partial")
        ]
        self._partial_refs_at_cancel = [ref for ref in partial_refs if ref in self._cancel_refs]
        if not self._cancel_refs:
            self.case_reason = "no local open orders remained to cancel"
            return
        self._cancel_requested = True
        self.case_events.append(
            {
                "kind": "local_batch_cancel_requested",
                "refs": list(self._cancel_refs),
                "partial_refs": list(self._partial_refs_at_cancel),
            }
        )
        batch_cancel = getattr(self.broker, "batch_cancel", None)
        if callable(batch_cancel):
            batch_cancel([self._orders_by_ref[ref] for ref in self._cancel_refs])
        else:
            for ref in self._cancel_refs:
                self.cancel(self._orders_by_ref[ref])
        self.case_reason = "local batch cancellation requested; awaiting terminal statuses"
