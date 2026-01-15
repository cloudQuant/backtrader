"""Crypto Broker Module - Cryptocurrency broker implementation.

This module provides the CryptoBroker for trading through bt_api_py
for cryptocurrency exchanges.

Classes:
    CryptoOrder: Crypto-specific order implementation.
    CryptoBroker: Broker implementation for crypto trading.

Example:
    >>> exchange_params = {...}
    >>> store = bt.stores.CryptoStore(exchange_params)
    >>> cerebro.setbroker(store.getbroker())
"""

import collections
from datetime import datetime

from ..broker import BrokerBase
from ..order import Order
from ..position import Position
from ..stores.cryptostore import CryptoStore
from ..utils.log_message import SpdLogManager
from ..utils.py3 import queue


class CryptoOrder(Order):
    """Crypto-specific order implementation for cryptocurrency trading.

    This class extends the base Order class to handle orders placed through
    cryptocurrency exchanges via the bt_api_py library.

    Attributes:
        owner: The strategy or object that owns this order.
        data: The data feed for this order.
        exectype: The order execution type (Market, Limit, etc.).
        ordtype: Order type (Buy or Sell).
        size: Order size/amount.
        price: Order price (None for market orders).
        data_type: Type of data ('order' or 'trade').
        bt_api_data: Raw API data from bt_api_py.
        executed_fills: List of executed fills for this order.
    """

    def __init__(self, owner, data, exectype, side, amount, price, data_type, bt_api_data):
        """Initialize a CryptoOrder instance.

        Args:
            owner: The strategy or object that owns this order.
            data: The data feed for this order.
            exectype: The order execution type (Market, Limit, etc.).
            side (str): Order side, either 'buy' or 'sell'.
            amount (float): Order size/amount.
            price (float, optional): Order price. None for market orders.
            data_type (str, optional): Type of data ('order' or 'trade'). Defaults to 'order'.
            bt_api_data: Raw API data from bt_api_py.
        """
        self.owner = owner
        self.data = data
        self.exectype = exectype
        self.ordtype = self.Buy if side == "buy" else self.Sell
        self.size = float(amount)
        self.price = float(price) if price else None
        self.data_type = data_type if data_type is not None else "order"
        self.bt_api_data = bt_api_data
        self.executed_fills = []
        super().__init__()


# Registration mechanism, automatically register broker class when module is imported
def _register_crypto_broker_class(broker_cls):
    """Register broker class with the store when module is loaded"""
    CryptoStore.BrokerCls = broker_cls
    return broker_cls


@_register_crypto_broker_class
class CryptoBroker(BrokerBase):
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

    def __init__(self, store=None, **kwargs):
        """Initialize the CryptoBroker instance.

        Args:
            store (CryptoStore, optional): CryptoStore instance for exchange connection.
                If None, will be retrieved from strategy data feed.
            **kwargs: Additional keyword arguments:
                debug (bool, optional): Enable debug logging. Defaults to True.

        Notes:
            - Initializes cash and value tracking.
            - Sets up logging system.
            - Creates position tracking dictionary.
            - Initializes notification queue and order lists.
        """
        super().__init__()
        self.value = None
        self.cash = None
        self.startingvalue = None
        self.startingcash = None
        self.store = None
        self.debug = kwargs.get("debug", True)
        self.logger = self.init_logger()
        self.init_store(store)
        self.positions = collections.defaultdict(Position)
        self.indent = 4  # For pretty printing dictionaries
        self.notifs = queue.Queue()  # holds orders which are notified
        self.open_orders = list()
        self._last_op_time = 0

    def init_store(self, store):
        """Initialize the store connection and set initial cash and value.

        Args:
            store (CryptoStore, optional): CryptoStore instance for exchange connection.
                If None, will be retrieved from strategy data feed.

        Notes:
            - Sets the store attribute.
            - Retrieves initial cash and value from store.
            - Logs initialization status.
        """
        if store is not None:
            self.store = store
        else:
            self.store = self.strategy.datas[0].store
        self.debug = self.store.debug
        self.startingcash = self.store.getcash()
        self.startingvalue = self.store.getvalue()
        self.log(f"init store success, debug = {self.debug}")

    def init_logger(self):
        """Initialize the logger for broker operations.

        Returns:
            logging.Logger: Configured logger instance.

        Notes:
            - Uses SpdLogManager to create logger.
            - Logs to 'cryptofeed.log' file.
            - Print info enabled/disabled based on debug flag.
        """
        if self.debug:
            print_info = True
        else:
            print_info = False
        logger = SpdLogManager(
            file_name="cryptofeed.log", logger_name="feed", print_info=print_info
        ).create_logger()
        return logger

    def log(self, txt, level="info"):
        """Log a message at the specified level.

        Args:
            txt (str): Message text to log.
            level (str, optional): Log level - 'info', 'warning', 'error', or 'debug'.
                Defaults to 'info'.
        """
        if level == "info":
            self.logger.info(txt)
        elif level == "warning":
            self.logger.warning(txt)
        elif level == "error":
            self.logger.error(txt)
        elif level == "debug":
            self.logger.debug(txt)
        else:
            pass

    def getcash(self, data=None, cache=True):
        """Get the available cash for trading.

        Args:
            data (DataFeed, optional): Data feed to get cash for. If None, uses first data feed.
            cache (bool, optional): Whether to use cached values. Defaults to True.

        Returns:
            float: Available cash amount in the account's base currency.

        Notes:
            - Retrieves cash from the store.
            - Extracts currency from symbol name (e.g., BTC-USDT -> USDT).
            - Returns cash for specific exchange and currency if data provided.
        """
        cash = self.store.getcash(cache=cache)
        if data is None:
            data = self.cerebro.datas[0]
        if data is not None:
            exchange_name = data.get_exchange_name()
            symbol_name = data.get_symbol_name()
            currency = symbol_name.split("-")[1]
            cash = cash.get(exchange_name, -1.0)
            if isinstance(cash, dict) and currency is not None:
                cash = cash.get(currency, -1.0)
                if isinstance(cash, dict):
                    cash = cash["cash"]
                    return cash
        return cash

    def getvalue(self, data=None, cache=True):
        """Get the total portfolio value including cash and positions.

        Args:
            data (DataFeed, optional): Data feed to get value for. If None, uses first data feed.
            cache (bool, optional): Whether to use cached values. Defaults to True.

        Returns:
            float: Total portfolio value in the account's base currency.

        Notes:
            - Retrieves value from the store.
            - Extracts currency from symbol name (e.g., BTC-USDT -> USDT).
            - Returns value for specific exchange and currency if data provided.
        """
        value = self.store.getvalue(cache=cache)
        if data is None:
            data = self.cerebro.datas[0]
        if data is not None:
            exchange_name = data.get_exchange_name()
            symbol_name = data.get_symbol_name()
            currency = symbol_name.split("-")[1]
            value = value.get(exchange_name, -1.0)
            if isinstance(value, dict) and currency is not None:
                value = value.get(currency, -1.0)
                if isinstance(value, dict):
                    value = value["value"]
                    return value
        return value

    def get_notification(self):
        """Get the next notification from the queue without blocking.

        Returns:
            CryptoOrder or None: The next order notification, or None if queue is empty.

        Notes:
            - Non-blocking get from notification queue.
            - Returns None immediately if no notifications available.
        """
        try:
            return self.notifs.get(False)
        except queue.Empty:
            return None

    def notify(self, order):
        """Add an order notification to the queue.

        Args:
            order (CryptoOrder): The order to notify about.

        Notes:
            - Puts order in notification queue for later retrieval.
            - Used to signal order status changes to strategy.
        """
        self.notifs.put(order)

    def getposition(self, data, clone=True):
        """Get the current position for a data feed.

        Args:
            data (DataFeed): Data feed to get position for.
            clone (bool, optional): Whether to return a clone of the position. Defaults to True.

        Returns:
            Position: Current position for the data feed.

        Notes:
            - Positions are stored internally by data feed name.
            - Cloning prevents modification of internal position state.
        """
        # return self.o.getposition(data._dataname, clone=clone)
        pos = self.positions[data.get_name()]
        if clone:
            pos = pos.clone()
        return pos

    def next(self):
        """Called on each iteration to process broker updates.

        Notes:
            - Implements rate limiting (1 second between operations).
            - Calls internal _next method to process queues.
            - Prevents excessive API calls to exchange.
        """
        # ===========================================
        # Operate every 3 seconds
        nts = datetime.now().timestamp()
        if nts - self._last_op_time < 1:
            return
        self._last_op_time = nts
        # ===========================================
        self._next()

    def _next(self):
        """Internal method to process order and trade updates from store.

        Notes:
            - Retrieves orders from store order queue and converts to backtrader format.
            - Retrieves trades from store trade queue and converts to backtrader format.
            - Sends notifications for each converted order/trade.
            - Non-blocking: processes all available items then returns.
        """
        # Get order info, trade info, position info, account info from store, and pass to strategy
        while True:
            try:
                data = self.store.order_queue.get(block=False)  # non-blocking
            except queue.Empty:
                break  # no data in the queue
            order = self.convert_bt_api_order_to_backtrader_order(data)
            self.notify(order)
        while True:
            try:
                data = self.store.trade_queue.get(block=False)
            except queue.Empty:
                break
            trade = self.convert_bt_api_trade_to_backtrader_trade(data)
            self.notify(trade)

    def getdatabyname(self, name):
        """Get a data feed by name from cerebro.

        Args:
            name (str): Name of the data feed to find.

        Returns:
            DataFeed or None: The matching data feed, or None if not found.

        Notes:
            - Iterates through all data feeds in cerebro.
            - Compares data feed names using get_name() method.
        """
        for data in self.cerebro.datas:
            print(data.get_name(), name)
            if data.get_name() == name:
                return data
        return None

    def convert_bt_api_order_to_backtrader_order(self, data):
        """Convert bt_api_py order data to backtrader CryptoOrder format.

        Args:
            data: bt_api_py order data object.

        Returns:
            CryptoOrder: Converted order in backtrader format.

        Notes:
            - Normalizes symbol names (e.g., adds dash to BTCUSDT -> BTC-USDT).
            - Removes suffixes like -SWAP and -SPOT.
            - Constructs data name from exchange, asset type, and symbol.
            - Logs order details for debugging.
        """
        data.init_data()
        exchange_name = data.get_exchange_name()
        symbol_name = data.get_symbol_name()
        if "-" not in symbol_name:
            if "USDT" in symbol_name:
                symbol_name = symbol_name.replace("USDT", "-USDT")
        if "-SWAP" in symbol_name:
            symbol_name = symbol_name.replace("-SWAP", "")
        if "-SPOT" in symbol_name:
            symbol_name = symbol_name.replace("-SPOT", "")

        asset_type = data.get_asset_type()
        data_name = exchange_name + "___" + asset_type + "___" + symbol_name
        exectype = data.get_order_type()
        order_side = data.get_order_side()
        order_amount = data.get_order_size()
        order_price = data.get_order_price()
        trade_data = self.getdatabyname(data_name)
        self.log(f"data_name = {data_name}, order_side = {order_side}, order_price = {order_price}")
        return CryptoOrder(
            None, trade_data, exectype, order_side, order_amount, order_price, "order", data
        )

    def convert_bt_api_trade_to_backtrader_trade(self, data):
        """Convert bt_api_py trade data to backtrader CryptoOrder format.

        Args:
            data: bt_api_py trade data object.

        Returns:
            CryptoOrder: Converted trade in backtrader format.

        Notes:
            - Normalizes symbol names (e.g., adds dash to BTCUSDT -> BTC-USDT).
            - Removes suffixes like -SWAP and -SPOT.
            - Constructs data name from exchange, asset type, and symbol.
            - Trade type is used for both exectype and side in CryptoOrder.
        """
        data.init_data()
        exchange_name = data.get_exchange_name()
        symbol_name = data.get_symbol_name()
        if "-" not in symbol_name:
            if "USDT" in symbol_name:
                symbol_name = symbol_name.replace("USDT", "-USDT")
        if "-SWAP" in symbol_name:
            symbol_name = symbol_name.replace("-SWAP", "")
        if "-SPOT" in symbol_name:
            symbol_name = symbol_name.replace("-SPOT", "")

        asset_type = data.get_asset_type()
        data_name = exchange_name + "___" + asset_type + "___" + symbol_name
        exectype = data.get_trade_type()
        trade_volume = data.get_trade_volume()
        price = data.get_price()
        trade_data = self.getdatabyname(data_name)
        return CryptoOrder(None, trade_data, exectype, exectype, trade_volume, price, "trade", data)

    def _submit(
        self,
        owner,
        data,
        size,
        side=None,
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
        """Submit an order to the cryptocurrency exchange.

        Args:
            owner: The strategy or object that owns this order.
            data (DataFeed): Data feed for the order.
            size (float): Order size (positive for buy, negative for sell).
            side (str, optional): Order side - 'buy' or 'sell'.
            price (float, optional): Order price (None for market orders).
            plimit (float, optional): Limit price for stop-limit orders.
            exectype (Order.ExecType, optional): Order execution type.
            valid (Order.Valid, optional): Order validity type.
            tradeid (int, optional): Trade identifier. Defaults to 0.
            oco (bool, optional): One cancels other order flag.
            trailamount (float, optional): Trailing amount for trailing orders.
            trailpercent (float, optional): Trailing percent for trailing orders.
            **kwargs: Additional broker-specific parameters.

        Returns:
            CryptoOrder: The created order object.

        Notes:
            - Logs order submission.
            - Constructs order type from side and exectype.
            - Delegates to store.make_order for actual submission.
        """
        self.log("crypto broker begin to submit order")
        order_type = side + "-" + exectype
        ret_ord = self.store.make_order(data, size, price=price, order_type=order_type, **kwargs)
        order = CryptoOrder(owner, data, exectype, side, size, price, "order", ret_ord)
        # self.open_orders.append(order)
        # self.notify(order.clone())  # Send order creation notification first
        # self._next()  # Then check if order is executed, if executed send notification
        return order

    # Buy order
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
        """Submit a buy order to the cryptocurrency exchange.

        Args:
            owner: The strategy or object that owns this order.
            data (DataFeed): Data feed for the order.
            size (float): Order size (must be positive).
            price (float, optional): Order price (None for market orders).
            plimit (float, optional): Limit price for stop-limit orders.
            exectype (Order.ExecType, optional): Order execution type.
            valid (Order.Valid, optional): Order validity type.
            tradeid (int, optional): Trade identifier. Defaults to 0.
            oco (bool, optional): One cancels other order flag.
            trailamount (float, optional): Trailing amount for trailing orders.
            trailpercent (float, optional): Trailing percent for trailing orders.
            **kwargs: Additional broker-specific parameters.

        Returns:
            CryptoOrder: The created buy order.

        Notes:
            - Removes 'parent' and 'transmit' from kwargs before submission.
            - Logs buy order creation.
        """
        print("crypto_broker begin to buy")
        self.log("crypto_broker begin to buy")
        kwargs.pop("parent", None)
        kwargs.pop("transmit", None)
        return self._submit(owner, data, size, "buy", price, exectype=exectype, **kwargs)

    # Sell order
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
        """Submit a sell order to the cryptocurrency exchange.

        Args:
            owner: The strategy or object that owns this order.
            data (DataFeed): Data feed for the order.
            size (float): Order size (must be positive).
            price (float, optional): Order price (None for market orders).
            plimit (float, optional): Limit price for stop-limit orders.
            exectype (Order.ExecType, optional): Order execution type.
            valid (Order.Valid, optional): Order validity type.
            tradeid (int, optional): Trade identifier. Defaults to 0.
            oco (bool, optional): One cancels other order flag.
            trailamount (float, optional): Trailing amount for trailing orders.
            trailpercent (float, optional): Trailing percent for trailing orders.
            **kwargs: Additional broker-specific parameters.

        Returns:
            CryptoOrder: The created sell order.

        Notes:
            - Removes 'parent' and 'transmit' from kwargs before submission.
            - Logs sell order creation.
        """
        self.log("crypto_broker begin to sell")
        kwargs.pop("parent", None)
        kwargs.pop("transmit", None)
        return self._submit(owner, data, size, "sell", price, exectype=exectype, **kwargs)

    # Cancel a specific unfilled order
    def cancel(self, order):
        """Cancel an existing order on the exchange.

        Args:
            order (CryptoOrder): The order to cancel.

        Notes:
            - Delegates to store.cancel_order for actual cancellation.
            - Order status will be updated through notification queue.
        """
        self.store.cancel_order(order)

    # Used to close all positions
    def close(self, owner, data):
        """Close all positions for a given data feed.

        Args:
            owner: The strategy or object that owns the positions.
            data (DataFeed): Data feed to close positions for.

        Notes:
            - Currently not implemented (pass only).
            - Future implementation should submit market orders to flatten positions.
        """
        pass

    # User gets unfilled order info through this interface
    def get_open_orders(self, data=None, cache=True):
        """Get all open (unfilled) orders.

        Args:
            data (DataFeed, optional): Data feed to filter orders by. If None, returns all orders.
            cache (bool, optional): If True, returns cached open_orders. If False, queries store.
                Defaults to True.

        Returns:
            list: List of open CryptoOrder objects.

        Notes:
            - When cache=True, returns internally tracked open_orders list.
            - When cache=False, queries store for live order data.
        """
        if cache:
            return self.open_orders
        else:
            return self.store.get_open_orders(data)

    # def getposition(self, data, clone=True):
    #     pos = self.positions[data._dataname]
    #     if clone:
    #         pos = pos.clone()
    #     return pos
    #
    # def orderstatus(self, order):
    #     o = self.orders[order.ref]
    #     return o.status
    #
    # def _submit(self, oref):
    #     order = self.orders[oref]
    #     order.submit(self)
    #     self.notify(order)
    #
    # def _reject(self, oref):
    #     order = self.orders[oref]
    #     order.reject(self)
    #     self.notify(order)
    #
    # def _accept(self, oref):
    #     order = self.orders[oref]
    #     order.accept()
    #     self.notify(order)
    #
    # def _cancel(self, oref):
    #     order = self.orders[oref]
    #     order.cancel()
    #     self.notify(order)
    #
    # def _expire(self, oref):
    #     order = self.orders[oref]
    #     order.expire()
    #     self.notify(order)
    #
    # def notify(self, order):
    #     self.notifs.append(order.clone())
    #
    # def get_notification(self):
    #     if not self.notifs:
    #         return None
    #     return self.notifs.popleft()

    # def next(self):
    #     self.notifs.append(None)  # mark notification boundary
