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
import time as _time

from ..broker import BrokerBase
from ..order import BuyOrder, Order, SellOrder
from ..parameters import BoolParam, FloatParam
from ..position import Position
from ..stores.ctpstore import (
    CTPStore,
    THOST_FTDC_D_Buy,
    THOST_FTDC_D_Sell,
    THOST_FTDC_OF_Close,
    THOST_FTDC_OF_CloseToday,
    THOST_FTDC_OF_CloseYesterday,
    THOST_FTDC_OF_Open,
    THOST_FTDC_OPT_AnyPrice,
    THOST_FTDC_OPT_LimitPrice,
    THOST_FTDC_OST_AllTraded,
    THOST_FTDC_OST_Canceled,
    THOST_FTDC_OST_NoTradeNotQueueing,
    THOST_FTDC_OST_NoTradeQueueing,
    THOST_FTDC_OST_PartTradedNotQueueing,
    THOST_FTDC_OST_PartTradedQueueing,
)
from ..utils.py3 import queue

logger = logging.getLogger(__name__)

# Exchanges that require CloseToday/CloseYesterday distinction
_SHFE_INE_EXCHANGES = frozenset({"SHFE", "INE"})


# Registration mechanism
def _register_ctp_broker_class(broker_cls):
    """Register broker class with the store when module is loaded."""
    CTPStore.BrokerCls = broker_cls
    return broker_cls


# Map backtrader Order exec types to CTP order price types
_BT_TO_CTP_ORDERTYPE = {
    Order.Market: THOST_FTDC_OPT_AnyPrice,
    Order.Limit: THOST_FTDC_OPT_LimitPrice,
    Order.Stop: THOST_FTDC_OPT_AnyPrice,  # C1: stop triggers market
    Order.StopLimit: THOST_FTDC_OPT_LimitPrice,  # C1: stop triggers limit
    None: THOST_FTDC_OPT_LimitPrice,
}

# Order types that require local stop-trigger logic
_STOP_EXEC_TYPES = frozenset({Order.Stop, Order.StopLimit})

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
_POSI_LONG = "2"
_POSI_SHORT = "3"


def _extract_exchange(symbol):
    """Extract exchange code from symbol like 'rb2501.SHFE' -> 'SHFE'."""
    if "." in symbol:
        return symbol.split(".", 1)[1].upper()
    return ""


def _extract_instrument(symbol):
    """Extract instrument from symbol like 'rb2501.SHFE' -> 'rb2501'."""
    if "." in symbol:
        return symbol.split(".", 1)[0]
    return symbol


@_register_ctp_broker_class
class CTPBroker(BrokerBase):
    """Broker implementation for CTP futures trading via ctp-python.

    Maps backtrader orders to CTP orders using native CTP API constants.
    Supports market and limit orders, order status tracking via CTP event
    callbacks, position management with open/close offset handling.

    For SHFE/INE exchanges, automatically uses CloseToday/CloseYesterday
    offsets based on position composition.

    Params:
      - `use_positions` (default:`True`): Use existing positions on start.
      - `commission` (default:`0.0`): Commission rate (absolute per contract).
    """

    use_positions = BoolParam(default=True, doc="Use existing positions to kickstart the broker")
    commission = FloatParam(default=0.0, doc="Commission per contract (absolute)")
    stop_slippage_ticks = FloatParam(default=0.0, doc="Max slippage ticks for stop orders (0=market order)")

    def __init__(self, **kwargs):
        """Initialize the CTPBroker with CTPStore connection.

        Args:
            **kwargs: Arguments passed to CTPStore constructor (e.g.,
                user_id, password, broker_id, investor_id).
        """
        super().__init__(**kwargs)
        self.o = CTPStore(**kwargs)

        self.orders = collections.OrderedDict()  # bt order ref -> Order
        self.open_orders = {}  # bt order ref -> Order (dict for O(1) removal)
        self.notifs = collections.deque()
        self._ref_to_bt = {}  # ctp order_ref -> bt order ref

        self.startingcash = self.cash = 0.0
        self.startingvalue = self.value = 0.0
        self.positions = collections.defaultdict(Position)
        # Track today/yesterday positions for SHFE/INE CloseToday/CloseYesterday
        # Key: instrument (e.g. 'rb2501')
        # Value: {'today_long': int, 'today_short': int, 'yd_long': int, 'yd_short': int}
        self._pos_detail = collections.defaultdict(
            lambda: {"today_long": 0, "today_short": 0, "yd_long": 0, "yd_short": 0}
        )
        # C1: Pending stop orders awaiting trigger
        self._pending_stops = []  # list of (order, stop_price, plimit)
        # T4: Dedup trade events from CTP
        self._processed_trade_ids = set()
        # T1: Rate-limit balance queries in next()
        self._last_balance_time = 0.0
        self._balance_interval = 10.0  # seconds
        # T13: Track trading day for position detail reset
        self._last_trading_day = None

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
                instrument = p.get("instrument", "")
                direction = p.get("direction", "")  # '2'=Long, '3'=Short
                volume = p.get("volume", 0)
                avg_price = p.get("avg_price", 0)
                yd_volume = p.get("yd_volume", 0)
                today_volume = p.get("today_volume", 0)

                if volume == 0:
                    continue

                size = volume if direction == _POSI_LONG else -volume
                final_size = self.positions[instrument].size + size
                final_price = (
                    avg_price
                    if ((final_size > 0 and direction == _POSI_LONG) or (final_size < 0 and direction == _POSI_SHORT))
                    else self.positions[instrument].price or avg_price
                )
                self.positions[instrument] = Position(final_size, final_price)

                # Track today/yd position detail for SHFE/INE
                detail = self._pos_detail[instrument]
                if direction == _POSI_LONG:
                    detail["today_long"] += today_volume
                    detail["yd_long"] += yd_volume
                else:
                    detail["today_short"] += today_volume
                    detail["yd_short"] += yd_volume

    def stop(self):
        """Stop the broker and release CTP connection."""
        super().stop()
        self.o.stop()

    def getcash(self):
        """Get the current available cash balance.

        Returns:
            float: The available cash for trading.
        """
        return self.o.get_cash()

    def getvalue(self, datas=None):
        """Get the current portfolio value.

        Args:
            datas: Optional data feeds to calculate value for.
                Not used in CTP implementation.

        Returns:
            float: The total portfolio value including cash and positions.
        """
        return self.o.get_value()

    def getposition(self, data, clone=True):
        """Get the current position for a data feed.

        Args:
            data: The data feed to get position for.
            clone: If True, return a clone of the position object.

        Returns:
            Position: The position object containing size and price.
        """
        # Use consistent key: data._dataname
        key = getattr(data, "_dataname", None) or data.p.dataname
        pos = self.positions[key]
        if clone:
            pos = pos.clone()
        return pos

    def orderstatus(self, order):
        """Get the current status of an order.

        Args:
            order: The order object to check status for.

        Returns:
            int: The order status constant (e.g., Order.Accepted,
                Order.Completed, Order.Rejected).
        """
        o = self.orders.get(order.ref)
        return o.status if o else Order.Rejected

    def notify(self, order):
        """Store an order notification for later retrieval.

        Args:
            order: The order object to create a notification for.
        """
        self.notifs.append(order.clone())

    def get_notification(self):
        """Get the next pending order notification.

        Returns:
            Order: A cloned order object with status updates, or None if
                no notifications are pending.
        """
        if not self.notifs:
            return None
        return self.notifs.popleft()

    # --- Order creation ---
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
        """Submit a buy order to CTP.

        Args:
            owner: The strategy or object creating this order.
            data: The data feed for this order.
            size: The number of contracts/shares to buy.
            price: The limit price for limit orders.
            plimit: The price limit for the order.
            exectype: The execution type (Market, Limit, Stop, StopLimit).
            valid: The order validity (Day, GTC, etc.).
            tradeid: An optional trade identifier.
            oco: One-cancels-other order reference.
            trailamount: Trailing amount for trailing stop orders.
            trailpercent: Trailing percent for trailing stop orders.
            **kwargs: Additional broker-specific parameters.

        Returns:
            Order: The created order object.
        """
        return self._submit_order(
            owner,
            data,
            Order.Buy,
            size,
            price,
            plimit,
            exectype,
            valid,
            tradeid,
            oco,
            trailamount,
            trailpercent,
            **kwargs,
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
        """Submit a sell order to CTP.

        Args:
            owner: The strategy or object creating this order.
            data: The data feed for this order.
            size: The number of contracts/shares to sell.
            price: The limit price for limit orders.
            plimit: The price limit for the order.
            exectype: The execution type (Market, Limit, Stop, StopLimit).
            valid: The order validity (Day, GTC, etc.).
            tradeid: An optional trade identifier.
            oco: One-cancels-other order reference.
            trailamount: Trailing amount for trailing stop orders.
            trailpercent: Trailing percent for trailing stop orders.
            **kwargs: Additional broker-specific parameters.

        Returns:
            Order: The created order object.
        """
        return self._submit_order(
            owner,
            data,
            Order.Sell,
            size,
            price,
            plimit,
            exectype,
            valid,
            tradeid,
            oco,
            trailamount,
            trailpercent,
            **kwargs,
        )

    def cancel(self, order):
        """Cancel an active order in CTP.

        Args:
            order: The order object to cancel.

        Returns:
            Order: The same order object passed in.
        """
        order_ref = getattr(order, "_ctp_order_ref", None)
        if order_ref is None:
            logger.warning(f"[CTPBroker] No CTP order_ref for order ref={order.ref}")
            return order
        symbol = order.data.p.dataname
        self.o.cancel_order(symbol, order_ref)
        return order

    def _determine_close_offsets(self, symbol, direction, volume):
        """Determine the correct close offset(s) for an order.

        For SHFE/INE: may need to split into CloseToday + CloseYesterday
        when the volume spans both today and yesterday positions.
        For other exchanges: returns a single Close offset.

        Args:
            symbol: Full symbol e.g. 'rb2501.SHFE'.
            direction: THOST_FTDC_D_Buy or THOST_FTDC_D_Sell.
            volume: Number of contracts to close.

        Returns:
            list of (offset, vol) tuples, e.g.
            [(THOST_FTDC_OF_CloseToday, 3), (THOST_FTDC_OF_CloseYesterday, 2)]
        """
        exchange = _extract_exchange(symbol)
        if exchange not in _SHFE_INE_EXCHANGES:
            return [(THOST_FTDC_OF_Close, volume)]

        instrument = _extract_instrument(symbol)
        detail = self._pos_detail.get(instrument, None)
        if detail is None:
            return [(THOST_FTDC_OF_Close, volume)]

        # Buying to close means closing short positions
        # Selling to close means closing long positions
        if direction == THOST_FTDC_D_Buy:
            today_vol = detail.get("today_short", 0)
            yd_vol = detail.get("yd_short", 0)
        else:
            today_vol = detail.get("today_long", 0)
            yd_vol = detail.get("yd_long", 0)

        # Split: close today first, then yesterday
        parts = []
        remaining = volume
        if today_vol > 0 and remaining > 0:
            close_today = min(today_vol, remaining)
            parts.append((THOST_FTDC_OF_CloseToday, close_today))
            remaining -= close_today
        if yd_vol > 0 and remaining > 0:
            close_yd = min(yd_vol, remaining)
            parts.append((THOST_FTDC_OF_CloseYesterday, close_yd))
            remaining -= close_yd
        if remaining > 0:
            # Fallback: if tracked positions don't cover, use generic Close
            parts.append((THOST_FTDC_OF_Close, remaining))
        if not parts:
            parts.append((THOST_FTDC_OF_Close, volume))
        return parts

    def _submit_order(
        self,
        owner,
        data,
        ordtype,
        size,
        price,
        plimit,
        exectype,
        valid,
        tradeid,
        oco,
        trailamount,
        trailpercent,
        **kwargs,
    ):
        """Create a backtrader Order and submit to CTP.

        Args:
            owner: The strategy or object creating this order.
            data: The data feed for this order.
            ordtype: Order.Buy or Order.Sell.
            size: The number of contracts/shares to trade.
            price: The limit price for limit orders.
            plimit: The price limit for the order.
            exectype: The execution type (Market, Limit, Stop, StopLimit).
            valid: The order validity (Day, GTC, etc.).
            tradeid: An optional trade identifier.
            oco: One-cancels-other order reference.
            trailamount: Trailing amount for trailing stop orders.
            trailpercent: Trailing percent for trailing stop orders.
            **kwargs: Additional broker-specific parameters.

        Returns:
            Order: The created order object.
        """
        kwargs.pop("parent", None)
        kwargs.pop("transmit", None)

        if ordtype == Order.Buy:
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
            )
        else:
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
            )

        self.orders[order.ref] = order
        order.submit(self)
        self.notify(order)

        # C1: Hold stop orders locally until triggered
        if exectype in _STOP_EXEC_TYPES:
            stop_price = price if price else 0.0
            order.accept()
            self.notify(order)
            self._pending_stops.append((order, stop_price, plimit))
            self.open_orders[order.ref] = order
            return order

        # Use consistent symbol key (A3 fix)
        symbol = data.p.dataname
        pos_key = getattr(data, "_dataname", None) or symbol
        pos = self.positions[pos_key]
        ctp_price_type = _BT_TO_CTP_ORDERTYPE.get(exectype, THOST_FTDC_OPT_LimitPrice)
        order_price = price if price else 0.0

        if ordtype == Order.Buy:
            direction = THOST_FTDC_D_Buy
            is_closing = pos.size < 0
        else:
            direction = THOST_FTDC_D_Sell
            is_closing = pos.size > 0

        if is_closing:
            offset_parts = self._determine_close_offsets(symbol, direction, abs(size))
        else:
            offset_parts = [(THOST_FTDC_OF_Open, abs(size))]

        # Submit order(s) to CTP — may be split for SHFE/INE
        first_ref = None
        for offset, vol in offset_parts:
            order_ref = self.o.send_order(
                symbol=symbol,
                direction=direction,
                offset=offset,
                price=order_price,
                volume=vol,
                order_price_type=ctp_price_type,
            )
            if order_ref is None:
                if first_ref is None:
                    # First (or only) part failed
                    order.reject(self)
                    self.notify(order)
                    return order
                else:
                    logger.error(f"[CTPBroker] Split order part failed: {symbol} offset={offset} vol={vol}")
                    continue
            if first_ref is None:
                first_ref = order_ref
                order._ctp_order_ref = order_ref
            # Map all sub-order refs to the same bt order
            self._ref_to_bt[order_ref] = order.ref

        self.open_orders[order.ref] = order
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

            order_ref = evt.get("order_ref")
            if order_ref is None:
                continue

            bt_ref = self._ref_to_bt.get(order_ref)
            if bt_ref is None:
                continue

            order = self.orders.get(bt_ref)
            if order is None:
                continue

            status = evt.get("status")
            is_rejected = evt.get("rejected", False)

            if is_rejected or status == THOST_FTDC_OST_Canceled:
                if is_rejected:
                    order.reject(self)
                else:
                    order.cancel()
                self.notify(order)
                self.open_orders.pop(order.ref, None)

    def _process_trade_events(self):
        """Process trade fill events from CTP."""
        comm_rate = self.get_param("commission")
        while True:
            try:
                evt = self.o.trade_queue.get_nowait()
            except queue.Empty:
                break

            # T4: Dedup trade events
            trade_id = evt.get("trade_id", "")
            if trade_id and trade_id in self._processed_trade_ids:
                continue
            if trade_id:
                self._processed_trade_ids.add(trade_id)

            order_ref = evt.get("order_ref")
            if order_ref is None:
                continue

            bt_ref = self._ref_to_bt.get(order_ref)
            if bt_ref is None:
                logger.debug(f"[CTPBroker] Trade for unknown ref: {order_ref}")
                continue

            order = self.orders.get(bt_ref)
            if order is None:
                continue

            fill_price = evt.get("price", 0.0)
            fill_size = evt.get("volume", 0)
            fill_offset = evt.get("offset", "")

            # Use consistent position key (A3 fix)
            pos_key = getattr(order.data, "_dataname", None) or order.data.p.dataname
            old_pos = self.positions[pos_key]

            # A2: Commission calculation
            fill_comm = comm_rate * fill_size

            # Determine opened vs closed quantities
            signed_size = fill_size if order.isbuy() else -fill_size
            is_closing = (order.isbuy() and old_pos.size < 0) or (order.issell() and old_pos.size > 0)
            if is_closing:
                closed_qty = min(fill_size, abs(old_pos.size))
                opened_qty = fill_size - closed_qty
            else:
                closed_qty = 0
                opened_qty = fill_size

            order.execute(
                dt=order.data.datetime[0],
                size=signed_size,
                price=fill_price,
                closed=closed_qty,
                closedvalue=closed_qty * fill_price,
                closedcomm=fill_comm * (closed_qty / fill_size) if fill_size else 0.0,
                opened=opened_qty,
                openedvalue=opened_qty * fill_price,
                openedcomm=fill_comm * (opened_qty / fill_size) if fill_size else 0.0,
                margin=0.0,
                pnl=0.0,
                psize=old_pos.size,
                pprice=old_pos.price,
            )

            # Update position
            new_size = old_pos.size + signed_size
            if new_size == 0:
                new_price = 0.0
            elif abs(new_size) > abs(old_pos.size):
                # Adding to position: weighted average price
                total_cost = old_pos.size * old_pos.price + signed_size * fill_price
                new_price = total_cost / new_size if new_size != 0 else 0.0
            else:
                # Reducing position: keep old price
                new_price = old_pos.price
            self.positions[pos_key] = Position(new_size, new_price)

            # Update today/yd position detail for SHFE/INE
            instrument = _extract_instrument(pos_key)
            detail = self._pos_detail[instrument]
            if fill_offset == THOST_FTDC_OF_Open:
                if order.isbuy():
                    detail["today_long"] += fill_size
                else:
                    detail["today_short"] += fill_size
            elif fill_offset == THOST_FTDC_OF_CloseToday:
                if order.isbuy():
                    detail["today_short"] = max(0, detail["today_short"] - fill_size)
                else:
                    detail["today_long"] = max(0, detail["today_long"] - fill_size)
            elif fill_offset in (THOST_FTDC_OF_CloseYesterday, THOST_FTDC_OF_Close):
                if order.isbuy():
                    detail["yd_short"] = max(0, detail["yd_short"] - fill_size)
                else:
                    detail["yd_long"] = max(0, detail["yd_long"] - fill_size)

            if order.executed.remsize == 0:
                order.completed()
                self.open_orders.pop(order.ref, None)
            else:
                order.partial()

            self.notify(order)

    def _check_stop_triggers(self):
        """C1: Check if any pending stop orders should be triggered."""
        if not self._pending_stops:
            return
        triggered = []
        for i, (order, stop_price, plimit) in enumerate(self._pending_stops):
            try:
                last = order.data.close[0]
            except (IndexError, TypeError, AttributeError):
                continue
            # Buy stop triggers when price >= stop_price
            # Sell stop triggers when price <= stop_price
            if order.isbuy() and last >= stop_price:
                triggered.append(i)
            elif order.issell() and last <= stop_price:
                triggered.append(i)

        # Process triggered stops in reverse to avoid index shifting
        for i in reversed(triggered):
            order, stop_price, plimit = self._pending_stops.pop(i)
            order.triggered = True

            symbol = order.data.p.dataname
            pos_key = getattr(order.data, "_dataname", None) or symbol
            pos = self.positions[pos_key]

            # T3: Use limit price with slippage instead of raw market price
            # for stop orders, to control max slippage
            max_slip_ticks = self.get_param("stop_slippage_ticks")
            if order.exectype == Order.Stop:
                if max_slip_ticks and max_slip_ticks > 0:
                    # Use limit order with slippage offset
                    ctp_price_type = THOST_FTDC_OPT_LimitPrice
                    if order.isbuy():
                        order_price = stop_price + max_slip_ticks
                    else:
                        order_price = max(0, stop_price - max_slip_ticks)
                else:
                    ctp_price_type = THOST_FTDC_OPT_AnyPrice
                    order_price = 0.0
            else:  # StopLimit
                ctp_price_type = THOST_FTDC_OPT_LimitPrice
                order_price = plimit if plimit else stop_price

            abs_size = abs(order.size)
            if order.isbuy():
                direction = THOST_FTDC_D_Buy
                is_closing = pos.size < 0
            else:
                direction = THOST_FTDC_D_Sell
                is_closing = pos.size > 0

            if is_closing:
                offset_parts = self._determine_close_offsets(symbol, direction, abs_size)
            else:
                offset_parts = [(THOST_FTDC_OF_Open, abs_size)]

            first_ref = None
            for offset, vol in offset_parts:
                order_ref = self.o.send_order(
                    symbol=symbol,
                    direction=direction,
                    offset=offset,
                    price=order_price,
                    volume=vol,
                    order_price_type=ctp_price_type,
                )
                if order_ref is None:
                    if first_ref is None:
                        order.reject(self)
                        self.notify(order)
                        self.open_orders.pop(order.ref, None)
                    else:
                        logger.error(f"[CTPBroker] Stop split order part failed: {symbol} offset={offset} vol={vol}")
                    continue
                if first_ref is None:
                    first_ref = order_ref
                    order._ctp_order_ref = order_ref
                self._ref_to_bt[order_ref] = order.ref

    def next(self):
        """Process pending order/trade events from CTP each iteration."""
        # T13: Reset position detail on trading day change
        self._check_day_change()
        self._check_stop_triggers()
        self._process_order_events()
        self._process_trade_events()
        # T1: Rate-limit balance queries — only after trades or periodically
        now = _time.time()
        if now - self._last_balance_time >= self._balance_interval:
            self.o.get_balance()
            self._last_balance_time = now

    def _check_day_change(self):
        """T13: Reset today/yd position detail when trading day changes.

        On a new trading day, all 'today' positions become 'yesterday'.
        """
        try:
            current_day = self.o.trader_spi._account.get("trading_day") if self.o.trader_spi._account else None
        except (AttributeError, TypeError):
            current_day = None
        if current_day is None:
            return
        if self._last_trading_day is None:
            self._last_trading_day = current_day
            return
        if current_day != self._last_trading_day:
            logger.info(f"[CTPBroker] Trading day changed: {self._last_trading_day} -> {current_day}")
            for detail in self._pos_detail.values():
                detail["yd_long"] += detail["today_long"]
                detail["today_long"] = 0
                detail["yd_short"] += detail["today_short"]
                detail["today_short"] = 0
            self._last_trading_day = current_day
