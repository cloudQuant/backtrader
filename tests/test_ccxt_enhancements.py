#!/usr/bin/env python
"""Unit tests for CCXT enhancement modules.

Tests for:
- RateLimiter and retry_with_backoff
- ThreadedDataManager and ThreadedOrderManager
- ExchangeConfig
- ConnectionManager
- BracketOrderManager

Note: These tests import modules directly to avoid backtrader dependency chain issues.
"""

import sys
import os
import time
import threading
import unittest
from unittest.mock import Mock, MagicMock, patch

# Add backtrader path for direct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backtrader'))


class TestRateLimiter(unittest.TestCase):
    """Tests for RateLimiter class."""
    
    def setUp(self):
        from ccxt.ratelimit import RateLimiter
        self.RateLimiter = RateLimiter
    
    def test_init(self):
        """Test RateLimiter initialization."""
        limiter = self.RateLimiter(requests_per_minute=100)
        self.assertEqual(limiter.rpm, 100)
        self.assertEqual(len(limiter.request_times), 0)
    
    def test_acquire_no_wait(self):
        """Test acquire when under limit."""
        limiter = self.RateLimiter(requests_per_minute=1000)
        start = time.time()
        limiter.acquire()
        elapsed = time.time() - start
        self.assertLess(elapsed, 0.1)  # Should be near instant
        self.assertEqual(limiter.current_usage, 1)
    
    def test_get_wait_time(self):
        """Test get_wait_time calculation."""
        limiter = self.RateLimiter(requests_per_minute=1000)
        wait = limiter.get_wait_time()
        self.assertEqual(wait, 0.0)
    
    def test_reset(self):
        """Test reset clears request history."""
        limiter = self.RateLimiter(requests_per_minute=1000)
        limiter.acquire()
        limiter.acquire()
        self.assertEqual(limiter.current_usage, 2)
        limiter.reset()
        self.assertEqual(limiter.current_usage, 0)


class TestRetryWithBackoff(unittest.TestCase):
    """Tests for retry_with_backoff decorator."""
    
    def setUp(self):
        from ccxt.ratelimit import retry_with_backoff
        self.retry_with_backoff = retry_with_backoff
    
    def test_success_no_retry(self):
        """Test successful call doesn't retry."""
        call_count = 0
        
        @self.retry_with_backoff(max_retries=3)
        def success_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = success_func()
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 1)
    
    def test_retry_then_success(self):
        """Test retry until success."""
        call_count = 0
        
        @self.retry_with_backoff(max_retries=3, base_delay=0.01)
        def fail_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("fail")
            return "success"
        
        result = fail_then_success()
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)
    
    def test_max_retries_exceeded(self):
        """Test exception raised after max retries."""
        @self.retry_with_backoff(max_retries=2, base_delay=0.01)
        def always_fail():
            raise ValueError("always fails")
        
        with self.assertRaises(ValueError):
            always_fail()


class TestExchangeConfig(unittest.TestCase):
    """Tests for ExchangeConfig class."""
    
    def setUp(self):
        from ccxt.config import ExchangeConfig
        self.ExchangeConfig = ExchangeConfig
    
    def test_get_order_type_binance(self):
        """Test order type mapping for Binance."""
        import backtrader as bt
        order_type = self.ExchangeConfig.get_order_type('binance', bt.Order.Market)
        self.assertEqual(order_type, 'market')
    
    def test_get_order_type_default(self):
        """Test order type fallback for unknown exchange."""
        import backtrader as bt
        order_type = self.ExchangeConfig.get_order_type('unknown_exchange', bt.Order.Market)
        self.assertEqual(order_type, 'market')
    
    def test_get_timeframe_binance(self):
        """Test timeframe mapping for Binance."""
        import backtrader as bt
        tf = self.ExchangeConfig.get_timeframe('binance', (bt.TimeFrame.Minutes, 60))
        self.assertEqual(tf, '1h')
    
    def test_get_params(self):
        """Test get exchange params."""
        params = self.ExchangeConfig.get_params('binance')
        self.assertIn('rateLimit', params)
        self.assertIn('enableRateLimit', params)
    
    def test_get_fees(self):
        """Test get fee structure."""
        fees = self.ExchangeConfig.get_fees('binance')
        self.assertIn('maker', fees)
        self.assertIn('taker', fees)
    
    def test_merge_config(self):
        """Test config merging."""
        user_config = {'apiKey': 'test_key'}
        merged = self.ExchangeConfig.merge_config('binance', user_config)
        self.assertEqual(merged['apiKey'], 'test_key')
        self.assertIn('rateLimit', merged)


class TestThreadedDataManager(unittest.TestCase):
    """Tests for ThreadedDataManager class."""
    
    def setUp(self):
        from ccxt.threading import ThreadedDataManager, DataUpdate
        self.ThreadedDataManager = ThreadedDataManager
        self.DataUpdate = DataUpdate
    
    def test_init(self):
        """Test ThreadedDataManager initialization."""
        mock_store = Mock()
        manager = self.ThreadedDataManager(mock_store, update_interval=1.0)
        self.assertEqual(manager.update_interval, 1.0)
        self.assertFalse(manager.is_running())
    
    def test_add_remove_symbol(self):
        """Test add and remove symbol."""
        mock_store = Mock()
        manager = self.ThreadedDataManager(mock_store)
        
        manager.add_symbol('BTC/USDT', '1h')
        self.assertIn('BTC/USDT', manager._symbols)
        
        manager.remove_symbol('BTC/USDT')
        self.assertNotIn('BTC/USDT', manager._symbols)
    
    def test_start_stop(self):
        """Test start and stop."""
        mock_store = Mock()
        manager = self.ThreadedDataManager(mock_store, update_interval=0.1)
        
        manager.start()
        self.assertTrue(manager.is_running())
        
        manager.stop()
        self.assertFalse(manager.is_running())


class TestThreadedOrderManager(unittest.TestCase):
    """Tests for ThreadedOrderManager class."""
    
    def setUp(self):
        from ccxt.threading import ThreadedOrderManager
        self.ThreadedOrderManager = ThreadedOrderManager
    
    def test_init(self):
        """Test ThreadedOrderManager initialization."""
        mock_store = Mock()
        manager = self.ThreadedOrderManager(mock_store, check_interval=3.0)
        self.assertEqual(manager.check_interval, 3.0)
        self.assertFalse(manager.is_running())
    
    def test_add_remove_order(self):
        """Test add and remove order."""
        mock_store = Mock()
        manager = self.ThreadedOrderManager(mock_store)
        
        manager.add_order('order123', 'BTC/USDT')
        self.assertIn('order123', manager._orders)
        
        manager.remove_order('order123')
        self.assertNotIn('order123', manager._orders)


class TestConnectionManager(unittest.TestCase):
    """Tests for ConnectionManager class."""
    
    def setUp(self):
        from ccxt.connection import ConnectionManager
        self.ConnectionManager = ConnectionManager
    
    def test_init(self):
        """Test ConnectionManager initialization."""
        mock_store = Mock()
        manager = self.ConnectionManager(mock_store, health_check_interval=30.0)
        self.assertEqual(manager.health_check_interval, 30.0)
        self.assertTrue(manager.is_connected())
    
    def test_callbacks(self):
        """Test disconnect/reconnect callbacks."""
        mock_store = Mock()
        manager = self.ConnectionManager(mock_store)
        
        disconnect_called = []
        reconnect_called = []
        
        manager.on_disconnect(lambda: disconnect_called.append(True))
        manager.on_reconnect(lambda: reconnect_called.append(True))
        
        self.assertEqual(len(manager._disconnect_callbacks), 1)
        self.assertEqual(len(manager._reconnect_callbacks), 1)
    
    def test_mark_success(self):
        """Test mark_success updates state."""
        mock_store = Mock()
        manager = self.ConnectionManager(mock_store)
        manager.mark_success()
        self.assertTrue(manager.is_connected())


class TestBracketOrder(unittest.TestCase):
    """Tests for BracketOrder and BracketState."""
    
    def setUp(self):
        from ccxt.orders.bracket import BracketOrder, BracketState
        self.BracketOrder = BracketOrder
        self.BracketState = BracketState
    
    def test_bracket_states(self):
        """Test BracketState enumeration."""
        self.assertEqual(self.BracketState.PENDING.value, "pending")
        self.assertEqual(self.BracketState.ACTIVE.value, "active")
        self.assertEqual(self.BracketState.STOPPED.value, "stopped")
    
    def test_bracket_order_init(self):
        """Test BracketOrder initialization."""
        bracket = self.BracketOrder(
            bracket_id="test_bracket",
            size=0.01,
            stop_price=49000,
            limit_price=52000,
            side="buy"
        )
        self.assertEqual(bracket.bracket_id, "test_bracket")
        self.assertEqual(bracket.state, self.BracketState.PENDING)
        self.assertFalse(bracket.is_active())
        self.assertFalse(bracket.is_closed())
    
    def test_bracket_is_active(self):
        """Test is_active method."""
        bracket = self.BracketOrder(bracket_id="test", state=self.BracketState.ACTIVE)
        self.assertTrue(bracket.is_active())
    
    def test_bracket_is_closed(self):
        """Test is_closed method."""
        bracket = self.BracketOrder(bracket_id="test", state=self.BracketState.STOPPED)
        self.assertTrue(bracket.is_closed())
        
        bracket2 = self.BracketOrder(bracket_id="test2", state=self.BracketState.TARGETED)
        self.assertTrue(bracket2.is_closed())


class TestBracketOrderManager(unittest.TestCase):
    """Tests for BracketOrderManager class."""
    
    def setUp(self):
        from ccxt.orders.bracket import BracketOrderManager
        self.BracketOrderManager = BracketOrderManager
    
    def test_init(self):
        """Test BracketOrderManager initialization."""
        mock_broker = Mock()
        manager = self.BracketOrderManager(mock_broker)
        self.assertEqual(len(manager.brackets), 0)
    
    def test_get_active_brackets(self):
        """Test get_active_brackets returns empty list initially."""
        mock_broker = Mock()
        manager = self.BracketOrderManager(mock_broker)
        active = manager.get_active_brackets()
        self.assertEqual(len(active), 0)


if __name__ == '__main__':
    unittest.main()
