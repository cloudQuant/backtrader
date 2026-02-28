#!/usr/bin/env python
"""CCXT Broker Module - Cryptocurrency exchange broker.

This module provides the CCXTBroker for trading on cryptocurrency
exchanges through the CCXT library.

Classes:
    CCXTOrder: CCXT-specific order implementation.
    CCXTBroker: Broker implementation for CCXT trading.

Functions:
    _register_ccxt_broker_class: Registers broker with store.

Example:
    >>> store = bt.stores.CCXTStore(exchange='binance')
    >>> cerebro.setbroker(store.getbroker())
"""

import collections
import json
import time
from datetime import datetime

from ccxt.base.errors import ExchangeError, ExchangeNotAvailable, NetworkError

from ..broker import BrokerBase
from ..order import Order
from ..position import Position
from ..stores.ccxtstore import CCXTStore
from ..utils.py3 import queue

# Import enhancement modules
try:
    from ..ccxt.config import ExchangeConfig
    from ..ccxt.orders.bracket import BracketOrderManager
    from ..ccxt.threading import ThreadedOrderManager
    from ..ccxt.websocket import CCXTWebSocketManager

    HAS_CCXT_ENHANCEMENTS = True
except ImportError:
    HAS_CCXT_ENHANCEMENTS = False
    ThreadedOrderManager = None
    BracketOrderManager = None
    ExchangeConfig = None
    CCXTWebSocketManager = None


class CCXTOrder(Order):
    """CCXT-specific order implementation.

    This class extends the base Order class to support orders placed through
    the CCXT library for cryptocurrency exchange trading.

    Attributes:
        ccxt_order: Raw CCXT order dictionary from the exchange.
        executed_fills: Set of fill IDs that have been processed.
    """

    def __init__(self, owner, data, exectype, side, amount, price, ccxt_order):
        """Initialize a CCXTOrder instance.

        Args:
            owner: The strategy or object that owns this order.
            data: The data feed associated with this order.
            exectype: Order execution type (Market, Limit, Stop, etc.).
            side: Order side ('buy' or 'sell').
            amount: Order size/quantity.
            price: Order price (None for market orders).
            ccxt_order: Raw CCXT order dictionary from the exchange.
        """
        self.ordtype = self.Buy if side == "buy" else self.Sell
        self.ccxt_order = ccxt_order
        self.executed_fills = set()
        # Use simulated=True to skip data.close[0] access in OrderBase.__init__
        super().__init__(
            owner=owner,
            data=data,
            size=float(amount),
            price=float(price) if price else None,
            exectype=exectype,
            simulated=True,
        )


# Registration mechanism, automatically register broker class when module is imported
def _register_ccxt_broker_class(broker_cls):
    """Register broker class with the store when module is loaded"""
    CCXTStore.BrokerCls = broker_cls
    return broker_cls


@_register_ccxt_broker_class
class CCXTBroker(BrokerBase):
    """Broker implementation for CCXT cryptocurrency trading library.
    This class maps the orders/positions from CCXT to the
    internal API of `backtrader`.

    Broker mapping added as I noticed that there are differences between the expected
    order_types and retuned status from canceling an order

    Added a new mappings parameter to the script with defaults.

    Added a get_balance function. Manually check the account balance and update brokers
    self.cash and self.value. This helps alleviate rate limit issues.

    Added a new get_wallet_balance method. This will allow manual checking of any coins
        The method will allow setting parameters. Useful for dealing with multiple assets

    Modified getcash() and getvalue():
        Backtrader will call getcash and getvalue before and after next, slowing things down
        with rest calls. As such, th

    The broker mapping should contain a new dict for order_types and mappings like below:

    broker_mapping = {
        'order_types': {
            bt.Order.Market: 'market',
            bt.Order.Limit: 'limit',
            bt.Order.Stop: 'stop-loss', #stop-loss for kraken, stop for bitmex
            bt.Order.StopLimit: 'stop limit'
        },
        'mappings':{
            'closed_order':{
                'key': 'status',
                'value':'closed'
                },
            'canceled_order':{
                'key': 'result',
                'value':1}
                }
        }

    Added new private_end_point method to allow using any private non-unified end point

    """

    order_types = {
        Order.Market: "market",
        Order.Limit: "limit",
        Order.Stop: "stop",  # stop-loss for kraken, stop for bitmex
        Order.StopLimit: "stop limit",
    }

    mappings = {
        "closed_order": {"key": "status", "value": "closed"},
        "canceled_order": {"key": "status", "value": "canceled"},
    }

    def __init__(
        self,
        broker_mapping=None,
        debug=False,
        use_threaded_order_manager=False,
        use_websocket_orders=False,
        store=None,
        max_retries=3,
        retry_delay=1.0,
        **kwargs,
    ):
        """Initialize the CCXTBroker instance.

        Args:
            broker_mapping: Optional dictionary containing custom mappings for
                order types and status values. Expected format:
                {
                    'order_types': {bt.Order.Market: 'market', ...},
                    'mappings': {
                        'closed_order': {'key': 'status', 'value': 'closed'},
                        'canceled_order': {'key': 'status', 'value': 'canceled'}
                    }
                }
            debug: If True, enable debug output.
            use_threaded_order_manager: If True, use background thread for order checking.
            use_websocket_orders: If True, use WebSocket watch_my_trades for order
                updates instead of REST polling. Lowest latency option. Requires ccxt.pro.
            store: Optional CCXTStore instance. If provided, use this store instead of
                creating a new one.
            max_retries: Maximum retry attempts for failed API calls.
            retry_delay: Base delay between retries (uses exponential backoff).
            **kwargs: Additional arguments passed to CCXTStore (exchange,
                api_key, secret, etc.) if store is not provided.

        Raises:
            KeyError: If broker_mapping is malformed (caught silently).
        """
        super().__init__()

        self.cash = None
        self._threaded_order_manager = None
        self._bracket_manager = None
        self._ws_order_manager = None
        self._use_threaded = use_threaded_order_manager
        self._use_ws_orders = use_websocket_orders
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._consecutive_failures = 0
        self._max_consecutive_failures = 10
        self._ws_order_updates = queue.Queue()  # WS order updates queue
        self._ws_subscribed_symbols = set()  # Symbols subscribed for WS order tracking
        if broker_mapping is not None:
            try:
                self.order_types = broker_mapping["order_types"]
            except KeyError:  # Might not want to change the order types
                pass
            try:
                self.mappings = broker_mapping["mappings"]
            except KeyError:  # might not want to change the mappings
                pass

        # Use provided store or create a new one
        if store is not None:
            self.store = store
        else:
            self.store = CCXTStore(**kwargs)

        self.currency = self.store.currency

        self.positions = collections.defaultdict(Position)

        self.debug = debug
        self.indent = 4  # For pretty printing dictionaries

        self.notifs = queue.Queue()  # holds orders which are notified

        self.open_orders = {}  # ccxt_order_id -> CCXTOrder for O(1) lookup

        self.startingcash = self.store._cash
        self.startingvalue = self.store._value

        self._last_op_time = 0

        # Initialize threaded order manager if requested
        if use_threaded_order_manager and not use_websocket_orders and HAS_CCXT_ENHANCEMENTS and ThreadedOrderManager:
            self._threaded_order_manager = ThreadedOrderManager(self.store, check_interval=3.0)
            self._threaded_order_manager.start()

        # Initialize WebSocket order manager if requested (takes priority over threaded)
        if use_websocket_orders and HAS_CCXT_ENHANCEMENTS and CCXTWebSocketManager:
            self._init_ws_order_manager()

        # Initialize bracket order manager
        if HAS_CCXT_ENHANCEMENTS and BracketOrderManager:
            self._bracket_manager = BracketOrderManager(self)

    def get_balance(self):
        """Get and update the account balance from the exchange.

        This method manually refreshes the account balance from the exchange,
        updating the broker's cash and value attributes. This can help alleviate
        rate limit issues by allowing manual balance checks instead of automatic
        checks before/after each operation.

        Returns:
            tuple: (cash, value) where cash is available funds and value is
                total portfolio value.
        """
        self.store.get_balance()
        self.cash = self.store._cash
        self.value = self.store._value
        return self.cash, self.value

    def get_wallet_balance(self, currency_list, params=None):
        """Get wallet balance for specific currencies.

        This method allows manual checking of balances for multiple currencies,
        useful for dealing with multiple assets or margin balances.

        Args:
            currency_list: List of currency symbols to query (e.g., ['BTC', 'ETH']).
            params: Optional dictionary of parameters to pass to the exchange API.

        Returns:
            dict: Dictionary mapping currency symbols to their balance information:
                {
                    'BTC': {'cash': <free_amount>, 'value': <total_amount>},
                    'ETH': {'cash': <free_amount>, 'value': <total_amount>},
                    ...
                }
        """
        result = {}
        if params is None:
            params = {}
        balance = self.store.get_wallet_balance(params=params)
        for currency in currency_list:
            result[currency] = {}
            result[currency]["cash"] = balance["free"].get(currency, 0)
            result[currency]["value"] = balance["total"].get(currency, 0)
        return result

    def _init_ws_order_manager(self):
        """Initialize WebSocket-based order tracking via watch_my_trades.

        Creates a CCXTWebSocketManager instance dedicated to receiving
        real-time trade/fill notifications from the exchange.
        """
        try:
            config = getattr(self.store.exchange, "config", {})
            if not config:
                config = {
                    "apiKey": getattr(self.store.exchange, "apiKey", ""),
                    "secret": getattr(self.store.exchange, "secret", ""),
                }
                password = getattr(self.store.exchange, "password", None)
                if password:
                    config["password"] = password
                config["enableRateLimit"] = True

            markets = getattr(self.store.exchange, "markets", None)
            self._ws_order_manager = CCXTWebSocketManager(
                self.store.exchange_id,
                config,
                markets=markets,
            )
            self._ws_order_manager.start()
            print("[CCXTBroker] WebSocket order tracking initialized")
        except (NetworkError, ExchangeError, OSError, ImportError) as e:
            print(f"[CCXTBroker] WebSocket order init failed, falling back to REST: {e}")
            self._ws_order_manager = None
            self._use_ws_orders = False

    def _ws_subscribe_symbol(self, symbol):
        """Subscribe to WebSocket my_trades for a symbol if not already subscribed.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT').
        """
        if not self._ws_order_manager or symbol in self._ws_subscribed_symbols:
            return

        try:
            self._ws_order_manager.subscribe_my_trades(symbol, self._on_ws_my_trades)
            self._ws_subscribed_symbols.add(symbol)
            if self.debug:
                print(f"[CCXTBroker] WS subscribed to my_trades for {symbol}")
        except (NetworkError, ExchangeError, OSError) as e:
            print(f"[CCXTBroker] WS subscribe_my_trades failed for {symbol}: {e}")

    def _on_ws_my_trades(self, trades):
        """Callback for WebSocket my_trades updates.

        Receives real-time fill notifications and enqueues them for processing
        in the main broker loop.

        Args:
            trades: List of trade dicts from the exchange, each containing:
                - id: Trade ID
                - order: Order ID this trade belongs to
                - symbol: Trading pair
                - side: 'buy' or 'sell'
                - amount: Fill size
                - price: Fill price
                - timestamp: Fill timestamp
        """
        if not trades:
            return
        for trade in trades:
            try:
                self._ws_order_updates.put_nowait(trade)
            except queue.Full:
                pass  # Queue full, will catch up next cycle

    def _process_ws_order_updates(self):
        """Process WebSocket trade/fill updates against open orders.

        Drains the WS update queue and matches fills to open orders,
        updating execution state and notifying the strategy.
        """
        processed = 0
        while not self._ws_order_updates.empty():
            try:
                trade = self._ws_order_updates.get_nowait()
            except queue.Empty:
                break

            order_id = trade.get("order")
            if not order_id:
                continue

            # Find matching open order by ID (O(1) lookup)
            matching_order = self.open_orders.get(order_id)

            if matching_order is None:
                continue

            # Check if this fill was already processed
            trade_id = trade.get("id", "")
            if trade_id and trade_id in matching_order.executed_fills:
                continue

            # Process the fill
            fill_size = float(trade.get("amount", 0))
            fill_price = float(trade.get("price", 0))
            fill_ts = trade.get("timestamp", 0)

            if fill_size <= 0 or fill_price <= 0:
                continue

            if trade_id:
                matching_order.executed_fills.add(trade_id)

            signed_size = fill_size if matching_order.isbuy() else -fill_size
            # C8: Extract commission from CCXT trade fee
            fee_info = trade.get("fee") or {}
            fill_comm = float(fee_info.get("cost", 0) or 0)
            fill_value = fill_size * fill_price
            matching_order.execute(
                fill_ts,
                signed_size,
                fill_price,
                0,
                0.0,
                0.0,
                signed_size,
                fill_value,
                fill_comm,
                0.0,
                0.0,
                0,
                0.0,
            )
            pos = self.getposition(matching_order.data, clone=False)
            pos.update(signed_size, fill_price)

            # Determine order state by checking remaining
            remaining = float(matching_order.ccxt_order.get("amount", 0)) - abs(matching_order.executed.size)
            if remaining <= 0:
                matching_order.completed()
                self.notify(matching_order.clone())
                self.open_orders.pop(order_id, None)
                if self._bracket_manager:
                    self._bracket_manager.on_order_update(matching_order)
            else:
                matching_order.partial()
                self.notify(matching_order.clone())

            processed += 1
            self._consecutive_failures = 0

        return processed

    def getcash(self):
        """Get the current available cash balance.

        Returns:
            float: Current available cash/funds in the broker currency.

        Note:
            This method returns cached cash values to avoid repeated REST API calls.
            Use get_balance() to refresh from the exchange.
        """
        # Get cash seems to always be called before get value,
        # Therefore, it makes sense to add getbalance here.
        # return self.store.getcash(self.currency)
        self.cash = self.store._cash
        return self.cash

    def getvalue(self, datas=None):
        """Get the current portfolio value.

        Args:
            datas: Unused parameter (kept for API compatibility).

        Returns:
            float: Current total portfolio value including cash and positions.
                   Uses the exchange-reported total balance which typically
                   includes unrealized PnL for margin/futures accounts.

        Note:
            This method returns cached value to avoid repeated REST API calls.
            Use get_balance() to refresh from the exchange.
        """
        # store._value is the exchange-reported total balance (including
        # unrealized PnL for futures/margin accounts).
        self.value = self.store._value
        return self.value

    def get_notification(self):
        """Get the next order notification from the queue.

        Returns:
            Order or None: The next order notification, or None if no
                notifications are available.
        """
        try:
            return self.notifs.get(False)
        except queue.Empty:
            return None

    def notify(self, order):
        """Add an order notification to the queue.

        Args:
            order: The order to notify (typically a clone of the order).
        """
        self.notifs.put(order)

    def getposition(self, data, clone=True):
        """Get the current position for a data feed.

        Args:
            data: The data feed to get the position for.
            clone: If True (default), return a clone of the position to prevent
                modification of the internal state.

        Returns:
            Position: The position object for the specified data feed.
        """
        # return self.o.getposition(data._dataname, clone=clone)
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos

    def _retry_api_call(self, func, *args, **kwargs):
        """Execute an API call with retry logic and exponential backoff.

        Args:
            func: Callable to execute.
            *args: Positional arguments for the callable.
            **kwargs: Keyword arguments for the callable.

        Returns:
            The result of the API call.

        Raises:
            The last exception if all retries fail.
        """
        last_exception = None
        for attempt in range(self._max_retries):
            try:
                result = func(*args, **kwargs)
                self._consecutive_failures = 0
                return result
            except (NetworkError, ExchangeNotAvailable) as e:
                last_exception = e
                self._consecutive_failures += 1
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay * (2**attempt)
                    if self.debug:
                        print(f"[CCXTBroker] API call failed (attempt {attempt + 1}/{self._max_retries}): {e}")
                        print(f"[CCXTBroker] Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    if self.debug:
                        print(f"[CCXTBroker] API call failed after {self._max_retries} attempts: {e}")
            except ExchangeError:
                # Exchange errors (invalid order, insufficient balance, etc.) should not retry
                raise
        raise last_exception

    def next(self):
        """Called on each iteration to update broker state.

        This method is called by the backtrader engine on each iteration.

        Order update priority (highest to lowest):
        1. WebSocket (push-based, no rate limiting needed)
        2. ThreadedOrderManager (background polling)
        3. Direct REST polling (rate-limited to 3s)
        """
        if self.debug:
            pass  # print("Broker next() called")  # Removed for performance

        # WebSocket mode: process push-based updates without rate limiting
        if self._use_ws_orders and self._ws_order_manager:
            self._process_ws_order_updates()
            # Still do periodic REST check for canceled/expired orders that WS might miss
            nts = datetime.now().timestamp()
            if nts - self._last_op_time >= 30 and self.open_orders:
                self._last_op_time = nts
                self._next()
            return

        # Check if store is connected before making API calls
        if hasattr(self.store, "is_connected") and not self.store.is_connected():
            if self._consecutive_failures == 0:
                print("[CCXTBroker] Exchange disconnected, skipping order check")
            self._consecutive_failures += 1
            return

        # If too many consecutive failures, reduce polling frequency
        if self._consecutive_failures >= self._max_consecutive_failures:
            nts = datetime.now().timestamp()
            # Back off to 30-second intervals after many failures
            if nts - self._last_op_time < 30:
                return
            self._last_op_time = nts
        else:
            # ===========================================
            # Perform operation every 3 seconds
            nts = datetime.now().timestamp()
            if nts - self._last_op_time < 3:
                return
            self._last_op_time = nts
            # ===========================================

        # Use threaded order manager if available, otherwise poll directly
        if self._threaded_order_manager and self._threaded_order_manager.is_running():
            self._process_threaded_updates()
        else:
            self._next()

    def _process_threaded_updates(self):
        """Process order updates from the threaded order manager.

        Reads all pending updates from the background thread and processes
        them against open orders.
        """
        updates = self._threaded_order_manager.get_updates()
        for update in updates:
            # Find the matching open order by ID (O(1) lookup)
            matching_order = self.open_orders.get(update.order_id)

            if matching_order is None:
                continue

            # Process fill if there's new fill data
            prev_filled = abs(matching_order.executed.size)
            if update.filled > prev_filled:
                fill_size = update.filled - prev_filled
                fill_price = update.average if update.average else 0
                if fill_size > 0 and fill_price > 0:
                    signed_size = fill_size if matching_order.isbuy() else -fill_size
                    matching_order.execute(
                        update.timestamp,
                        signed_size,
                        fill_price,
                        0,
                        0.0,
                        0.0,
                        0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        0,
                        0.0,
                    )
                    pos = self.getposition(matching_order.data, clone=False)
                    pos.update(signed_size, fill_price)

                    if update.status == "open":
                        matching_order.partial()
                    elif update.status == "closed":
                        matching_order.completed()
                    self.notify(matching_order.clone())

            # Handle terminal states
            if update.status == "closed":
                self.open_orders.pop(update.order_id, None)
                # Notify bracket manager
                if self._bracket_manager:
                    self._bracket_manager.on_order_update(matching_order)
            elif update.status in ("canceled", "expired", "rejected"):
                matching_order.cancel()
                self.notify(matching_order.clone())
                self.open_orders.pop(update.order_id, None)

    def _next(self):
        """Poll exchange for order status updates with error handling.

        1. For spot trading, don't use market orders, only use limit orders. When market orders are needed,
           simulate with limit orders, because some exchanges' market order size field is amount, backtrader
           doesn't consider this case and will error, so market orders are not adapted here
        2. For futures, Chinese futures simultaneous long and short positions on same symbol are not supported,
           because backtrader doesn't consider this case, so here we only support one-direction position
           for same symbol at same time
        """
        for oID, o_order in list(self.open_orders.items()):
            # Print debug before fetching so we know which order is giving an
            # issue if it crashes
            if self.debug:
                pass  # print("Fetching Order ID: {}".format(oID))  # Removed for performance

            # Get the order with error handling
            try:
                ccxt_order = self._retry_api_call(self.store.fetch_order, oID, o_order.data.p.dataname)
            except (NetworkError, ExchangeNotAvailable) as e:
                print(f"[CCXTBroker] Cannot fetch order {oID}: {e}")
                continue  # Skip this order, will retry next cycle
            except ExchangeError as e:
                print(f"[CCXTBroker] Exchange error for order {oID}: {e}")
                # Order may no longer exist on exchange
                if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                    o_order.cancel()
                    self.notify(o_order.clone())
                    self.open_orders.pop(oID, None)
                continue

            status = ccxt_order["status"]

            # Check for new fills
            if "trades" in ccxt_order and ccxt_order["trades"] is not None:  # Check if this order has fills
                for fill in ccxt_order["trades"]:  # Iterate through all fills of this order
                    if fill["id"] not in o_order.executed_fills:  # Whether this fill has been processed
                        fill_id, fill_dt, fill_size, fill_price = (
                            fill["id"],
                            fill["datetime"],
                            fill["amount"],
                            fill["price"],
                        )
                        o_order.executed_fills.add(fill_id)  # Record that this fill has been processed
                        fill_size = (
                            fill_size if o_order.isbuy() else -fill_size
                        )  # Meet backtrader specification, sell orders or short positions use negative numbers
                        o_order.execute(
                            fill_dt,
                            fill_size,
                            fill_price,
                            0,
                            0.0,
                            0.0,
                            0,
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            0,
                            0.0,
                        )  # Process this fill, internally marks order status, partial or complete fill
                        # Prepare to notify upper strategy
                        # self.get_balance() #Refresh account balance (balance no longer updated, reduce communication to improve performance, can be updated as needed in strategy)
                        pos = self.getposition(o_order.data, clone=False)  # Get corresponding position
                        pos.update(fill_size, fill_price)  # Refresh position
                        # -------------------------------------------------------------------
                        # Using order.executed.remsize to judge if all filled may be unreliable for market buy orders,
                        # so use following code to judge if partial or complete fill
                        if status == "open":  # If status is still open when there are fills, it must be partially filled
                            o_order.partial()
                        elif status == "closed":  # If status is closed when there are fills, it means completely filled
                            o_order.completed()
                        # -------------------------------------------------------------------
                        self.notify(o_order.clone())  # Notify strategy
            else:
                fill_dt, cum_fill_size, average_fill_price = (
                    ccxt_order["timestamp"],
                    ccxt_order["filled"],
                    ccxt_order["average"],
                )
                if cum_fill_size > abs(o_order.executed.size):  # Check if there are new fills this time
                    new_cum_fill_value = (
                        cum_fill_size * average_fill_price
                    )  # Cumulative fill quantity * average fill price = cumulative fill total value
                    old_cum_fill_value = abs(o_order.executed.size) * o_order.executed.price
                    fill_value = new_cum_fill_value - old_cum_fill_value  # Value of this new fill
                    fill_size = cum_fill_size - abs(o_order.executed.size)  # Quantity of this new fill
                    fill_price = fill_value / fill_size  # Price of this new fill
                    fill_size = (
                        fill_size if o_order.isbuy() else -fill_size
                    )  # Meet backtrader specification, sell orders or short positions use negative numbers
                    o_order.execute(
                        fill_dt, fill_size, fill_price, 0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0
                    )  # Process this fill, internally marks order status, partial or complete fill
                    # Prepare to notify upper strategy
                    # self.get_balance() #Refresh account balance (balance no longer updated, reduce communication to improve performance, can be updated as needed in strategy)
                    pos = self.getposition(o_order.data, clone=False)  # Get corresponding position
                    pos.update(fill_size, fill_price)  # Refresh position
                    # -------------------------------------------------------------------
                    # Using order.executed.remsize to judge if all filled may be unreliable for market buy orders,
                    # so use following code to judge if partial or complete fill
                    if status == "open":  # If status is still open when there are fills, it must be partially filled
                        o_order.partial()
                    elif status == "closed":  # If status is closed when there are fills, it means completely filled
                        o_order.completed()
                    # -------------------------------------------------------------------
                    self.notify(o_order.clone())  # Notify strategy

            if self.debug:
                pass  # print(json.dumps(ccxt_order, indent=self.indent))  # Removed for performance

            # Check if the order is closed
            if status == "closed":
                # If the order is completely filled, it will be in this status. Since strategy has been notified above, no need to notify again here
                self.open_orders.pop(oID, None)
                # Notify bracket manager of order completion
                if self._bracket_manager:
                    self._bracket_manager.on_order_update(o_order)
            elif status == "canceled":
                # Consider two cases: user placed limit order without fills and cancelled directly,
                # user placed limit order with partial fills then cancelled
                o_order.cancel()  # Mark order as cancelled
                self.notify(o_order.clone())  # Notify strategy
                self.open_orders.pop(oID, None)

    def _submit(self, owner, data, exectype, side, amount, price, params):
        """Submit an order to the exchange with error handling.

        Args:
            owner: Strategy that owns this order.
            data: Data feed for the order.
            exectype: Order execution type.
            side: 'buy' or 'sell'.
            amount: Order size.
            price: Order price (None for market).
            params: Additional parameters.

        Returns:
            CCXTOrder: The created order, or a rejected order on failure.
        """
        order_type = self.order_types.get(exectype) if exectype else "market"
        created = int(data.datetime.datetime(0).timestamp() * 1000)
        # Extract CCXT specific params if passed to the order
        params = params["params"] if "params" in params else params
        params["created"] = created  # Add timestamp of order creation for backtesting

        try:
            ret_ord = self._retry_api_call(
                self.store.create_order,
                symbol=data.p.dataname,
                order_type=order_type,
                side=side,
                amount=amount,
                price=price,
                params=params,
            )
        except (NetworkError, ExchangeNotAvailable) as e:
            print(f"[CCXTBroker] Order submission failed (network): {e}")
            # Create a rejected order to notify strategy
            ret_ord = {
                "id": f"failed_{created}",
                "status": "rejected",
                "error": str(e),
            }
            order = CCXTOrder(owner, data, exectype, side, amount, price, ret_ord)
            order.reject()
            self.notify(order.clone())
            return order
        except ExchangeError as e:
            print(f"[CCXTBroker] Order submission failed (exchange): {e}")
            ret_ord = {
                "id": f"failed_{created}",
                "status": "rejected",
                "error": str(e),
            }
            order = CCXTOrder(owner, data, exectype, side, amount, price, ret_ord)
            order.reject()
            self.notify(order.clone())
            return order

        order = CCXTOrder(owner, data, exectype, side, amount, price, ret_ord)
        self.open_orders[ret_ord["id"]] = order
        self.notify(order.clone())  # Send order creation notification first

        # Subscribe to WebSocket my_trades for this symbol (auto-dedup)
        if self._use_ws_orders and self._ws_order_manager:
            self._ws_subscribe_symbol(data.p.dataname)
        # Register with threaded order manager if available
        elif self._threaded_order_manager and self._threaded_order_manager.is_running():
            self._threaded_order_manager.add_order(ret_ord["id"], data.p.dataname)
        else:
            self._next()  # Then check if order has been filled, send notification if filled

        return order

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
        """Create a buy order.

        Args:
            owner: The strategy creating this order.
            data: The data feed to trade.
            size: Order size (positive for buy).
            price: Order price (None for market orders).
            plimit: Limit price for stop-limit orders.
            exectype: Order execution type (Market, Limit, Stop, StopLimit).
            valid: Order validity (e.g., Good Till Cancelled).
            tradeid: Trade identifier.
            oco: One-Cancels-Other order ID.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional parameters including 'params' for CCXT-specific
                options.

        Returns:
            CCXTOrder: The created order instance.
        """
        del kwargs["parent"]
        del kwargs["transmit"]
        return self._submit(owner, data, exectype, "buy", size, price, kwargs)

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
        """Create a sell order.

        Args:
            owner: The strategy creating this order.
            data: The data feed to trade.
            size: Order size (positive for sell, will be converted internally).
            price: Order price (None for market orders).
            plimit: Limit price for stop-limit orders.
            exectype: Order execution type (Market, Limit, Stop, StopLimit).
            valid: Order validity (e.g., Good Till Cancelled).
            tradeid: Trade identifier.
            oco: One-Cancels-Other order ID.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional parameters including 'params' for CCXT-specific
                options.

        Returns:
            CCXTOrder: The created order instance.
        """
        del kwargs["parent"]
        del kwargs["transmit"]
        return self._submit(owner, data, exectype, "sell", size, price, kwargs)

    def cancel(self, order):
        """Cancel an open order with error handling.

        Args:
            order: The CCXTOrder instance to cancel.

        Returns:
            CCXTOrder: The canceled order instance.

        Note:
            If the order is already filled or canceled, this method returns
            the order without taking action. Otherwise, it cancels the order
            on the exchange and updates the order status.
        """
        oID = order.ccxt_order["id"]

        if self.debug:
            print("Broker cancel() called")
            print(f"Fetching Order ID: {oID}")

        # check first if the order has already been filled, otherwise an error
        # might be raised if we try to cancel an order that is not open.
        try:
            ccxt_order = self._retry_api_call(self.store.fetch_order, oID, order.data.p.dataname)
        except (NetworkError, ExchangeNotAvailable) as e:
            print(f"[CCXTBroker] Cannot fetch order {oID} for cancel: {e}")
            return order
        except ExchangeError as e:
            print(f"[CCXTBroker] Exchange error fetching order {oID} for cancel: {e}")
            if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                order.cancel()
                self.notify(order.clone())
                self.open_orders.pop(oID, None)
            return order

        if self.debug:
            print(json.dumps(ccxt_order, indent=self.indent))

        if (ccxt_order[self.mappings["closed_order"]["key"]] == self.mappings["closed_order"]["value"]) or (
            ccxt_order[self.mappings["canceled_order"]["key"]] == self.mappings["canceled_order"]["value"]
        ):
            return order

        try:
            ccxt_order = self._retry_api_call(self.store.cancel_order, oID, order.data.p.dataname)
        except (NetworkError, ExchangeNotAvailable) as e:
            print(f"[CCXTBroker] Cannot cancel order {oID}: {e}")
            return order
        except ExchangeError as e:
            print(f"[CCXTBroker] Exchange error canceling order {oID}: {e}")
            return order

        if self.debug:
            print(json.dumps(ccxt_order, indent=self.indent))
            print("Value Received: {}".format(ccxt_order[self.mappings["canceled_order"]["key"]]))
            print("Value Expected: {}".format(self.mappings["canceled_order"]["value"]))

        # Unify strategy notification processing in next function
        self._next()
        if ccxt_order["status"] == "canceled":
            order.cancel()

        return order

    def get_orders_open(self, safe=False):
        """Get all open orders from the exchange.

        Args:
            safe: Unused parameter (kept for API compatibility).

        Returns:
            list: List of open order dictionaries from the exchange.
        """
        return self.store.fetch_open_orders()

    def private_end_point(self, type, endpoint, params):
        """Call a private API endpoint on the exchange.

        This method allows access to any private, non-unified endpoint provided
        by the CCXT exchange. For more details, see:
        https://github.com/ccxt/ccxt/wiki/Manual#implicit-api-methods

        Args:
            type: HTTP method type ('Get', 'Post', 'Put', or 'Delete').
            endpoint: String containing the endpoint address (e.g., 'order/{id}/cancel').
            params: Dictionary of parameters to send with the request.

        Returns:
            dict: Exchange-specific JSON result from the API, returned as-is
                without parsing.

        Example:
            To get a list of all available methods with an exchange instance:
            >>> print(dir(ccxt.hitbtc()))

            To call a private endpoint:
            >>> broker.private_end_point(
            ...     'Get',
            ...     'order/{id}/cancel',
            ...     {'id': '12345'}
            ... )
        """
        endpoint_str = endpoint.replace("/", "_")
        endpoint_str = endpoint_str.replace("{", "")
        endpoint_str = endpoint_str.replace("}", "")

        method_str = "private_" + type.lower() + endpoint_str.lower()

        return self.store.private_end_point(type=type, endpoint=method_str, params=params)

    def create_bracket_order(self, data, size, entry_price, stop_price, limit_price, entry_type=None, side="buy"):
        """Create a bracket order (entry + stop-loss + take-profit).

        A bracket order consists of three linked orders:
        1. Entry order (market or limit)
        2. Stop-loss order (triggered after entry fills)
        3. Take-profit order (triggered after entry fills)

        When either stop or take-profit fills, the other is cancelled (OCO).

        Args:
            data: Data feed for the order.
            size: Order size.
            entry_price: Entry order price.
            stop_price: Stop-loss price.
            limit_price: Take-profit price.
            entry_type: Entry order type (default: Limit).
            side: 'buy' for long, 'sell' for short.

        Returns:
            BracketOrder or None if bracket orders not available.
        """
        if not self._bracket_manager:
            print("Warning: Bracket orders not available. Install ccxt enhancements.")
            return None

        if entry_type is None:
            entry_type = Order.Limit

        return self._bracket_manager.create_bracket(
            data=data,
            size=size,
            entry_price=entry_price,
            stop_price=stop_price,
            limit_price=limit_price,
            entry_type=entry_type,
            side=side,
        )

    def get_bracket_manager(self):
        """Get the bracket order manager.

        Returns:
            BracketOrderManager or None.
        """
        return self._bracket_manager

    def stop(self):
        """Stop the broker and cleanup resources."""
        if self._threaded_order_manager:
            self._threaded_order_manager.stop()
        if hasattr(self.store, "stop"):
            self.store.stop()
