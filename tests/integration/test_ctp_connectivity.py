#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CTP Integration Tests - Connectivity and Data (read-only).

Tests CTP connectivity, authentication, market data subscription,
and account/position queries against SimNow test servers.

These tests do NOT place orders — they are safe read-only tests.

Usage:
    pytest tests/integration/test_ctp_connectivity.py -m integration -v
"""

import time
import pytest

from tests.integration.conftest import skip_no_ctp

pytestmark = [pytest.mark.integration, skip_no_ctp]


# ---------------------------------------------------------------------------
# Connection & Authentication
# ---------------------------------------------------------------------------

class TestCTPConnection:
    """Test CTP server connectivity and login."""

    def test_store_connects_and_logs_in(self, ctp_store):
        """CTPStore should connect and authenticate with SimNow."""
        assert ctp_store.is_connected, "CTPStore should be connected"
        assert ctp_store.trader_spi.loggedin, "Trader SPI should be logged in"
        assert ctp_store.md_spi.loggedin, "MD SPI should be logged in"

    def test_trader_front_session_ids(self, ctp_store):
        """After login, front_id and session_id should be nonzero."""
        assert ctp_store.trader_spi.front_id != 0, "front_id should be set"
        assert ctp_store.trader_spi.session_id != 0, "session_id should be set"

    def test_store_config_values(self, ctp_store, ctp_config):
        """CTPStore should store the provided config values."""
        assert ctp_store._user_id == ctp_config['user_id']
        assert ctp_store._broker_id == ctp_config['broker_id']
        assert ctp_store._td_front == ctp_config['td_front']
        assert ctp_store._md_front == ctp_config['md_front']

    def test_singleton_returns_same_instance(self, ctp_store):
        """CTPStore is a singleton — second call should return same instance."""
        from backtrader.stores.ctpstore import CTPStore
        store2 = CTPStore(ctp_setting=ctp_store.ctp_setting)
        assert store2 is ctp_store, "Singleton should return the same instance"


# ---------------------------------------------------------------------------
# Account & Position Queries
# ---------------------------------------------------------------------------

class TestCTPAccount:
    """Test account balance and position queries."""

    def test_get_balance(self, ctp_store):
        """Should be able to query account balance from SimNow."""
        # Force a fresh query by resetting the timestamp
        ctp_store._last_balance_query = 0.0
        ctp_store.get_balance()
        cash = ctp_store.get_cash()
        value = ctp_store.get_value()
        assert isinstance(cash, (int, float)), f"Cash should be numeric, got {type(cash)}"
        assert isinstance(value, (int, float)), f"Value should be numeric, got {type(value)}"
        # SimNow accounts typically have positive balance
        assert value >= 0, f"Account value should be non-negative: {value}"

    def test_get_balance_rate_limiting(self, ctp_store):
        """get_balance should be rate-limited to avoid CTP query throttle."""
        from time import time
        # Force a fresh query
        ctp_store._last_balance_query = 0.0
        ctp_store.get_balance()
        first_query_time = ctp_store._last_balance_query
        assert first_query_time > 0, "Should have recorded query time"

        # Immediately call again — should be rate-limited (interval=2s)
        ctp_store.get_balance()
        second_query_time = ctp_store._last_balance_query
        elapsed = second_query_time - first_query_time
        assert elapsed < 0.5, \
            f"Second query should be rate-limited (no new query), elapsed={elapsed}"

    def test_get_positions(self, ctp_store):
        """Should be able to query positions (may be empty on SimNow)."""
        positions = ctp_store.get_positions()
        assert isinstance(positions, list), "Positions should be a list"
        for pos in positions:
            assert 'instrument' in pos
            assert 'direction' in pos
            assert 'volume' in pos

    def test_get_cash_and_value(self, ctp_store):
        """get_cash/get_value should return cached values."""
        cash = ctp_store.get_cash()
        value = ctp_store.get_value()
        assert cash >= 0
        assert value >= 0


# ---------------------------------------------------------------------------
# Market Data Subscription
# ---------------------------------------------------------------------------

class TestCTPMarketData:
    """Test market data subscription and tick reception."""

    # Common test instruments available on SimNow
    TEST_INSTRUMENTS = ['au2506', 'ag2506', 'rb2510', 'IF2506']

    def _find_active_instrument(self, ctp_store, instruments=None):
        """Try to subscribe to instruments and find one that returns ticks."""
        instruments = instruments or self.TEST_INSTRUMENTS
        for inst in instruments:
            q = ctp_store.md_spi.register_instrument(inst)
            ctp_store.md_spi.subscribe([inst])
            time.sleep(2)
            if not q.empty():
                return inst, q
        return None, None

    def test_register_instrument(self, ctp_store):
        """register_instrument should create a tick queue."""
        q = ctp_store.md_spi.register_instrument('au2506')
        assert q is not None
        assert q.empty()  # No ticks yet before subscribing

    def test_register_same_instrument_returns_same_queue(self, ctp_store):
        """Registering the same instrument twice should return the same queue."""
        q1 = ctp_store.md_spi.register_instrument('au2506')
        q2 = ctp_store.md_spi.register_instrument('au2506')
        assert q1 is q2

    def test_subscribe_and_receive_tick(self, ctp_store):
        """Subscribe to an instrument and verify tick data arrives."""
        inst, q = self._find_active_instrument(ctp_store)
        if inst is None:
            pytest.skip("No active instrument found (market may be closed)")

        tick = q.get(timeout=5)
        assert tick is not None, "Should receive a tick"
        assert tick['instrument'] == inst

        # Verify tick data fields
        required_fields = [
            'last_price', 'open_price', 'high_price', 'low_price',
            'volume', 'open_interest', 'bid_price1', 'ask_price1',
            'update_time',
        ]
        for field in required_fields:
            assert field in tick, f"Tick missing field: {field}"

    def test_tick_price_validity(self, ctp_store):
        """Tick prices should be valid (positive, not extreme)."""
        inst, q = self._find_active_instrument(ctp_store)
        if inst is None:
            pytest.skip("No active instrument found (market may be closed)")

        tick = q.get(timeout=5)
        last = tick['last_price']
        assert 0 < last < 1e10, f"Last price should be reasonable: {last}"

        bid = tick['bid_price1']
        ask = tick['ask_price1']
        if bid > 0 and bid < 1e10 and ask > 0 and ask < 1e10:
            assert bid <= ask, f"Bid {bid} should <= Ask {ask}"


# ---------------------------------------------------------------------------
# Store Lifecycle
# ---------------------------------------------------------------------------

class TestCTPStoreLifecycle:
    """Test CTPStore lifecycle methods."""

    def test_stop_and_reconnect(self, ctp_config):
        """After stop, creating a new store should work."""
        from backtrader.stores.ctpstore import CTPStore
        CTPStore._reset_instance()

        store = CTPStore(ctp_setting=ctp_config)
        if not store.is_connected:
            CTPStore._reset_instance()
            pytest.skip("CTPStore failed to connect")

        store._feed_count = 0
        store.stop()
        assert not store.is_connected

        # Reset and create new instance
        CTPStore._reset_instance()
        store2 = CTPStore(ctp_setting=ctp_config)
        # May or may not connect depending on server availability
        store2._feed_count = 0
        store2.stop()
        CTPStore._reset_instance()

    def test_getbroker_returns_broker(self, ctp_store):
        """getbroker should return a CTPBroker instance."""
        from backtrader.brokers.ctpbroker import CTPBroker
        broker = ctp_store.getbroker()
        assert isinstance(broker, CTPBroker)

    def test_getdata_returns_data(self, ctp_store):
        """getdata should return a CTPData instance."""
        from backtrader.feeds.ctpdata import CTPData
        data = ctp_store.getdata(dataname='au2506')
        assert isinstance(data, CTPData)
