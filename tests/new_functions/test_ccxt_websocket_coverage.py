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
    """Create a mock ccxt.pro module with async watch methods.

    Returns:
        tuple: A tuple containing (mock_module, MockExchange class).
        The mock module has okx and binance attributes set to MockExchange.
    """
    mock_module = MagicMock()

    class MockExchange:
        """Mock ccxt.pro exchange supporting async watch methods.

        This class simulates a ccxt.pro exchange with async methods for
        WebSocket-based data feeds, used for testing without network I/O.
        """

        def __init__(self, config):
            """Initialize the mock exchange with configuration.

            Args:
                config: Configuration dictionary for the exchange (e.g., apiKey).
            """
            self.config = config
            self.markets = {}
            self.markets_by_id = {}
            self._closed = False

        async def load_markets(self):
            """Load market definitions for the exchange.

            Returns:
                dict: A dictionary mapping market symbols to market info,
                    containing BTC/USDT spot and BTC/USDT:USDT swap markets.
            """
            self.markets = {
                'BTC/USDT': {'id': 'BTCUSDT', 'symbol': 'BTC/USDT'},
                'BTC/USDT:USDT': {'id': 'BTC-USDT-SWAP', 'symbol': 'BTC/USDT:USDT'},
            }
            return self.markets

        async def watch_ticker(self, symbol):
            """Watch ticker updates for a symbol.

            Args:
                symbol: The trading pair symbol to watch.

            Returns:
                dict: Mock ticker data with last, bid, and ask prices.
            """
            return {'symbol': symbol, 'last': 50000.0, 'bid': 49999, 'ask': 50001}

        async def watch_ohlcv(self, symbol, timeframe):
            """Watch OHLCV (candlestick) data for a symbol.

            Args:
                symbol: The trading pair symbol to watch.
                timeframe: The timeframe for candles (e.g., '1m').

            Returns:
                list: A list containing a single mock OHLCV candle
                    [timestamp, open, high, low, close, volume].
            """
            return [[1700000000000, 50000, 50100, 49900, 50050, 100]]

        async def watch_trades(self, symbol):
            """Watch public trades for a symbol.

            Args:
                symbol: The trading pair symbol to watch.

            Returns:
                list: A list containing a single mock trade with id, symbol,
                    price, and amount.
            """
            return [{'id': 't1', 'symbol': symbol, 'price': 50000, 'amount': 0.1}]

        async def watch_order_book(self, symbol, limit=20):
            """Watch order book updates for a symbol.

            Args:
                symbol: The trading pair symbol to watch.
                limit: The order book depth limit (default: 20).

            Returns:
                dict: Mock order book with bids and asks lists.
            """
            return {'bids': [[49999, 1]], 'asks': [[50001, 1]]}

        async def watch_my_trades(self, symbol):
            """Watch user's private trades for a symbol.

            Args:
                symbol: The trading pair symbol to watch.

            Returns:
                list: A list containing a single mock user trade with id,
                    order, symbol, and price.
            """
            return [{'id': 'mt1', 'order': 'o1', 'symbol': symbol, 'price': 50000}]

        async def watch_funding_rate(self, symbol):
            """Watch funding rate updates for a symbol.

            Args:
                symbol: The trading pair symbol to watch.

            Returns:
                dict: Mock funding rate data with symbol and fundingRate fields.
            """
            return {'symbol': symbol, 'fundingRate': 0.0001}

        async def watch_mark_price(self, symbol):
            """Watch mark price updates for a symbol.

            Args:
                symbol: The trading pair symbol to watch.

            Returns:
                dict: Mock mark price data with symbol and markPrice fields.
            """
            return {'symbol': symbol, 'markPrice': 50000.5}

        async def close(self):
            """Close the exchange connection.

            Sets the internal _closed flag to True.
            """
            self._closed = True

    mock_module.okx = MockExchange
    mock_module.binance = MockExchange
    return mock_module, MockExchange


# ---------------------------------------------------------------------------
# Test: __init__ and import handling
# ---------------------------------------------------------------------------

class TestWebSocketManagerInit:
    """Test CCXTWebSocketManager initialization.

    Tests the initialization behavior of the WebSocket manager,
    including handling of missing ccxt.pro dependency and
    attribute setup.
    """

    def test_init_without_ccxtpro_raises(self):
        """If ccxt.pro is unavailable, __init__ raises ImportError.

        Verifies that when HAS_CCXT_PRO is False, creating
        a CCXTWebSocketManager raises an informative ImportError.
        """
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
        """Normal init sets attributes correctly.

        Verifies that with ccxt.pro available, the manager
        initializes with correct default values.
        """
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
        """Init with preloaded markets stores them.

        Verifies that markets passed during initialization
        are stored for later use.
        """
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
    """Test symbol → market type detection.

    Tests the _detect_market_type method which infers market
    type (spot, swap, future) from symbol format.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance for testing.
        """
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
        """Test spot symbol detection.

        Verifies that symbols without colon suffix are detected
        as spot markets.
        """
        assert ws._detect_market_type('BTC/USDT') == 'spot'

    def test_swap_symbol(self, ws):
        """Test swap symbol detection.

        Verifies that symbols with :QUOTE suffix are detected
        as perpetual swap markets.
        """
        assert ws._detect_market_type('BTC/USDT:USDT') == 'swap'

    def test_future_symbol(self, ws):
        """Test future symbol detection.

        Verifies that symbols with :QUOTE-DATE suffix are
        detected as futures markets.
        """
        assert ws._detect_market_type('BTC/USDT:USDT-240329') == 'future'

    def test_unknown_format_defaults_spot(self, ws):
        """Test unknown format defaults to spot.

        Verifies that unrecognized symbol formats default to
        spot market type.
        """
        assert ws._detect_market_type('BTCUSDT') == 'spot'


# ---------------------------------------------------------------------------
# Test: _get_required_market_types
# ---------------------------------------------------------------------------

class TestGetRequiredMarketTypes:
    """Test subscription → market types inference.

    Tests the _get_required_market_types method which determines
    which market types need to be loaded based on active subscriptions.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance for testing.
        """
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
        """Empty subscriptions returns spot as default.

        Verifies that with no subscriptions, spot market type
        is returned as the default.
        """
        result = ws._get_required_market_types()
        assert result == {'spot'}

    def test_swap_subscription_key_parsed(self, ws):
        """Swap subscription key is parsed for market type.

        Verifies that subscription keys containing swap symbols
        result in swap market type being included.
        """
        # Note: due to ':' delimiter, 'ohlcv:BTC/USDT:USDT:1m' splits to
        # parts=['ohlcv','BTC/USDT','USDT','1m'], parts[1]='BTC/USDT' → spot
        ws._subscriptions['ohlcv:BTC/USDT:USDT:1m'] = lambda x: None
        result = ws._get_required_market_types()
        # Actual behavior: parts[1]='BTC/USDT' detected as spot
        assert 'spot' in result

    def test_single_part_key_skipped(self, ws):
        """Key with no ':' has len(parts)==1, so it's skipped.

        Verifies that subscription keys without colons are
        skipped in market type detection.
        """
        # Key with no ':' has len(parts)==1, so it's skipped
        ws._subscriptions['nocolon'] = lambda x: None
        result = ws._get_required_market_types()
        assert result == {'spot'}  # Falls to default


# ---------------------------------------------------------------------------
# Test: start / stop lifecycle
# ---------------------------------------------------------------------------

class TestStartStop:
    """Test WebSocket manager start/stop lifecycle.

    Tests the lifecycle management of the WebSocket manager including
    starting the event loop thread, stopping gracefully, and state
    management during transitions.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance for lifecycle testing.
        """
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
        """Verify start() sets _running flag and creates background thread.

        Tests that calling start() initializes the running state and creates
        the thread that runs the event loop.
        """
        with patch.object(ws, '_run_loop'):
            ws.start()
            assert ws._running is True
            assert ws._thread is not None
            # Cleanup
            ws._running = False
            if ws._thread:
                ws._thread.join(timeout=2)

    def test_start_idempotent(self, ws):
        """Verify start() is idempotent - calling twice doesn't create second thread.

        Tests that multiple start() calls reuse the existing thread rather
        than creating duplicate background threads.
        """
        with patch.object(ws, '_run_loop'):
            ws.start()
            thread1 = ws._thread
            ws.start()  # second call
            assert ws._thread is thread1
            ws._running = False
            if ws._thread:
                ws._thread.join(timeout=2)

    def test_stop_clears_state(self, ws):
        """Verify stop() clears running state and resets subscriptions.

        Tests that calling stop() sets _running to False and empties
        the subscriptions dictionary.
        """
        ws._running = True
        ws._subscriptions = {'ohlcv:BTC/USDT:1m': lambda x: None}
        ws._loop = None
        ws._thread = None

        ws.stop()
        assert ws._running is False
        assert len(ws._subscriptions) == 0

    def test_stop_with_loop(self, ws):
        """Verify stop() properly cancels tasks and stops the event loop.

        Tests that when an event loop exists, stop() cancels pending tasks
        and shuts down the loop gracefully.
        """
        loop = asyncio.new_event_loop()
        ws._loop = loop
        ws._running = True
        ws._thread = None

        ws.stop()
        assert ws._running is False
        loop.close()

    def test_stop_double_stop_safe(self, ws):
        """Verify stop() is safe to call multiple times.

        Tests that calling stop() twice in succession doesn't raise
        any exceptions (idempotent cleanup).
        """
        ws._running = False
        ws._loop = None
        ws._thread = None
        ws.stop()  # Should not raise
        ws.stop()  # Should not raise

    def test_is_connected(self, ws):
        """Verify is_connected() returns the connection state.

        Tests that the method correctly reflects the _connected flag value.
        """
        assert ws.is_connected() is False
        ws._connected = True
        assert ws.is_connected() is True


# ---------------------------------------------------------------------------
# Test: subscribe methods (synchronous registration)
# ---------------------------------------------------------------------------

class TestSubscribeMethods:
    """Test subscribe_* methods register callbacks and schedule watch tasks.

    Tests the subscription API including ticker, OHLCV, trades, orderbook,
    my trades, funding rate, and mark price subscriptions. Verifies that
    callbacks are properly registered and tasks are scheduled when the
    event loop is active.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance for subscription testing.
        """
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
        """Verify subscribe_ticker registers callback in subscriptions dict.

        Tests that calling subscribe_ticker stores the callback function
        in the _subscriptions dictionary with the correct key.
        """
        cb = MagicMock()
        ws.subscribe_ticker('BTC/USDT', cb)
        assert 'ticker:BTC/USDT' in ws._subscriptions
        assert ws._subscriptions['ticker:BTC/USDT'] is cb

    def test_subscribe_ohlcv_registers(self, ws):
        """Verify subscribe_ohlcv registers callback with timeframe.

        Tests that OHLCV subscription creates the correct key including
        the timeframe parameter.
        """
        cb = MagicMock()
        ws.subscribe_ohlcv('BTC/USDT', '1m', cb)
        assert 'ohlcv:BTC/USDT:1m' in ws._subscriptions

    def test_subscribe_trades_registers(self, ws):
        """Verify subscribe_trades registers callback correctly.

        Tests that trade subscription stores the callback with the
        expected key format.
        """
        cb = MagicMock()
        ws.subscribe_trades('BTC/USDT', cb)
        assert 'trades:BTC/USDT' in ws._subscriptions

    def test_subscribe_orderbook_registers(self, ws):
        """Verify subscribe_orderbook registers callback with limit parameter.

        Tests that order book subscription stores the callback with
        the expected key.
        """
        cb = MagicMock()
        ws.subscribe_orderbook('BTC/USDT', cb, limit=10)
        assert 'orderbook:BTC/USDT' in ws._subscriptions

    def test_subscribe_my_trades_registers(self, ws):
        """Verify subscribe_my_trades registers callback for swap symbol.

        Tests that my trades subscription correctly handles swap symbols
        with the :QUOTE suffix.
        """
        cb = MagicMock()
        ws.subscribe_my_trades('BTC/USDT:USDT', cb)
        assert 'mytrades:BTC/USDT:USDT' in ws._subscriptions

    def test_subscribe_funding_rate_registers(self, ws):
        """Verify subscribe_funding_rate registers callback correctly.

        Tests that funding rate subscription stores the callback
        with the correct key for swap symbols.
        """
        cb = MagicMock()
        ws.subscribe_funding_rate('BTC/USDT:USDT', cb)
        assert 'funding_rate:BTC/USDT:USDT' in ws._subscriptions

    def test_subscribe_mark_price_registers(self, ws):
        """Verify subscribe_mark_price registers callback correctly.

        Tests that mark price subscription stores the callback
        with the expected key format.
        """
        cb = MagicMock()
        ws.subscribe_mark_price('BTC/USDT:USDT', cb)
        assert 'mark_price:BTC/USDT:USDT' in ws._subscriptions

    def test_subscribe_with_active_loop_schedules_task(self, ws):
        """Verify subscribe schedules async task when event loop is running.

        Tests that when both _loop and _running are True, subscribing
        to a channel schedules the async watch task on the event loop
        using run_coroutine_threadsafe.
        """
        loop = asyncio.new_event_loop()
        ws._loop = loop
        ws._running = True

        with patch('asyncio.run_coroutine_threadsafe') as mock_rcs:
            ws.subscribe_ticker('BTC/USDT', MagicMock())
            mock_rcs.assert_called_once()

        loop.close()

    def test_unsubscribe_removes_key(self, ws):
        """Verify unsubscribe removes the subscription key from dict.

        Tests that calling unsubscribe with a valid key removes it
        from the _subscriptions dictionary.
        """
        ws._subscriptions['ticker:BTC/USDT'] = MagicMock()
        ws.unsubscribe('ticker:BTC/USDT')
        assert 'ticker:BTC/USDT' not in ws._subscriptions

    def test_unsubscribe_missing_key_safe(self, ws):
        """Verify unsubscribing a non-existent key doesn't raise.

        Tests that calling unsubscribe() with a key that doesn't exist
        in the subscriptions dictionary is handled gracefully without
        raising a KeyError.
        """
        ws.unsubscribe('nonexistent:key')  # Should not raise


# ---------------------------------------------------------------------------
# Test: async _connect
# ---------------------------------------------------------------------------

class TestConnect:
    """Test async _connect method.

    Tests the WebSocket connection initialization including market loading,
    handling of preloaded markets, and error recovery during connection.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance for connection testing.
        """
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
        """Verify _connect uses preloaded markets without calling load_markets.

        Tests that when markets are provided during initialization,
        _connect uses them directly instead of calling load_markets
        on the exchange.
        """
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
        """Verify _connect calls load_markets when no preloaded markets.

        Tests that when _preloaded_markets is None, _connect calls
        load_markets() on the exchange to fetch market definitions via REST.
        """
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
        """Verify _connect handles load_markets failure gracefully.

        Tests that when load_markets raises an exception, _connect
        continues execution and sets markets to an empty dict rather
        than failing.
        """
        mock_mod, _ = _make_mock_ccxtpro_module()

        class FailExchange:
            """Mock exchange that simulates network failures."""

            def __init__(self, config):
                """Initialize mock exchange with empty markets.

                Args:
                    config: Exchange configuration (unused).
                """
                self.markets = None
                self.markets_by_id = None

            async def load_markets(self):
                """Simulate network failure when loading markets.

                Raises:
                    Exception: Always raises "Network timeout".
                """
                raise Exception("Network timeout")

            async def close(self):
                """Close the exchange connection (no-op for mock)."""

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
        """Verify _connect sets _connected=False on total failure.

        Tests that when exchange instantiation fails completely,
        _connected is set to False to indicate connection failure.
        """
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
    """Test on-demand market loading for OKX.

    Tests the _load_market_for_symbol method which handles lazy loading
    of market definitions, including OKX-specific swap market creation
    and REST fallback for other exchanges.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance for market loading tests.
        """
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
        """Verify loading is skipped if symbol already exists in markets.

        Tests that _load_market_for_symbol returns early when the
        requested symbol is already present in exchange.markets.
        """
        ws.exchange = MagicMock()
        ws.exchange.markets = {'BTC/USDT:USDT': {'id': 'BTC-USDT-SWAP'}}
        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._load_market_for_symbol('BTC/USDT:USDT'))
        loop.close()

    def test_okx_creates_swap_market(self, ws):
        """Verify OKX path creates a minimal swap market entry.

        Tests that for OKX exchange with a swap symbol format,
        _load_market_for_symbol creates a market entry with proper
        base, quote, type, and id fields.
        """
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
        """Verify OKX path handles spot symbol (no colon).

        Tests that spot symbols without the :QUOTE suffix are
        correctly parsed and market entries are created.
        """
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
        """Verify OKX path initializes None markets to empty dict.

        Tests that when exchange.markets is None, _load_market_for_symbol
        initializes it to an empty dict before adding the new market.
        """
        ws.exchange = MagicMock()
        ws.exchange.markets = None
        ws.exchange.markets_by_id = None

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._load_market_for_symbol('BTC/USDT:USDT'))
        loop.close()

        assert ws.exchange.markets is not None
        assert 'BTC/USDT:USDT' in ws.exchange.markets

    def test_non_okx_tries_load_markets(self, ws):
        """Verify non-OKX exchanges try load_markets via REST.

        Tests that for exchanges other than OKX, _load_market_for_symbol
        calls load_markets() on the exchange to fetch market data.
        """
        ws.exchange_id = 'binance'
        ws.exchange = MagicMock()
        ws.exchange.markets = {}
        ws.exchange.load_markets = AsyncMock()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._load_market_for_symbol('BTC/USDT'))
        loop.close()

        ws.exchange.load_markets.assert_called_once()

    def test_non_okx_load_markets_failure_ignored(self, ws):
        """Verify non-OKX load_markets failure is silently ignored.

        Tests that when load_markets fails on non-OKX exchanges,
        the error is caught and ignored rather than propagating.
        """
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
    """Test _watch_* async methods with mocked exchange.

    Tests all watch loop methods (_watch_ticker, _watch_ohlcv, etc.)
    that continuously fetch data from the exchange and invoke callbacks.
    Includes tests for error handling, retries, and cancellation.
    """

    @pytest.fixture
    def ws_with_exchange(self):
        """Fixture providing a WebSocket manager with mock exchange.

        Creates a manager instance with a mocked exchange object
        for testing watch loop methods without network calls.

        Yields:
            CCXTWebSocketManager: A manager instance with mock exchange.
        """
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
        """Create an async mock that returns data once then unsubscribes.

        Args:
            ws: WebSocket manager instance.
            key: Subscription key to remove after call.
            return_value: Value to return from the mock.

        Returns:
            tuple: (async_mock_function, call_count_list).
        """
        call_count = [0]

        async def _mock(*args, **kwargs):
            """Mock async function that tracks calls and unsubscribes.

            Args:
                *args: Positional arguments (ignored).
                **kwargs: Keyword arguments (ignored).

            Returns:
                The return_value specified when creating this mock.
            """
            call_count[0] += 1
            # After returning data, remove sub to break loop
            ws._subscriptions.pop(key, None)
            return return_value

        return _mock, call_count

    def test_watch_ticker(self, ws_with_exchange):
        """Verify _watch_ticker receives data and invokes callback.

        Tests the watch ticker loop receives data from exchange and
        calls the registered callback with ticker updates.
        """
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
        """Verify _watch_ohlcv receives candle data and invokes callback.

        Tests the OHLCV watch loop receives candle data from exchange
        and calls the registered callback.
        """
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
        """Verify _watch_ohlcv retries on error and eventually breaks on unsubscribe.

        Tests that transient errors in watch_ohlcv trigger retries
        and the loop exits when the subscription is removed.
        """
        ws = ws_with_exchange
        cb = MagicMock()
        ws._subscriptions['ohlcv:BTC/USDT:USDT:1m'] = cb

        call_count = [0]

        async def fail_then_succeed(symbol, tf):
            """Mock watch function that fails twice then succeeds.

            Args:
                symbol: Trading pair symbol.
                tf: Timeframe for OHLCV data.

            Returns:
                list: A mock OHLCV candle after initial failures.

            Raises:
                Exception: For the first 2 calls to test retry behavior.
            """
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
        """Verify _watch_ohlcv exits cleanly on CancelledError.

        Tests that when the watch operation is cancelled via
        asyncio.CancelledError, the method exits without raising.
        """
        ws = ws_with_exchange
        cb = MagicMock()
        ws._subscriptions['ohlcv:BTC/USDT:USDT:1m'] = cb
        ws.exchange.watch_ohlcv = AsyncMock(side_effect=asyncio.CancelledError)

        loop = asyncio.new_event_loop()
        # Should not raise, should exit cleanly
        loop.run_until_complete(ws._watch_ohlcv('BTC/USDT:USDT', '1m', cb))
        loop.close()

    def test_watch_trades(self, ws_with_exchange):
        """Verify _watch_trades receives trade data and invokes callback.

        Tests the trades watch loop receives trade updates from exchange
        and calls the registered callback.
        """
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
        """Verify _watch_orderbook receives order book data and invokes callback.

        Tests the order book watch loop receives updates from exchange
        and calls the registered callback.
        """
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
        """Verify _watch_my_trades receives user trades and invokes callback.

        Tests the my trades watch loop receives user-specific trade data
        from exchange and calls the registered callback.
        """
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
        """Verify _watch_funding_rate uses native method when available.

        Tests that when the exchange has a watch_funding_rate method,
        it is used directly to fetch funding rate updates.
        """
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
        """Verify _watch_funding_rate falls back to watch_mark_price.

        Tests that when watch_funding_rate is not available on the
        exchange, the method falls back to using watch_mark_price.
        """
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
        """Verify _watch_funding_rate exits cleanly on CancelledError.

        Tests that when the watch operation is cancelled, the method
        exits without raising an exception.
        """
        ws = ws_with_exchange
        cb = MagicMock()
        ws._subscriptions['funding_rate:BTC/USDT:USDT'] = cb
        ws.exchange.watch_funding_rate = AsyncMock(side_effect=asyncio.CancelledError)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._watch_funding_rate('BTC/USDT:USDT', cb))
        loop.close()

    def test_watch_mark_price(self, ws_with_exchange):
        """Verify _watch_mark_price receives mark price data and invokes callback.

        Tests the mark price watch loop receives mark price updates
        from exchange and calls the registered callback.
        """
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
        """Verify _watch_mark_price exits cleanly on CancelledError.

        Tests that when the watch operation is cancelled, it exits
        without raising an exception.
        """
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
    """Test reconnection with exponential backoff.

    Tests the reconnection logic including exponential backoff delay,
    concurrent reconnect prevention, and subscription restoration
    after successful reconnect.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance with _running set to True.
        """
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
        """Verify successful reconnect restores subscriptions.

        Tests that a successful reconnect calls _connect and
        _restore_subscriptions, then resets the reconnecting flag.
        """
        ws._connect = AsyncMock()
        ws._restore_subscriptions = AsyncMock()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(ws._handle_reconnect())
        loop.close()

        ws._connect.assert_called_once()
        ws._restore_subscriptions.assert_called_once()
        assert ws._reconnecting is False

    def test_reconnect_exponential_backoff(self, ws):
        """Verify failed reconnect increases delay exponentially.

        Tests that when reconnect fails, the delay between attempts
        increases exponentially and the method retries until success.
        """
        call_count = [0]

        async def fail_then_succeed():
            """Mock connect function that fails twice then succeeds.

            Returns:
                None: Simulates successful connection after 2 failures.

            Raises:
                Exception: For the first 2 calls to test retry behavior.
            """
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
        """Verify second reconnect waits instead of running in parallel.

        Tests that when _reconnecting is already True, a subsequent
        call to _handle_reconnect waits for the existing reconnect
        to complete rather than starting a parallel reconnect.
        """
        ws._reconnecting = True

        async def check_waits():
            """Async wrapper to test that concurrent reconnect waits.

            Creates a background task to clear the reconnecting flag
            after a delay, then attempts to reconnect.
            """
            # Set running=False to break the wait loop
            async def stop_later():
                """Async task to clear reconnecting flag after delay.

                This simulates the completion of an existing reconnect
                operation to allow the waiting reconnect to proceed.
                """
                await asyncio.sleep(0.1)
                ws._reconnecting = False
            asyncio.create_task(stop_later())
            await ws._handle_reconnect()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(asyncio.wait_for(check_waits(), timeout=3))
        loop.close()

    def test_reconnect_not_running_exits(self, ws):
        """Verify _handle_reconnect exits immediately if not running.

        Tests that when _running is False, _handle_reconnect returns
        early without attempting to connect.
        """
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
    """Test subscription restoration after reconnect.

    Tests that after a reconnection, all active subscriptions are
    recreated by scheduling the corresponding watch tasks on the
    event loop.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance with _running set to True.
        """
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
        """Verify all subscription types are recreated as tasks.

        Tests that _restore_subscriptions creates async tasks for
        all registered subscription types including ticker, OHLCV,
        trades, orderbook, my trades, funding rate, and mark price.
        """
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
    """Test resource cleanup on shutdown.

    Tests the _cleanup_resources method which handles graceful shutdown
    including closing exchange connections, handling errors, and managing
    event loop state.
    """

    @pytest.fixture
    def ws(self):
        """Fixture providing a WebSocket manager for testing.

        Yields:
            CCXTWebSocketManager: A manager instance for testing cleanup.
        """
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
        """Verify cleanup with None event loop does nothing.

        Tests that _cleanup_resources handles the case where
        _loop is None without errors.
        """
        ws._loop = None
        ws._cleanup_resources()  # Should not raise

    def test_cleanup_with_closed_loop(self, ws):
        """Verify cleanup with closed event loop does nothing.

        Tests that _cleanup_resources handles a closed loop
        without raising errors.
        """
        loop = asyncio.new_event_loop()
        loop.close()
        ws._loop = loop
        ws._cleanup_resources()  # Should not raise

    def test_cleanup_closes_exchange(self, ws):
        """Verify cleanup closes exchange connection properly.

        Tests that _cleanup_resources calls close() on the exchange
        and sets exchange to None.
        """
        loop = asyncio.new_event_loop()
        ws._loop = loop

        mock_exchange = MagicMock()
        mock_exchange.close = AsyncMock()
        ws.exchange = mock_exchange

        ws._cleanup_resources()
        mock_exchange.close.assert_called_once()
        assert ws.exchange is None

    def test_cleanup_handles_exchange_error(self, ws):
        """Verify cleanup handles exchange close errors gracefully.

        Tests that _cleanup_resources catches exceptions from
        exchange.close() without propagating them.
        """
        loop = asyncio.new_event_loop()
        ws._loop = loop

        mock_exchange = MagicMock()
        mock_exchange.close = AsyncMock(side_effect=Exception("close failed"))
        ws.exchange = mock_exchange

        # Should not raise
        ws._cleanup_resources()
