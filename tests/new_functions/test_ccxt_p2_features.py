#!/usr/bin/env python
"""Unit tests for CCXT P2 features:

- P2-1: WebSocket order push (watch_my_trades) in CCXTBroker
- P2-2: Multi-symbol shared WebSocket via CCXTStore
- P2-3: Funding rate shared WebSocket in CCXTFeedWithFunding
"""

import sys
import os
import time
import unittest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


# ============================================================================
# P2-1: WebSocket Order Push Tests
# ============================================================================

class TestBrokerWsOrderInit(unittest.TestCase):
    """Tests for CCXTBroker WebSocket order manager initialization."""

    def _make_broker(self, use_ws=False):
        from backtrader.brokers.ccxtbroker import CCXTBroker
        broker = CCXTBroker.__new__(CCXTBroker)
        broker.store = Mock()
        broker.store.exchange_id = 'binance'
        broker.store.exchange = Mock()
        broker.store.exchange.apiKey = 'test_key'
        broker.store.exchange.secret = 'test_secret'
        broker.store.exchange.password = None
        broker.store.exchange.markets = {'BTC/USDT': {}}
        broker.debug = False
        broker._max_retries = 3
        broker._retry_delay = 0.01
        broker._consecutive_failures = 0
        broker._max_consecutive_failures = 10
        broker._threaded_order_manager = None
        broker._bracket_manager = None
        broker._ws_order_manager = None
        broker._use_threaded = False
        broker._use_ws_orders = use_ws
        broker._ws_order_updates = __import__('queue').Queue()
        broker._ws_subscribed_symbols = set()
        broker.order_types = {0: 'market', 2: 'limit'}
        broker.notifs = __import__('queue').Queue()
        broker.open_orders = []
        broker.positions = __import__('collections').defaultdict(
            lambda: Mock(clone=Mock(return_value=Mock()))
        )
        broker._last_op_time = 0
        return broker

    def test_ws_subscribe_symbol(self):
        """_ws_subscribe_symbol subscribes once per symbol."""
        broker = self._make_broker(use_ws=True)
        broker._ws_order_manager = Mock()

        broker._ws_subscribe_symbol('BTC/USDT')
        broker._ws_order_manager.subscribe_my_trades.assert_called_once()
        self.assertIn('BTC/USDT', broker._ws_subscribed_symbols)

        # Second call should not subscribe again
        broker._ws_order_manager.subscribe_my_trades.reset_mock()
        broker._ws_subscribe_symbol('BTC/USDT')
        broker._ws_order_manager.subscribe_my_trades.assert_not_called()

    def test_ws_subscribe_multiple_symbols(self):
        """_ws_subscribe_symbol handles multiple symbols."""
        broker = self._make_broker(use_ws=True)
        broker._ws_order_manager = Mock()

        broker._ws_subscribe_symbol('BTC/USDT')
        broker._ws_subscribe_symbol('ETH/USDT')

        self.assertEqual(broker._ws_order_manager.subscribe_my_trades.call_count, 2)
        self.assertEqual(broker._ws_subscribed_symbols, {'BTC/USDT', 'ETH/USDT'})

    def test_ws_subscribe_no_manager(self):
        """_ws_subscribe_symbol is no-op without manager."""
        broker = self._make_broker(use_ws=True)
        broker._ws_order_manager = None

        broker._ws_subscribe_symbol('BTC/USDT')
        self.assertEqual(len(broker._ws_subscribed_symbols), 0)


class TestBrokerWsOrderCallback(unittest.TestCase):
    """Tests for CCXTBroker._on_ws_my_trades callback."""

    def _make_broker(self):
        from backtrader.brokers.ccxtbroker import CCXTBroker
        broker = CCXTBroker.__new__(CCXTBroker)
        broker._ws_order_updates = __import__('queue').Queue()
        return broker

    def test_callback_enqueues_trades(self):
        """_on_ws_my_trades puts trades in the queue."""
        broker = self._make_broker()
        trades = [
            {'id': 't1', 'order': 'o1', 'amount': 0.01, 'price': 50000},
            {'id': 't2', 'order': 'o1', 'amount': 0.02, 'price': 50100},
        ]
        broker._on_ws_my_trades(trades)
        self.assertEqual(broker._ws_order_updates.qsize(), 2)

    def test_callback_empty_trades(self):
        """_on_ws_my_trades handles empty list."""
        broker = self._make_broker()
        broker._on_ws_my_trades([])
        self.assertEqual(broker._ws_order_updates.qsize(), 0)

    def test_callback_none_trades(self):
        """_on_ws_my_trades handles None."""
        broker = self._make_broker()
        broker._on_ws_my_trades(None)
        self.assertEqual(broker._ws_order_updates.qsize(), 0)


class TestBrokerWsOrderProcessing(unittest.TestCase):
    """Tests for CCXTBroker._process_ws_order_updates."""

    def _make_broker(self):
        from backtrader.brokers.ccxtbroker import CCXTBroker
        broker = CCXTBroker.__new__(CCXTBroker)
        broker.debug = False
        broker._ws_order_updates = __import__('queue').Queue()
        broker._consecutive_failures = 0
        broker._bracket_manager = None
        broker.open_orders = []
        broker.notifs = __import__('queue').Queue()
        broker.positions = __import__('collections').defaultdict(
            lambda: Mock(clone=Mock(return_value=Mock()))
        )
        return broker

    def _make_mock_order(self, order_id, amount, is_buy=True):
        order = Mock()
        order.ccxt_order = {'id': order_id, 'amount': amount}
        order.executed_fills = []
        order.isbuy.return_value = is_buy
        order.executed = Mock()
        order.executed.size = 0
        order.data = Mock()
        order.data._dataname = 'BTC/USDT'
        order.clone.return_value = Mock()
        return order

    def test_process_fill_updates_position(self):
        """WS fill updates position and notifies."""
        broker = self._make_broker()
        order = self._make_mock_order('order_1', 0.01)
        broker.open_orders.append(order)

        # Simulate a complete fill
        trade = {
            'id': 'trade_1',
            'order': 'order_1',
            'amount': 0.01,
            'price': 50000.0,
            'timestamp': 1000000,
        }
        broker._ws_order_updates.put(trade)

        processed = broker._process_ws_order_updates()
        self.assertEqual(processed, 1)
        order.execute.assert_called_once()
        self.assertIn('trade_1', order.executed_fills)

    def test_process_ignores_duplicate_fill(self):
        """WS processing skips already-processed trades."""
        broker = self._make_broker()
        order = self._make_mock_order('order_1', 0.01)
        order.executed_fills = ['trade_1']  # Already processed
        broker.open_orders.append(order)

        trade = {
            'id': 'trade_1',
            'order': 'order_1',
            'amount': 0.01,
            'price': 50000.0,
            'timestamp': 1000000,
        }
        broker._ws_order_updates.put(trade)

        processed = broker._process_ws_order_updates()
        self.assertEqual(processed, 0)
        order.execute.assert_not_called()

    def test_process_ignores_unknown_order(self):
        """WS processing skips trades for unknown orders."""
        broker = self._make_broker()

        trade = {
            'id': 'trade_1',
            'order': 'unknown_order',
            'amount': 0.01,
            'price': 50000.0,
            'timestamp': 1000000,
        }
        broker._ws_order_updates.put(trade)

        processed = broker._process_ws_order_updates()
        self.assertEqual(processed, 0)

    def test_process_ignores_no_order_id(self):
        """WS processing skips trades without order ID."""
        broker = self._make_broker()

        trade = {'id': 'trade_1', 'amount': 0.01, 'price': 50000.0}
        broker._ws_order_updates.put(trade)

        processed = broker._process_ws_order_updates()
        self.assertEqual(processed, 0)

    def test_process_resets_failure_counter(self):
        """Successful WS processing resets consecutive failures."""
        broker = self._make_broker()
        broker._consecutive_failures = 5
        order = self._make_mock_order('order_1', 0.01)
        broker.open_orders.append(order)

        trade = {
            'id': 'trade_1',
            'order': 'order_1',
            'amount': 0.01,
            'price': 50000.0,
            'timestamp': 1000000,
        }
        broker._ws_order_updates.put(trade)

        broker._process_ws_order_updates()
        self.assertEqual(broker._consecutive_failures, 0)


class TestBrokerNextWsMode(unittest.TestCase):
    """Tests for CCXTBroker.next() in WebSocket mode."""

    def _make_broker(self, use_ws=True):
        from backtrader.brokers.ccxtbroker import CCXTBroker
        broker = CCXTBroker.__new__(CCXTBroker)
        broker.debug = False
        broker._use_ws_orders = use_ws
        broker._ws_order_manager = Mock() if use_ws else None
        broker._threaded_order_manager = None
        broker._ws_order_updates = __import__('queue').Queue()
        broker._consecutive_failures = 0
        broker._max_consecutive_failures = 10
        broker._bracket_manager = None
        broker.open_orders = []
        broker.notifs = __import__('queue').Queue()
        broker.positions = __import__('collections').defaultdict(
            lambda: Mock(clone=Mock(return_value=Mock()))
        )
        broker._last_op_time = 0
        broker.store = Mock()
        return broker

    @patch.object(
        __import__('backtrader.brokers.ccxtbroker', fromlist=['CCXTBroker']).CCXTBroker,
        '_process_ws_order_updates'
    )
    def test_next_uses_ws_mode(self, mock_process):
        """next() calls _process_ws_order_updates in WS mode."""
        broker = self._make_broker(use_ws=True)
        broker.next()
        mock_process.assert_called_once()

    def test_next_ws_does_periodic_rest_check(self):
        """next() in WS mode does periodic REST check for stale orders."""
        broker = self._make_broker(use_ws=True)
        broker.open_orders = [Mock()]
        broker._last_op_time = time.time() - 60  # 60s ago

        with patch.object(broker, '_process_ws_order_updates'), \
             patch.object(broker, '_next') as mock_next:
            broker.next()
            mock_next.assert_called_once()


# ============================================================================
# P2-2: Shared WebSocket Manager Tests
# ============================================================================

class TestStoreSharedWebSocket(unittest.TestCase):
    """Tests for CCXTStore shared WebSocket manager."""

    def _make_store(self):
        from backtrader.stores.ccxtstore import CCXTStore
        store = CCXTStore.__new__(CCXTStore)
        store.exchange_id = 'binance'
        store.exchange = Mock()
        store.exchange.apiKey = 'test_key'
        store.exchange.secret = 'test_secret'
        store.exchange.password = None
        store.exchange.options = {}
        store.exchange.markets = {'BTC/USDT': {}}
        store.debug = False
        store._ws_manager = None
        store._connection_manager = None
        store._rate_limiter = None
        return store

    @patch('backtrader.stores.ccxtstore.CCXTWebSocketManager')
    def test_get_websocket_manager_creates_once(self, MockWSManager):
        """get_websocket_manager creates manager only once."""
        store = self._make_store()
        mock_instance = Mock()
        MockWSManager.return_value = mock_instance

        ws1 = store.get_websocket_manager()
        ws2 = store.get_websocket_manager()

        self.assertIs(ws1, ws2)
        MockWSManager.assert_called_once()
        mock_instance.start.assert_called_once()

    @patch('backtrader.stores.ccxtstore.CCXTWebSocketManager')
    def test_get_websocket_manager_passes_markets(self, MockWSManager):
        """get_websocket_manager passes pre-loaded markets."""
        store = self._make_store()
        mock_instance = Mock()
        MockWSManager.return_value = mock_instance

        store.get_websocket_manager()

        call_kwargs = MockWSManager.call_args
        self.assertEqual(call_kwargs[1].get('markets') or call_kwargs[0][2],
                         {'BTC/USDT': {}})

    @patch('backtrader.stores.ccxtstore.HAS_CCXT_ENHANCEMENTS', False)
    def test_get_websocket_manager_returns_none_without_enhancements(self):
        """get_websocket_manager returns None when enhancements unavailable."""
        store = self._make_store()
        result = store.get_websocket_manager()
        self.assertIsNone(result)

    @patch('backtrader.stores.ccxtstore.CCXTWebSocketManager')
    def test_stop_cleans_up_ws_manager(self, MockWSManager):
        """stop() stops and clears the shared WS manager."""
        store = self._make_store()
        mock_instance = Mock()
        MockWSManager.return_value = mock_instance

        store.get_websocket_manager()
        self.assertIsNotNone(store._ws_manager)

        store.stop()
        mock_instance.stop.assert_called_once()
        self.assertIsNone(store._ws_manager)

    @patch('backtrader.stores.ccxtstore.CCXTWebSocketManager')
    def test_get_websocket_manager_handles_init_error(self, MockWSManager):
        """get_websocket_manager handles init errors gracefully."""
        store = self._make_store()
        MockWSManager.side_effect = Exception("ccxtpro not available")

        result = store.get_websocket_manager()
        self.assertIsNone(result)


class TestFeedSharedWebSocket(unittest.TestCase):
    """Tests for CCXTFeed using shared WebSocket from store."""

    def _make_feed(self):
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = CCXTFeed.__new__(CCXTFeed)
        feed.p = Mock()
        feed.p.dataname = 'BTC/USDT'
        feed.p.use_websocket = True
        feed.p.debug = False
        feed._timeframe = 4  # Minutes
        feed._compression = 1
        feed._websocket_manager = None
        feed._ws_connected = False
        feed._ws_lock = __import__('threading').Lock()
        feed.store = Mock()
        feed.store.exchange_id = 'binance'
        feed.store.exchange = Mock()
        feed.store.exchange.config = {}
        feed.store.exchange.markets = {}
        feed.store.get_granularity.return_value = '1m'
        return feed

    def test_start_websocket_uses_shared_manager(self):
        """_start_websocket uses store.get_websocket_manager()."""
        feed = self._make_feed()
        mock_ws = Mock()
        feed.store.get_websocket_manager.return_value = mock_ws

        feed._start_websocket()

        feed.store.get_websocket_manager.assert_called_once()
        self.assertIs(feed._websocket_manager, mock_ws)
        mock_ws.subscribe_ohlcv.assert_called_once_with(
            'BTC/USDT', '1m', feed._on_websocket_ohlcv
        )

    def test_start_websocket_fallback_to_per_feed(self):
        """_start_websocket creates per-feed WS if store returns None."""
        feed = self._make_feed()
        feed.store.get_websocket_manager.return_value = None

        with patch('backtrader.feeds.ccxtfeed.CCXTWebSocketManager') as MockWS:
            mock_ws = Mock()
            MockWS.return_value = mock_ws
            feed._start_websocket()

            MockWS.assert_called_once()
            mock_ws.start.assert_called_once()
            mock_ws.subscribe_ohlcv.assert_called_once()


# ============================================================================
# P2-3: Funding Rate Shared WebSocket Tests
# ============================================================================

class TestFundingFeedSharedWebSocket(unittest.TestCase):
    """Tests for CCXTFeedWithFunding using shared WebSocket."""

    def _make_feed(self):
        from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding
        feed = CCXTFeedWithFunding.__new__(CCXTFeedWithFunding)
        feed.p = Mock()
        feed.p.dataname = 'BTC/USDT:USDT'
        feed.p.use_websocket = True
        feed.p.include_funding = True
        feed.p.debug = False
        feed.p.ws_startup_timeout = 1
        feed._timeframe = 4
        feed._compression = 1
        feed._websocket_manager = None
        feed._ws_connected = False
        feed._ws_lock = __import__('threading').Lock()
        feed._ws_funding_connected = False
        feed._ws_ohlcv_connected = False
        feed._ws_is_shared = False
        feed.store = Mock()
        feed.store.exchange_id = 'binance'
        feed.store.exchange = Mock()
        feed.store.exchange.config = {}
        feed.store.exchange.markets = {}
        feed.store.get_granularity.return_value = '1m'
        return feed

    def test_start_websocket_uses_shared_manager(self):
        """Funding feed uses store's shared WS manager."""
        feed = self._make_feed()
        mock_ws = Mock()
        mock_ws.is_connected.return_value = True
        feed.store.get_websocket_manager.return_value = mock_ws

        feed._start_websocket()

        feed.store.get_websocket_manager.assert_called_once()
        self.assertTrue(feed._ws_is_shared)
        # Should subscribe to 3 channels: ohlcv, funding_rate, mark_price
        self.assertEqual(mock_ws.subscribe_ohlcv.call_count, 1)
        self.assertEqual(mock_ws.subscribe_funding_rate.call_count, 1)
        self.assertEqual(mock_ws.subscribe_mark_price.call_count, 1)

    def test_stop_does_not_kill_shared_ws(self):
        """stop() should NOT stop the shared WS manager."""
        feed = self._make_feed()
        mock_ws = Mock()
        feed._websocket_manager = mock_ws
        feed._ws_is_shared = True
        feed._threaded_data_manager = None

        feed.stop()

        mock_ws.stop.assert_not_called()
        self.assertIsNone(feed._websocket_manager)

    def test_stop_kills_per_feed_ws(self):
        """stop() SHOULD stop a per-feed WS manager."""
        feed = self._make_feed()
        mock_ws = Mock()
        feed._websocket_manager = mock_ws
        feed._ws_is_shared = False
        feed._threaded_data_manager = None

        feed.stop()

        mock_ws.stop.assert_called_once()


# ============================================================================
# P2 Integration: Broker _submit() with WS subscription
# ============================================================================

class TestBrokerSubmitWsSubscription(unittest.TestCase):
    """Tests for _submit() auto-subscribing WS for new symbols."""

    def _make_broker(self):
        from backtrader.brokers.ccxtbroker import CCXTBroker
        broker = CCXTBroker.__new__(CCXTBroker)
        broker.store = Mock()
        broker.store.create_order.return_value = {'id': 'order_123', 'status': 'open'}
        broker.debug = False
        broker._max_retries = 2
        broker._retry_delay = 0.01
        broker._consecutive_failures = 0
        broker._max_consecutive_failures = 10
        broker._threaded_order_manager = None
        broker._bracket_manager = None
        broker._ws_order_manager = Mock()
        broker._use_threaded = False
        broker._use_ws_orders = True
        broker._ws_order_updates = __import__('queue').Queue()
        broker._ws_subscribed_symbols = set()
        broker.order_types = {0: 'market', 2: 'limit'}
        broker.notifs = __import__('queue').Queue()
        broker.open_orders = []
        broker.positions = __import__('collections').defaultdict(
            lambda: Mock(clone=Mock(return_value=Mock()))
        )
        return broker

    @patch('backtrader.brokers.ccxtbroker.CCXTOrder')
    def test_submit_subscribes_ws_for_symbol(self, MockCCXTOrder):
        """_submit() subscribes WS my_trades for the order symbol."""
        broker = self._make_broker()
        mock_order = Mock()
        mock_order.clone.return_value = Mock()
        MockCCXTOrder.return_value = mock_order

        mock_data = Mock()
        mock_data.p.dataname = 'ETH/USDT'
        mock_data.datetime.datetime.return_value = datetime(2025, 1, 1)

        broker._submit(
            owner=Mock(), data=mock_data, exectype=0,
            side='buy', amount=0.1, price=None, params={}
        )

        self.assertIn('ETH/USDT', broker._ws_subscribed_symbols)
        broker._ws_order_manager.subscribe_my_trades.assert_called_once()


if __name__ == '__main__':
    unittest.main()
