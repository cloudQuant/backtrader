"""CTP Broker Module - CTP futures broker implementation via ctp-python.

This module provides the CTPBroker for trading through CTP (China
Futures) using the native ctp-python package.

Classes:
    CTPBroker: Broker implementation for CTP futures trading.

Example:
    >>> store = bt.stores.CTPStore(
    ...     user_id='your_id',
    ...     password='your_password'
    ... )
    >>> cerebro.setbroker(store.getbroker())
"""

import collections
import logging

from ..broker import BrokerBase
from ..order import BuyOrder, Order, SellOrder
from ..parameters import BoolParam
from ..position import Position
from ..stores.ctpstore import (
    CTPStore,
    THOST_FTDC_D_Buy,
    THOST_FTDC_D_Sell,
    THOST_FTDC_OF_Open,
    THOST_FTDC_OF_Close,
    THOST_FTDC_OF_CloseToday,
    THOST_FTDC_OF_CloseYesterday,
    THOST_FTDC_OPT_LimitPrice,
    THOST_FTDC_OPT_AnyPrice,
    THOST_FTDC_OST_AllTraded,
    THOST_FTDC_OST_PartTradedQueueing,
    THOST_FTDC_OST_PartTradedNotQueueing,
    THOST_FTDC_OST_NoTradeQueueing,
    THOST_FTDC_OST_NoTradeNotQueueing,
    THOST_FTDC_OST_Canceled,
    THOST_FTDC_OST_Unknown,
)
from ..utils.py3 import queue

logger = logging.getLogger(__name__)


# Registration mechanism
def _register_ctp_broker_class(broker_cls):
    """Register broker class with the store when module is loaded."""
    CTPStore.BrokerCls = broker_cls
    return broker_cls


# Map backtrader Order exec types to CTP order price types
_BT_TO_CTP_ORDERTYPE = {
    Order.Market: THOST_FTDC_OPT_AnyPrice,
    Order.Limit: THOST_FTDC_OPT_LimitPrice,
    None: THOST_FTDC_OPT_LimitPrice,
}

# Map CTP OrderStatus char to backtrader Order status
_CTP_STATUS_MAP = {
    THOST_FTDC_OST_AllTraded: Order.Completed,
    THOST_FTDC_OST_PartTradedQueueing: Order.Partial,
    THOST_FTDC_OST_PartTradedNotQueueing: Order.Partial,
    THOST_FTDC_OST_NoTradeQueueing: Order.Accepted,
    THOST_FTDC_OST_NoTradeNotQueueing: Order.Accepted,
    THOST_FTDC_OST_Canceled: Order.Canceled,
}

# CTP PosiDirection: '2'=Long, '3'=Short
_POSI_LONG = '2'
_POSI_SHORT = '3'


@_register_ctp_broker_class
class CTPBroker(BrokerBase):
    """Broker implementation for CTP futures trading via ctp-python.

    Maps backtrader orders to CTP orders using native CTP API constants.
    Supports market and limit orders, order status tracking via CTP event
    callbacks, position management with open/close offset handling.

    Params:
      - `use_positions` (default:`True`): Use existing positions on start.
    """

    use_positions = BoolParam(default=True, doc="Use existing positions to kickstart the broker")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.o = CTPStore(**kwargs)

        self.orders = collections.OrderedDict()  # bt order ref -> Order
        self.open_orders = []  # list of open Order objects
        self.notifs = collections.deque()
        self._ref_to_bt = {}  # ctp order_ref -> bt order ref

        self.startingcash = self.cash = 0.0
        self.startingvalue = self.value = 0.0
        self.positions = collections.defaultdict(Position)

    def start(self):
        """Start the broker and initialize account state."""
        super().start()
        self.o.get_balance()
        self.startingcash = self.cash = self.o.get_cash()
        self.startingvalue = self.value = self.o.get_value()

        if self.get_param("use_positions"):
            positions = self.o.get_positions()
            if not positions:
                return
            for p in positions:
                instrument = p.get('instrument', '')
                direction = p.get('direction', '')  # '2'=Long, '3'=Short
                volume = p.get('volume', 0)
                avg_price = p.get('avg_price', 0)

                if volume == 0:
                    continue

                size = volume if direction == _POSI_LONG else -volume
                final_size = self.positions[instrument].size + size
                final_price = avg_price if (
                    (final_size > 0 and direction == _POSI_LONG) or
                    (final_size < 0 and direction == _POSI_SHORT)
                ) else self.positions[instrument].price or avg_price
                self.positions[instrument] = Position(final_size, final_price)

    def stop(self):
        """Stop the broker and release CTP connection."""
        super().stop()
        self.o.stop()

    def getcash(self):
        return self.o.get_cash()

    def getvalue(self, datas=None):
        return self.o.get_value()

    def getposition(self, data, clone=True):
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    def orderstatus(self, order):
        o = self.orders.get(order.ref)
        return o.status if o else Order.Rejected

    def notify(self, order):
        self.notifs.append(order.clone())

    def get_notification(self):
        if not self.notifs:
            return None
        return self.notifs.popleft()

    # --- Order creation ---
    def buy(self, owner, data, size, price=None, plimit=None, exectype=None,
            valid=None, tradeid=0, oco=None, trailamount=None,
            trailpercent=None, **kwargs):
        return self._submit_order(
            owner, data, Order.Buy, size, price, plimit, exectype, valid,
            tradeid, oco, trailamount, trailpercent, **kwargs
        )

    def sell(self, owner, data, size, price=None, plimit=None, exectype=None,
             valid=None, tradeid=0, oco=None, trailamount=None,
             trailpercent=None, **kwargs):
        return self._submit_order(
            owner, data, Order.Sell, size, price, plimit, exectype, valid,
            tradeid, oco, trailamount, trailpercent, **kwargs
        )

    def cancel(self, order):
        order_ref = getattr(order, '_ctp_order_ref', None)
        if order_ref is None:
            logger.warning(f"[CTPBroker] No CTP order_ref for order ref={order.ref}")
            return order
        symbol = order.data.p.dataname
        self.o.cancel_order(symbol, order_ref)
        return order

    def _submit_order(self, owner, data, ordtype, size, price, plimit,
                      exectype, valid, tradeid, oco, trailamount,
                      trailpercent, **kwargs):
        """Create a backtrader Order and submit to CTP."""
        kwargs.pop('parent', None)
        kwargs.pop('transmit', None)

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

        self.orders[order.ref] = order
        order.submit(self)
        self.notify(order)

        # Determine CTP direction and offset
        symbol = data.p.dataname
        pos = self.positions[data._dataname]
        ctp_price_type = _BT_TO_CTP_ORDERTYPE.get(exectype, THOST_FTDC_OPT_LimitPrice)
        order_price = price if price else 0.0

        if ordtype == Order.Buy:
            direction = THOST_FTDC_D_Buy
            offset = THOST_FTDC_OF_Close if pos.size < 0 else THOST_FTDC_OF_Open
        else:
            direction = THOST_FTDC_D_Sell
            offset = THOST_FTDC_OF_Close if pos.size > 0 else THOST_FTDC_OF_Open

        # Submit to CTP
        order_ref = self.o.send_order(
            symbol=symbol,
            direction=direction,
            offset=offset,
            price=order_price,
            volume=abs(size),
            order_price_type=ctp_price_type,
        )

        if order_ref is None:
            order.reject(self)
            self.notify(order)
            return order

        order._ctp_order_ref = order_ref
        self._ref_to_bt[order_ref] = order.ref
        self.open_orders.append(order)

        order.accept()
        self.notify(order)
        return order

    # --- Event processing ---
    def _process_order_events(self):
        """Process order status updates from CTP."""
        while True:
            try:
                evt = self.o.order_queue.get_nowait()
            except queue.Empty:
                break

            order_ref = evt.get('order_ref')
            if order_ref is None:
                continue

            bt_ref = self._ref_to_bt.get(order_ref)
            if bt_ref is None:
                continue

            order = self.orders.get(bt_ref)
            if order is None:
                continue

            status = evt.get('status')
            is_rejected = evt.get('rejected', False)

            if is_rejected or status == THOST_FTDC_OST_Canceled:
                if is_rejected:
                    order.reject(self)
                else:
                    order.cancel()
                self.notify(order)
                if order in self.open_orders:
                    self.open_orders.remove(order)

    def _process_trade_events(self):
        """Process trade fill events from CTP."""
        while True:
            try:
                evt = self.o.trade_queue.get_nowait()
            except queue.Empty:
                break

            order_ref = evt.get('order_ref')
            if order_ref is None:
                continue

            bt_ref = self._ref_to_bt.get(order_ref)
            if bt_ref is None:
                logger.debug(f"[CTPBroker] Trade for unknown ref: {order_ref}")
                continue

            order = self.orders.get(bt_ref)
            if order is None:
                continue

            fill_price = evt.get('price', 0.0)
            fill_size = evt.get('volume', 0)

            order.execute(
                dt=order.data.datetime[0],
                size=fill_size if order.isbuy() else -fill_size,
                price=fill_price,
                closed=0, closedvalue=0.0, closedcomm=0.0,
                opened=fill_size,
                openedvalue=fill_size * fill_price,
                openedcomm=0.0, margin=0.0, pnl=0.0,
                psize=self.positions[order.data._dataname].size,
                pprice=self.positions[order.data._dataname].price,
            )

            psize = fill_size if order.isbuy() else -fill_size
            old_pos = self.positions[order.data._dataname]
            new_size = old_pos.size + psize
            if new_size == 0:
                new_price = 0.0
            elif abs(new_size) > abs(old_pos.size):
                # Adding to position: weighted average price
                total_cost = old_pos.size * old_pos.price + psize * fill_price
                new_price = total_cost / new_size if new_size != 0 else 0.0
            else:
                # Reducing position: keep old price
                new_price = old_pos.price
            self.positions[order.data._dataname] = Position(new_size, new_price)

            if order.executed.remsize == 0:
                order.completed()
                if order in self.open_orders:
                    self.open_orders.remove(order)
            else:
                order.partial()

            self.notify(order)

    def next(self):
        """Process pending order/trade events from CTP each iteration."""
        self.o.get_balance()
        self._process_order_events()
        self._process_trade_events()
