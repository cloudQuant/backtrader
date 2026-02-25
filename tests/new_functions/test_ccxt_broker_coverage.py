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
    """Create a mock CCXTStore with essential attributes."""
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
    """Create a CCXTBroker with mocked internals."""
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
    broker.open_orders = []
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
    """Create a mock CCXTOrder."""
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
    order.executed_fills = []
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
    """Test getcash, getvalue, get_notification, getposition, etc."""

    def test_getcash(self):
        broker = _make_broker()
        broker.store._cash = 5000.0
        assert broker.getcash() == 5000.0

    def test_getvalue(self):
        broker = _make_broker()
        broker.store._value = 15000.0
        assert broker.getvalue() == 15000.0

    def test_get_notification_empty(self):
        broker = _make_broker()
        assert broker.get_notification() is None

    def test_get_notification_with_order(self):
        broker = _make_broker()
        order = _make_mock_order()
        broker.notify(order)
        result = broker.get_notification()
        assert result is order

    def test_getposition_clone(self):
        broker = _make_broker()
        data = MagicMock()
        data._dataname = 'BTC/USDT:USDT'
        pos = broker.getposition(data, clone=True)
        assert pos is not None

    def test_getposition_no_clone(self):
        broker = _make_broker()
        data = MagicMock()
        data._dataname = 'BTC/USDT:USDT'
        pos = broker.getposition(data, clone=False)
        assert pos is not None

    def test_get_balance(self):
        broker = _make_broker()
        broker.store._cash = 8000.0
        broker.store._value = 12000.0
        cash, value = broker.get_balance()
        assert cash == 8000.0
        assert value == 12000.0
        broker.store.get_balance.assert_called_once()

    def test_get_wallet_balance(self):
        broker = _make_broker()
        result = broker.get_wallet_balance(['BTC', 'USDT'])
        assert result['BTC']['cash'] == 1.0
        assert result['USDT']['value'] == 10000.0

    def test_get_wallet_balance_with_params(self):
        broker = _make_broker()
        result = broker.get_wallet_balance(['BTC'], params={'type': 'trading'})
        assert 'BTC' in result

    def test_get_orders_open(self):
        broker = _make_broker()
        broker.get_orders_open()
        broker.store.fetch_open_orders.assert_called_once()

    def test_get_bracket_manager_none(self):
        broker = _make_broker()
        assert broker.get_bracket_manager() is None

    def test_get_bracket_manager_set(self):
        broker = _make_broker()
        broker._bracket_manager = MagicMock()
        assert broker.get_bracket_manager() is not None

    def test_stop_broker(self):
        broker = _make_broker()
        broker.stop()
        broker.store.stop.assert_called_once()

    def test_stop_broker_with_threaded_manager(self):
        broker = _make_broker()
        broker._threaded_order_manager = MagicMock()
        broker.stop()
        broker._threaded_order_manager.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Test: _retry_api_call
# ---------------------------------------------------------------------------

class TestRetryApiCall:
    """Test exponential backoff retry logic."""

    def test_success_on_first_try(self):
        broker = _make_broker()
        func = MagicMock(return_value='ok')
        result = broker._retry_api_call(func, 'arg1', key='val1')
        assert result == 'ok'
        func.assert_called_once_with('arg1', key='val1')

    def test_retry_on_network_error(self):
        from ccxt import NetworkError
        broker = _make_broker()
        broker._retry_delay = 0.001

        func = MagicMock(side_effect=[NetworkError('timeout'), 'ok'])
        result = broker._retry_api_call(func, 'arg1')
        assert result == 'ok'
        assert func.call_count == 2

    def test_all_retries_fail_raises(self):
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
    """Test WebSocket order tracking (P2-1) code paths."""

    def test_init_ws_order_manager_success(self):
        """_init_ws_order_manager creates manager and starts it."""
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
        """_init_ws_order_manager falls back to REST on error."""
        broker = _make_broker(use_ws=True)
        broker._ws_order_manager = None

        with patch('backtrader.brokers.ccxtbroker.CCXTWebSocketManager', side_effect=ImportError("no ccxtpro")):
            broker._init_ws_order_manager()
            assert broker._ws_order_manager is None
            assert broker._use_ws_orders is False

    def test_init_ws_order_manager_no_config(self):
        """_init_ws_order_manager builds config from exchange attrs when config is empty."""
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
        """_ws_subscribe_symbol subscribes and tracks the symbol."""
        broker = _make_broker(use_ws=True)
        broker._ws_subscribe_symbol('BTC/USDT:USDT')

        broker._ws_order_manager.subscribe_my_trades.assert_called_once()
        assert 'BTC/USDT:USDT' in broker._ws_subscribed_symbols

    def test_ws_subscribe_symbol_already_subscribed(self):
        """_ws_subscribe_symbol skips if already subscribed."""
        broker = _make_broker(use_ws=True)
        broker._ws_subscribed_symbols.add('BTC/USDT:USDT')
        broker._ws_subscribe_symbol('BTC/USDT:USDT')
        broker._ws_order_manager.subscribe_my_trades.assert_not_called()

    def test_ws_subscribe_symbol_no_manager(self):
        """_ws_subscribe_symbol skips if no WS manager."""
        broker = _make_broker(use_ws=False)
        broker._ws_subscribe_symbol('BTC/USDT:USDT')
        # No error raised

    def test_ws_subscribe_symbol_error_handled(self):
        """_ws_subscribe_symbol catches exceptions."""
        broker = _make_broker(use_ws=True)
        from ccxt.base.errors import NetworkError
        broker._ws_order_manager.subscribe_my_trades.side_effect = NetworkError("ws error")
        broker._ws_subscribe_symbol('BTC/USDT:USDT')
        # Should not raise, symbol not added
        assert 'BTC/USDT:USDT' not in broker._ws_subscribed_symbols

    def test_on_ws_my_trades_empty(self):
        """_on_ws_my_trades ignores empty trades."""
        broker = _make_broker(use_ws=True)
        broker._on_ws_my_trades([])
        assert broker._ws_order_updates.empty()

    def test_on_ws_my_trades_none(self):
        """_on_ws_my_trades ignores None."""
        broker = _make_broker(use_ws=True)
        broker._on_ws_my_trades(None)
        assert broker._ws_order_updates.empty()

    def test_on_ws_my_trades_enqueues(self):
        """_on_ws_my_trades enqueues trade updates."""
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
    """Test WS fill processing against open orders."""

    def test_empty_queue(self):
        broker = _make_broker(use_ws=True)
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_no_matching_order(self):
        """Trade with unknown order_id is skipped."""
        broker = _make_broker(use_ws=True)
        broker._ws_order_updates.put({'id': 't1', 'order': 'unknown', 'amount': 0.1, 'price': 50000})
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_no_order_id(self):
        """Trade without order field is skipped."""
        broker = _make_broker(use_ws=True)
        broker._ws_order_updates.put({'id': 't1', 'amount': 0.1, 'price': 50000})
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_duplicate_fill_skipped(self):
        """Already-processed fill is skipped."""
        broker = _make_broker(use_ws=True)
        order = _make_mock_order(order_id='o1')
        order.executed_fills = ['t1']  # Already processed
        broker.open_orders.append(order)

        broker._ws_order_updates.put({'id': 't1', 'order': 'o1', 'amount': 0.1, 'price': 50000})
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_zero_size_skipped(self):
        """Fill with zero size is skipped."""
        broker = _make_broker(use_ws=True)
        order = _make_mock_order(order_id='o1')
        broker.open_orders.append(order)

        broker._ws_order_updates.put({'id': 't1', 'order': 'o1', 'amount': 0, 'price': 50000})
        result = broker._process_ws_order_updates()
        assert result == 0

    def test_partial_fill(self):
        """Partial fill updates order and keeps it open."""
        broker = _make_broker(use_ws=True)
        order = _make_mock_order(order_id='o1', amount=1.0)
        order.executed.size = 0
        broker.open_orders.append(order)

        broker._ws_order_updates.put({
            'id': 't1', 'order': 'o1', 'amount': 0.5, 'price': 50000, 'timestamp': 1700000000
        })
        result = broker._process_ws_order_updates()
        assert result == 1
        order.execute.assert_called_once()
        order.partial.assert_called_once()
        assert order in broker.open_orders  # Still open

    def test_complete_fill(self):
        """Complete fill removes order from open_orders."""
        broker = _make_broker(use_ws=True)
        order = _make_mock_order(order_id='o1', amount=0.5)
        order.executed.size = 0
        broker.open_orders.append(order)

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
        assert order not in broker.open_orders

    def test_complete_fill_with_bracket_manager(self):
        """Complete fill notifies bracket manager."""
        broker = _make_broker(use_ws=True)
        broker._bracket_manager = MagicMock()
        order = _make_mock_order(order_id='o1', amount=0.5)
        order.executed.size = 0
        broker.open_orders.append(order)

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
    """Test next() method's priority dispatch (WS > Threaded > REST)."""

    def test_next_ws_mode(self):
        """WS mode calls _process_ws_order_updates."""
        broker = _make_broker(use_ws=True)
        broker._process_ws_order_updates = MagicMock(return_value=0)
        broker._last_op_time = time.time()  # Recent, no REST fallback

        broker.next()
        broker._process_ws_order_updates.assert_called_once()

    def test_next_ws_mode_periodic_rest_check(self):
        """WS mode does periodic REST check for stale orders."""
        broker = _make_broker(use_ws=True)
        broker._process_ws_order_updates = MagicMock(return_value=0)
        broker._next = MagicMock()
        broker._last_op_time = 0  # Long ago
        broker.open_orders = [_make_mock_order()]  # Has open orders

        broker.next()
        broker._process_ws_order_updates.assert_called_once()
        broker._next.assert_called_once()

    def test_next_ws_mode_no_rest_without_open_orders(self):
        """WS mode skips REST check if no open orders."""
        broker = _make_broker(use_ws=True)
        broker._process_ws_order_updates = MagicMock(return_value=0)
        broker._next = MagicMock()
        broker._last_op_time = 0
        broker.open_orders = []  # No open orders

        broker.next()
        broker._next.assert_not_called()

    def test_next_disconnected_skips(self):
        """next() skips when exchange is disconnected."""
        broker = _make_broker()
        broker.store.is_connected.return_value = False
        broker._next = MagicMock()

        broker.next()
        broker._next.assert_not_called()
        assert broker._consecutive_failures == 1

    def test_next_many_failures_backs_off(self):
        """next() backs off to 30s intervals after many failures."""
        broker = _make_broker()
        broker._consecutive_failures = 15  # > max
        broker._last_op_time = time.time()  # Recent
        broker._next = MagicMock()

        broker.next()
        broker._next.assert_not_called()  # Backed off

    def test_next_normal_rate_limit(self):
        """next() rate-limits REST polling to 3s intervals."""
        broker = _make_broker()
        broker._last_op_time = time.time()  # Recent
        broker._next = MagicMock()

        broker.next()
        broker._next.assert_not_called()  # Within 3s cooldown

    def test_next_normal_calls_next(self):
        """next() calls _next() when enough time has passed."""
        broker = _make_broker()
        broker._last_op_time = 0  # Long ago
        broker._next = MagicMock()

        broker.next()
        broker._next.assert_called_once()


# ---------------------------------------------------------------------------
# Test: _next() REST polling
# ---------------------------------------------------------------------------

class TestNextPolling:
    """Test _next() REST order polling."""

    def test_next_no_open_orders(self):
        """_next() with no open orders does nothing."""
        broker = _make_broker()
        broker._next()  # Should not raise

    def test_next_order_closed_with_trades(self):
        """_next() processes order with trade fills."""
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        broker.open_orders.append(order)

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'closed', 'filled': 0.1, 'average': 50000,
            'timestamp': 1700000000,
            'trades': [{'id': 'f1', 'datetime': '2024-01-01', 'amount': 0.1, 'price': 50000}],
        }

        broker._next()
        order.execute.assert_called_once()
        order.completed.assert_called_once()
        assert order not in broker.open_orders

    def test_next_order_closed_without_trades(self):
        """_next() processes order via filled/average when no trades list."""
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        order.executed.size = 0
        broker.open_orders.append(order)

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'closed', 'filled': 0.1, 'average': 50000,
            'timestamp': 1700000000, 'trades': None,
        }

        broker._next()
        order.execute.assert_called_once()
        order.completed.assert_called_once()
        assert order not in broker.open_orders

    def test_next_order_partial_fill(self):
        """_next() handles partial fill (status=open with fills)."""
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        order.executed.size = 0
        broker.open_orders.append(order)

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'open', 'filled': 0.05, 'average': 50000,
            'timestamp': 1700000000, 'trades': None,
        }

        broker._next()
        order.partial.assert_called_once()
        assert order in broker.open_orders  # Still open

    def test_next_order_canceled(self):
        """_next() handles canceled order."""
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        broker.open_orders.append(order)

        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'canceled', 'filled': 0, 'average': 0,
            'timestamp': 1700000000, 'trades': None,
        }

        broker._next()
        order.cancel.assert_called_once()
        assert order not in broker.open_orders

    def test_next_network_error_skips(self):
        """_next() skips order on NetworkError."""
        from ccxt import NetworkError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.open_orders.append(order)
        broker.store.fetch_order.side_effect = NetworkError('timeout')

        broker._next()
        assert order in broker.open_orders  # Not removed

    def test_next_order_not_found_removes(self):
        """_next() removes order when exchange says 'not found'."""
        from ccxt import ExchangeError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.open_orders.append(order)
        broker.store.fetch_order.side_effect = ExchangeError('Order not found')

        broker._next()
        order.cancel.assert_called_once()
        assert order not in broker.open_orders

    def test_next_order_closed_with_bracket(self):
        """_next() notifies bracket manager on order completion."""
        broker = _make_broker()
        broker._bracket_manager = MagicMock()
        order = _make_mock_order(order_id='o1')
        broker.open_orders.append(order)

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
    """Test order cancellation."""

    def test_cancel_already_closed(self):
        """cancel() returns immediately if order is already closed."""
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'closed',
        }

        result = broker.cancel(order)
        assert result is order
        broker.store.cancel_order.assert_not_called()

    def test_cancel_already_canceled(self):
        """cancel() returns immediately if order is already canceled."""
        broker = _make_broker()
        order = _make_mock_order(order_id='o1')
        broker.store.fetch_order.return_value = {
            'id': 'o1', 'status': 'canceled',
        }

        result = broker.cancel(order)
        assert result is order
        broker.store.cancel_order.assert_not_called()

    def test_cancel_success(self):
        """cancel() cancels an open order."""
        broker = _make_broker()
        broker._next = MagicMock()
        order = _make_mock_order(order_id='o1')

        broker.store.fetch_order.return_value = {'id': 'o1', 'status': 'open'}
        broker.store.cancel_order.return_value = {'id': 'o1', 'status': 'canceled'}

        result = broker.cancel(order)
        broker.store.cancel_order.assert_called_once()
        order.cancel.assert_called_once()

    def test_cancel_network_error_on_fetch(self):
        """cancel() returns order on network error during fetch."""
        from ccxt import NetworkError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.store.fetch_order.side_effect = NetworkError('timeout')

        result = broker.cancel(order)
        assert result is order

    def test_cancel_order_not_found(self):
        """cancel() handles 'not found' on fetch by canceling locally."""
        from ccxt import ExchangeError
        broker = _make_broker()
        broker._max_retries = 1
        broker._retry_delay = 0.001
        order = _make_mock_order(order_id='o1')
        broker.open_orders.append(order)
        broker.store.fetch_order.side_effect = ExchangeError('Order does not exist')

        broker.cancel(order)
        order.cancel.assert_called_once()
        assert order not in broker.open_orders

    def test_cancel_network_error_on_cancel(self):
        """cancel() returns order on network error during cancel call."""
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
    """Test private API endpoint proxy."""

    def test_private_endpoint_formats_correctly(self):
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
    """Test bracket order creation."""

    def test_no_bracket_manager(self):
        broker = _make_broker()
        result = broker.create_bracket_order(
            data=MagicMock(), size=0.1,
            entry_price=50000, stop_price=49000, limit_price=51000,
        )
        assert result is None

    def test_with_bracket_manager(self):
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
        """Default entry_type is Order.Limit."""
        broker = _make_broker()
        broker._bracket_manager = MagicMock()

        broker.create_bracket_order(
            data=MagicMock(), size=0.1,
            entry_price=50000, stop_price=49000, limit_price=51000,
        )
        call_kwargs = broker._bracket_manager.create_bracket.call_args[1]
        assert call_kwargs['entry_type'] == Order.Limit
