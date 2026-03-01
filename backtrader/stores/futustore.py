#!/usr/bin/env python
"""Futu Store Module - Futu OpenD trading integration.

This module provides the FutuStore for connecting to Futu OpenD
for Hong Kong/US/A-Share stock trading.

Classes:
    FutuStore: Singleton store for Futu OpenD connections.

Example:
    >>> store = bt.stores.FutuStore(
    ...     host='127.0.0.1',
    ...     port=11111
    ... )
    >>> cerebro.setbroker(store.getbroker())

Note:
    Requires futu-api package: pip install futu-api
    And FutuOpenD running locally or accessible via network.
"""

from datetime import datetime

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.utils.py3 import queue

# Try to import futu API
try:
    from futu import (
        RET_ERROR,
        RET_OK,
        KLType,
        OpenQuoteContext,
        OpenSecTradeContext,
        StockQuoteHandlerBase,
        SubType,
        TrdEnv,
        TrdMarket,
    )

    HAS_FUTU = True
except ImportError:
    HAS_FUTU = False
    OpenQuoteContext = None
    OpenSecTradeContext = None


class FutuQuoteHandler(StockQuoteHandlerBase if HAS_FUTU else object):
    """Handler for real-time stock quotes from Futu.

    This class processes incoming quote data from Futu OpenD and distributes
    it to registered market data queues.

    Attributes:
        md_queue: Dictionary mapping stock codes to their market data queues.
    """

    def __init__(self, md_queue=None):
        """Initialize the FutuQuoteHandler.

        Args:
            md_queue: Dictionary mapping stock codes to queues for quote
                distribution. If None, uses an empty dict.
        """
        if HAS_FUTU:
            super().__init__()
        self.md_queue = md_queue or {}

    def on_recv_rsp(self, rsp_str):
        """Handle received quote response from Futu OpenD.

        This method is called automatically when new quote data is received.
        It parses the response and distributes data to appropriate queues.

        Args:
            rsp_str: Raw response string from Futu API containing quote data.

        Returns:
            tuple: A tuple of (ret_code, data) where:
                - ret_code: RET_OK if successful, RET_ERROR otherwise.
                - data: pandas DataFrame with quote data, or error message.
        """
        if not HAS_FUTU:
            return RET_ERROR, None
        ret_code, data = super().on_recv_rsp(rsp_str)
        if ret_code != RET_OK:
            return RET_ERROR, data

        # Distribute data to corresponding queues
        for _, row in data.iterrows():
            code = row["code"]
            if code in self.md_queue:
                self.md_queue[code].put(row.to_dict())

        return RET_OK, data


class FutuStore(ParameterizedSingletonMixin):
    """Singleton store for Futu OpenD connections.

    This class provides connection management and API access for Futu OpenD,
    supporting Hong Kong, US, and China A-Share markets. It handles both
    market data retrieval and order execution.

    The store implements a singleton pattern ensuring only one connection
    exists per unique set of connection parameters.

    Attributes:
        host: Futu OpenD host address.
        port: Futu OpenD port number.
        trd_env: Trading environment (REAL or SIMULATE).
        market: Trading market (HK, US, CN, etc.).
        quote_ctx: OpenQuoteContext for market data operations.
        trade_ctx: OpenSecTradeContext for order execution.
    """

    # Supported timeframes mapping
    _GRANULARITIES = {
        (4, 1): KLType.K_1M if HAS_FUTU else "1m",  # 1 minute
        (4, 5): KLType.K_5M if HAS_FUTU else "5m",  # 5 minutes
        (4, 15): KLType.K_15M if HAS_FUTU else "15m",  # 15 minutes
        (4, 30): KLType.K_30M if HAS_FUTU else "30m",  # 30 minutes
        (4, 60): KLType.K_60M if HAS_FUTU else "1h",  # 1 hour
        (5, 1): KLType.K_DAY if HAS_FUTU else "1d",  # 1 day
        (6, 1): KLType.K_WEEK if HAS_FUTU else "1w",  # 1 week
        (7, 1): KLType.K_MON if HAS_FUTU else "1M",  # 1 month
    }

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Create a data feed instance for Futu market data.

        This is a factory method that returns a DataCls instance configured
        with the provided arguments.

        Args:
            *args: Positional arguments to pass to DataCls constructor.
            **kwargs: Keyword arguments to pass to DataCls constructor.

        Returns:
            DataCls: An instance of the registered data feed class.
        """
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Create a broker instance for Futu order execution.

        This is a factory method that returns a BrokerCls instance configured
        with the provided arguments for trading operations.

        Args:
            *args: Positional arguments to pass to BrokerCls constructor.
            **kwargs: Keyword arguments to pass to BrokerCls constructor.

        Returns:
            BrokerCls: An instance of the registered broker class.
        """
        return cls.BrokerCls(*args, **kwargs)

    def __init__(
        self,
        host="127.0.0.1",
        port=11111,
        trd_env=None,
        market=None,
        password=None,
        debug=False,
        **kwargs,
    ):
        """Initialize the FutuStore instance.

        Creates connections to Futu OpenD for both market data and trading
        operations. Sets up the quote handler for real-time data streaming.

        Args:
            host: Futu OpenD host address. Defaults to '127.0.0.1'.
            port: Futu OpenD port number. Defaults to 11111.
            trd_env: Trading environment (TrdEnv.REAL or TrdEnv.SIMULATE).
                Defaults to TrdEnv.SIMULATE.
            market: Trading market (TrdMarket.HK, TrdMarket.US, etc.).
                Defaults to TrdMarket.HK.
            password: Trading password for unlocking real trading. Required
                for TrdEnv.REAL.
            debug: Enable debug output for logging. Defaults to False.
            **kwargs: Additional keyword arguments passed to parent class.

        Raises:
            ImportError: If futu-api package is not installed.
        """
        super().__init__()

        if not HAS_FUTU:
            raise ImportError(
                "futu-api package is required for FutuStore. Install it with: pip install futu-api"
            )

        self.host = host
        self.port = port
        self.trd_env = trd_env or TrdEnv.SIMULATE
        self.market = market or TrdMarket.HK
        self.password = password
        self.debug = debug

        # Initialize values
        self._cash = 0.0
        self._value = 0.0

        # Market data queues for each feed
        self.q_feed_qlive = {}

        # Create contexts
        self.quote_ctx = OpenQuoteContext(host=host, port=port)
        self.trade_ctx = OpenSecTradeContext(host=host, port=port)

        # Set trading environment
        self.trade_ctx.set_trd_env(self.trd_env)

        # Unlock trade if password provided
        if password and self.trd_env == TrdEnv.REAL:
            ret, data = self.trade_ctx.unlock_trade(password)
            if ret != RET_OK:
                print(f"Warning: Failed to unlock trade: {data}")

        # Set up quote handler
        self.quote_handler = FutuQuoteHandler(md_queue=self.q_feed_qlive)
        self.quote_ctx.set_handler(self.quote_handler)

        # Get initial balance
        self.get_balance()

        if debug:
            print(f"FutuStore initialized: {host}:{port}, market={market}")

    def register(self, feed):
        """Register a data feed for real-time market data updates.

        Creates a new queue for the feed's symbol to receive live quotes.

        Args:
            feed: Data feed instance with a 'p.dataname' attribute containing
                the stock code.

        Returns:
            queue.Queue: A queue instance for receiving market data updates
                for the registered feed.
        """
        self.q_feed_qlive[feed.p.dataname] = queue.Queue()
        return self.q_feed_qlive[feed.p.dataname]

    def subscribe(self, dataname, subtype=None):
        """Subscribe to market data for a specific symbol.

        Registers interest in a stock's market data through Futu OpenD,
        enabling real-time quote updates.

        Args:
            dataname: Stock code to subscribe to (e.g., 'HK.00700' for
                Tencent, 'US.AAPL' for Apple).
            subtype: List of subscription types (e.g., SubType.QUOTE for
                quotes, SubType.K_1M for 1-minute K-line). Defaults to
                [SubType.QUOTE, SubType.K_1M].

        Returns:
            bool: True if subscription was successful, False otherwise.
        """
        if subtype is None:
            subtype = [SubType.QUOTE, SubType.K_1M]

        ret, data = self.quote_ctx.subscribe([dataname], subtype)
        if ret != RET_OK:
            print(f"Failed to subscribe to {dataname}: {data}")
            return False

        if self.debug:
            print(f"Subscribed to {dataname}")
        return True

    def get_granularity(self, timeframe, compression):
        """Convert backtrader timeframe to Futu K-line type.

        Maps backtrader timeframe and compression codes to the corresponding
        Futu KLType enum values for K-line data requests.

        Args:
            timeframe: Backtrader timeframe code (e.g., 4 for minutes,
                5 for days, 6 for weeks, 7 for months).
            compression: Compression multiplier for the timeframe.

        Returns:
            KLType: Futu K-line type enum value (e.g., KLType.K_1M,
                KLType.K_DAY).

        Raises:
            ValueError: If the timeframe/compression combination is not
                supported.
        """
        kl_type = self._GRANULARITIES.get((timeframe, compression))
        if kl_type is None:
            raise ValueError(f"Unsupported timeframe/compression: {timeframe}/{compression}")
        return kl_type

    def fetch_ohlcv(self, symbol, kl_type, start=None, end=None, limit=100):
        """Fetch historical OHLCV data from Futu.

        Retrieves historical K-line (candlestick) data for a specified symbol
        and K-line type.

        Args:
            symbol: Stock code to fetch data for (e.g., 'HK.00700').
            kl_type: K-line type (KLType.K_1M, KLType.K_DAY, etc.).
            start: Start date string in 'YYYY-MM-DD' format. Optional.
            end: End date string in 'YYYY-MM-DD' format. Optional.
            limit: Maximum number of bars to fetch. Defaults to 100.

        Returns:
            list: List of OHLCV data where each element is
                [timestamp, open, high, low, close, volume]. Returns empty
                list on error.
        """
        ret, data, _ = self.quote_ctx.request_history_kline(
            symbol, ktype=kl_type, start=start, end=end, max_count=limit
        )

        if ret != RET_OK:
            print(f"Failed to fetch OHLCV for {symbol}: {data}")
            return []

        # Convert to list of [timestamp, open, high, low, close, volume]
        result = []
        for _, row in data.iterrows():
            dt = datetime.strptime(row["time_key"], "%Y-%m-%d %H:%M:%S")
            timestamp = int(dt.timestamp() * 1000)
            result.append(
                [timestamp, row["open"], row["high"], row["low"], row["close"], row["volume"]]
            )

        return result

    def get_balance(self):
        """Query account balance from Futu.

        Retrieves and updates the internal cash and total asset values from
        the Futu trading account.

        Side Effects:
            Updates self._cash with available cash.
            Updates self._value with total account value.
        """
        ret, data = self.trade_ctx.accinfo_query(trd_env=self.trd_env, market=self.market)
        if ret != RET_OK:
            print(f"Failed to get balance: {data}")
            return

        if len(data) > 0:
            self._cash = float(data["cash"][0]) if "cash" in data.columns else 0.0
            self._value = float(data["total_assets"][0]) if "total_assets" in data.columns else 0.0

        if self.debug:
            print(f"Balance: cash={self._cash}, value={self._value}")

    def get_positions(self):
        """Query current positions from Futu.

        Retrieves all open positions in the trading account.

        Returns:
            list: List of position dictionaries, each containing:
                - symbol (str): Stock code.
                - size (int): Position quantity.
                - price (float): Cost price.
                - market_value (float): Current market value.
                - pl (float): Profit/loss value.
        """
        ret, data = self.trade_ctx.position_list_query(trd_env=self.trd_env, market=self.market)

        if ret != RET_OK:
            print(f"Failed to get positions: {data}")
            return []

        positions = []
        for _, row in data.iterrows():
            positions.append(
                {
                    "symbol": row["code"],
                    "size": row["qty"],
                    "price": row["cost_price"],
                    "market_value": row["market_val"],
                    "pl": row["pl_val"],
                }
            )

        return positions

    def get_cash(self):
        """Get available cash balance.

        Returns:
            float: Current available cash for trading.
        """
        return self._cash

    def get_value(self):
        """Get total account value.

        Returns:
            float: Total account value including cash and positions.
        """
        return self._value

    def create_order(self, symbol, order_type, side, amount, price=None, **kwargs):
        """Create and place a new order on Futu.

        Submits a buy or sell order to the Futu trading system.

        Args:
            symbol: Stock code to trade (e.g., 'HK.00700').
            order_type: Order type ('market' for market order, any other
                value for limit order).
            side: Order side - 'buy' or 'sell'.
            amount: Order quantity in shares.
            price: Limit price for limit orders. Required for limit orders,
                ignored for market orders.
            **kwargs: Additional order parameters (e.g., time_in_force).

        Returns:
            dict: Order information dictionary containing order details,
                or None if order creation failed.
        """
        from futu import OrderType as FutuOrderType
        from futu import TrdSide

        trd_side = TrdSide.BUY if side.lower() == "buy" else TrdSide.SELL

        # Map order type
        if order_type == "market":
            futu_order_type = FutuOrderType.MARKET
        else:
            futu_order_type = FutuOrderType.NORMAL

        ret, data = self.trade_ctx.place_order(
            price=price or 0,
            qty=amount,
            code=symbol,
            trd_side=trd_side,
            order_type=futu_order_type,
            trd_env=self.trd_env,
            **kwargs,
        )

        if ret != RET_OK:
            print(f"Failed to create order: {data}")
            return None

        return data.to_dict("records")[0] if len(data) > 0 else None

    def cancel_order(self, order_id, **kwargs):
        """Cancel an existing order.

        Cancels a previously placed order by its order ID.

        Args:
            order_id: The order ID to cancel.
            **kwargs: Additional parameters (currently unused).

        Returns:
            dict: Cancellation result information, or None if cancellation
                failed.
        """
        ret, data = self.trade_ctx.modify_order(
            modify_order_op=2,
            order_id=order_id,
            qty=0,
            price=0,
            trd_env=self.trd_env,  # Cancel
        )

        if ret != RET_OK:
            print(f"Failed to cancel order: {data}")
            return None

        return data.to_dict("records")[0] if len(data) > 0 else None

    def fetch_order(self, order_id):
        """Fetch order status and details.

        Retrieves current information about an existing order.

        Args:
            order_id: The order ID to query.

        Returns:
            dict: Order information dictionary containing current order
                status and details, or None if query failed.
        """
        ret, data = self.trade_ctx.order_list_query(order_id=order_id, trd_env=self.trd_env)

        if ret != RET_OK:
            print(f"Failed to fetch order: {data}")
            return None

        return data.to_dict("records")[0] if len(data) > 0 else None

    def stop(self):
        """Close all connections to Futu OpenD.

        Gracefully shuts down both quote and trade contexts, releasing
        network resources.
        """
        if self.quote_ctx:
            self.quote_ctx.close()
        if self.trade_ctx:
            self.trade_ctx.close()
