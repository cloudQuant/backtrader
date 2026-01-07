#!/usr/bin/env python
"""CCXT Store Module - Cryptocurrency exchange store.

This module provides the CCXTStore for connecting to cryptocurrency
exchanges through the CCXT library.

Classes:
    CCXTStore: Singleton store for CCXT exchange connections.

Example:
    >>> store = bt.stores.CCXTStore(
    ...     exchange='binance',
    ...     api_key='your_key',
    ...     secret='your_secret'
    ... )
    >>> cerebro.setbroker(store.getbroker())
"""
import time
from functools import wraps

import ccxt
from ccxt.base.errors import ExchangeError, NetworkError

from ..dataseries import TimeFrame
from .mixins import ParameterizedSingletonMixin


class CCXTStore(ParameterizedSingletonMixin):
    """API provider for CCXT feed and broker classes.

    This class now uses ParameterizedSingletonMixin instead of MetaSingleton metaclass
    to implement the singleton pattern. This provides the same functionality without
    metaclasses while maintaining full backward compatibility.

    Added a new get_wallet_balance method. This will allow manual checking of the balance.
        The method will allow setting parameters. Useful for getting margin balances

    Added new private_end_point method to allow using any private non-unified end point

    """

    # Supported granularities
    _GRANULARITIES = {
        (TimeFrame.Minutes, 1): "1m",
        (TimeFrame.Minutes, 3): "3m",
        (TimeFrame.Minutes, 5): "5m",
        (TimeFrame.Minutes, 15): "15m",
        (TimeFrame.Minutes, 30): "30m",
        (TimeFrame.Minutes, 60): "1h",
        (TimeFrame.Minutes, 90): "90m",
        (TimeFrame.Minutes, 120): "2h",
        (TimeFrame.Minutes, 180): "3h",
        (TimeFrame.Minutes, 240): "4h",
        (TimeFrame.Minutes, 360): "6h",
        (TimeFrame.Minutes, 480): "8h",
        (TimeFrame.Minutes, 720): "12h",
        (TimeFrame.Days, 1): "1d",
        (TimeFrame.Days, 3): "3d",
        (TimeFrame.Weeks, 1): "1w",
        (TimeFrame.Weeks, 2): "2w",
        (TimeFrame.Months, 1): "1M",
        (TimeFrame.Months, 3): "3M",
        (TimeFrame.Months, 6): "6M",
        (TimeFrame.Years, 1): "1y",
    }

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self, exchange, currency, config, retries, debug=False, sandbox=False):
        """Initialize the CCXTStore.

        Args:
            exchange: Name of the exchange (e.g., 'binance', 'coinbase').
            currency: Base currency to use for the account.
            config: Configuration dictionary containing API credentials and settings.
            retries: Number of times to retry failed requests.
            debug: Whether to enable debug mode. Defaults to False.
            sandbox: Whether to use sandbox/testnet mode. Defaults to False.
        """
        self.exchange = getattr(ccxt, exchange)(config)
        if sandbox:
            self.exchange.set_sandbox_mode(True)
        self.currency = currency
        self.retries = retries
        self.debug = debug
        balance = self.exchange.fetch_balance() if "secret" in config else 0

        if balance == 0 or not balance["free"][currency]:
            self._cash = 0
        else:
            self._cash = balance["free"][currency]

        if balance == 0 or not balance["total"][currency]:
            self._value = 0
        else:
            self._value = balance["total"][currency]

    def get_granularity(self, timeframe, compression):
        """Get the exchange-specific granularity string for a timeframe.

        Args:
            timeframe: TimeFrame value (e.g., TimeFrame.Minutes, TimeFrame.Days).
            compression: Compression factor for the timeframe.

        Returns:
            str: Exchange-specific granularity string (e.g., '1m', '1h', '1d').

        Raises:
            NotImplementedError: If the exchange doesn't support fetching OHLCV data.
            ValueError: If the timeframe/compression combination is not supported
                or not supported by the specific exchange.
        """
        if not self.exchange.has["fetchOHLCV"]:
            raise NotImplementedError(
                "'%s' exchange doesn't support fetching OHLCV data" % self.exchange.name
            )

        granularity = self._GRANULARITIES.get((timeframe, compression))
        if granularity is None:
            raise ValueError(
                "backtrader CCXT module doesn't support fetching OHLCV "
                "data for time frame %s, compression %s"
                % (TimeFrame.getname(timeframe), compression)
            )

        if self.exchange.timeframes and granularity not in self.exchange.timeframes:
            raise ValueError(
                "'%s' exchange doesn't support fetching OHLCV data for "
                "%s time frame" % (self.exchange.name, granularity)
            )

        return granularity

    def retry(method):
        """Decorator to retry methods on exchange errors with rate limit delays.

        This decorator wraps methods that interact with the exchange API to
        automatically retry on network or exchange errors, with delays based
        on the exchange's rate limit.

        Args:
            method: The method to wrap with retry logic.

        Returns:
            The wrapped method that will retry on failures.

        Raises:
            NetworkError: If retry attempts are exhausted.
            ExchangeError: If retry attempts are exhausted.
        """
        @wraps(method)
        def retry_method(self, *args, **kwargs):
            for i in range(self.retries):
                if self.debug:
                    pass
                    # print("{} - {} - Attempt {}".format(datetime.now(), method.__name__, i))  # Removed for performance
                time.sleep(self.exchange.rateLimit / 1000)
                try:
                    return method(self, *args, **kwargs)
                except (NetworkError, ExchangeError):
                    if i == self.retries - 1:
                        raise

        return retry_method

    @retry
    def get_wallet_balance(self, params=None):
        """Get the wallet balance from the exchange.

        Args:
            params: Optional dictionary of parameters to pass to the exchange.
                Useful for getting margin balances or other specific balance types.

        Returns:
            dict: Balance information from the exchange.
        """
        balance = self.exchange.fetch_balance(params)
        return balance

    @retry
    def get_balance(self):
        """Fetch and update the current balance from the exchange.

        Updates the internal _cash and _value attributes with the free and
        total balance for the configured currency. Handles None values by
        setting them to 0.
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
            float: The total value of the position in the configured currency.
        """
        return self._value

    @retry
    def create_order(self, symbol, order_type, side, amount, price, params):
        """Create an order on the exchange.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USD').
            order_type: Type of order (e.g., 'market', 'limit').
            side: Order side ('buy' or 'sell').
            amount: Amount of the asset to trade.
            price: Price for limit orders.
            params: Additional exchange-specific parameters.

        Returns:
            dict: Order information from the exchange.
        """
        return self.exchange.create_order(
            symbol=symbol, type=order_type, side=side, amount=amount, price=price, params=params
        )

    @retry
    def cancel_order(self, order_id, symbol):
        """Cancel an order on the exchange.

        Args:
            order_id: The ID of the order to cancel.
            symbol: Trading pair symbol for the order.

        Returns:
            dict: Cancellation confirmation from the exchange.
        """
        return self.exchange.cancel_order(order_id, symbol)

    @retry
    def fetch_trades(self, symbol):
        """Fetch recent trades for a symbol from the exchange.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USD').

        Returns:
            list: List of recent trades.
        """
        return self.exchange.fetch_trades(symbol)

    @retry
    def fetch_ohlcv(self, symbol, timeframe, since, limit, params=None):
        """Fetch OHLCV (candlestick) data from the exchange.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USD').
            timeframe: Timeframe for the candles (e.g., '1m', '1h', '1d').
            since: Timestamp to fetch data from (in milliseconds).
            limit: Maximum number of candles to fetch.
            params: Optional dictionary of additional parameters.

        Returns:
            list: List of OHLCV data points. Each data point is a list
                containing [timestamp, open, high, low, close, volume].
        """
        if self.debug:
            pass
            # print("Fetching: {}, TF: {}, Since: {}, Limit: {}".format(symbol, timeframe, since, limit))  # Removed for performance
        if params is None:
            params = {}
        return self.exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, since=since, limit=limit, params=params
        )

    @retry
    def fetch_order(self, oid, symbol):
        """Fetch order information from the exchange.

        Args:
            oid: Order ID to fetch.
            symbol: Trading pair symbol for the order.

        Returns:
            dict: Order information including status, price, amount, etc.
        """
        return self.exchange.fetch_order(oid, symbol)

    @retry
    def fetch_open_orders(self):
        """Fetch all open orders from the exchange.

        Returns:
            list: List of open orders.
        """
        return self.exchange.fetchOpenOrders()

    @retry
    def private_end_point(self, type, endpoint, params):
        """
        Open method to allow calls to be made to any private end point.
        See here: https://github.com/ccxt/ccxt/wiki/Manual#implicit-api-methods

        - type: String, 'Get', 'Post','Put' or 'Delete'.
        - endpoint = String containing the endpoint address e.g. 'order/{id}/cancel'
        - Params: Dict: An implicit method takes a dictionary of parameters, sends
          the request to the exchange and returns an exchange-specific JSON
          result from the API as is unparsed.

        To get a list of all available methods with an exchange instance,
        including implicit methods and unified methods, you can do the
        following:

        # print(dir(ccxt.hitbtc()))  # Removed for performance
        """
        return getattr(self.exchange, endpoint)(params)
