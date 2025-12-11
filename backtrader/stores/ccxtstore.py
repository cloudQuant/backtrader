#!/usr/bin/env python
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
        balance = self.exchange.fetch_balance(params)
        return balance

    @retry
    def get_balance(self):
        balance = self.exchange.fetch_balance()
        cash = balance["free"][self.currency]
        value = balance["total"][self.currency]
        # Fix if None is returned
        self._cash = cash if cash else 0
        self._value = value if value else 0

    @retry
    def getposition(self):
        return self._value

    @retry
    def create_order(self, symbol, order_type, side, amount, price, params):
        # returns the order
        return self.exchange.create_order(
            symbol=symbol, type=order_type, side=side, amount=amount, price=price, params=params
        )

    @retry
    def cancel_order(self, order_id, symbol):
        return self.exchange.cancel_order(order_id, symbol)

    @retry
    def fetch_trades(self, symbol):
        return self.exchange.fetch_trades(symbol)

    @retry
    def fetch_ohlcv(self, symbol, timeframe, since, limit, params=None):
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
        return self.exchange.fetch_order(oid, symbol)

    @retry
    def fetch_open_orders(self):
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
