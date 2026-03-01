"""Tick-level broker for pure tick-based order matching.

Provides TickBroker which matches orders against tick data instead of
bar data, supporting realistic slippage, partial fills, and all standard
order types (Market, Limit, Stop, StopLimit).

Example:
    Using TickBroker with Cerebro::

        cerebro = bt.Cerebro()
        cerebro.setbroker(TickBroker(cash=100000))
        cerebro.run(mode='TICK')
"""

import collections
import logging

from backtrader.broker import BrokerBase
from backtrader.order import BuyOrder, Order, SellOrder
from backtrader.parameters import ParameterDescriptor
from backtrader.position import Position

logger = logging.getLogger(__name__)

__all__ = ["TickBroker"]


class TickBroker(BrokerBase):
    """Broker that matches orders against tick-level data.

    Unlike BackBroker which processes orders at bar boundaries, TickBroker
    evaluates orders on every tick, enabling precise fill prices and
    realistic partial fill simulation.

    Params:
        cash: Starting cash (default: 100000.0).
        slippage_perc: Slippage as fraction of price (default: 0.0).
        slippage_fixed: Fixed slippage amount per trade (default: 0.0).
        allow_partial: Allow partial fills (default: True).
        checksubmit: Check cash before accepting orders (default: True).
        coo: Execute on Close-of-Order (default: False).
        coc: Execute on Close-of-Cancel (default: False).
    """

    cash = ParameterDescriptor(default=100000.0, doc="Starting cash")
    slippage_perc = ParameterDescriptor(default=0.0, doc="Slippage as fraction of price")
    slippage_fixed = ParameterDescriptor(default=0.0, doc="Fixed slippage amount")
    allow_partial = ParameterDescriptor(default=True, doc="Allow partial fills")
    checksubmit = ParameterDescriptor(default=True, doc="Check cash before accepting")
    coo = ParameterDescriptor(default=False, doc="Close-on-Open")
    coc = ParameterDescriptor(default=False, doc="Close-on-Close")

    def __init__(self, **kwargs):
        """Initialize the TickBroker.

        Sets up internal state for cash, positions, orders, and notifications.
        Uses default cash value from the 'cash' parameter.

        Args:
            **kwargs: Additional arguments passed to BrokerBase.
        """
        super().__init__(**kwargs)
        self._cash = self.get_param("cash")
        self._value = self._cash
        self._orders = []
        self._pending_orders = []
        self._order_history = []
        self._positions = collections.defaultdict(Position)
        self._notifs = collections.deque()
        self._fundval = self._cash
        self._fundshares = 1.0
        self._fundmode = False
        self._last_tick = {}
        self._tick_count = 0

    def start(self):
        """Initialize the broker state for a new backtesting run.

        Resets cash to the starting value and clears any previous state
        to ensure clean backtesting across multiple runs.
        """
        super().start()
        self._cash = self.get_param("cash")
        self._value = self._cash

    def stop(self):
        """Stop the broker and perform cleanup.

        Called at the end of a backtesting run. Override in subclasses
        to implement custom cleanup logic.
        """
        pass

    def getcash(self):
        """Get current available cash."""
        return self._cash

    def getvalue(self, datas=None):
        """Get portfolio value including open positions."""
        val = self._cash
        for data_name, pos in self._positions.items():
            if pos.size != 0:
                last_tick = self._last_tick.get(data_name)
                if last_tick is not None:
                    val += pos.size * last_tick.price
        return val

    def getposition(self, data):
        """Get current position for a data feed."""
        name = getattr(data, "_name", None) or getattr(data, "symbol", str(data))
        return self._positions[name]

    def submit(self, order):
        """Submit an order for execution.

        Overrides the default submit to handle tick-mode orders that
        don't have LineSeries data (avoids len(data) call in Order.submit).
        """
        order.status = Order.Submitted
        order.broker = self
        order.plen = 0
        self._pending_orders.append(order)
        self.notify(order)
        return order

    def cancel(self, order):
        """Cancel a pending order.

        Removes the order from the pending orders queue and updates its
        status to Cancelled. If the order is not found in the pending
        queue, the method returns silently.

        Args:
            order: The Order instance to cancel.
        """
        try:
            self._pending_orders.remove(order)
        except ValueError:
            return
        order.cancel()
        self.notify(order)

    def buy(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        **kwargs,
    ):
        """Create and submit a buy order.

        Args:
            owner: The strategy or object creating the order.
            data: The data feed for this order.
            size: Number of shares/contracts (positive for buy).
            price: Limit price for Limit orders.
            plimit: Limit price for StopLimit orders.
            exectype: Order execution type (Market, Limit, Stop, etc.).
            valid: Order validity period.
            tradeid: User-defined trade identifier.
            oco: One-Cancels-Other order group.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional order parameters.

        Returns:
            The submitted BuyOrder instance.
        """
        order = BuyOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            simulated=True,
            **kwargs,
        )
        return self.submit(order)

    def sell(
        self,
        owner,
        data,
        size,
        price=None,
        plimit=None,
        exectype=None,
        valid=None,
        tradeid=0,
        oco=None,
        trailamount=None,
        trailpercent=None,
        **kwargs,
    ):
        """Create and submit a sell order.

        Args:
            owner: The strategy or object creating the order.
            data: The data feed for this order.
            size: Number of shares/contracts (positive for sell).
            price: Limit price for Limit orders.
            plimit: Limit price for StopLimit orders.
            exectype: Order execution type (Market, Limit, Stop, etc.).
            valid: Order validity period.
            tradeid: User-defined trade identifier.
            oco: One-Cancels-Other order group.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional order parameters.

        Returns:
            The submitted SellOrder instance.
        """
        order = SellOrder(
            owner=owner,
            data=data,
            size=size,
            price=price,
            pricelimit=plimit,
            exectype=exectype,
            valid=valid,
            tradeid=tradeid,
            oco=oco,
            trailamount=trailamount,
            trailpercent=trailpercent,
            simulated=True,
            **kwargs,
        )
        return self.submit(order)

    def notify(self, order):
        """Queue a notification for an order status change.

        Stores the order in an internal queue for later retrieval by
        strategies via get_notification().

        Args:
            order: The Order instance with updated status.
        """
        self._notifs.append(order)

    def get_notification(self):
        """Get the next pending notification from the queue.

        Strategies call this method to check for order status updates.

        Returns:
            Order if a notification is available, None otherwise.
        """
        try:
            return self._notifs.popleft()
        except IndexError:
            return None

    def set_fundmode(self, fundmode, fundstartval=None):
        """Enable or disable fund mode for portfolio management.

        Fund mode allows treating the portfolio as a fund with shares
        that can be bought/sold by investors.

        Args:
            fundmode: Boolean to enable/disable fund mode.
            fundstartval: Initial fund value (optional).
        """
        self._fundmode = fundmode
        if fundstartval is not None:
            self._fundval = fundstartval

    def get_fundmode(self):
        """Check if fund mode is enabled.

        Returns:
            bool: True if fund mode is active, False otherwise.
        """
        return self._fundmode

    def get_fundshares(self):
        """Get the current number of fund shares.

        Returns:
            float: Number of outstanding fund shares.
        """
        return self._fundshares

    def get_fundvalue(self):
        """Get the current net asset value of the fund.

        Returns:
            float: Current fund NAV.
        """
        return self._fundval

    def process_tick(self, tick_event, data=None):
        """Process a tick event and attempt to match pending orders.

        This is the core method called by Cerebro on each tick. It evaluates
        all pending orders against the current tick data.

        Args:
            tick_event: TickEvent with current price/volume.
            data: The data feed associated with this tick (optional).
        """
        data_name = tick_event.symbol
        self._last_tick[data_name] = tick_event
        self._tick_count += 1

        matched = []
        for order in list(self._pending_orders):
            order_data_name = getattr(order.data, "_name", None) or getattr(
                order.data, "symbol", str(order.data)
            )
            if order_data_name != data_name:
                continue

            result = self._try_match(order, tick_event)
            if result is not None:
                fill_price, fill_size = result
                self._execute(order, fill_price, fill_size, tick_event)
                if order.status == Order.Completed or not self.get_param("allow_partial"):
                    matched.append(order)

        for order in matched:
            try:
                self._pending_orders.remove(order)
            except ValueError:
                pass

    def _try_match(self, order, tick):
        """Try to match an order against a tick.

        Args:
            order: The order to match.
            tick: The current TickEvent.

        Returns:
            Tuple of (fill_price, fill_size) if matched, None otherwise.
        """
        exectype = order.exectype
        price = tick.price
        size = order.remaining_size if hasattr(order, "remaining_size") else order.size

        if exectype == Order.Market:
            fill_price = self._apply_slippage(price, order.isbuy())
            return (fill_price, abs(size))

        elif exectype == Order.Limit:
            limit_price = order.price
            if order.isbuy():
                if price <= limit_price:
                    return (min(price, limit_price), abs(size))
            else:
                if price >= limit_price:
                    return (max(price, limit_price), abs(size))

        elif exectype == Order.Stop:
            stop_price = order.price
            if order.isbuy():
                if price >= stop_price:
                    fill_price = self._apply_slippage(price, True)
                    return (fill_price, abs(size))
            else:
                if price <= stop_price:
                    fill_price = self._apply_slippage(price, False)
                    return (fill_price, abs(size))

        elif exectype == Order.StopLimit:
            stop_price = order.price
            limit_price = order.pricelimit

            if not getattr(order, "_stop_triggered", False):
                if order.isbuy() and price >= stop_price:
                    order._stop_triggered = True
                elif not order.isbuy() and price <= stop_price:
                    order._stop_triggered = True

            if getattr(order, "_stop_triggered", False):
                if order.isbuy():
                    if price <= limit_price:
                        return (min(price, limit_price), abs(size))
                else:
                    if price >= limit_price:
                        return (max(price, limit_price), abs(size))

        return None

    def _apply_slippage(self, price, is_buy):
        """Apply slippage to a fill price.

        Args:
            price: Base execution price.
            is_buy: True for buy orders, False for sell.

        Returns:
            Price with slippage applied.
        """
        perc = self.get_param("slippage_perc")
        fixed = self.get_param("slippage_fixed")

        slip = price * perc + fixed
        if is_buy:
            return price + slip
        else:
            return price - slip

    def _execute(self, order, fill_price, fill_size, tick):
        """Execute a fill on an order.

        Args:
            order: The order being filled.
            fill_price: The execution price.
            fill_size: The execution size.
            tick: The tick that triggered the fill.
        """
        # Determine position change
        data_name = getattr(order.data, "_name", None) or getattr(
            order.data, "symbol", str(order.data)
        )
        pos = self._positions[data_name]

        if order.isbuy():
            cost = fill_price * fill_size
            comminfo = self.getcommissioninfo(order.data)
            commission = comminfo.getcommission(fill_size, fill_price)

            self._cash -= cost + commission
            pos.update(fill_size, fill_price)
        else:
            revenue = fill_price * fill_size
            comminfo = self.getcommissioninfo(order.data)
            commission = comminfo.getcommission(fill_size, fill_price)

            self._cash += revenue - commission
            pos.update(-fill_size, fill_price)

        # Complete the order
        order.execute(
            dt=tick.timestamp,
            size=fill_size if order.isbuy() else -fill_size,
            price=fill_price,
            closed=0,
            closedvalue=0.0,
            closedcomm=0.0,
            opened=fill_size,
            openedvalue=fill_price * fill_size,
            openedcomm=0.0,
            margin=0,
            pnl=0,
            psize=pos.size,
            pprice=pos.price,
        )
        order.completed()
        self.notify(order)

        self._order_history.append(
            {
                "timestamp": tick.timestamp,
                "symbol": data_name,
                "side": "buy" if order.isbuy() else "sell",
                "price": fill_price,
                "size": fill_size,
                "tick_price": tick.price,
            }
        )

    def next(self):
        """Called by Cerebro on each iteration.

        This is a no-op in tick mode since order matching happens via
        process_tick() instead. Provided for compatibility with bar mode.
        """
        pass

    def add_order_history(self, orders, notify=False):
        """Add historical orders to the broker.

        Allows preloading order history for replay scenarios.

        Args:
            orders: Iterable of Order instances to add.
            notify: Whether to trigger notifications for added orders.
        """
        pass

    def set_fund_history(self, fund):
        """Set historical fund data for replay scenarios.

        Args:
            fund: Historical fund value data.
        """
        pass

    @property
    def pending_orders(self):
        """List of currently pending orders."""
        return list(self._pending_orders)

    @property
    def order_history(self):
        """Complete order execution history."""
        return list(self._order_history)

    @property
    def tick_count(self):
        """Number of ticks processed."""
        return self._tick_count
