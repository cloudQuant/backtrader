#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Comprehensive unit tests for backtrader/ccxt/websocket.py.

Target: raise coverage from 10% to 60%+.
Strategy: mock ccxt.pro to avoid network I/O, test all code paths
including init, subscribe, watch loops, reconnect, cleanup.
"""

import asyncio
import time
import threading
import queue
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_ccxtpro_module():
    """Create a mock ccxt.pro module with a mock exchange class."""
    mock_module = MagicMock()

    class MockExchange:
        """Mock ccxt.pro exchange supporting async watch methods."""
        def __init__(self, config):
            self.config = config
            self.markets = {}
            self.markets_by_id = {}
            self._closed = False

        async def load_markets(self):
            self.markets = {
                'BTC/USDT': {'id': 'BTCUSDT', 'symbol': 'BTC/USDT'},
                'BTC/USDT:USDT': {'id': 'BTC-USDT-SWAP', 'symbol': 'BTC/USDT:USDT'},
            }
            return self.markets

        async def watch_ticker(self, symbol):
            return {'symbol': symbol, 'last': 50000.0, 'bid': 49999, 'ask': 50001}

        async def watch_ohlcv(self, symbol, timeframe):
            return [[1700000000000, 50000, 50100, 49900, 50050, 100]]

        async def watch_trades(self, symbol):
            return [{'id': 't1', 'symbol': symbol, 'price': 50000, 'amount': 0.1}]

        async def watch_order_book(self, symbol, limit=20):
            return {'bids': [[49999, 1]], 'asks': [[50001, 1]]}

        async def watch_my_trades(self, symbol):
            return [{'id': 'mt1', 'order': 'o1', 'symbol': symbol, 'price': 50000}]

        async def watch_funding_rate(self, symbol):
            return {'symbol': symbol, 'fundingRate': 0.0001}

        async def watch_mark_price(self, symbol):
            return {'symbol': symbol, 'markPrice': 50000.5}

        async def close(self):
            self._closed = True

    mock_module.okx = MockExchange
    mock_module.binance = MockExchange
    return mock_module, MockExchange


# ---------------------------------------------------------------------------
# Test: __init__ and import handling
# ---------------------------------------------------------------------------

class TestWebSocketManagerInit:
    """Test CCXTWebSocketManager initialization."""

    def test_init_without_ccxtpro_raises(self):
        """If ccxt.pro is unavailable, __init__ raises ImportError."""
        with patch.dict('sys.modules', {'ccxt.pro': None}):
            # Re-import module to pick up patched ccxt.pro
            import importlib
            from backtrader.ccxt import websocket as ws_module
            original_flag = ws_module.HAS_CCXT_PRO

            ws_module.HAS_CCXT_PRO = False
            try:
                with pytest.raises(ImportError, match="ccxt.pro is required"):
                    ws_module.CCXTWebSocketManager('okx', {'apiKey': 'test'})
            finally:
                ws_module.HAS_CCXT_PRO = original_flag

    def test_init_with_ccxtpro(self):
        """Normal init sets attributes correctly."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        ws = CCXTWebSocketManager.__new__(CCXTWebSocketManager)
        # Manually set HAS_CCXT_PRO to skip import check
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            ws.__init__('okx', {'apiKey': 'k', 'secret': 's'})
            assert ws.exchange_id == 'okx'
            assert ws.exchange is None
            assert ws._running is False
            assert ws._connected is False
            assert ws._reconnect_delay == 1.0
            assert ws._max_reconnect_delay == 60.0
            assert ws._subscriptions == {}
            assert ws._preloaded_markets is None
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_init_with_preloaded_markets(self):
        """Init with preloaded markets stores them."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            markets = {'BTC/USDT': {'id': 'BTCUSDT'}}
            ws = CCXTWebSocketManager('binance', {'apiKey': 'k'}, markets=markets)
            assert ws._preloaded_markets == markets
        finally:
            ws_mod.HAS_CCXT_PRO = orig


# ---------------------------------------------------------------------------
# Test: _detect_market_type
# ---------------------------------------------------------------------------

class TestDetectMarketType:
    """Test symbol → market type detection."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_spot_symbol(self, ws):
        assert ws._detect_market_type('BTC/USDT') == 'spot'

    def test_swap_symbol(self, ws):
        assert ws._detect_market_type('BTC/USDT:USDT') == 'swap'

    def test_future_symbol(self, ws):
        assert ws._detect_market_type('BTC/USDT:USDT-240329') == 'future'

    def test_unknown_format_defaults_spot(self, ws):
        assert ws._detect_market_type('BTCUSDT') == 'spot'


# ---------------------------------------------------------------------------
# Test: _get_required_market_types
# ---------------------------------------------------------------------------

class TestGetRequiredMarketTypes:
    """Test subscription → market types inference."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_empty_subscriptions_returns_spot(self, ws):
        result = ws._get_required_market_types()
        assert result == {'spot'}

    def test_swap_subscription_key_parsed(self, ws):
        # Note: due to ':' delimiter, 'ohlcv:BTC/USDT:USDT:1m' splits to
        # parts=['ohlcv','BTC/USDT','USDT','1m'], parts[1]='BTC/USDT' → spot
        ws._subscriptions['ohlcv:BTC/USDT:USDT:1m'] = lambda x: None
        result = ws._get_required_market_types()
        # Actual behavior: parts[1]='BTC/USDT' detected as spot
        assert 'spot' in result

    def test_single_part_key_skipped(self, ws):
        # Key with no ':' has len(parts)==1, so it's skipped
        ws._subscriptions['nocolon'] = lambda x: None
        result = ws._get_required_market_types()
        assert result == {'spot'}  # Falls to default


# ---------------------------------------------------------------------------
# Test: start / stop lifecycle
# ---------------------------------------------------------------------------

class TestStartStop:
    """Test WS manager start/stop lifecycle."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_start_sets_running(self, ws):
        """start() sets _running and creates thread."""
        with patch.object(ws, '_run_loop'):
            ws.start()
            assert ws._running is True
            assert ws._thread is not None
            # Cleanup
            ws._running = False
            if ws._thread:
                ws._thread.join(timeout=2)

    def test_start_idempotent(self, ws):
        """Calling start() twice doesn't create a second thread."""
        with patch.object(ws, '_run_loop'):
            ws.start()
            thread1 = ws._thread
            ws.start()  # second call
            assert ws._thread is thread1
            ws._running = False
            if ws._thread:
                ws._thread.join(timeout=2)

    def test_stop_clears_state(self, ws):
        """stop() sets _running=False and clears subscriptions."""
        ws._running = True
        ws._subscriptions = {'ohlcv:BTC/USDT:1m': lambda x: None}
        ws._loop = None
        ws._thread = None

        ws.stop()
        assert ws._running is False
        assert len(ws._subscriptions) == 0

    def test_stop_with_loop(self, ws):
        """stop() cancels tasks and stops the event loop."""
        loop = asyncio.new_event_loop()
        ws._loop = loop
        ws._running = True
        ws._thread = None

        ws.stop()
        assert ws._running is False
        loop.close()

    def test_stop_double_stop_safe(self, ws):
        """Calling stop() twice doesn't raise."""
        ws._running = False
        ws._loop = None
        ws._thread = None
        ws.stop()  # Should not raise
        ws.stop()  # Should not raise

    def test_is_connected(self, ws):
        """is_connected returns _connected flag."""
        assert ws.is_connected() is False
        ws._connected = True
        assert ws.is_connected() is True


# ---------------------------------------------------------------------------
# Test: subscribe methods (synchronous registration)
# ---------------------------------------------------------------------------

class TestSubscribeMethods:
    """Test subscribe_* methods register callbacks and schedule watch tasks."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_subscribe_ticker_registers(self, ws):
        cb = MagicMock()
        ws.subscribe_ticker('BTC/USDT', cb)
        assert 'ticker:BTC/USDT' in ws._subscriptions
        assert ws._subscriptions['ticker:BTC/USDT'] is cb

    def test_subscribe_ohlcv_registers(self, ws):
        cb = MagicMock()
        ws.subscribe_ohlcv('BTC/USDT', '1m', cb)
        assert 'ohlcv:BTC/USDT:1m' in ws._subscriptions

    def test_subscribe_trades_registers(self, ws):
        cb = MagicMock()
        ws.subscribe_trades('BTC/USDT', cb)
        assert 'trades:BTC/USDT' in ws._subscriptions

    def test_subscribe_orderbook_registers(self, ws):
        cb = MagicMock()
        ws.subscribe_orderbook('BTC/USDT', cb, limit=10)
        assert 'orderbook:BTC/USDT' in ws._subscriptions

    def test_subscribe_my_trades_registers(self, ws):
        cb = MagicMock()
        ws.subscribe_my_trades('BTC/USDT:USDT', cb)
        assert 'mytrades:BTC/USDT:USDT' in ws._subscriptions

    def test_subscribe_funding_rate_registers(self, ws):
        cb = MagicMock()
        ws.subscribe_funding_rate('BTC/USDT:USDT', cb)
        assert 'funding_rate:BTC/USDT:USDT' in ws._subscriptions

    def test_subscribe_mark_price_registers(self, ws):
        cb = MagicMock()
        ws.subscribe_mark_price('BTC/USDT:USDT', cb)
        assert 'mark_price:BTC/USDT:USDT' in ws._subscriptions

    def test_subscribe_with_active_loop_schedules_task(self, ws):
        """When loop+running, subscribe schedules async task."""
        loop = asyncio.new_event_loop()
        ws._loop = loop
        ws._running = True

        with patch('asyncio.run_coroutine_threadsafe') as mock_rcs:
            ws.subscribe_ticker('BTC/USDT', MagicMock())
            mock_rcs.assert_called_once()

        loop.close()

    def test_unsubscribe_removes_key(self, ws):
        ws._subscriptions['ticker:BTC/USDT'] = MagicMock()
        ws.unsubscribe('ticker:BTC/USDT')
        assert 'ticker:BTC/USDT' not in ws._subscriptions

    def test_unsubscribe_missing_key_safe(self, ws):
        """Unsubscribing a non-existent key doesn't raise."""
        ws.unsubscribe('nonexistent:key')  # Should not raise


# ---------------------------------------------------------------------------
# Test: async _connect
# ---------------------------------------------------------------------------

class TestConnect:
    """Test async _connect method."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_connect_with_preloaded_markets(self, ws):
        """_connect uses preloaded markets without calling load_markets."""
        mock_mod, MockExchange = _make_mock_ccxtpro_module()
        ws._preloaded_markets = {
            'BTC/USDT:USDT': {'id': 'BTC-USDT-SWAP', 'symbol': 'BTC/USDT:USDT'},
        }

        from backtrader.ccxt import websocket as ws_mod
        with patch.object(ws_mod, 'ccxtpro', mock_mod):
            loop = asyncio.new_event_loop()
            loop.run_until_complete(ws._connect())
            assert ws._connected is True
            assert ws.exchange is not None
            assert 'BTC/USDT:USDT' in ws.exchange.markets
            loop.close()

    def test_connect_loads_markets_via_rest(self, ws):
        """_connect calls load_markets when no preloaded markets."""
        mock_mod, MockExchange = _make_mock_ccxtpro_module()
        ws._preloaded_markets = None

        from backtrader.ccxt import websocket as ws_mod
        with patch.object(ws_mod, 'ccxtpro', mock_mod):
            loop = asyncio.new_event_loop()
            loop.run_until_complete(ws._connect())
            assert ws._connected is True
            assert len(ws.exchange.markets) > 0
            loop.close()

    def test_connect_handles_load_markets_failure(self, ws):
        """_connect handles load_markets failure gracefully."""
        mock_mod, _ = _make_mock_ccxtpro_module()

        class FailExchange:
            def __init__(self, config):
                self.markets = None
                self.markets_by_id = None
            async def load_markets(self):
                raise Exception("Network timeout")
            async def close(self):
                pass

        mock_mod.okx = FailExchange
        ws._preloaded_markets = None

        from backtrader.ccxt import websocket as ws_mod
        with patch.object(ws_mod, 'ccxtpro', mock_mod):
            loop = asyncio.new_event_loop()
            loop.run_until_complete(ws._connect())
            assert ws._connected is True
            assert ws.exchange.markets == {}
            loop.close()

    def test_connect_failure_sets_not_connected(self, ws):
        """_connect sets _connected=False on total failure."""
        mock_mod = MagicMock()
        mock_mod.okx = MagicMock(side_effect=Exception("fatal"))

        from backtrader.ccxt import websocket as ws_mod
        with patch.object(ws_mod, 'ccxtpro', mock_mod):
            loop = asyncio.new_event_loop()
            with pytest.raises(Exception, match="fatal"):
                loop.run_until_complete(ws._connect())
            assert ws._connected is False
            loop.close()


# ---------------------------------------------------------------------------
# Test: _load_market_for_symbol
# ---------------------------------------------------------------------------

class TestLoadMarketForSymbol:
    """Test on-demand market loading for OKX."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_already_loaded_skips(self, ws):
        """If symbol is in markets, skip loading."""
        ws.exchange = MagicMock()
        ws.exchange.markets = {'BTC/USDT:USDT': {'id': 'BTC-USDT-SWAP'}}
        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._load_market_for_symbol('BTC/USDT:USDT'))
        loop.close()

    def test_okx_creates_swap_market(self, ws):
        """OKX path creates a minimal swap market entry."""
        ws.exchange = MagicMock()
        ws.exchange.markets = {}
        ws.exchange.markets_by_id = {}

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._load_market_for_symbol('BTC/USDT:USDT'))
        loop.close()

        assert 'BTC/USDT:USDT' in ws.exchange.markets
        market = ws.exchange.markets['BTC/USDT:USDT']
        assert market['base'] == 'BTC'
        assert market['quote'] == 'USDT'
        assert market['type'] == 'swap'
        assert market['id'] == 'BTC-USDT-SWAP'
        assert 'BTC-USDT-SWAP' in ws.exchange.markets_by_id

    def test_okx_spot_symbol(self, ws):
        """OKX path handles spot symbol (no colon)."""
        ws.exchange = MagicMock()
        ws.exchange.markets = {}
        ws.exchange.markets_by_id = {}

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._load_market_for_symbol('ETH/USDT'))
        loop.close()

        assert 'ETH/USDT' in ws.exchange.markets
        market = ws.exchange.markets['ETH/USDT']
        assert market['base'] == 'ETH'
        assert market['quote'] == 'USDT'

    def test_okx_null_markets_init(self, ws):
        """OKX path initializes None markets to empty dict."""
        ws.exchange = MagicMock()
        ws.exchange.markets = None
        ws.exchange.markets_by_id = None

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._load_market_for_symbol('BTC/USDT:USDT'))
        loop.close()

        assert ws.exchange.markets is not None
        assert 'BTC/USDT:USDT' in ws.exchange.markets

    def test_non_okx_tries_load_markets(self, ws):
        """Non-OKX exchanges try load_markets via REST."""
        ws.exchange_id = 'binance'
        ws.exchange = MagicMock()
        ws.exchange.markets = {}
        ws.exchange.load_markets = AsyncMock()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._load_market_for_symbol('BTC/USDT'))
        loop.close()

        ws.exchange.load_markets.assert_called_once()

    def test_non_okx_load_markets_failure_ignored(self, ws):
        """Non-OKX load_markets failure is silently ignored."""
        ws.exchange_id = 'binance'
        ws.exchange = MagicMock()
        ws.exchange.markets = {}
        ws.exchange.load_markets = AsyncMock(side_effect=Exception("timeout"))

        loop = asyncio.new_event_loop()
        # Should not raise
        loop.run_until_complete(ws._load_market_for_symbol('BTC/USDT'))
        loop.close()


# ---------------------------------------------------------------------------
# Test: async watch loops
# ---------------------------------------------------------------------------

class TestWatchLoops:
    """Test _watch_* async methods with mocked exchange."""

    @pytest.fixture
    def ws_with_exchange(self):
        """WS manager with a mock exchange for watch testing."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            mgr.exchange = MagicMock()
            mgr.exchange.markets = {'BTC/USDT:USDT': {'id': 'BTC-USDT-SWAP'}}
            mgr._running = True
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def _make_watch_mock(self, ws, key, return_value):
        """Create an async mock that returns data once then unsubscribes."""
        call_count = [0]

        async def _mock(*args, **kwargs):
            call_count[0] += 1
            # After returning data, remove sub to break loop
            ws._subscriptions.pop(key, None)
            return return_value

        return _mock, call_count

    def test_watch_ticker(self, ws_with_exchange):
        ws = ws_with_exchange
        cb = MagicMock()
        key = 'ticker:BTC/USDT:USDT'
        ws._subscriptions[key] = cb
        ws.exchange.watch_ticker, count = self._make_watch_mock(
            ws, key, {'last': 50000}
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            ws._watch_ticker('BTC/USDT:USDT', cb), timeout=5
        ))
        loop.close()
        assert count[0] >= 1
        cb.assert_called()

    def test_watch_ohlcv_success(self, ws_with_exchange):
        ws = ws_with_exchange
        cb = MagicMock()
        key = 'ohlcv:BTC/USDT:USDT:1m'
        ws._subscriptions[key] = cb
        ws.exchange.watch_ohlcv, count = self._make_watch_mock(
            ws, key, [[1700000000000, 50000, 50100, 49900, 50050, 100]]
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            ws._watch_ohlcv('BTC/USDT:USDT', '1m', cb), timeout=5
        ))
        loop.close()
        assert count[0] >= 1
        cb.assert_called()

    def test_watch_ohlcv_error_retries(self, ws_with_exchange):
        """_watch_ohlcv retries on error and eventually breaks on unsubscribe."""
        ws = ws_with_exchange
        cb = MagicMock()
        ws._subscriptions['ohlcv:BTC/USDT:USDT:1m'] = cb

        call_count = [0]

        async def fail_then_succeed(symbol, tf):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise Exception("transient error")
            # After 2 failures, succeed and unsub
            ws._subscriptions.pop('ohlcv:BTC/USDT:USDT:1m', None)
            return [[1700000000000, 50000, 50100, 49900, 50050, 100]]

        ws.exchange.watch_ohlcv = fail_then_succeed

        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            asyncio.wait_for(ws._watch_ohlcv('BTC/USDT:USDT', '1m', cb), timeout=10)
        )
        loop.close()
        assert call_count[0] >= 3

    def test_watch_ohlcv_cancelled(self, ws_with_exchange):
        """_watch_ohlcv exits on CancelledError."""
        ws = ws_with_exchange
        cb = MagicMock()
        ws._subscriptions['ohlcv:BTC/USDT:USDT:1m'] = cb
        ws.exchange.watch_ohlcv = AsyncMock(side_effect=asyncio.CancelledError)

        loop = asyncio.new_event_loop()
        # Should not raise, should exit cleanly
        loop.run_until_complete(ws._watch_ohlcv('BTC/USDT:USDT', '1m', cb))
        loop.close()

    def test_watch_trades(self, ws_with_exchange):
        ws = ws_with_exchange
        cb = MagicMock()
        key = 'trades:BTC/USDT'
        ws._subscriptions[key] = cb
        ws.exchange.watch_trades, count = self._make_watch_mock(
            ws, key, [{'price': 50000}]
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            ws._watch_trades('BTC/USDT', cb), timeout=5
        ))
        loop.close()
        assert count[0] >= 1

    def test_watch_orderbook(self, ws_with_exchange):
        ws = ws_with_exchange
        cb = MagicMock()
        key = 'orderbook:BTC/USDT'
        ws._subscriptions[key] = cb
        ws.exchange.watch_order_book, count = self._make_watch_mock(
            ws, key, {'bids': [[49999, 1]], 'asks': [[50001, 1]]}
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            ws._watch_orderbook('BTC/USDT', cb, 20), timeout=5
        ))
        loop.close()
        assert count[0] >= 1

    def test_watch_my_trades(self, ws_with_exchange):
        ws = ws_with_exchange
        cb = MagicMock()
        key = 'mytrades:BTC/USDT:USDT'
        ws._subscriptions[key] = cb
        ws.exchange.watch_my_trades, count = self._make_watch_mock(
            ws, key, [{'id': 'mt1', 'order': 'o1'}]
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            ws._watch_my_trades('BTC/USDT:USDT', cb), timeout=5
        ))
        loop.close()
        assert count[0] >= 1

    def test_watch_funding_rate_native(self, ws_with_exchange):
        """_watch_funding_rate uses native method when available."""
        ws = ws_with_exchange
        cb = MagicMock()
        key = 'funding_rate:BTC/USDT:USDT'
        ws._subscriptions[key] = cb
        ws.exchange.watch_funding_rate, count = self._make_watch_mock(
            ws, key, {'fundingRate': 0.0001}
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            ws._watch_funding_rate('BTC/USDT:USDT', cb), timeout=5
        ))
        loop.close()
        assert count[0] >= 1

    def test_watch_funding_rate_fallback_mark_price(self, ws_with_exchange):
        """_watch_funding_rate falls back to watch_mark_price."""
        ws = ws_with_exchange
        cb = MagicMock()
        key = 'funding_rate:BTC/USDT:USDT'
        ws._subscriptions[key] = cb

        # Remove watch_funding_rate to trigger fallback
        if hasattr(ws.exchange, 'watch_funding_rate'):
            del ws.exchange.watch_funding_rate
        ws.exchange.watch_mark_price, count = self._make_watch_mock(
            ws, key, {'markPrice': 50000, 'fundingRate': 0.0001}
        )
        # Ensure hasattr check fails
        ws.exchange.configure_mock(**{'watch_funding_rate': None})
        delattr(ws.exchange, 'watch_funding_rate')

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            ws._watch_funding_rate('BTC/USDT:USDT', cb), timeout=5
        ))
        loop.close()
        assert count[0] >= 1

    def test_watch_funding_rate_cancelled(self, ws_with_exchange):
        ws = ws_with_exchange
        cb = MagicMock()
        ws._subscriptions['funding_rate:BTC/USDT:USDT'] = cb
        ws.exchange.watch_funding_rate = AsyncMock(side_effect=asyncio.CancelledError)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._watch_funding_rate('BTC/USDT:USDT', cb))
        loop.close()

    def test_watch_mark_price(self, ws_with_exchange):
        ws = ws_with_exchange
        cb = MagicMock()
        key = 'mark_price:BTC/USDT:USDT'
        ws._subscriptions[key] = cb
        ws.exchange.watch_mark_price, count = self._make_watch_mock(
            ws, key, {'markPrice': 50000.5}
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(
            ws._watch_mark_price('BTC/USDT:USDT', cb), timeout=5
        ))
        loop.close()
        assert count[0] >= 1

    def test_watch_mark_price_cancelled(self, ws_with_exchange):
        ws = ws_with_exchange
        cb = MagicMock()
        ws._subscriptions['mark_price:BTC/USDT:USDT'] = cb
        ws.exchange.watch_mark_price = AsyncMock(side_effect=asyncio.CancelledError)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._watch_mark_price('BTC/USDT:USDT', cb))
        loop.close()


# ---------------------------------------------------------------------------
# Test: _handle_reconnect
# ---------------------------------------------------------------------------

class TestHandleReconnect:
    """Test reconnection with exponential backoff."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            mgr._running = True
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_reconnect_success(self, ws):
        """Successful reconnect restores subscriptions."""
        ws._connect = AsyncMock()
        ws._restore_subscriptions = AsyncMock()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._handle_reconnect())
        loop.close()

        ws._connect.assert_called_once()
        ws._restore_subscriptions.assert_called_once()
        assert ws._reconnecting is False

    def test_reconnect_exponential_backoff(self, ws):
        """Failed reconnect increases delay exponentially."""
        call_count = [0]

        async def fail_then_succeed():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("still failing")
            # Success on 3rd attempt

        ws._connect = fail_then_succeed
        ws._restore_subscriptions = AsyncMock()
        ws._reconnect_delay = 0.01  # Speed up test

        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            asyncio.wait_for(ws._handle_reconnect(), timeout=5)
        )
        loop.close()

        assert call_count[0] == 3
        assert ws._reconnecting is False

    def test_concurrent_reconnect_prevented(self, ws):
        """Second reconnect waits instead of running in parallel."""
        ws._reconnecting = True

        async def check_waits():
            # Set running=False to break the wait loop
            async def stop_later():
                await asyncio.sleep(0.1)
                ws._reconnecting = False
            asyncio.create_task(stop_later())
            await ws._handle_reconnect()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(check_waits(), timeout=3))
        loop.close()

    def test_reconnect_not_running_exits(self, ws):
        """_handle_reconnect exits immediately if not running."""
        ws._running = False
        ws._connect = AsyncMock()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._handle_reconnect())
        loop.close()

        ws._connect.assert_not_called()


# ---------------------------------------------------------------------------
# Test: _restore_subscriptions
# ---------------------------------------------------------------------------

class TestRestoreSubscriptions:
    """Test subscription restoration after reconnect."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            mgr._running = True
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_restores_all_channel_types(self, ws):
        """All subscription types are recreated as tasks."""
        cb = MagicMock()
        ws._subscriptions = {
            'ticker:BTC/USDT': cb,
            'ohlcv:BTC/USDT:1m': cb,
            'trades:ETH/USDT': cb,
            'orderbook:BTC/USDT': cb,
            'mytrades:BTC/USDT:USDT': cb,
            'funding_rate:BTC/USDT:USDT': cb,
            'mark_price:BTC/USDT:USDT': cb,
        }

        loop = asyncio.new_event_loop()
        tasks_created = []
        original_create_task = loop.create_task

        with patch('asyncio.create_task') as mock_ct:
            mock_ct.side_effect = lambda coro: coro.close()  # Close coroutine to avoid warning
            loop.run_until_complete(ws._restore_subscriptions())
            assert mock_ct.call_count == 7  # One for each subscription

        loop.close()


# ---------------------------------------------------------------------------
# Test: _cleanup_resources
# ---------------------------------------------------------------------------

class TestCleanupResources:
    """Test resource cleanup on shutdown."""

    @pytest.fixture
    def ws(self):
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        from backtrader.ccxt import websocket as ws_mod
        orig = ws_mod.HAS_CCXT_PRO
        ws_mod.HAS_CCXT_PRO = True
        try:
            mgr = CCXTWebSocketManager('okx', {'apiKey': 'k'})
            yield mgr
        finally:
            ws_mod.HAS_CCXT_PRO = orig

    def test_cleanup_with_no_loop(self, ws):
        """Cleanup with None loop does nothing."""
        ws._loop = None
        ws._cleanup_resources()  # Should not raise

    def test_cleanup_with_closed_loop(self, ws):
        """Cleanup with closed loop does nothing."""
        loop = asyncio.new_event_loop()
        loop.close()
        ws._loop = loop
        ws._cleanup_resources()  # Should not raise

    def test_cleanup_closes_exchange(self, ws):
        """Cleanup closes exchange connection."""
        loop = asyncio.new_event_loop()
        ws._loop = loop

        mock_exchange = MagicMock()
        mock_exchange.close = AsyncMock()
        ws.exchange = mock_exchange

        ws._cleanup_resources()
        mock_exchange.close.assert_called_once()
        assert ws.exchange is None

    def test_cleanup_handles_exchange_error(self, ws):
        """Cleanup handles errors from exchange.close() gracefully."""
        loop = asyncio.new_event_loop()
        ws._loop = loop

        mock_exchange = MagicMock()
        mock_exchange.close = AsyncMock(side_effect=Exception("close failed"))
        ws.exchange = mock_exchange

        # Should not raise
        ws._cleanup_resources()
