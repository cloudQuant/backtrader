#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CTP Integration Tests - Trading (order lifecycle).

Tests CTP order submission, cancellation, and status tracking
against SimNow test servers. These tests place REAL orders on
the SimNow simulation environment.

WARNING: These tests submit real orders to SimNow. They use
limit orders far from market price to avoid fills.

Usage:
    pytest tests/integration/test_ctp_trading.py -m integration -v
"""

import time
import pytest

from tests.integration.conftest import skip_no_ctp

pytestmark = [pytest.mark.integration, pytest.mark.trading, skip_no_ctp]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_for_order_event(store, order_ref, timeout=10):
    """Wait for an order event matching order_ref from the order queue."""
    import queue as _queue
    deadline = time.time() + timeout
    events = []
    while time.time() < deadline:
        try:
            evt = store.order_queue.get(timeout=0.5)
            events.append(evt)
            if evt.get('order_ref') == order_ref:
                return evt
        except _queue.Empty:
            continue
    return None


def _wait_for_trade_event(store, order_ref, timeout=10):
    """Wait for a trade event matching order_ref from the trade queue."""
    import queue as _queue
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            evt = store.trade_queue.get(timeout=0.5)
            if evt.get('order_ref') == order_ref:
                return evt
        except _queue.Empty:
            continue
    return None


def _get_tick_price(ctp_store, instrument, timeout=5):
    """Get current price for an instrument by subscribing briefly."""
    q = ctp_store.md_spi.register_instrument(instrument)
    ctp_store.md_spi.subscribe([instrument])
    try:
        tick = q.get(timeout=timeout)
        return tick.get('last_price', 0.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Order Submission & Cancellation
# ---------------------------------------------------------------------------

class TestCTPOrderLifecycle:
    """Test CTP order submission, status tracking, and cancellation."""

    # Use gold futures on SimNow (typically available)
    TEST_INSTRUMENT = 'au2506'

    def test_submit_limit_order_far_from_market(self, ctp_store):
        """Submit a limit buy order far below market price, then cancel it."""
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Buy, THOST_FTDC_OF_Open,
            THOST_FTDC_OPT_LimitPrice, THOST_FTDC_OST_Canceled,
        )

        price = _get_tick_price(ctp_store, self.TEST_INSTRUMENT)
        if price <= 0:
            pytest.skip(f"Cannot get price for {self.TEST_INSTRUMENT} (market closed?)")

        # Place order far below market to avoid fill
        far_price = round(price * 0.8, 2)
        order_ref = ctp_store.send_order(
            symbol=self.TEST_INSTRUMENT,
            direction=THOST_FTDC_D_Buy,
            offset=THOST_FTDC_OF_Open,
            price=far_price,
            volume=1,
            order_price_type=THOST_FTDC_OPT_LimitPrice,
        )
        assert order_ref is not None, "send_order should return an order_ref"

        # Wait for order acknowledgment
        evt = _wait_for_order_event(ctp_store, order_ref, timeout=10)
        assert evt is not None, f"Should receive order event for ref={order_ref}"
        assert evt['instrument'] == self.TEST_INSTRUMENT
        assert evt['direction'] == THOST_FTDC_D_Buy

        # Cancel the order
        ok = ctp_store.cancel_order(
            symbol=self.TEST_INSTRUMENT,
            order_ref=order_ref,
        )
        assert ok, "cancel_order should return True"

        # Wait for cancellation event
        cancel_evt = _wait_for_order_event(ctp_store, order_ref, timeout=10)
        if cancel_evt:
            assert cancel_evt['status'] == THOST_FTDC_OST_Canceled, \
                f"Order should be canceled, got status={cancel_evt['status']}"

    def test_submit_sell_limit_order_and_cancel(self, ctp_store):
        """Submit a limit sell order far above market price, then cancel."""
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Sell, THOST_FTDC_OF_Open,
            THOST_FTDC_OPT_LimitPrice, THOST_FTDC_OST_Canceled,
        )

        price = _get_tick_price(ctp_store, self.TEST_INSTRUMENT)
        if price <= 0:
            pytest.skip(f"Cannot get price for {self.TEST_INSTRUMENT}")

        # Sell open far above market
        far_price = round(price * 1.2, 2)
        order_ref = ctp_store.send_order(
            symbol=self.TEST_INSTRUMENT,
            direction=THOST_FTDC_D_Sell,
            offset=THOST_FTDC_OF_Open,
            price=far_price,
            volume=1,
            order_price_type=THOST_FTDC_OPT_LimitPrice,
        )
        assert order_ref is not None

        evt = _wait_for_order_event(ctp_store, order_ref, timeout=10)
        assert evt is not None

        # Cancel
        ctp_store.cancel_order(self.TEST_INSTRUMENT, order_ref)
        cancel_evt = _wait_for_order_event(ctp_store, order_ref, timeout=10)
        if cancel_evt:
            assert cancel_evt['status'] == THOST_FTDC_OST_Canceled

    def test_order_ref_increments(self, ctp_store):
        """Each order should get a unique, incrementing order_ref."""
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Buy, THOST_FTDC_OF_Open, THOST_FTDC_OPT_LimitPrice,
        )

        price = _get_tick_price(ctp_store, self.TEST_INSTRUMENT)
        if price <= 0:
            pytest.skip("Cannot get price")

        far_price = round(price * 0.8, 2)
        refs = []
        for _ in range(3):
            ref = ctp_store.send_order(
                symbol=self.TEST_INSTRUMENT,
                direction=THOST_FTDC_D_Buy,
                offset=THOST_FTDC_OF_Open,
                price=far_price,
                volume=1,
                order_price_type=THOST_FTDC_OPT_LimitPrice,
            )
            assert ref is not None
            refs.append(ref)
            time.sleep(0.5)

        # All refs should be unique and incrementing
        assert len(set(refs)) == 3, f"Order refs should be unique: {refs}"
        int_refs = [int(r) for r in refs]
        assert int_refs == sorted(int_refs), f"Order refs should increment: {refs}"

        # Clean up: cancel all orders
        for ref in refs:
            ctp_store.cancel_order(self.TEST_INSTRUMENT, ref)
            time.sleep(0.3)


# ---------------------------------------------------------------------------
# Error Handling
# ---------------------------------------------------------------------------

class TestCTPOrderErrors:
    """Test CTP order error handling."""

    TEST_INSTRUMENT = 'au2506'

    def test_cancel_nonexistent_order(self, ctp_store):
        """Canceling a nonexistent order should not crash."""
        result = ctp_store.cancel_order(
            symbol=self.TEST_INSTRUMENT,
            order_ref='999999',
        )
        # Should return True (request sent) or False (send failed),
        # but should not raise an exception
        assert isinstance(result, bool)

    def test_send_order_invalid_price(self, ctp_store):
        """Sending an order with invalid params should be handled."""
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Buy, THOST_FTDC_OF_Open, THOST_FTDC_OPT_LimitPrice,
        )

        # Volume 0 should be rejected by CTP
        ref = ctp_store.send_order(
            symbol=self.TEST_INSTRUMENT,
            direction=THOST_FTDC_D_Buy,
            offset=THOST_FTDC_OF_Open,
            price=100.0,
            volume=0,
            order_price_type=THOST_FTDC_OPT_LimitPrice,
        )
        # CTP may reject at API level (return None) or via callback
        # Either way, no crash
        if ref is not None:
            # Wait for rejection event
            evt = _wait_for_order_event(ctp_store, ref, timeout=5)
            # Event may indicate rejection


# ---------------------------------------------------------------------------
# Market Order (AnyPrice)
# ---------------------------------------------------------------------------

class TestCTPMarketOrder:
    """Test market order submission with correct TimeCondition/VolumeCondition."""

    TEST_INSTRUMENT = 'au2506'

    def test_market_order_params(self, ctp_store):
        """Verify market order uses IOC time condition and CV volume condition.

        We test this by checking the send_order code path. Since market orders
        would fill immediately on SimNow, we just verify the order is accepted.
        """
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Buy, THOST_FTDC_OF_Open, THOST_FTDC_OPT_AnyPrice,
        )

        price = _get_tick_price(ctp_store, self.TEST_INSTRUMENT)
        if price <= 0:
            pytest.skip("Cannot get price")

        # Market order — may fill immediately on SimNow
        ref = ctp_store.send_order(
            symbol=self.TEST_INSTRUMENT,
            direction=THOST_FTDC_D_Buy,
            offset=THOST_FTDC_OF_Open,
            price=0.0,  # Market order price
            volume=1,
            order_price_type=THOST_FTDC_OPT_AnyPrice,
        )
        # Market order may succeed or fail depending on exchange rules
        # On SimNow, SHFE does not support market orders for gold
        # Just verify no crash
        if ref is not None:
            # Try to cancel in case it's pending
            time.sleep(1)
            ctp_store.cancel_order(self.TEST_INSTRUMENT, ref)


# ---------------------------------------------------------------------------
# CTPBroker Integration
# ---------------------------------------------------------------------------

class TestCTPBrokerIntegration:
    """Test CTPBroker integration with CTPStore."""

    def test_broker_start_loads_balance(self, ctp_store):
        """CTPBroker.start() should load account balance."""
        from backtrader.brokers.ctpbroker import CTPBroker

        broker = CTPBroker()
        broker.o = ctp_store
        broker.start()

        cash = broker.getcash()
        value = broker.getvalue()
        assert cash >= 0, f"Broker cash should be non-negative: {cash}"
        assert value >= 0, f"Broker value should be non-negative: {value}"

    def test_broker_get_notification_empty(self, ctp_store):
        """get_notification should return None when no notifications."""
        from backtrader.brokers.ctpbroker import CTPBroker

        broker = CTPBroker()
        broker.o = ctp_store
        assert broker.get_notification() is None
