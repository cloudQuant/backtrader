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
import logging

from ctpbee.constant import (
    Direction as CTPDirection,
    Offset as CTPOffset,
    OrderType as CTPOrderType,
    Status as CTPStatus,
)

from ..broker import BrokerBase
from ..order import BuyOrder, Order, SellOrder
from ..parameters import BoolParam
from ..position import Position
from ..stores.ctpstore import CTPStore
from ..utils.py3 import queue

logger = logging.getLogger(__name__)


# Registration mechanism, automatically register broker class when module is imported
def _register_ctp_broker_class(broker_cls):
    """Register broker class with the store when module is loaded"""
    CTPStore.BrokerCls = broker_cls
    return broker_cls


# Map backtrader Order exec types to CTP order types
_BT_TO_CTP_ORDERTYPE = {
    Order.Market: CTPOrderType.MARKET,
    Order.Limit: CTPOrderType.LIMIT,
    Order.Stop: CTPOrderType.STOP,
    None: CTPOrderType.MARKET,
}

# Map CTP Status to backtrader Order status
_CTP_STATUS_MAP = {
    CTPStatus.SUBMITTING: Order.Submitted,
    CTPStatus.NOTTRADED: Order.Accepted,
    CTPStatus.PARTTRADED: Order.Partial,
    CTPStatus.ALLTRADED: Order.Completed,
    CTPStatus.CANCELLED: Order.Canceled,
    CTPStatus.REJECTED: Order.Rejected,
}


@_register_ctp_broker_class
class CTPBroker(BrokerBase):
    """Broker implementation for CTP futures trading.

    Maps backtrader orders to CTP orders via ctpbee. Supports:
    - Market and limit orders
    - Order status tracking via CTP event callbacks
    - Position management with long/short offset handling
    - Account balance queries

    Params:
      - `use_positions` (default:`True`): Use existing positions on start.
    """

    # Parameter definition
    use_positions = BoolParam(default=True, doc="Use existing positions to kickstart the broker")

    def __init__(self, **kwargs):
        """Initialize CTPBroker with CTP store connection.

        Args:
            **kwargs: Keyword arguments passed to CTPStore and parent class.
        """
        super().__init__(**kwargs)
        self.o = CTPStore(**kwargs)

        self.orders = collections.OrderedDict()  # bt order ref -> Order
        self.open_orders = []  # list of open Order objects
        self.notifs = collections.deque()  # holds orders which are notified
        self._ctp_to_bt = {}  # ctp_order_id -> bt order ref

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
            if not positions:
                return
            for p in positions:
                # Determine direction string from dict or object
                if isinstance(p, dict):
                    direction = p.get("direction", "")
                    volume = p.get("volume", 0)
                    price = p.get("price", 0)
                    local_sym = p.get("local_symbol", "")
                else:
                    direction = getattr(p, 'direction', '')
                    volume = getattr(p, 'volume', 0)
                    price = getattr(p, 'price', 0)
                    local_sym = getattr(p, 'local_symbol', '')

                if hasattr(direction, 'value'):
                    direction = direction.value

                size = volume if direction in ("long", "多", "LONG") else -volume
                final_size = self.positions[local_sym].size + size
                # Price: use this direction's price if net matches
                final_price = 0
                if final_size < 0:
                    if direction in ("short", "空", "SHORT"):
                        final_price = price
                    else:
                        final_price = self.positions[local_sym].price
                else:
                    if direction in ("short", "空", "SHORT"):
                        final_price = self.positions[local_sym].price
                    else:
                        final_price = price
                self.positions[local_sym] = Position(final_size, final_price)

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
        """Create and submit a buy order to CTP."""
        return self._submit_order(
            owner, data, Order.Buy, size, price, plimit, exectype, valid,
            tradeid, oco, trailamount, trailpercent, **kwargs
        )

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
        """Create and submit a sell order to CTP."""
        return self._submit_order(
            owner, data, Order.Sell, size, price, plimit, exectype, valid,
            tradeid, oco, trailamount, trailpercent, **kwargs
        )

    def cancel(self, order):
        """Cancel an open order."""
        ctp_id = getattr(order, '_ctp_order_id', None)
        if ctp_id is None:
            logger.warning(f"[CTPBroker] No CTP order ID for order ref={order.ref}")
            return order

        symbol = order.data.p.dataname
        success = self.o.cancel_order(symbol, ctp_id)
        if not success:
            logger.warning(f"[CTPBroker] Cancel request failed for {ctp_id}")
        return order

    def _submit_order(
        self, owner, data, ordtype, size, price, plimit, exectype, valid,
        tradeid, oco, trailamount, trailpercent, **kwargs
    ):
        """Internal method to create a backtrader Order and submit to CTP."""
        # Remove parent/transmit if present (from bracket orders)
        kwargs.pop('parent', None)
        kwargs.pop('transmit', None)

        # Create the backtrader order object
        if ordtype == Order.Buy:
            order = BuyOrder(
                owner=owner, data=data, size=size, price=price,
                pricelimit=plimit, exectype=exectype, valid=valid,
                tradeid=tradeid, oco=oco, trailamount=trailamount,
                trailpercent=trailpercent,
            )
        else:
            order = SellOrder(
                owner=owner, data=data, size=size, price=price,
                pricelimit=plimit, exectype=exectype, valid=valid,
                tradeid=tradeid, oco=oco, trailamount=trailamount,
                trailpercent=trailpercent,
            )

        # Store the order
        self.orders[order.ref] = order
        order.submit(self)
        self.notify(order)

        # Determine CTP direction and offset
        symbol = data.p.dataname
        pos = self.positions[data._dataname]
        ctp_order_type = _BT_TO_CTP_ORDERTYPE.get(exectype, CTPOrderType.LIMIT)
        order_price = price if price else 0.0

        if ordtype == Order.Buy:
            if pos.size < 0:
                # Closing short position
                direction = CTPDirection.LONG
                offset = CTPOffset.CLOSE
            else:
                # Opening long position
                direction = CTPDirection.LONG
                offset = CTPOffset.OPEN
        else:  # Sell
            if pos.size > 0:
                # Closing long position
                direction = CTPDirection.SHORT
                offset = CTPOffset.CLOSE
            else:
                # Opening short position
                direction = CTPDirection.SHORT
                offset = CTPOffset.OPEN

        # Submit to CTP
        ctp_order_id = self.o.send_order(
            symbol=symbol,
            direction=direction,
            offset=offset,
            order_type=ctp_order_type,
            volume=abs(size),
            price=order_price,
        )

        if ctp_order_id is None:
            # Submission failed
            order.reject(self)
            self.notify(order)
            return order

        # Map CTP order ID to backtrader order ref
        order._ctp_order_id = ctp_order_id
        self._ctp_to_bt[ctp_order_id] = order.ref
        self.open_orders.append(order)

        # Mark accepted
        order.accept()
        self.notify(order)
        return order

    def _process_order_events(self):
        """Process order status updates from CTP order queue."""
        while True:
            try:
                ctp_order = self.o.order_queue.get_nowait()
            except queue.Empty:
                break

            ctp_id = ctp_order.order_id if hasattr(ctp_order, 'order_id') else None
            if ctp_id is None:
                continue

            # Find the corresponding backtrader order
            # CTP order_id might be local_order_id
            bt_ref = self._ctp_to_bt.get(ctp_id)
            if hasattr(ctp_order, 'local_order_id'):
                bt_ref = bt_ref or self._ctp_to_bt.get(ctp_order.local_order_id)

            if bt_ref is None:
                logger.debug(f"[CTPBroker] Unknown CTP order_id: {ctp_id}")
                continue

            order = self.orders.get(bt_ref)
            if order is None:
                continue

            status = ctp_order.status if hasattr(ctp_order, 'status') else None
            bt_status = _CTP_STATUS_MAP.get(status)

            if bt_status == Order.Canceled:
                order.cancel()
                self.notify(order)
                if order in self.open_orders:
                    self.open_orders.remove(order)
            elif bt_status == Order.Rejected:
                order.reject(self)
                self.notify(order)
                if order in self.open_orders:
                    self.open_orders.remove(order)

    def _process_trade_events(self):
        """Process trade fill events from CTP trade queue."""
        while True:
            try:
                ctp_trade = self.o.trade_queue.get_nowait()
            except queue.Empty:
                break

            ctp_id = ctp_trade.order_id if hasattr(ctp_trade, 'order_id') else None
            if ctp_id is None:
                continue

            bt_ref = self._ctp_to_bt.get(ctp_id)
            if hasattr(ctp_trade, 'local_order_id'):
                bt_ref = bt_ref or self._ctp_to_bt.get(ctp_trade.local_order_id)

            if bt_ref is None:
                logger.debug(f"[CTPBroker] Trade for unknown order_id: {ctp_id}")
                continue

            order = self.orders.get(bt_ref)
            if order is None:
                continue

            # Extract fill info
            fill_price = ctp_trade.price if hasattr(ctp_trade, 'price') else 0.0
            fill_size = ctp_trade.volume if hasattr(ctp_trade, 'volume') else 0.0

            # Execute the fill on the order
            order.execute(
                dt=order.data.datetime[0],
                size=fill_size if order.isbuy() else -fill_size,
                price=fill_price,
                closed=0,
                closedvalue=0.0,
                closedcomm=0.0,
                opened=fill_size,
                openedvalue=fill_size * fill_price,
                openedcomm=0.0,
                margin=0.0,
                pnl=0.0,
                psize=self.positions[order.data._dataname].size,
                pprice=self.positions[order.data._dataname].price,
            )

            # Update position
            psize = fill_size if order.isbuy() else -fill_size
            self.positions[order.data._dataname] = Position(
                self.positions[order.data._dataname].size + psize,
                fill_price,
            )

            # Check if order is fully filled
            if order.executed.remsize == 0:
                order.completed()
                if order in self.open_orders:
                    self.open_orders.remove(order)
            else:
                order.partial()

            self.notify(order)

    def next(self):
        """Process pending order/trade events from CTP each iteration."""
        # Update balance
        self.o.get_balance()

        # Process CTP events
        self._process_order_events()
        self._process_trade_events()

        self.notifs.append(None)  # mark notification boundary
