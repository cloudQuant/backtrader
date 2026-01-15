"""CTP Broker Module - CTP futures broker implementation.

This module provides the CTPBroker for trading through CTP (China
Futures) for futures trading.

Classes:
    CTPBroker: Broker implementation for CTP futures trading.

Functions:
    _register_ctp_broker_class: Registers broker with store.

Example:
    >>> store = bt.stores.CTPStore(
    ...     userid='your_id',
    ...     password='your_password'
    ... )
    >>> cerebro.setbroker(store.getbroker())
"""

import collections

from ..broker import BrokerBase
from ..parameters import BoolParam
from ..position import Position
from ..stores.ctpstore import CTPStore


# Registration mechanism, automatically register broker class when module is imported
def _register_ctp_broker_class(broker_cls):
    """Register broker class with the store when module is loaded"""
    CTPStore.BrokerCls = broker_cls
    return broker_cls


@_register_ctp_broker_class
class CTPBroker(BrokerBase):
    """Broker implementation for ctp

    This class maps the orders/positions from MetaTrader to the
    internal API of `backtrader`.

    Params:

      - `Use_positions` (default:`False`): When connecting to the broker
        provider use the existing positions to kickstart the broker.

        Set to `False` during instantiation to disregard any existing
        position
    """

    # Parameter definition - converted to ParameterDescriptor system
    use_positions = BoolParam(default=True, doc="Use existing positions to kickstart the broker")

    def __init__(self, **kwargs):
        """Initialize CTPBroker with CTP store connection.

        Args:
            **kwargs: Keyword arguments passed to CTPStore and parent class.
        """
        super().__init__(**kwargs)
        self.o = CTPStore(**kwargs)

        self.orders = collections.OrderedDict()  # orders by order id
        self.notifs = collections.deque()  # holds orders which are notified

        self.startingcash = self.cash = 0.0
        self.startingvalue = self.value = 0.0
        self.positions = collections.defaultdict(Position)

    def start(self):
        """Start the broker and initialize account state.

        Retrieves initial balance and existing positions from the CTP broker.
        """
        super().start()
        # Get balance on start
        self.o.get_balance()
        self.startingcash = self.cash = self.o.get_cash()
        self.startingvalue = self.value = self.o.get_value()

        if self.get_param("use_positions"):
            positions = self.o.get_positions()
            if positions is None:
                return
            for p in positions:  # Same symbol may have one long and one short position record
                size = (
                    p["volume"] if p["direction"] == "long" else -p["volume"]
                )  # Short position is negative
                price = p[
                    "price"
                ]  # Write later, handling long and short positions simultaneously is slightly more complex
                final_size = (
                    self.positions[p["local_symbol"]].size + size
                )  # Set local net position size (after loop it's net position, because long and short have been offset)
                # Below handles position price, after loop, if net position > 0, net position price is remote long position price (average price), otherwise short position price.
                # So, if remote has both long and short positions, this price is not the average of long and short (cannot be defined). But if remote doesn't have both long and short, this price is correct, as average position price
                final_price = 0
                if final_size < 0:
                    if p["direction"] == "short":
                        final_price = price
                    else:
                        final_price = self.positions[p["local_symbol"]].price
                else:
                    if p["direction"] == "short":
                        final_price = self.positions[p["local_symbol"]].price
                    else:
                        final_price = price
                # Loop
                self.positions[p["local_symbol"]] = Position(final_size, final_price)

    def stop(self):
        """Stop the broker and release CTP connection."""
        super().stop()
        self.o.stop()

    def getcash(self):
        """Get current cash balance.

        Returns:
            float: Current available cash.
        """
        self.cash = self.o.get_cash()
        return self.cash

    def getvalue(self):
        """Get current portfolio value.

        Returns:
            float: Current portfolio value including cash and positions.
        """
        self.value = self.o.get_value()
        return self.value

    def getposition(self, data, clone=True):
        """Get position for a data feed.

        Args:
            data: Data feed object.
            clone: If True, return a cloned copy of the position.

        Returns:
            Position: Position object for the specified data feed.
        """
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    def orderstatus(self, order):
        """Get the status of an order.

        Args:
            order: Order object.

        Returns:
            Order.Status: The current status of the order.
        """
        o = self.orders[order.ref]
        return o.status

    def _submit(self, oref):
        """Submit an order to the broker.

        Args:
            oref: Order reference ID.
        """
        order = self.orders[oref]
        order.submit(self)
        self.notify(order)

    def _reject(self, oref):
        """Reject an order.

        Args:
            oref: Order reference ID.
        """
        order = self.orders[oref]
        order.reject(self)
        self.notify(order)

    def _accept(self, oref):
        """Accept an order.

        Args:
            oref: Order reference ID.
        """
        order = self.orders[oref]
        order.accept()
        self.notify(order)

    def _cancel(self, oref):
        """Cancel an order.

        Args:
            oref: Order reference ID.
        """
        order = self.orders[oref]
        order.cancel()
        self.notify(order)

    def _expire(self, oref):
        """Mark an order as expired.

        Args:
            oref: Order reference ID.
        """
        order = self.orders[oref]
        order.expire()
        self.notify(order)

    def notify(self, order):
        """Store order notification for later retrieval.

        Args:
            order: Order object to notify.
        """
        self.notifs.append(order.clone())

    def get_notification(self):
        """Get the next order notification.

        Returns:
            Order or None: The next order notification, or None if no notifications.
        """
        if not self.notifs:
            return None
        return self.notifs.popleft()

    def next(self):
        """Mark notification boundary for each iteration.

        Appends None to separate notifications from different iterations.
        """
        self.notifs.append(None)  # mark notification boundary
