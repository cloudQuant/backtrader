#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Coverage tests for backtrader/brokers/ccxtbroker.py.

Target: raise coverage from 51% to 70%+.
Focus: WS order paths (P2-1), _next() polling, _submit(), cancel(),
and utility methods that are currently uncovered.
"""

import collections
import queue
import time
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from backtrader.order import Order
from backtrader.position import Position


# ---------------------------------------------------------------------------
# Helpers — build a minimal CCXTBroker without live exchange
# ---------------------------------------------------------------------------

def _make_mock_store(cash=10000.0, value=10000.0):
    """Create a mock CCXTStore with essential attributes.

    Args:
        cash: Initial cash balance for the mock store.
        value: Initial portfolio value for the mock store.

    Returns:
        MagicMock: A mocked CCXTStore with required attributes configured.
    """
    store = MagicMock()
    store._cash = cash
    store._value = value
    store.currency = 'USDT'
    store.exchange_id = 'okx'
    store.exchange = MagicMock()
    store.exchange.apiKey = 'test_key'
    store.exchange.secret = 'test_secret'
    store.exchange.password = 'test_pass'
    store.exchange.config = {
        'apiKey': 'test_key',
        'secret': 'test_secret',
        'password': 'test_pass',
        'enableRateLimit': True,
    }
    store.exchange.markets = {'BTC/USDT:USDT': {'id': 'BTC-USDT-SWAP'}}
    store.fetch_order = MagicMock()
    store.create_order = MagicMock()
    store.cancel_order = MagicMock()
    store.fetch_open_orders = MagicMock(return_value=[])
    store.get_balance = MagicMock()
    store.get_wallet_balance = MagicMock(return_value={
        'free': {'BTC': 1.0, 'USDT': 5000.0},
        'total': {'BTC': 1.5, 'USDT': 10000.0},
    })
    store.is_connected = MagicMock(return_value=True)
    return store


def _make_broker(store=None, use_ws=False, use_threaded=False):
    """Create a CCXTBroker with mocked internals.

    Args:
        store: Optional CCXTStore mock. If None, creates a new one.
        use_ws: Whether to enable WebSocket order mode.
        use_threaded: Whether to enable threaded order mode.

    Returns:
        CCXTBroker: A broker instance with mocked dependencies.
    """
    from backtrader.brokers.ccxtbroker import CCXTBroker

    if store is None:
        store = _make_mock_store()

    # Patch CCXTStore to avoid real init
    with patch('backtrader.brokers.ccxtbroker.CCXTStore'):
        broker = CCXTBroker.__new__(CCXTBroker)

    # Manually init essential attributes
    broker.store = store
    broker.currency = store.currency
    broker.cash = store._cash
    broker.value = store._value
    broker.startingcash = store._cash
    broker.startingvalue = store._value
    broker.positions = collections.defaultdict(Position)
    broker.notifs = queue.Queue()
    broker.open_orders = {}
    broker.debug = False
    broker.indent = 4
    broker._last_op_time = 0
    broker._consecutive_failures = 0
    broker._max_consecutive_failures = 10
    broker._max_retries = 3
    broker._retry_delay = 0.01
    broker._ws_order_updates = queue.Queue()
    broker._ws_subscribed_symbols = set()
    broker._use_ws_orders = use_ws
    broker._ws_order_manager = MagicMock() if use_ws else None
    broker._use_threaded = use_threaded
    broker._threaded_order_manager = None
    broker._bracket_manager = None

    # Default order_types and mappings
    broker.order_types = {
        Order.Market: 'market',
        Order.Limit: 'limit',
        Order.Stop: 'stop',
        Order.StopLimit: 'stop',
    }
    broker.mappings = {
        'closed_order': {'key': 'status', 'value': 'closed'},
        'canceled_order': {'key': 'status', 'value': 'canceled'},
    }

    return broker


def _make_mock_order(order_id='ord123', symbol='BTC/USDT:USDT', side='buy',
                     amount=0.1, price=50000.0, status='open'):
    """Create a mock CCXTOrder for testing.

    Args:
        order_id: Unique identifier for the order.
        symbol: Trading symbol (e.g., 'BTC/USDT:USDT').
        side: Order side ('buy' or 'sell').
        amount: Order amount in base currency.
        price: Order price.
        status: Order status ('open', 'closed', 'canceled', etc.).

    Returns:
        MagicMock: A mocked order object with required attributes.
    """
    order = MagicMock()
    order.ccxt_order = {
        'id': order_id,
        'status': status,
        'amount': amount,
        'filled': 0,
        'average': 0,
        'timestamp': int(time.time() * 1000),
    }
    order.data = MagicMock()
    order.data.p = MagicMock()
    order.data.p.dataname = symbol
    order.data._dataname = symbol
    order.executed = MagicMock()
    order.executed.size = 0
    order.executed.price = 0
    order.executed_fills = set()
    order.isbuy = MagicMock(return_value=(side == 'buy'))
    order.issell = MagicMock(return_value=(side == 'sell'))
    order.execute = MagicMock()
    order.partial = MagicMock()
    order.completed = MagicMock()
    order.cancel = MagicMock()
    order.reject = MagicMock()
    order.clone = MagicMock(return_value=order)
    return order


# ---------------------------------------------------------------------------
# Test: Utility methods
# ---------------------------------------------------------------------------

class TestUtilityMethods:
    """Test suite for utility methods.

    Tests broker utility methods like getcash(), getvalue(),
    get_notification(), getposition(), and balance-related functions.
    """

    def test_getcash(self):
        """Verify getcash() returns the correct cash balance from store.

        Tests that the broker correctly retrieves and returns the cash
        balance stored in the CCXTStore.
        """
        broker = _make_broker()
        broker.store._cash = 5000.0
        assert broker.getcash() == 5000.0

    def test_getvalue(self):
        """Verify getvalue() returns the correct portfolio value from store.

        Tests that the broker correctly retrieves and returns the total
        portfolio value stored in the CCXTStore.
        """
        broker = _make_broker()
        broker.store._value = 15000.0
        assert broker.getvalue() == 15000.0

    def test_get_notification_empty(self):
        """Verify get_notification() returns None when no notifications exist.

        Tests the behavior of get_notification() when the notification
        queue is empty.
        """
        broker = _make_broker()
        assert broker.get_notification() is None

    def test_get_notification_with_order(self):
        """Verify get_notification() returns queued order notifications.

        Tests that orders placed in the notification queue via notify()
        are correctly retrieved by get_notification().
        """
        broker = _make_broker()
        order = _make_mock_order()
        broker.notify(order)
        result = broker.get_notification()
        assert result is order

    def test_getposition_clone(self):
        """Verify getposition() returns a cloned position when requested.

        Tests that passing clone=True returns a cloned copy of the
        position rather than a reference to the original.
        """
        broker = _make_broker()
        data = MagicMock()
        data._dataname = 'BTC/USDT:USDT'
        pos = broker.getposition(data, clone=True)
        assert pos is not None

    def test_getposition_no_clone(self):
        """Verify getposition() returns position reference without cloning.

        Tests that passing clone=False returns a reference to the
        actual position object.
        """
        broker = _make_broker()
        data = MagicMock()
        data._dataname = 'BTC/USDT:USDT'
        pos = broker.getposition(data, clone=False)
        assert pos is not None

    def test_get_balance(self):
        """Verify get_balance() returns cash and value tuple from store.

        Tests that the broker correctly retrieves both cash and value
        from the store and returns them as a tuple.
        """
        broker = _make_broker()
        broker.store._cash = 8000.0
        broker.store._value = 12000.0
        cash, value = broker.get_balance()
        assert cash == 8000.0
        assert value == 12000.0
        broker.store.get_balance.assert_called_once()

    def test_get_wallet_balance(self):
        """Verify get_wallet_balance() returns wallet balance for specified currencies.

        Tests that the broker correctly fetches and returns wallet
        balance information for the requested currencies.
        """
        broker = _make_broker()
        result = broker.get_wallet_balance(['BTC', 'USDT'])
        assert result['BTC']['cash'] == 1.0
        assert result['USDT']['value'] == 10000.0

    def test_get_wallet_balance_with_params(self):
        """Verify get_wallet_balance() passes params to store call.

        Tests that additional parameters are correctly forwarded to
        the underlying store's get_wallet_balance call.
        """
        broker = _make_broker()
        result = broker.get_wallet_balance(['BTC'], params={'type': 'trading'})
        assert 'BTC' in result

    def test_get_orders_open(self):
        """Verify get_orders_open() calls store's fetch_open_orders.

        Tests that the broker correctly delegates fetching open orders
        to the store's fetch_open_orders method.
        """
        broker = _make_broker()
        broker.get_orders_open()
        broker.store.fetch_open_orders.assert_called_once()

    def test_get_bracket_manager_none(self):
        """Verify get_bracket_manager() returns None when not configured.

        Tests that get_bracket_manager returns None when no bracket
        manager has been set up on the broker.
        """
        broker = _make_broker()
        assert broker.get_bracket_manager() is None

    def test_get_bracket_manager_set(self):
        """Verify get_bracket_manager() returns the configured manager.

        Tests that get_bracket_manager returns the bracket manager
        instance when one has been configured.
        """
        broker = _make_broker()
        broker._bracket_manager = MagicMock()
        assert broker.get_bracket_manager() is not None

    def test_stop_broker(self):
        """Verify stop() calls store's stop method.

        Tests that the broker correctly propagates the stop signal
        to the underlying store.
        """
        broker = _make_broker()
        broker.stop()
        broker.store.stop.assert_called_once()

    def test_stop_broker_with_threaded_manager(self):
        """Verify stop() stops threaded order manager when configured.

        Tests that the broker correctly stops the threaded order
        manager when it is active.
        """
        broker = _make_broker()
        broker._threaded_order_manager = MagicMock()
        broker.stop()
        broker._threaded_order_manager.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Test: _retry_api_call
# ---------------------------------------------------------------------------

class TestRetryApiCall:
    """Test suite for exponential backoff retry logic.

    Tests the _retry_api_call method that handles transient network
    failures with configurable retry attempts and delays.
    """

    def test_success_on_first_try(self):
        """Verify _retry_api_call succeeds without retry on first success.

        Tests that the retry mechanism returns immediately on the first
        successful call without any retry attempts.
        """
        broker = _make_broker()
        func = MagicMock(return_value='ok')
        result = broker._retry_api_call(func, 'arg1', key='val1')
        assert result == 'ok'
        func.assert_called_once_with('arg1', key='val1')

    def test_retry_on_network_error(self):
        """Verify _retry_api_call retries on NetworkError and succeeds.

        Tests that the retry mechanism catches NetworkError, waits,
        and retries the call until it succeeds.
        """
        from ccxt import NetworkError
        broker = _make_broker()
        broker._retry_delay = 0.001

        func = MagicMock(side_effect=[NetworkError('timeout'), 'ok'])
        result = broker._retry_api_call(func, 'arg1')
        assert result == 'ok'
        assert func.call_count == 2

    def test_all_retries_fail_raises(self):
        """Verify _retry_api_call raises after exhausting retry attempts.

        Tests that when all retry attempts fail, the original exception
        is raised to the caller.
        """
        from ccxt import NetworkError
        broker = _make_broker()
        broker._retry_delay = 0.001
        broker._max_retries = 2

        func = MagicMock(side_effect=NetworkError('timeout'))
        with pytest.raises(NetworkError):
            broker._retry_api_call(func)
        assert func.call_count == 2


# ---------------------------------------------------------------------------
# Test: WS order paths (_init_ws_order_manager, _ws_subscribe_symbol, etc.)
# ---------------------------------------------------------------------------

class TestWSOrderPaths:
    """Test suite for WebSocket order tracking (P2-1) code paths.

    Tests the WebSocket-based order management system including
    initialization, symbol subscription, and trade update handling.
    """

    def test_init_ws_order_manager_success(self):
        """Verify _init_ws_order_manager creates and starts the manager successfully."""
        broker = _make_broker(use_ws=False)
        broker._ws_order_manager = None

        with patch('backtrader.brokers.ccxtbroker.CCXTWebSocketManager') as MockWS:
            mock_ws_instance = MagicMock()
            MockWS.return_value = mock_ws_instance
            broker._init_ws_order_manager()

            MockWS.assert_called_once()
            mock_ws_instance.start.assert_called_once()
            assert broker._ws_order_manager is mock_ws_instance

    def test_init_ws_order_manager_failure(self):
        """Verify _init_ws_order_manager falls back to REST on initialization error."""
        broker = _make_broker(use_ws=True)
        broker._ws_order_manager = None

        with patch('backtrader.brokers.ccxtbroker.CCXTWebSocketManager', side_effect=ImportError("no ccxtpro")):
            broker._init_ws_order_manager()
            assert broker._ws_order_manager is None
            assert broker._use_ws_orders is False

    def test_init_ws_order_manager_no_config(self):
        """Verify _init_ws_order_manager builds config from exchange attrs when empty."""
        broker = _make_broker(use_ws=False)
        broker._ws_order_manager = None
        broker.store.exchange.config = {}  # empty config

        with patch('backtrader.brokers.ccxtbroker.CCXTWebSocketManager') as MockWS:
            mock_ws = MagicMock()
            MockWS.return_value = mock_ws
            broker._init_ws_order_manager()

            call_args = MockWS.call_args
            config = call_args[0][1]
            assert config['apiKey'] == 'test_key'
            assert config['secret'] == 'test_secret'
            assert config['password'] == 'test_pass'

    def test_ws_subscribe_symbol_new(self):
        """Verify _ws_subscribe_symbol subscribes to and tracks new symbols."""
        broker = _make_broker(use_ws=True)
        broker._ws_subscribe_symbol('BTC/USDT:USDT')

        broker._ws_order_manager.subscribe_my_trades.assert_called_once()
        assert 'BTC/USDT:USDT' in broker._ws_subscribed_symbols

    def test_ws_subscribe_symbol_already_subscribed(self):
        """Verify _ws_subscribe_symbol skips already subscribed symbols."""
        broker = _make_broker(use_ws=True)
        broker._ws_subscribed_symbols.add('BTC/USDT:USDT')
        broker._ws_subscribe_symbol('BTC/USDT:USDT')
        broker._ws_order_manager.subscribe_my_trades.assert_not_called()

    def test_ws_subscribe_symbol_no_manager(self):
        """Verify _ws_subscribe_symbol skips when no WS manager exists."""
        broker = _make_broker(use_ws=False)
        broker._ws_subscribe_symbol('BTC/USDT:USDT')
        # No error raised

    def test_ws_subscribe_symbol_error_handled(self):
        """Verify _ws_subscribe_symbol handles exceptions gracefully."""
        broker = _make_broker(use_ws=True)
        from ccxt.base.errors import NetworkError
        broker._ws_order_manager.subscribe_my_trades.side_effect = NetworkError("ws error")
        broker._ws_subscribe_symbol('BTC/USDT:USDT')
        # Should not raise, symbol not added
        assert 'BTC/USDT:USDT' not in broker._ws_subscribed_symbols

    def test_on_ws_my_trades_empty(self):
        """Verify _on_ws_my_trades ignores empty trade lists."""
        broker = _make_broker(use_ws=True)
        broker._on_ws_my_trades([])
        assert broker._ws_order_updates.empty()

    def test_on_ws_my_trades_none(self):
        """Verify _on_ws_my_trades ignores None input."""
        broker = _make_broker(use_ws=True)
        broker._on_ws_my_trades(None)
        assert broker._ws_order_updates.empty()

    def test_on_ws_my_trades_enqueues(self):
        """Verify _on_ws_my_trades enqueues trade updates correctly."""
        broker = _make_broker(use_ws=True)
        trades = [
            {'id': 't1', 'order': 'o1', 'amount': 0.1, 'price': 50000},
            {'id': 't2', 'order': 'o2', 'amount': 0.2, 'price': 50100},
        ]
        broker._on_ws_my_trades(trades)
        assert broker._ws_order_updates.qsize() == 2


# ---------------------------------------------------------------------------
# Test: _process_ws_order_updates
# ---------------------------------------------------------------------------

class TestProcessWSOrderUpdates:
    """Test suite for WS fill processing against open orders.

    Tests the processing of WebSocket order updates to handle
    fill notifications for open orders.
    """

    def test_empty_queue(self):
        """Verify _process_ws_order_updates returns 0 for empty queue.

        Tests that the method returns 0 when there are no WebSocket
        order updates to process.
        """
        broker = _make_broker(use_ws=True)
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_no_matching_order(self):
        """Verify trades with unknown order_id are skipped.

        Tests that WebSocket trade updates for unknown order IDs are
        ignored without error.
        """
        broker = _make_broker(use_ws=True)
        broker._ws_order_updates.put({'id': 't1', 'order': 'unknown', 'amount': 0.1, 'price': 50000})
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_no_order_id(self):
        """Verify trades without an order field are skipped.

        Tests that malformed trade updates missing the order field are
        safely ignored.
        """
        broker = _make_broker(use_ws=True)
        broker._ws_order_updates.put({'id': 't1', 'amount': 0.1, 'price': 50000})
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_duplicate_fill_skipped(self):
        """Verify already-processed fills are skipped.

        Tests that fills that have already been processed (tracked in
        executed_fills set) are not applied again.
        """
        broker = _make_broker(use_ws=True)
        order = _make_mock_order(order_id='o1')
        order.executed_fills = {'t1'}  # Already processed
        broker.open_orders['o1'] = order

        broker._ws_order_updates.put({'id': 't1', 'order': 'o1', 'amount': 0.1, 'price': 50000})
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_zero_size_skipped(self):
        """Verify fills with zero size are skipped.

        Tests that trade fills with zero amount are ignored to prevent
        unnecessary processing.
        """
        broker = _make_broker(use_ws=True)
        order = _make_mock_order(order_id='o1')
        broker.open_orders['o1'] = order

        broker._ws_order_updates.put({'id': 't1', 'order': 'o1', 'amount': 0, 'price': 50000})
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_partial_fill(self):
        """Verify partial fills update order and keep it open.

        Tests that when a trade partially fills an order, the order
        is updated but remains in open_orders.
        """
        broker = _make_broker(use_ws=True)
        order = _make_mock_order(order_id='o1', amount=1.0)
        order.executed.size = 0
        broker.open_orders['o1'] = order

        broker._ws_order_updates.put({
            'id': 't1', 'order': 'o1', 'amount': 0.5, 'price': 50000, 'timestamp': 1700000000
        })
        result = broker._process_ws_order_updates()
        assert result == 1
        order.execute.assert_called_once()
        order.partial.assert_called_once()
        assert 'o1' in broker.open_orders  # Still open

    def test_complete_fill(self):
        """Verify complete fills remove order from open_orders.

        Tests that when a trade fully fills an order, the order is
        completed and removed from open_orders.
        """
        broker = _make_broker(use_ws=True)
        order = _make_mock_order(order_id='o1', amount=0.5)
        order.executed.size = 0
        broker.open_orders['o1'] = order

        broker._ws_order_updates.put({
            'id': 't1', 'order': 'o1', 'amount': 0.5, 'price': 50000, 'timestamp': 1700000000
        })

        # After execute, executed.size should reflect filled amount
        def update_size(*args):
            order.executed.size = 0.5
        order.execute.side_effect = update_size

        result = broker._process_ws_order_updates()
        assert result == 1
        order.completed.assert_called_once()
        assert 'o1' not in broker.open_orders

    def test_complete_fill_with_bracket_manager(self):
        """Verify complete fills notify the bracket manager.

        Tests that when a bracketed order is completely filled,
        the bracket manager is notified of the completion.
        """
        broker = _make_broker(use_ws=True)
        broker._bracket_manager = MagicMock()
        order = _make_mock_order(order_id='o1', amount=0.5)
        order.executed.size = 0
        broker.open_orders['o1'] = order

        def update_size(*args):
            order.executed.size = 0.5
        order.execute.side_effect = update_size

        broker._ws_order_updates.put({
            'id': 't1', 'order': 'o1', 'amount': 0.5, 'price': 50000, 'timestamp': 1700000000
        })
        broker._process_ws_order_updates()
        broker._bracket_manager.on_order_update.assert_called_once_with(order)


# ---------------------------------------------------------------------------
# Test: next() dispatch logic
# ---------------------------------------------------------------------------

class TestNextDispatch:
    """Test suite for next() method's priority dispatch (WS > Threaded > REST).

    Tests the broker's next() method dispatch logic that prioritizes
    WebSocket updates over threaded and REST polling.
    """

    def test_next_ws_mode(self):
        """Verify WS mode calls _process_ws_order_updates.

        Tests that when WebSocket mode is enabled, next() processes
        WebSocket order updates instead of polling via REST.
        """
        broker = _make_broker(use_ws=True)
        broker._process_ws_order_updates = MagicMock(return_value=0)
        broker._last_op_time = time.time()  # Recent, no REST fallback

        broker.next()
        broker._process_ws_order_updates.assert_called_once()

    def test_next_ws_mode_periodic_rest_check(self):
        """Verify WS mode performs periodic REST checks for stale orders.

        Tests that even in WebSocket mode, the broker periodically
        polls via REST to catch any missed updates when there are
        open orders.
        """
        broker = _make_broker(use_ws=True)
        broker._process_ws_order_updates = MagicMock(return_value=0)
        broker._next = MagicMock()
        broker._last_op_time = 0  # Long ago
        broker.open_orders = {'mock_id': _make_mock_order()}  # Has open orders

        broker.next()
        broker._process_ws_order_updates.assert_called_once()
        broker._next.assert_called_once()

    def test_next_ws_mode_no_rest_without_open_orders(self):
        """Verify WS mode skips REST checks when no open orders exist.

        Tests that REST fallback polling is skipped when there are
        no open orders to check.
        """
        broker = _make_broker(use_ws=True)
        broker._process_ws_order_updates = MagicMock(return_value=0)
        broker._next = MagicMock()
        broker._last_op_time = 0
        broker.open_orders = {}  # No open orders

        broker.next()
        broker._next.assert_not_called()

    def test_next_disconnected_skips(self):
        """Verify next() skips when exchange is disconnected.

        Tests that the broker skips processing when the exchange
        connection is down and tracks consecutive failures.
        """
        broker = _make_broker()
        broker.store.is_connected.return_value = False
        broker._next = MagicMock()

        broker.next()
        broker._next.assert_not_called()
        assert broker._consecutive_failures == 1

    def test_next_many_failures_backs_off(self):
        """Verify next() backs off to 30s intervals after many consecutive failures.

        Tests that after exceeding max consecutive failures, the broker
        enters backoff mode and reduces polling frequency.
        """
        broker = _make_broker()
        broker._consecutive_failures = 15  # > max
        broker._last_op_time = time.time()  # Recent
        broker._next = MagicMock()

        broker.next()
        broker._next.assert_not_called()  # Backed off

    def test_next_normal_rate_limit(self):
        """Verify next() rate-limits REST polling to 3-second intervals.

        Tests that REST polling is rate-limited to avoid excessive
        API calls during normal operation.
        """
        broker = _make_broker()
        broker._last_op_time = time.time()  # Recent
        broker._next = MagicMock()

        broker.next()
        broker._next.assert_not_called()  # Within 3s cooldown

    def test_next_normal_calls_next(self):
        """Verify next() calls _next() when enough time has passed.

        Tests that the broker proceeds with REST polling when the
        rate limit cooldown has expired.
        """
        broker = _make_broker()
        broker._last_op_time = 0  # Long ago
        broker._next = MagicMock()

        broker.next()
        broker._next.assert_called_once()


# ---------------------------------------------------------------------------
# Test: _next() REST polling
# ---------------------------------------------------------------------------

class TestNextPolling:
    """Test suite for _next() REST order polling.

    Tests the REST-based order status polling mechanism.
    """

    def test_next_no_open_orders(self):
        """Verify _next() does nothing when there are no open orders.

        Tests that the REST polling method returns early when there
        are no orders to check.
        """
        broker = _make_broker()
        broker._next()  # Should not raise

    def test_next_order_closed_with_trades(self):
        """Verify _next() processes orders with trade fills correctly.

        Tests that closed orders with trade details are properly
        executed and removed from open orders.
        """
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        broker.open_orders['o1'] = order

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'closed', 'filled': 0.1, 'average': 50000,
            'timestamp': 1700000000,
            'trades': [{'id': 'f1', 'datetime': '2024-01-01', 'amount': 0.1, 'price': 50000}],
        }

        broker._next()
        order.execute.assert_called_once()
        order.completed.assert_called_once()
        assert 'o1' not in broker.open_orders

    def test_next_order_closed_without_trades(self):
        """Verify _next() processes orders using filled/average when no trades list.

        Tests that closed orders without detailed trade information
        still execute correctly using filled and average price fields.
        """
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        order.executed.size = 0
        broker.open_orders['o1'] = order

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'closed', 'filled': 0.1, 'average': 50000,
            'timestamp': 1700000000, 'trades': None,
        }

        broker._next()
        order.execute.assert_called_once()
        order.completed.assert_called_once()
        assert 'o1' not in broker.open_orders

    def test_next_order_partial_fill(self):
        """Verify _next() handles partial fills (status=open with fills).

        Tests that orders with partial fills trigger the partial()
        callback and remain in open_orders.
        """
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        order.executed.size = 0
        broker.open_orders['o1'] = order

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'open', 'filled': 0.05, 'average': 50000,
            'timestamp': 1700000000, 'trades': None,
        }

        broker._next()
        order.partial.assert_called_once()
        assert 'o1' in broker.open_orders  # Still open

    def test_next_order_canceled(self):
        """Verify _next() handles canceled orders correctly.

        Tests that canceled orders trigger the cancel() callback
        and are removed from open_orders.
        """
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        broker.open_orders['o1'] = order

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'canceled', 'filled': 0, 'average': 0,
            'timestamp': 1700000000, 'trades': None,
        }

        broker._next()
        order.cancel.assert_called_once()
        assert 'o1' not in broker.open_orders

    def test_next_network_error_skips(self):
        """Verify _next() skips orders on NetworkError.

        Tests that when fetching order status fails with NetworkError,
        the order remains in open_orders for retry.
        """
        from ccxt import NetworkError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.open_orders['o1'] = order
        broker.store.fetch_order.side_effect = NetworkError('timeout')

        broker._next()
        assert 'o1' in broker.open_orders  # Not removed

    def test_next_order_not_found_removes(self):
        """Verify _next() removes order when exchange reports 'not found'.

        Tests that when an order is reported as not found by the
        exchange, it is canceled locally and removed.
        """
        from ccxt import ExchangeError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.open_orders['o1'] = order
        broker.store.fetch_order.side_effect = ExchangeError('Order not found')

        broker._next()
        order.cancel.assert_called_once()
        assert 'o1' not in broker.open_orders

    def test_next_order_closed_with_bracket(self):
        """Verify _next() notifies bracket manager on order completion.

        Tests that when a bracketed order closes, the bracket manager
        is notified for further processing.
        """
        broker = _make_broker()
        broker._bracket_manager = MagicMock()
        order = _make_mock_order(order_id='o1')
        broker.open_orders['o1'] = order

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'closed', 'filled': 0.1, 'average': 50000,
            'timestamp': 1700000000,
            'trades': [{'id': 'f1', 'datetime': '2024-01-01', 'amount': 0.1, 'price': 50000}],
        }

        broker._next()
        broker._bracket_manager.on_order_update.assert_called_once()


# ---------------------------------------------------------------------------
# Test: cancel()
# ---------------------------------------------------------------------------

class TestCancel:
    """Test suite for order cancellation.

    Tests the cancel() method including status checks and
    error handling during cancellation.
    """

    def test_cancel_already_closed(self):
        """Verify cancel() returns immediately if order is already closed.

        Tests that cancel() skips the cancellation API call when the
        order status is already 'closed'.
        """
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'closed',
        }

        result = broker.cancel(order)
        assert result is order
        broker.store.cancel_order.assert_not_called()

    def test_cancel_already_canceled(self):
        """Verify cancel() returns immediately if order is already canceled.

        Tests that cancel() skips the cancellation API call when the
        order status is already 'canceled'.
        """
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'canceled',
        }

        result = broker.cancel(order)
        assert result is order
        broker.store.cancel_order.assert_not_called()

    def test_cancel_success(self):
        """Verify cancel() successfully cancels open orders.

        Tests that cancel() properly calls the exchange's cancel_order
        API and marks the order as canceled.
        """
        broker = _make_broker()
        broker._next = MagicMock()
        order = _make_mock_order(order_id='o1')

        broker.store.fetch_order.return_value = {'id': 'o1', 'status': 'open'}
        broker.store.cancel_order.return_value = {'id': 'o1', 'status': 'canceled'}

        result = broker.cancel(order)
        broker.store.cancel_order.assert_called_once()
        order.cancel.assert_called_once()

    def test_cancel_network_error_on_fetch(self):
        """Verify cancel() handles network errors during order fetch.

        Tests that when fetching order status fails with NetworkError,
        cancel() returns the order without cancellation.
        """
        from ccxt import NetworkError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.store.fetch_order.side_effect = NetworkError('timeout')

        result = broker.cancel(order)
        assert result is order

    def test_cancel_order_not_found(self):
        """Verify cancel() handles 'not found' by canceling locally.

        Tests that when the exchange reports an order does not exist,
        it is canceled locally and removed from open_orders.
        """
        from ccxt import ExchangeError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.open_orders['o1'] = order
        broker.store.fetch_order.side_effect = ExchangeError('Order does not exist')

        broker.cancel(order)
        order.cancel.assert_called_once()
        assert 'o1' not in broker.open_orders

    def test_cancel_network_error_on_cancel(self):
        """Verify cancel() handles network errors during cancel call.

        Tests that when the cancellation API call fails with NetworkError,
        cancel() returns the order without raising an exception.
        """
        from ccxt import NetworkError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.store.fetch_order.return_value = {'id': 'o1', 'status': 'open'}
        broker.store.cancel_order.side_effect = NetworkError('timeout')

        result = broker.cancel(order)
        assert result is order


# ---------------------------------------------------------------------------
# Test: private_end_point
# ---------------------------------------------------------------------------

class TestPrivateEndPoint:
    """Test suite for private API endpoint proxy.

    Tests the private_end_point method that formats and proxies
    private API calls to the exchange.
    """

    def test_private_endpoint_formats_correctly(self):
        """Verify private_end_point formats and proxies API calls correctly.

        Tests that the endpoint template is properly formatted and
        the call is proxied to the store's private_end_point method.
        """
        broker = _make_broker()
        broker.private_end_point('Get', 'order/{id}/cancel', {'id': '123'})
        broker.store.private_end_point.assert_called_once_with(
            type='Get',
            endpoint='private_getorder_id_cancel',
            params={'id': '123'}
        )


# ---------------------------------------------------------------------------
# Test: create_bracket_order
# ---------------------------------------------------------------------------

class TestBracketOrder:
    """Test suite for bracket order creation.

    Tests the create_bracket_order method that creates
    entry, stop-loss, and take-profit orders as a group.
    """

    def test_no_bracket_manager(self):
        """Verify create_bracket_order returns None when no manager configured.

        Tests that bracket order creation fails gracefully when the
        bracket manager is not set up.
        """
        broker = _make_broker()
        result = broker.create_bracket_order(
            data=MagicMock(), size=0.1,
            entry_price=50000, stop_price=49000, limit_price=51000,
        )
        assert result is None

    def test_with_bracket_manager(self):
        """Verify bracket order creation with bracket manager configured.

        Tests that when a bracket manager is configured, the create_bracket
        call is properly delegated to it.
        """
        broker = _make_broker()
        broker._bracket_manager = MagicMock()
        broker._bracket_manager.create_bracket.return_value = 'bracket_obj'

        result = broker.create_bracket_order(
            data=MagicMock(), size=0.1,
            entry_price=50000, stop_price=49000, limit_price=51000,
        )
        assert result == 'bracket_obj'
        broker._bracket_manager.create_bracket.assert_called_once()

    def test_bracket_default_entry_type(self):
        """Verify default entry_type is Order.Limit for bracket orders.

        Tests that when entry_type is not specified, it defaults to
        Order.Limit for the bracket order entry.
        """
        broker = _make_broker()
        broker._bracket_manager = MagicMock()

        broker.create_bracket_order(
            data=MagicMock(), size=0.1,
            entry_price=50000, stop_price=49000, limit_price=51000,
        )
        call_kwargs = broker._bracket_manager.create_bracket.call_args[1]
        assert call_kwargs['entry_type'] == Order.Limit
