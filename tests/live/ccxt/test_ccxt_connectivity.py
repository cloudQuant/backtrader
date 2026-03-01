#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Integration tests for CCXT connectivity and data fetching.

These are read-only tests that verify:
- Exchange connection and authentication
- Market data fetching (OHLCV, ticker, orderbook)
- Balance retrieval
- CCXTStore initialization with sandbox mode

Run:
    pytest tests/integration/test_ccxt_connectivity.py -m integration -v
"""

import time
import pytest
from ccxt.base.errors import PermissionDenied, AuthenticationError

from tests.integration.conftest import skip_no_okx

pytestmark = [pytest.mark.integration, skip_no_okx]


class TestExchangeConnectivity:
    """Test basic exchange connectivity via ccxt REST API."""

    def test_exchange_connection(self, ccxt_exchange):
        """Verify exchange instance connects and loads markets."""
        markets = ccxt_exchange.load_markets()
        assert len(markets) > 0, "No markets loaded"
        assert 'BTC/USDT:USDT' in markets, "BTC/USDT:USDT swap not found"

    def test_fetch_ticker(self, ccxt_exchange):
        """Verify ticker data can be fetched."""
        ticker = ccxt_exchange.fetch_ticker('BTC/USDT:USDT')
        assert ticker is not None
        assert 'last' in ticker
        assert ticker['last'] > 0, "Ticker last price should be positive"
        assert 'bid' in ticker
        assert 'ask' in ticker

    def test_fetch_ohlcv(self, ccxt_exchange):
        """Verify OHLCV data can be fetched."""
        ohlcv = ccxt_exchange.fetch_ohlcv('BTC/USDT:USDT', '1h', limit=10)
        assert len(ohlcv) > 0, "No OHLCV data returned"
        assert len(ohlcv[0]) == 6, "OHLCV should have 6 fields [t,o,h,l,c,v]"
        # Verify data makes sense
        for candle in ohlcv:
            timestamp, open_, high, low, close, volume = candle
            assert high >= low, f"High {high} < Low {low}"
            assert high >= open_, f"High {high} < Open {open_}"
            assert high >= close, f"High {high} < Close {close}"
            assert low <= open_, f"Low {low} > Open {open_}"
            assert volume >= 0, f"Volume {volume} negative"

    def test_fetch_orderbook(self, ccxt_exchange):
        """Verify orderbook data can be fetched."""
        ob = ccxt_exchange.fetch_order_book('BTC/USDT:USDT', limit=5)
        assert 'bids' in ob
        assert 'asks' in ob
        assert len(ob['bids']) > 0, "No bids in orderbook"
        assert len(ob['asks']) > 0, "No asks in orderbook"
        # Best bid should be below best ask
        best_bid = ob['bids'][0][0]
        best_ask = ob['asks'][0][0]
        assert best_bid < best_ask, f"Bid {best_bid} >= Ask {best_ask}"

    def test_fetch_balance(self, ccxt_exchange):
        """Verify balance can be fetched with authentication."""
        try:
            balance = ccxt_exchange.fetch_balance()
        except (PermissionDenied, AuthenticationError) as e:
            pytest.skip(f"Auth failed (IP whitelist?): {e}")
        assert balance is not None
        assert 'total' in balance
        assert 'free' in balance

    def test_fetch_multiple_symbols_ohlcv(self, ccxt_exchange):
        """Verify OHLCV for multiple symbols (multi-data scenario)."""
        symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
        for symbol in symbols:
            ohlcv = ccxt_exchange.fetch_ohlcv(symbol, '1h', limit=5)
            assert len(ohlcv) > 0, f"No OHLCV for {symbol}"
            # Small delay to respect rate limits
            time.sleep(0.2)


class TestCCXTStoreConnectivity:
    """Test CCXTStore initialization and basic operations."""

    def test_store_init_sandbox(self, ccxt_store):
        """Verify CCXTStore initializes correctly in sandbox mode."""
        assert ccxt_store is not None
        assert ccxt_store.exchange is not None
        assert ccxt_store.exchange_id == 'okx'

    def test_store_get_balance(self, ccxt_store):
        """Verify CCXTStore can fetch balance."""
        try:
            ccxt_store.get_balance()
        except (PermissionDenied, AuthenticationError) as e:
            pytest.skip(f"Auth failed (IP whitelist?): {e}")
        assert ccxt_store._cash is not None
        assert ccxt_store._value is not None

    def test_store_get_granularity(self, ccxt_store):
        """Verify CCXTStore timeframe mapping works."""
        # Import timeframe constants
        from backtrader.stores.ccxtstore import _TF_MINUTES, _TF_DAYS
        
        gran_1h = ccxt_store.get_granularity(_TF_MINUTES, 60)
        assert gran_1h == '1h'
        
        gran_1d = ccxt_store.get_granularity(_TF_DAYS, 1)
        assert gran_1d == '1d'

    def test_store_fetch_ohlcv(self, ccxt_store):
        """Verify CCXTStore can proxy OHLCV requests."""
        ohlcv = ccxt_store.exchange.fetch_ohlcv('BTC/USDT:USDT', '1h', limit=5)
        assert len(ohlcv) >= 1

    def test_store_shared_ws_manager(self, ccxt_store):
        """Verify shared WebSocket manager can be created."""
        ws_manager = ccxt_store.get_websocket_manager()
        assert ws_manager is not None
        # Second call should return same instance
        ws_manager2 = ccxt_store.get_websocket_manager()
        assert ws_manager is ws_manager2


class TestMultipleTimeframes:
    """Test fetching data across different timeframes."""

    @pytest.mark.parametrize("timeframe,expected_min", [
        ('1m', 1),
        ('5m', 1),
        ('1h', 1),
        ('1d', 1),
    ])
    def test_fetch_various_timeframes(self, ccxt_exchange, timeframe, expected_min):
        """Verify OHLCV works for different timeframes."""
        ohlcv = ccxt_exchange.fetch_ohlcv(
            'BTC/USDT:USDT', timeframe, limit=5
        )
        assert len(ohlcv) >= expected_min, (
            f"Expected >= {expected_min} candles for {timeframe}, got {len(ohlcv)}"
        )
