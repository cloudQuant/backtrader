"""Mixed-mode broker for Tick+Bar hybrid order matching.

MixBroker prioritizes tick-level matching when tick data is available,
falling back to bar-level matching when ticks are unavailable or when
a configurable timeout is exceeded.

Example:
    Using MixBroker with Cerebro::

        cerebro = bt.Cerebro()
        cerebro.setbroker(MixBroker(cash=100000, tick_timeout=5.0))
        cerebro.run(mode='MIXED')
"""

import logging

from backtrader.brokers.tickbroker import TickBroker
from backtrader.order import Order
from backtrader.parameters import ParameterDescriptor

logger = logging.getLogger(__name__)

__all__ = ["MixBroker"]


class MixBroker(TickBroker):
    """Broker for mixed Tick+Bar mode with Tick-first matching.

    Inherits all tick-matching logic from TickBroker and adds bar-level
    fallback for orders that haven't been matched within a configurable
    timeout window.

    Params:
        tick_timeout: Seconds to wait for tick match before bar fallback (default: 5.0).
        bar_fallback: Whether to enable bar-level fallback (default: True).
    """

    tick_timeout = ParameterDescriptor(default=5.0, doc="Tick match timeout before bar fallback")
    bar_fallback = ParameterDescriptor(default=True, doc="Enable bar-level fallback matching")

    def __init__(self, **kwargs):
        """Initialize the MixBroker.

        Sets up tracking for order submission timestamps to enable
        timeout-based fallback to bar-level matching.

        Args:
            **kwargs: Additional arguments passed to TickBroker.
        """
        super().__init__(**kwargs)
        self._order_submit_ts = {}
        self._bar_matched_orders = set()

    def start(self):
        super().start()
        self._order_submit_ts = {}
        self._bar_matched_orders = set()

    def submit(self, order):
        """Submit an order to the broker and record its submission timestamp.

        This method overrides the parent submit method to track when orders
        are submitted for timeout-based bar fallback matching. The timestamp
        is recorded as None initially and set to the first tick's timestamp
        when tick processing begins.

        Args:
            order: The Order instance to submit for execution.

        Returns:
            The submitted Order instance.
        """
        result = super().submit(order)
        self._order_submit_ts[id(order)] = None
        return result

    def process_tick(self, tick_event, data=None):
        """Process a tick event and record first-tick timestamp for timeout tracking.

        Delegates to parent TickBroker for order matching and tracks submission
        timestamps to enable timeout-based fallback to bar-level matching.

        Args:
            tick_event: TickEvent with current price/volume.
            data: The data feed associated with this tick (optional).
        """
        _ = tick_event.symbol  # noqa: F841

        # Record submission timestamp on first tick seen
        for order in self._orders_by_symbol.get(tick_event.symbol, []):
            order_id = id(order)
            if order_id in self._order_submit_ts and self._order_submit_ts[order_id] is None:
                self._order_submit_ts[order_id] = tick_event.timestamp

        super().process_tick(tick_event, data)

        # Clean up completed orders from timestamp tracking
        pending_ids = {id(o) for o in self._orders_by_symbol.get(tick_event.symbol, [])}
        stale = [k for k in self._order_submit_ts if k not in pending_ids]
        for k in stale:
            del self._order_submit_ts[k]

    def process_bar(self, bar_event, data=None):
        """Process a bar event and match remaining orders via bar fallback.

        Orders that haven't been matched by ticks within tick_timeout
        are matched against the bar's OHLC data.

        Args:
            bar_event: BarEvent with OHLC data.
            data: The data feed associated with this bar (optional).
        """
        if not self.get_param("bar_fallback"):
            return

        data_name = bar_event.symbol
        timeout = self.get_param("tick_timeout")
        current_ts = bar_event.timestamp
        self._last_event_ts = current_ts
        self._activate_visible_orders(current_ts)

        self._last_tick.setdefault(data_name, bar_event)

        matched = []
        for order in list(self._orders_by_symbol.get(data_name, [])):

            # Check if order has timed out waiting for tick match
            order_id = id(order)
            submit_ts = self._order_submit_ts.get(order_id)

            if submit_ts is not None and (current_ts - submit_ts) < timeout:
                continue

            result = self._try_match_bar(order, bar_event)
            if result is not None:
                fill_price, fill_size = result
                self._execute_bar(order, fill_price, fill_size, bar_event)
                matched.append(order)
                self._bar_matched_orders.add(order_id)

        for order in matched:
            self._remove_pending_order(order)
            self._order_submit_ts.pop(id(order), None)

    def _try_match_bar(self, order, bar):
        """Try to match an order against bar OHLC data.

        Args:
            order: The order to match.
            bar: The BarEvent with OHLC data.

        Returns:
            Tuple of (fill_price, fill_size) or None.
        """
        size = order.remaining_size if hasattr(order, "remaining_size") else order.size
        exectype = order.exectype

        if exectype == Order.Market:
            fill_price = self._apply_slippage(bar.open, order.isbuy())
            return (fill_price, abs(size))

        elif exectype == Order.Limit:
            limit_price = order.price
            if order.isbuy():
                if bar.low <= limit_price:
                    return (limit_price, abs(size))
            else:
                if bar.high >= limit_price:
                    return (limit_price, abs(size))

        elif exectype == Order.Stop:
            stop_price = order.price
            if order.isbuy():
                if bar.high >= stop_price:
                    fill_price = self._apply_slippage(max(bar.open, stop_price), True)
                    return (fill_price, abs(size))
            else:
                if bar.low <= stop_price:
                    fill_price = self._apply_slippage(min(bar.open, stop_price), False)
                    return (fill_price, abs(size))

        elif exectype == Order.StopLimit:
            stop_price = order.price
            limit_price = order.pricelimit

            if not getattr(order, "_stop_triggered", False):
                if order.isbuy() and bar.high >= stop_price:
                    order._stop_triggered = True
                elif not order.isbuy() and bar.low <= stop_price:
                    order._stop_triggered = True

            if getattr(order, "_stop_triggered", False):
                if order.isbuy():
                    if bar.low <= limit_price:
                        return (limit_price, abs(size))
                else:
                    if bar.high >= limit_price:
                        return (limit_price, abs(size))

        return None

    def _execute_bar(self, order, fill_price, fill_size, bar):
        """Execute a fill from bar-level matching.

        Args:
            order: The order being filled.
            fill_price: The execution price.
            fill_size: The execution size.
            bar: The bar that triggered the fill.
        """
        self._execute(order, fill_price, fill_size, bar, source="bar_fallback")

    @property
    def bar_matched_count(self):
        """Number of orders matched via bar fallback."""
        return len(self._bar_matched_orders)
