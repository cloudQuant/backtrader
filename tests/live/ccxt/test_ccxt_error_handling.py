#!/usr/bin/env python
"""Unit tests for CCXT Broker and Feed error handling and reconnection logic.

Tests for:
- CCXTBroker._retry_api_call() with exponential backoff
- CCXTBroker.next() connection awareness and adaptive polling
- CCXTBroker._process_threaded_updates() integration
- CCXTBroker._submit() error handling with rejection notifications
- CCXTBroker.cancel() error handling
- CCXTFeed._fetch_ohlcv_with_retry() retry logic
- CCXTFeed._check_ws_health() stale connection detection
- CCXTFeed._load() WebSocket fallback to REST
- CCXTFeed._on_websocket_ohlcv() reconnection backfill detection
"""

import sys
import os
import time
import threading
import unittest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime

# Add backtrader path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))


class TestBrokerRetryApiCall(unittest.TestCase):
    """Tests for CCXTBroker._retry_api_call()."""

    def _make_broker(self, **kwargs):
        """Create a CCXTBroker with mocked store."""
        from backtrader.brokers.ccxtbroker import CCXTBroker
        mock_store = Mock()
        mock_store._cash = 10000.0
        mock_store._value = 10000.0
        mock_store.currency = 'USDT'
        mock_store.is_connected.return_value = True
        broker = CCXTBroker.__new__(CCXTBroker)
        broker.store = mock_store
        broker.debug = kwargs.get('debug', False)
        broker._max_retries = kwargs.get('max_retries', 3)
        broker._retry_delay = kwargs.get('retry_delay', 0.01)  # Fast for tests
        broker._consecutive_failures = 0
        broker._max_consecutive_failures = 10
        return broker

    def test_success_first_try(self):
        """API call succeeds on first attempt."""
        broker = self._make_broker()
        func = Mock(return_value={'id': '123', 'status': 'open'})
        result = broker._retry_api_call(func, 'arg1', key='val')
        self.assertEqual(result, {'id': '123', 'status': 'open'})
        func.assert_called_once_with('arg1', key='val')
        self.assertEqual(broker._consecutive_failures, 0)

    def test_retry_on_network_error(self):
        """Retries on NetworkError with exponential backoff."""
        from ccxt.base.errors import NetworkError
        broker = self._make_broker(max_retries=3, retry_delay=0.01)
        func = Mock(side_effect=[
            NetworkError("timeout"),
            NetworkError("timeout"),
            {'id': '123', 'status': 'open'}
        ])
        result = broker._retry_api_call(func)
        self.assertEqual(result, {'id': '123', 'status': 'open'})
        self.assertEqual(func.call_count, 3)
        self.assertEqual(broker._consecutive_failures, 0)

    def test_retry_on_exchange_not_available(self):
        """Retries on ExchangeNotAvailable."""
        from ccxt.base.errors import ExchangeNotAvailable
        broker = self._make_broker(max_retries=2, retry_delay=0.01)
        func = Mock(side_effect=[
            ExchangeNotAvailable("maintenance"),
            {'status': 'ok'}
        ])
        result = broker._retry_api_call(func)
        self.assertEqual(result, {'status': 'ok'})

    def test_no_retry_on_exchange_error(self):
        """ExchangeError (business logic) should not retry."""
        from ccxt.base.errors import ExchangeError
        broker = self._make_broker()
        func = Mock(side_effect=ExchangeError("insufficient balance"))
        with self.assertRaises(ExchangeError):
            broker._retry_api_call(func)
        func.assert_called_once()

    def test_all_retries_exhausted(self):
        """Raises last exception after max retries."""
        from ccxt.base.errors import NetworkError
        broker = self._make_broker(max_retries=3, retry_delay=0.01)
        func = Mock(side_effect=NetworkError("persistent failure"))
        with self.assertRaises(NetworkError):
            broker._retry_api_call(func)
        self.assertEqual(func.call_count, 3)
        self.assertEqual(broker._consecutive_failures, 3)

    def test_consecutive_failure_tracking(self):
        """Consecutive failures are tracked and reset on success."""
        from ccxt.base.errors import NetworkError
        broker = self._make_broker(max_retries=1, retry_delay=0.01)

        # Fail once
        func_fail = Mock(side_effect=NetworkError("fail"))
        try:
            broker._retry_api_call(func_fail)
        except NetworkError:
            pass
        self.assertEqual(broker._consecutive_failures, 1)

        # Succeed resets counter
        func_ok = Mock(return_value="ok")
        broker._retry_api_call(func_ok)
        self.assertEqual(broker._consecutive_failures, 0)


class TestBrokerNextConnectionAwareness(unittest.TestCase):
    """Tests for CCXTBroker.next() connection awareness."""

    def _make_broker(self):
        from backtrader.brokers.ccxtbroker import CCXTBroker
        broker = CCXTBroker.__new__(CCXTBroker)
        broker.store = Mock()
        broker.store.is_connected.return_value = True
        broker.store._cash = 10000.0
        broker.store._value = 10000.0
        broker.debug = False
        broker._max_retries = 3
        broker._retry_delay = 0.01
        broker._consecutive_failures = 0
        broker._max_consecutive_failures = 10
        broker._last_op_time = 0
        broker._threaded_order_manager = None
        broker._use_ws_orders = False
        broker._ws_order_manager = None
        broker.open_orders = {}
        broker._bracket_manager = None
        return broker

    def test_skips_when_disconnected(self):
        """next() should skip API calls when store is disconnected."""
        broker = self._make_broker()
        broker.store.is_connected.return_value = False
        broker._consecutive_failures = 0

        # Patch _next to ensure it's not called
        broker._next = Mock()
        broker.next()
        broker._next.assert_not_called()
        self.assertEqual(broker._consecutive_failures, 1)

    def test_normal_polling_when_connected(self):
        """next() should call _next() when connected."""
        broker = self._make_broker()
        broker._last_op_time = 0  # Force execution
        broker._next = Mock()
        broker.next()
        broker._next.assert_called_once()

    def test_backs_off_after_many_failures(self):
        """next() backs off to 30s intervals after many consecutive failures."""
        broker = self._make_broker()
        broker._consecutive_failures = 15  # > max_consecutive_failures
        broker._last_op_time = time.time() - 5  # Only 5 seconds ago
        broker._next = Mock()
        broker.next()
        # Should not call _next because < 30 seconds have passed
        broker._next.assert_not_called()

    def test_uses_threaded_manager_when_available(self):
        """next() should use threaded order manager when available."""
        broker = self._make_broker()
        broker._last_op_time = 0
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        broker._threaded_order_manager = mock_manager
        broker._process_threaded_updates = Mock()
        broker._next = Mock()

        broker.next()
        broker._process_threaded_updates.assert_called_once()
        broker._next.assert_not_called()


class TestBrokerProcessThreadedUpdates(unittest.TestCase):
    """Tests for CCXTBroker._process_threaded_updates()."""

    def _make_broker_with_order(self):
        from backtrader.brokers.ccxtbroker import CCXTBroker, CCXTOrder
        from backtrader.ccxt.threading import OrderUpdate

        broker = CCXTBroker.__new__(CCXTBroker)
        broker.store = Mock()
        broker.debug = False
        broker._bracket_manager = None
        broker.notifs = __import__('queue').Queue()
        broker.positions = __import__('collections').defaultdict(
            lambda: Mock(clone=Mock(return_value=Mock()))
        )

        # Create mock order
        mock_order = Mock()
        mock_order.ccxt_order = {'id': 'order_123'}
        mock_order.isbuy.return_value = True
        mock_order.executed = Mock()
        mock_order.executed.size = 0.0
        mock_order.clone.return_value = Mock()

        broker.open_orders = {'order_123': mock_order}

        # Create mock threaded manager
        mock_manager = Mock()
        broker._threaded_order_manager = mock_manager

        return broker, mock_order, mock_manager, OrderUpdate

    def test_processes_fill_update(self):
        """Processes a fill update from threaded manager."""
        broker, order, manager, OrderUpdate = self._make_broker_with_order()

        update = OrderUpdate(
            order_id='order_123',
            status='open',
            filled=0.5,
            remaining=0.5,
            average=50000.0,
            timestamp=1000000
        )
        manager.get_updates.return_value = [update]

        broker._process_threaded_updates()
        order.execute.assert_called_once()
        order.partial.assert_called_once()

    def test_handles_closed_order(self):
        """Removes order from open_orders when closed."""
        broker, order, manager, OrderUpdate = self._make_broker_with_order()

        update = OrderUpdate(
            order_id='order_123',
            status='closed',
            filled=1.0,
            remaining=0.0,
            average=50000.0,
            timestamp=1000000
        )
        manager.get_updates.return_value = [update]

        broker._process_threaded_updates()
        self.assertNotIn('order_123', broker.open_orders)

    def test_handles_canceled_order(self):
        """Cancels and removes order on cancel update."""
        broker, order, manager, OrderUpdate = self._make_broker_with_order()

        update = OrderUpdate(
            order_id='order_123',
            status='canceled',
            filled=0.0,
            remaining=1.0,
            average=0.0,
            timestamp=1000000
        )
        manager.get_updates.return_value = [update]

        broker._process_threaded_updates()
        order.cancel.assert_called_once()
        self.assertNotIn('order_123', broker.open_orders)

    def test_ignores_unknown_order(self):
        """Ignores updates for unknown order IDs."""
        broker, order, manager, OrderUpdate = self._make_broker_with_order()

        update = OrderUpdate(
            order_id='unknown_456',
            status='closed',
            filled=1.0,
            remaining=0.0,
            average=50000.0,
            timestamp=1000000
        )
        manager.get_updates.return_value = [update]

        broker._process_threaded_updates()
        # Order should still be in open_orders
        self.assertIn('order_123', broker.open_orders)


class TestBrokerSubmitErrorHandling(unittest.TestCase):
    """Tests for CCXTBroker._submit() error handling.

    We patch CCXTOrder to avoid the complex Order.__init__ chain which
    requires fully initialized data feeds.
    """

    def _make_broker(self):
        from backtrader.brokers.ccxtbroker import CCXTBroker
        broker = CCXTBroker.__new__(CCXTBroker)
        broker.store = Mock()
        broker.debug = False
        broker._max_retries = 2
        broker._retry_delay = 0.01
        broker._consecutive_failures = 0
        broker._max_consecutive_failures = 10
        broker._threaded_order_manager = None
        broker._bracket_manager = None
        broker._use_ws_orders = False
        broker._ws_order_manager = None
        broker._ws_subscribed_symbols = set()
        broker.order_types = {0: 'market', 2: 'limit'}
        broker.notifs = __import__('queue').Queue()
        broker.open_orders = {}
        broker.positions = __import__('collections').defaultdict(
            lambda: Mock(clone=Mock(return_value=Mock()))
        )
        return broker

    def _make_mock_data(self):
        """Create a mock data feed for _submit()."""
        mock_data = Mock()
        mock_data.p.dataname = 'BTC/USDT'
        mock_data.datetime.datetime.return_value = datetime(2025, 1, 1)
        return mock_data

    @patch('backtrader.brokers.ccxtbroker.CCXTOrder')
    def test_submit_network_error_returns_rejected(self, MockCCXTOrder):
        """Order submission returns rejected order on network error."""
        from ccxt.base.errors import NetworkError
        broker = self._make_broker()
        broker.store.create_order.side_effect = NetworkError("timeout")

        mock_order_instance = Mock()
        mock_order_instance.clone.return_value = Mock()
        MockCCXTOrder.return_value = mock_order_instance

        mock_data = self._make_mock_data()
        order = broker._submit(
            owner=Mock(), data=mock_data, exectype=0,
            side='buy', amount=0.01, price=None, params={}
        )
        # Order should be rejected, not in open_orders
        self.assertEqual(len(broker.open_orders), 0)
        mock_order_instance.reject.assert_called_once()
        self.assertFalse(broker.notifs.empty())

    @patch('backtrader.brokers.ccxtbroker.CCXTOrder')
    def test_submit_exchange_error_returns_rejected(self, MockCCXTOrder):
        """Order submission returns rejected order on exchange error."""
        from ccxt.base.errors import ExchangeError
        broker = self._make_broker()
        broker.store.create_order.side_effect = ExchangeError("insufficient balance")

        mock_order_instance = Mock()
        mock_order_instance.clone.return_value = Mock()
        MockCCXTOrder.return_value = mock_order_instance

        mock_data = self._make_mock_data()
        order = broker._submit(
            owner=Mock(), data=mock_data, exectype=2,
            side='buy', amount=0.01, price=50000, params={}
        )
        self.assertEqual(len(broker.open_orders), 0)
        mock_order_instance.reject.assert_called_once()

    @patch('backtrader.brokers.ccxtbroker.CCXTOrder')
    def test_submit_success_registers_with_threaded_manager(self, MockCCXTOrder):
        """Successful order registers with threaded order manager."""
        broker = self._make_broker()
        broker.store.create_order.return_value = {'id': 'order_123', 'status': 'open'}
        mock_manager = Mock()
        mock_manager.is_running.return_value = True
        broker._threaded_order_manager = mock_manager

        mock_order_instance = Mock()
        mock_order_instance.clone.return_value = Mock()
        MockCCXTOrder.return_value = mock_order_instance

        mock_data = self._make_mock_data()
        order = broker._submit(
            owner=Mock(), data=mock_data, exectype=0,
            side='buy', amount=0.01, price=None, params={}
        )
        mock_manager.add_order.assert_called_once_with('order_123', 'BTC/USDT')
        self.assertEqual(len(broker.open_orders), 1)


class TestBrokerCancelErrorHandling(unittest.TestCase):
    """Tests for CCXTBroker.cancel() error handling."""

    def _make_broker_with_order(self):
        from backtrader.brokers.ccxtbroker import CCXTBroker
        broker = CCXTBroker.__new__(CCXTBroker)
        broker.store = Mock()
        broker.debug = False
        broker._max_retries = 2
        broker._retry_delay = 0.01
        broker._consecutive_failures = 0
        broker._max_consecutive_failures = 10
        broker._threaded_order_manager = None
        broker._bracket_manager = None
        broker._last_op_time = 0
        broker.mappings = {
            "closed_order": {"key": "status", "value": "closed"},
            "canceled_order": {"key": "status", "value": "canceled"},
        }
        broker.notifs = __import__('queue').Queue()
        broker.open_orders = {}
        broker.positions = __import__('collections').defaultdict(
            lambda: Mock(clone=Mock(return_value=Mock()))
        )

        mock_order = Mock()
        mock_order.ccxt_order = {'id': 'order_123'}
        mock_order.data = Mock()
        mock_order.data.p.dataname = 'BTC/USDT'
        mock_order.clone.return_value = Mock()
        broker.open_orders = {'order_123': mock_order}

        return broker, mock_order

    def test_cancel_network_error_returns_order(self):
        """cancel() returns order gracefully on network error."""
        from ccxt.base.errors import NetworkError
        broker, order = self._make_broker_with_order()
        broker.store.fetch_order.side_effect = NetworkError("timeout")

        result = broker.cancel(order)
        self.assertEqual(result, order)
        # Order should still be in open_orders
        self.assertIn('order_123', broker.open_orders)

    def test_cancel_order_not_found(self):
        """cancel() marks order canceled if exchange says not found."""
        from ccxt.base.errors import ExchangeError
        broker, order = self._make_broker_with_order()
        broker.store.fetch_order.side_effect = ExchangeError("Order not found")

        result = broker.cancel(order)
        order.cancel.assert_called_once()
        self.assertNotIn('order_123', broker.open_orders)


class TestFeedFetchWithRetry(unittest.TestCase):
    """Tests for CCXTFeed._fetch_ohlcv_with_retry()."""

    def _make_feed(self):
        """Create a minimal CCXTFeed-like object for testing."""
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = CCXTFeed.__new__(CCXTFeed)
        feed.store = Mock()
        feed.p = Mock()
        feed.p.max_fetch_retries = 3
        feed.p.fetch_retry_delay = 0.01
        feed.p.debug = False
        return feed

    def test_success_first_try(self):
        """Fetch succeeds on first attempt."""
        feed = self._make_feed()
        feed.store.fetch_ohlcv.return_value = [[1000, 1, 2, 0.5, 1.5, 100]]
        result = feed._fetch_ohlcv_with_retry('BTC/USDT', '1h', 0, 10)
        self.assertEqual(len(result), 1)
        feed.store.fetch_ohlcv.assert_called_once()

    def test_retry_on_network_error(self):
        """Retries on network error then succeeds."""
        from ccxt.base.errors import NetworkError
        feed = self._make_feed()
        feed.store.fetch_ohlcv.side_effect = [
            NetworkError("timeout"),
            [[1000, 1, 2, 0.5, 1.5, 100]]
        ]
        result = feed._fetch_ohlcv_with_retry('BTC/USDT', '1h', 0, 10)
        self.assertEqual(len(result), 1)
        self.assertEqual(feed.store.fetch_ohlcv.call_count, 2)

    def test_no_retry_on_exchange_error(self):
        """ExchangeError should not be retried."""
        from ccxt.base.errors import ExchangeError
        feed = self._make_feed()
        feed.store.fetch_ohlcv.side_effect = ExchangeError("bad symbol")
        with self.assertRaises(ExchangeError):
            feed._fetch_ohlcv_with_retry('BAD/SYMBOL', '1h', 0, 10)
        feed.store.fetch_ohlcv.assert_called_once()

    def test_all_retries_exhausted(self):
        """Raises after all retries exhausted."""
        from ccxt.base.errors import NetworkError
        feed = self._make_feed()
        feed.store.fetch_ohlcv.side_effect = NetworkError("persistent")
        with self.assertRaises(NetworkError):
            feed._fetch_ohlcv_with_retry('BTC/USDT', '1h', 0, 10)
        self.assertEqual(feed.store.fetch_ohlcv.call_count, 3)


class TestFeedWsHealthCheck(unittest.TestCase):
    """Tests for CCXTFeed._check_ws_health()."""

    def _make_feed(self):
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = CCXTFeed.__new__(CCXTFeed)
        feed._ws_connected = True
        feed._websocket_manager = Mock()
        feed._websocket_manager.is_connected.return_value = True
        feed._ws_last_data_time = time.time()
        feed.p = Mock()
        feed.p.ws_health_check_interval = 30.0
        feed.p.debug = False
        return feed

    def test_healthy_connection(self):
        """Connected WS with recent data stays connected."""
        feed = self._make_feed()
        feed._ws_last_data_time = time.time()
        feed._check_ws_health()
        self.assertTrue(feed._ws_connected)

    def test_stale_connection_detected(self):
        """WS with no recent data is marked disconnected."""
        feed = self._make_feed()
        feed._ws_last_data_time = time.time() - 60  # 60s silence
        feed.p.ws_health_check_interval = 30.0
        feed._check_ws_health()
        self.assertFalse(feed._ws_connected)

    def test_ws_manager_disconnected(self):
        """WS manager reporting disconnected marks feed disconnected."""
        feed = self._make_feed()
        feed._websocket_manager.is_connected.return_value = False
        feed._check_ws_health()
        self.assertFalse(feed._ws_connected)

    def test_no_manager_skips_check(self):
        """No WS manager skips health check."""
        feed = self._make_feed()
        feed._websocket_manager = None
        feed._check_ws_health()  # Should not raise
        self.assertTrue(feed._ws_connected)


class TestFeedWsReconnectBackfill(unittest.TestCase):
    """Tests for WebSocket reconnection and backfill detection."""

    def _make_feed(self):
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = CCXTFeed.__new__(CCXTFeed)
        feed._ws_connected = False
        feed._ws_last_data_time = 0
        feed._ws_disconnected_since = time.time() - 120  # Disconnected 2 min ago
        feed._ws_backfill_needed = False
        feed._last_ts = 1000
        feed._last_update_bar_time = 1000
        feed._ws_lock = threading.Lock()
        feed._data = __import__('queue').Queue(maxsize=1000)
        feed.p = Mock()
        feed.p.debug = False
        return feed

    def test_backfill_detected_after_long_disconnect(self):
        """Backfill is flagged after reconnection with > 60s gap."""
        feed = self._make_feed()
        feed._ws_disconnected_since = time.time() - 120  # 2 min gap

        # Simulate reconnection data
        bar = [2000, 1.0, 2.0, 0.5, 1.5, 100]
        feed._on_websocket_ohlcv([bar])

        self.assertTrue(feed._ws_connected)
        self.assertTrue(feed._ws_backfill_needed)
        self.assertEqual(feed._ws_disconnected_since, 0)

    def test_no_backfill_for_short_disconnect(self):
        """No backfill for short disconnections (< 60s)."""
        feed = self._make_feed()
        feed._ws_disconnected_since = time.time() - 30  # 30s gap

        bar = [2000, 1.0, 2.0, 0.5, 1.5, 100]
        feed._on_websocket_ohlcv([bar])

        self.assertTrue(feed._ws_connected)
        self.assertFalse(feed._ws_backfill_needed)

    def test_empty_data_ignored(self):
        """Empty OHLCV data is ignored."""
        feed = self._make_feed()
        feed._on_websocket_ohlcv([])
        self.assertFalse(feed._ws_connected)

    def test_old_data_filtered(self):
        """Data older than last timestamp is filtered out."""
        feed = self._make_feed()
        feed._last_ts = 5000
        feed._ws_disconnected_since = 0

        bar = [3000, 1.0, 2.0, 0.5, 1.5, 100]  # Older than _last_ts
        feed._on_websocket_ohlcv([bar])

        self.assertTrue(feed._data.empty())


class TestFeedUpdateBarErrorHandling(unittest.TestCase):
    """Tests for CCXTFeed._update_bar() error handling."""

    def _make_feed(self):
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = CCXTFeed.__new__(CCXTFeed)
        feed.store = Mock()
        feed.store.is_connected.return_value = True
        feed.store.get_granularity.return_value = '1h'
        feed._data = __import__('queue').Queue(maxsize=1000)
        feed._last_ts = 0
        feed._last_update_bar_time = 0
        feed._timeframe = 4  # Minutes
        feed._compression = 60
        feed._consecutive_fetch_errors = 0
        feed._max_consecutive_errors = 10
        feed._last_error_time = 0
        feed.p = Mock()
        feed.p.dataname = 'BTC/USDT'
        feed.p.fetch_ohlcv_params = {}
        feed.p.ohlcv_limit = 100
        feed.p.drop_newest = False
        feed.p.debug = False
        feed.p.max_fetch_retries = 2
        feed.p.fetch_retry_delay = 0.01
        return feed

    def test_skips_when_disconnected(self):
        """_update_bar() skips fetch when store is disconnected."""
        feed = self._make_feed()
        feed.store.is_connected.return_value = False
        feed._update_bar(livemode=True)
        feed.store.fetch_ohlcv.assert_not_called()

    def test_error_tracking(self):
        """Consecutive errors are tracked."""
        from ccxt.base.errors import NetworkError
        feed = self._make_feed()
        feed.store.fetch_ohlcv.side_effect = NetworkError("timeout")

        feed._update_bar(livemode=True)
        self.assertEqual(feed._consecutive_fetch_errors, 1)

        feed._update_bar(livemode=True)
        self.assertEqual(feed._consecutive_fetch_errors, 2)

    def test_error_counter_resets_on_success(self):
        """Error counter resets after successful fetch."""
        feed = self._make_feed()
        feed._consecutive_fetch_errors = 5
        feed.store.fetch_ohlcv.return_value = [[2000, 1.0, 2.0, 0.5, 1.5, 100]]

        feed._update_bar(livemode=True)
        self.assertEqual(feed._consecutive_fetch_errors, 0)


if __name__ == '__main__':
    unittest.main()
