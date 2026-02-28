#!/usr/bin/env python
"""CCXT Store Module - Cryptocurrency exchange connections.

This module provides the CCXTStore for connecting to cryptocurrency
exchanges through the CCXT library with enhanced features.

Features:
    - Rate limiting with automatic wait
    - Connection management with auto-reconnect
    - WebSocket support (optional, requires ccxt.pro)
    - Exchange-specific configuration

Example:
    >>> store = bt.stores.CCXTStore(
    ...     exchange='binance',
    ...     currency='USDT',
    ...     config={'apiKey': 'xxx', 'secret': 'xxx'}
    ... )
"""

import logging
import time
from datetime import datetime
from functools import wraps

import ccxt
from ccxt.base.errors import ExchangeError, NetworkError

from backtrader.mixins.singleton import ParameterizedSingletonMixin

logger = logging.getLogger(__name__)

# TimeFrame constants to avoid circular import with backtrader
# Values match backtrader.dataseries.TimeFrame
_TF_MINUTES = 4
_TF_DAYS = 5
_TF_WEEKS = 6
_TF_MONTHS = 7
_TF_YEARS = 8

# Import enhancement modules
try:
    from backtrader.ccxt.config import ExchangeConfig
    from backtrader.ccxt.connection import ConnectionManager
    from backtrader.ccxt.ratelimit import AdaptiveRateLimiter, RateLimiter
    from backtrader.ccxt.websocket import CCXTWebSocketManager

    HAS_CCXT_ENHANCEMENTS = True
except ImportError:
    HAS_CCXT_ENHANCEMENTS = False
    RateLimiter = None
    ConnectionManager = None
    ExchangeConfig = None
    CCXTWebSocketManager = None


class CCXTStore(ParameterizedSingletonMixin):
    """API provider for CCXT feed and broker classes.

    Added a new get_wallet_balance method. This will allow manual checking of the balance.
        The method will allow setting parameters. Useful for getting margin balances

    Added new private_end_point method to allow using any private non-unified end point

    """

    # Supported granularities (using constants to avoid circular import)
    _GRANULARITIES = {
        (_TF_MINUTES, 1): "1m",
        (_TF_MINUTES, 3): "3m",
        (_TF_MINUTES, 5): "5m",
        (_TF_MINUTES, 15): "15m",
        (_TF_MINUTES, 30): "30m",
        (_TF_MINUTES, 60): "1h",
        (_TF_MINUTES, 90): "90m",
        (_TF_MINUTES, 120): "2h",
        (_TF_MINUTES, 180): "3h",
        (_TF_MINUTES, 240): "4h",
        (_TF_MINUTES, 360): "6h",
        (_TF_MINUTES, 480): "8h",
        (_TF_MINUTES, 720): "12h",
        (_TF_DAYS, 1): "1d",
        (_TF_DAYS, 3): "3d",
        (_TF_WEEKS, 1): "1w",
        (_TF_WEEKS, 2): "2w",
        (_TF_MONTHS, 1): "1M",
        (_TF_MONTHS, 3): "3M",
        (_TF_MONTHS, 6): "6M",
        (_TF_YEARS, 1): "1y",
    }

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    def getdata(self, *args, **kwargs):
        """Returns data feed with this store instance.

        This instance method creates a data feed that uses this store instance
        rather than creating a new one.

        Returns:
            CCXTFeed: A data feed instance connected to this store.
        """
        # Pass this store instance to the data feed
        kwargs["store"] = self
        return self.DataCls(*args, **kwargs)

    def getbroker(self, *args, **kwargs):
        """Returns broker with this store instance.

        This instance method creates a broker that uses this store instance
        rather than creating a new one.

        Returns:
            CCXTBroker: A broker instance connected to this store.
        """
        # Pass this store instance to the broker
        kwargs["store"] = self
        return self.BrokerCls(*args, **kwargs)

    def __init__(
        self,
        exchange,
        currency,
        config,
        retries,
        debug=False,
        sandbox=False,
        use_rate_limiter=True,
        use_connection_manager=False,
    ):
        """Initialize the CCXTStore.

        Args:
            exchange: Exchange ID (e.g., 'binance', 'okx').
            currency: Base currency for balance (e.g., 'USDT').
            config: Exchange configuration dict with API keys.
            retries: Number of retry attempts for failed requests.
            debug: Enable debug output.
            sandbox: Use exchange sandbox/testnet mode.
            use_rate_limiter: Enable intelligent rate limiting.
            use_connection_manager: Enable auto-reconnect management.
        """
        # Merge with exchange-specific defaults if available
        if HAS_CCXT_ENHANCEMENTS and ExchangeConfig:
            config = ExchangeConfig.merge_config(exchange, config)

        self.exchange_id = exchange
        self.exchange = getattr(ccxt, exchange)(config)
        self._sandbox = sandbox
        if sandbox:
            self.exchange.set_sandbox_mode(True)
        self.currency = currency
        self.retries = retries
        self.debug = debug

        # Initialize rate limiter
        self._rate_limiter = None
        if use_rate_limiter and HAS_CCXT_ENHANCEMENTS and RateLimiter:
            rpm = ExchangeConfig.get_rate_limit(exchange) if ExchangeConfig else 1200
            self._rate_limiter = AdaptiveRateLimiter(requests_per_minute=rpm)

        # Initialize connection manager
        self._connection_manager = None
        if use_connection_manager and HAS_CCXT_ENHANCEMENTS and ConnectionManager:
            self._connection_manager = ConnectionManager(self)
            self._connection_manager.start_monitoring()

        # Shared WebSocket manager (lazy-initialized on first request)
        self._ws_manager = None

        # Fetch initial balance with retry logic for network resilience
        balance = 0
        if "secret" in config:
            for attempt in range(retries):
                try:
                    balance = self.exchange.fetch_balance()
                    break
                except NetworkError as e:
                    if attempt < retries - 1:
                        wait_time = 2**attempt  # Exponential backoff: 1, 2, 4...
                        if debug:
                            print(f"[CCXTStore] fetch_balance failed (attempt {attempt + 1}/{retries}): {e}")
                            print(f"[CCXTStore] Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"[CCXTStore] Warning: Could not fetch balance after {retries} attempts: {e}")
                        print("[CCXTStore] Starting with zero balance. Will retry on first trade.")
                        balance = 0

        if balance == 0 or not balance.get("free", {}).get(currency):
            self._cash = 0
        else:
            self._cash = balance["free"][currency]

        if balance == 0 or not balance.get("total", {}).get(currency):
            self._value = 0
        else:
            self._value = balance["total"][currency]

    def get_granularity(self, timeframe, compression):
        """Get the exchange-specific granularity string for a timeframe.

        Converts backtrader timeframe and compression into the exchange's
        expected granularity string (e.g., '1m', '1h', '1d').

        Args:
            timeframe: Backtrader timeframe constant (e.g., TimeFrame.Minutes).
            compression: Compression factor for the timeframe.

        Returns:
            str: The exchange-specific granularity string.

        Raises:
            NotImplementedError: If the exchange doesn't support OHLCV data.
            ValueError: If the timeframe/compression combination is not supported.
        """
        if not self.exchange.has["fetchOHLCV"]:
            raise NotImplementedError("'%s' exchange doesn't support fetching OHLCV data" % self.exchange.name)

        granularity = self._GRANULARITIES.get((timeframe, compression))
        if granularity is None:
            raise ValueError(
                "backtrader CCXT module doesn't support fetching OHLCV "
                "data for time frame %s, compression %s" % (timeframe, compression)
            )

        if self.exchange.timeframes and granularity not in self.exchange.timeframes:
            raise ValueError(
                "'%s' exchange doesn't support fetching OHLCV data for %s time frame" % (self.exchange.name, granularity)
            )

        return granularity

    @staticmethod
    def retry(method):
        """Decorator for retry with rate limiting."""

        @wraps(method)
        def retry_method(self, *args, **kwargs):
            for i in range(self.retries):
                if self.debug:
                    logger.debug("%s - %s - Attempt %d", datetime.now(), method.__name__, i)

                # Use rate limiter if available, otherwise fall back to basic sleep
                if self._rate_limiter:
                    self._rate_limiter.acquire()
                else:
                    time.sleep(self.exchange.rateLimit / 1000)

                try:
                    result = method(self, *args, **kwargs)
                    # Mark success for adaptive rate limiter
                    if self._rate_limiter and hasattr(self._rate_limiter, "on_success"):
                        self._rate_limiter.on_success()
                    if self._connection_manager:
                        self._connection_manager.mark_success()
                    return result
                except (NetworkError, ExchangeError) as e:
                    # Mark failure for adaptive rate limiter
                    if self._rate_limiter and hasattr(self._rate_limiter, "on_rate_limit_error"):
                        if "rate" in str(e).lower() or "429" in str(e):
                            self._rate_limiter.on_rate_limit_error()
                    if self._connection_manager:
                        self._connection_manager.mark_failure()
                    if i == self.retries - 1:
                        raise

        return retry_method

    @retry
    def get_wallet_balance(self, params=None):
        """Fetch the wallet balance from the exchange.

        Args:
            params: Optional parameters for the balance request (e.g., for
                margin trading accounts).

        Returns:
            dict: The balance response from the exchange containing 'free' and
                'total' currency balances.
        """
        balance = self.exchange.fetch_balance(params)
        return balance

    @retry
    def get_balance(self):
        """Fetch and update the current balance from the exchange.

        Retrieves the current wallet balance and updates the internal cash
        and value attributes. Cash represents available free balance, while
        value represents total balance including locked funds.
        """
        balance = self.exchange.fetch_balance()
        cash = balance["free"][self.currency]
        value = balance["total"][self.currency]
        # Fix if None is returned
        self._cash = cash if cash else 0
        self._value = value if value else 0

    @retry
    def getposition(self):
        """Get the current position value.

        Returns:
            float: The total value of the position in the store's currency.
        """
        return self._value

    @retry
    def create_order(self, symbol, order_type, side, amount, price, params):
        """Create an order on the exchange.

        Args:
            symbol: The trading pair symbol (e.g., 'BTC/USDT').
            order_type: The type of order ('market', 'limit', etc.).
            side: Order side ('buy' or 'sell').
            amount: The order amount in base currency.
            price: The limit price (None for market orders).
            params: Additional exchange-specific parameters.

        Returns:
            dict: The order response from the exchange.
        """
        # returns the order
        return self.exchange.create_order(
            symbol=symbol, type=order_type, side=side, amount=amount, price=price, params=params
        )

    @retry
    def cancel_order(self, order_id, symbol):
        """Cancel an existing order on the exchange.

        Args:
            order_id: The ID of the order to cancel.
            symbol: The trading pair symbol.

        Returns:
            dict: The cancellation response from the exchange.
        """
        return self.exchange.cancel_order(order_id, symbol)

    @retry
    def fetch_trades(self, symbol):
        """Fetch recent trades for a symbol from the exchange.

        Args:
            symbol: The trading pair symbol (e.g., 'BTC/USDT').

        Returns:
            list: A list of recent trade dictionaries from the exchange.
        """
        return self.exchange.fetch_trades(symbol)

    @retry
    def fetch_ohlcv(self, symbol, timeframe, since, limit, params=None):
        """Fetch OHLCV (candlestick) data from the exchange.

        Args:
            symbol: The trading pair symbol (e.g., 'BTC/USDT').
            timeframe: The timeframe string (e.g., '1m', '1h', '1d').
            since: Timestamp to fetch data from (in milliseconds).
            limit: Maximum number of candles to fetch.
            params: Optional additional parameters for the request.

        Returns:
            list: A list of OHLCV data points. Each data point is a list
                containing [timestamp, open, high, low, close, volume].
        """
        if self.debug:
            print(f"Fetching: {symbol}, TF: {timeframe}, Since: {since}, Limit: {limit}")
        if params is None:
            params = {}
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit, params=params)

    @retry
    def fetch_order(self, oid, symbol):
        """Fetch details of a specific order from the exchange.

        Args:
            oid: The order ID to fetch.
            symbol: The trading pair symbol.

        Returns:
            dict: The order details from the exchange.
        """
        return self.exchange.fetch_order(oid, symbol)

    @retry
    def fetch_open_orders(self):
        """Fetch all open orders from the exchange.

        Returns:
            list: A list of open order dictionaries from the exchange.
        """
        return self.exchange.fetchOpenOrders()

    @retry
    def private_end_point(self, type, endpoint, params):
        """Call any private endpoint on the exchange.

        This method allows access to exchange-specific private API endpoints
        that may not be available through the unified CCXT API.

        Reference:
            https://github.com/ccxt/ccxt/wiki/Manual#implicit-api-methods

        Args:
            type: HTTP method type ('Get', 'Post', 'Put', or 'Delete').
            endpoint: The endpoint address (e.g., 'order/{id}/cancel').
            params: Dictionary of parameters to send with the request.

        Returns:
            dict: The exchange-specific JSON response from the API, unparsed.

        Note:
            To list all available methods for an exchange instance, including
            implicit and unified methods:
                print(dir(ccxt.hitbtc()))
        """
        return getattr(self.exchange, endpoint)(params)

    def get_websocket_manager(self):
        """Get or create the shared WebSocket manager.

        Multiple feeds and brokers can share a single WebSocket connection
        through this manager, reducing connection overhead.

        Returns:
            CCXTWebSocketManager or None: The shared manager, or None if
                ccxt.pro is not available.
        """
        if self._ws_manager is not None:
            return self._ws_manager

        if not HAS_CCXT_ENHANCEMENTS or not CCXTWebSocketManager:
            return None

        try:
            config = {
                "apiKey": getattr(self.exchange, "apiKey", ""),
                "secret": getattr(self.exchange, "secret", ""),
                "enableRateLimit": True,
            }
            password = getattr(self.exchange, "password", None)
            if password:
                config["password"] = password
            # Copy exchange options (defaultType, etc.)
            options = getattr(self.exchange, "options", {})
            if options:
                config["options"] = dict(options)
            # Copy proxy settings if present
            proxies = getattr(self.exchange, "proxies", None)
            if proxies:
                config["proxies"] = dict(proxies)
            aiohttp_proxy = getattr(self.exchange, "aiohttp_proxy", None)
            if aiohttp_proxy:
                config["aiohttp_proxy"] = aiohttp_proxy

            # Ensure markets are loaded before passing to WS manager
            # This avoids WS loading ALL market types and hitting duplicate ID issues
            markets = getattr(self.exchange, "markets", None)
            if not markets:
                try:
                    self.exchange.load_markets()
                    markets = self.exchange.markets
                except Exception as e:
                    if self.debug:
                        print(f"[CCXTStore] load_markets for WS failed: {e}")
            self._ws_manager = CCXTWebSocketManager(
                self.exchange_id, config, markets=markets, sandbox=getattr(self, "_sandbox", False)
            )
            self._ws_manager.start()
            if self.debug:
                print(f"[CCXTStore] Shared WebSocket manager started for {self.exchange_id}")
        except Exception as e:
            print(f"[CCXTStore] Failed to create WebSocket manager: {e}")
            self._ws_manager = None

        return self._ws_manager

    def stop(self):
        """Stop the store and cleanup resources."""
        if self._ws_manager:
            self._ws_manager.stop()
            self._ws_manager = None
        if self._connection_manager:
            self._connection_manager.stop_monitoring()

    def is_connected(self):
        """Check if connected to exchange.

        Returns:
            bool: True if connected.
        """
        if self._connection_manager:
            return self._connection_manager.is_connected()
        return True  # Assume connected if no manager

    def get_rate_limiter(self):
        """Get the rate limiter instance.

        Returns:
            RateLimiter or None.
        """
        return self._rate_limiter

    def get_connection_manager(self):
        """Get the connection manager instance.

        Returns:
            ConnectionManager or None.
        """
        return self._connection_manager
