#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
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

from __future__ import (absolute_import, division, print_function, unicode_literals)

import time
from datetime import datetime
from functools import wraps

import ccxt
from backtrader.mixins.singleton import ParameterizedSingletonMixin
from ccxt.base.errors import NetworkError, ExchangeError

# TimeFrame constants to avoid circular import with backtrader
# Values match backtrader.dataseries.TimeFrame
_TF_MINUTES = 4
_TF_DAYS = 5
_TF_WEEKS = 6
_TF_MONTHS = 7
_TF_YEARS = 8

# Import enhancement modules
try:
    from backtrader.ccxt.ratelimit import RateLimiter, AdaptiveRateLimiter
    from backtrader.ccxt.connection import ConnectionManager
    from backtrader.ccxt.config import ExchangeConfig
    HAS_CCXT_ENHANCEMENTS = True
except ImportError:
    HAS_CCXT_ENHANCEMENTS = False
    RateLimiter = None
    ConnectionManager = None
    ExchangeConfig = None


class CCXTStore(ParameterizedSingletonMixin):
    """API provider for CCXT feed and broker classes.

    Added a new get_wallet_balance method. This will allow manual checking of the balance.
        The method will allow setting parameters. Useful for getting margin balances

    Added new private_end_point method to allow using any private non-unified end point

    """

    # Supported granularities (using constants to avoid circular import)
    _GRANULARITIES = {
        (_TF_MINUTES, 1): '1m',
        (_TF_MINUTES, 3): '3m',
        (_TF_MINUTES, 5): '5m',
        (_TF_MINUTES, 15): '15m',
        (_TF_MINUTES, 30): '30m',
        (_TF_MINUTES, 60): '1h',
        (_TF_MINUTES, 90): '90m',
        (_TF_MINUTES, 120): '2h',
        (_TF_MINUTES, 180): '3h',
        (_TF_MINUTES, 240): '4h',
        (_TF_MINUTES, 360): '6h',
        (_TF_MINUTES, 480): '8h',
        (_TF_MINUTES, 720): '12h',
        (_TF_DAYS, 1): '1d',
        (_TF_DAYS, 3): '3d',
        (_TF_WEEKS, 1): '1w',
        (_TF_WEEKS, 2): '2w',
        (_TF_MONTHS, 1): '1M',
        (_TF_MONTHS, 3): '3M',
        (_TF_MONTHS, 6): '6M',
        (_TF_YEARS, 1): '1y',
    }

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        return cls.DataCls(*args, **kwargs)

    def getdata(self, *args, **kwargs):
        """Returns data feed with this store instance.

        This instance method creates a data feed that uses this store instance
        rather than creating a new one.

        Returns:
            CCXTFeed: A data feed instance connected to this store.
        """
        # Pass this store instance to the data feed
        kwargs['store'] = self
        return self.DataCls(*args, **kwargs)

    def getbroker(self, *args, **kwargs):
        """Returns broker with this store instance.

        This instance method creates a broker that uses this store instance
        rather than creating a new one.

        Returns:
            CCXTBroker: A broker instance connected to this store.
        """
        # Pass this store instance to the broker
        kwargs['store'] = self
        return self.BrokerCls(*args, **kwargs)

    def __init__(self, exchange, currency, config, retries, debug=False, sandbox=False,
                 use_rate_limiter=True, use_connection_manager=False):
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
        
        # Fetch initial balance
        balance = self.exchange.fetch_balance() if 'secret' in config else 0

        if balance == 0 or not balance['free'][currency]:
            self._cash = 0
        else:
            self._cash = balance['free'][currency]

        if balance == 0 or not balance['total'][currency]:
            self._value = 0
        else:
            self._value = balance['total'][currency]

    def get_granularity(self, timeframe, compression):
        if not self.exchange.has['fetchOHLCV']:
            raise NotImplementedError("'%s' exchange doesn't support fetching OHLCV data" % \
                                      self.exchange.name)

        granularity = self._GRANULARITIES.get((timeframe, compression))
        if granularity is None:
            raise ValueError("backtrader CCXT module doesn't support fetching OHLCV "
                             "data for time frame %s, comression %s" % \
                             (bt.TimeFrame.getname(timeframe), compression))

        if self.exchange.timeframes and granularity not in self.exchange.timeframes:
            raise ValueError("'%s' exchange doesn't support fetching OHLCV data for "
                             "%s time frame" % (self.exchange.name, granularity))

        return granularity

    def retry(method):
        """Decorator for retry with rate limiting."""
        @wraps(method)
        def retry_method(self, *args, **kwargs):
            for i in range(self.retries):
                if self.debug:
                    print('{} - {} - Attempt {}'.format(datetime.now(), method.__name__, i))
                
                # Use rate limiter if available, otherwise fall back to basic sleep
                if self._rate_limiter:
                    self._rate_limiter.acquire()
                else:
                    time.sleep(self.exchange.rateLimit / 1000)
                
                try:
                    result = method(self, *args, **kwargs)
                    # Mark success for adaptive rate limiter
                    if self._rate_limiter and hasattr(self._rate_limiter, 'on_success'):
                        self._rate_limiter.on_success()
                    if self._connection_manager:
                        self._connection_manager.mark_success()
                    return result
                except (NetworkError, ExchangeError) as e:
                    # Mark failure for adaptive rate limiter
                    if self._rate_limiter and hasattr(self._rate_limiter, 'on_rate_limit_error'):
                        if 'rate' in str(e).lower() or '429' in str(e):
                            self._rate_limiter.on_rate_limit_error()
                    if self._connection_manager:
                        self._connection_manager.mark_failure()
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
        cash = balance['free'][self.currency]
        value = balance['total'][self.currency]
        # Fix if None is returned
        self._cash = cash if cash else 0
        self._value = value if value else 0

    @retry
    def getposition(self):
        return self._value

    @retry
    def create_order(self, symbol, order_type, side, amount, price, params):
        # returns the order
        return self.exchange.create_order(symbol=symbol, type=order_type, side=side,
                                          amount=amount, price=price, params=params)

    @retry
    def cancel_order(self, order_id, symbol):
        return self.exchange.cancel_order(order_id, symbol)

    @retry
    def fetch_trades(self, symbol):
        return self.exchange.fetch_trades(symbol)

    @retry
    def fetch_ohlcv(self, symbol, timeframe, since, limit, params=None):
        if self.debug:
            print('Fetching: {}, TF: {}, Since: {}, Limit: {}'.format(symbol, timeframe, since, limit))
        if params is None:
            params = {}
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit, params=params)

    @retry
    def fetch_order(self, oid, symbol):
        return self.exchange.fetch_order(oid, symbol)

    @retry
    def fetch_open_orders(self):
        return self.exchange.fetchOpenOrders()

    @retry
    def private_end_point(self, type, endpoint, params):
        '''
        Open method to allow calls to be made to any private end point.
        See here: https://github.com/ccxt/ccxt/wiki/Manual#implicit-api-methods

        - type: String, 'Get', 'Post','Put' or 'Delete'.
        - endpoint = String containing the endpoint address eg. 'order/{id}/cancel'
        - Params: Dict: An implicit method takes a dictionary of parameters, sends
          the request to the exchange and returns an exchange-specific JSON
          result from the API as is, unparsed.

        To get a list of all available methods with an exchange instance,
        including implicit methods and unified methods you can simply do the
        following:

        print(dir(ccxt.hitbtc()))
        '''
        return getattr(self.exchange, endpoint)(params)

    def stop(self):
        """Stop the store and cleanup resources."""
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
