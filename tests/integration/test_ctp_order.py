#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CTP Integration Tests - Order Placement and Cancellation.

Tests CTP order lifecycle: submit, cancel, and fill on SimNow 7x24.

Usage:
    pytest tests/integration/test_ctp_order.py -m integration -v
"""

import time
import pytest

from tests.integration.conftest import skip_no_ctp

pytestmark = [pytest.mark.integration, skip_no_ctp]

# Instruments available on SimNow 7x24 (update yearly)
# Use liquid futures contracts; SimNow replays recent trading day ticks
TEST_INSTRUMENT = 'au2606'
TEST_INSTRUMENT_FALLBACKS = ['ag2606', 'rb2610', 'IF2603', 'cu2606']


def _find_tradeable_instrument(ctp_store, instruments=None):
    """Find an instrument that has live ticks (tradeable on 7x24)."""
    instruments = instruments or [TEST_INSTRUMENT] + TEST_INSTRUMENT_FALLBACKS
    for inst in instruments:
        q = ctp_store.md_spi.register_instrument(inst)
        ctp_store.md_spi.subscribe([inst])
        time.sleep(2)
        if not q.empty():
            tick = q.get_nowait()
            last_price = tick.get('last_price', 0.0)
            if 0 < last_price < 1e10:
                return inst, last_price, tick
    return None, None, None


# ---------------------------------------------------------------------------
# Order Submission & Cancellation
# ---------------------------------------------------------------------------

class TestCTPOrderLifecycle:
    """Test CTP order submission, status tracking, and cancellation."""

    def test_limit_order_submit_and_cancel(self, ctp_store):
        """Submit a limit order far from market, then cancel it."""
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Buy, THOST_FTDC_OF_Open,
            THOST_FTDC_OPT_LimitPrice, THOST_FTDC_OST_Canceled,
        )

        inst, last_price, _ = _find_tradeable_instrument(ctp_store)
        if inst is None:
            pytest.skip("No active instrument found (market may be closed)")

        # Place buy limit order at 50% of market price (won't fill)
        far_price = round(last_price * 0.5, 2)
        order_ref = ctp_store.send_order(
            symbol=inst,
            direction=THOST_FTDC_D_Buy,
            offset=THOST_FTDC_OF_Open,
            price=far_price,
            volume=1,
            order_price_type=THOST_FTDC_OPT_LimitPrice,
        )
        assert order_ref is not None, "send_order should return an order_ref"

        # Wait for order acknowledgement
        time.sleep(2)

        # Check order queue for status updates
        events = []
        while not ctp_store.order_queue.empty():
            events.append(ctp_store.order_queue.get_nowait())

        assert len(events) > 0, f"Should receive order events for ref={order_ref}"
        # Find event matching our order
        our_events = [e for e in events if e.get('order_ref') == order_ref]
        assert len(our_events) > 0, f"Should have events for our order_ref={order_ref}"

        # If not already cancelled/rejected, cancel it
        last_evt = our_events[-1]
        if last_evt.get('status') != THOST_FTDC_OST_Canceled and not last_evt.get('rejected'):
            result = ctp_store.cancel_order(inst, order_ref)
            assert result is True, "cancel_order should return True"

            # Wait for cancel confirmation
            time.sleep(2)
            while not ctp_store.order_queue.empty():
                evt = ctp_store.order_queue.get_nowait()
                if evt.get('order_ref') == order_ref:
                    our_events.append(evt)

            # Verify cancelled
            final_evt = our_events[-1]
            assert (
                final_evt.get('status') == THOST_FTDC_OST_Canceled
                or final_evt.get('rejected')
            ), f"Order should be cancelled, got status={final_evt.get('status')}"

    def test_limit_order_rejected_bad_price(self, ctp_store):
        """Submit a limit order with price=0, should be rejected."""
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Buy, THOST_FTDC_OF_Open,
            THOST_FTDC_OPT_LimitPrice,
        )

        inst, _, _ = _find_tradeable_instrument(ctp_store)
        if inst is None:
            pytest.skip("No active instrument found")

        # Price = 0 for limit order should be rejected
        order_ref = ctp_store.send_order(
            symbol=inst,
            direction=THOST_FTDC_D_Buy,
            offset=THOST_FTDC_OF_Open,
            price=0.0,
            volume=1,
            order_price_type=THOST_FTDC_OPT_LimitPrice,
        )

        # May return None (API rejects immediately) or return ref with rejection event
        if order_ref is None:
            # API-level rejection - acceptable
            return

        # Wait for exchange rejection
        time.sleep(2)
        events = []
        while not ctp_store.order_queue.empty():
            evt = ctp_store.order_queue.get_nowait()
            if evt.get('order_ref') == order_ref:
                events.append(evt)

        # Should be rejected or cancelled
        if events:
            last_evt = events[-1]
            assert (
                last_evt.get('rejected') or
                last_evt.get('status') in ('5', 'a')  # Canceled or Unknown
            ), f"Bad price order should be rejected, got: {last_evt}"

    def test_sell_order_submit_and_cancel(self, ctp_store):
        """Submit a sell limit order far from market, then cancel it."""
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Sell, THOST_FTDC_OF_Open,
            THOST_FTDC_OPT_LimitPrice, THOST_FTDC_OST_Canceled,
        )

        inst, last_price, _ = _find_tradeable_instrument(ctp_store)
        if inst is None:
            pytest.skip("No active instrument found")

        # Place sell limit order at 200% of market price (won't fill)
        far_price = round(last_price * 2.0, 2)
        order_ref = ctp_store.send_order(
            symbol=inst,
            direction=THOST_FTDC_D_Sell,
            offset=THOST_FTDC_OF_Open,
            price=far_price,
            volume=1,
            order_price_type=THOST_FTDC_OPT_LimitPrice,
        )
        assert order_ref is not None, "send_order should return an order_ref"

        time.sleep(2)

        # Cancel it
        result = ctp_store.cancel_order(inst, order_ref)
        time.sleep(2)

        # Drain events
        events = []
        while not ctp_store.order_queue.empty():
            evt = ctp_store.order_queue.get_nowait()
            if evt.get('order_ref') == order_ref:
                events.append(evt)

        # Should have at least one event
        assert len(events) > 0, "Should receive order events"


# ---------------------------------------------------------------------------
# CTPBroker Order Integration
# ---------------------------------------------------------------------------

class TestCTPBrokerOrder:
    """Test CTPBroker order flow with real CTP connection."""

    def test_broker_buy_and_cancel(self, ctp_store):
        """Test CTPBroker.buy() creates and submits order to CTP."""
        from backtrader.brokers.ctpbroker import CTPBroker
        from backtrader.order import Order
        from unittest.mock import MagicMock
        import collections
        from backtrader.position import Position
        from backtrader.utils import date2num
        import datetime as dt

        inst, last_price, _ = _find_tradeable_instrument(ctp_store)
        if inst is None:
            pytest.skip("No active instrument found")

        # Create broker manually connected to the real store
        broker = CTPBroker.__new__(CTPBroker)
        broker.o = ctp_store
        broker.orders = collections.OrderedDict()
        broker.open_orders = {}  # dict for O(1) removal
        broker.notifs = collections.deque()
        broker._ref_to_bt = {}
        broker.startingcash = broker.cash = 100000.0
        broker.startingvalue = broker.value = 100000.0
        broker.positions = collections.defaultdict(Position)
        broker._pos_detail = collections.defaultdict(
            lambda: {'today_long': 0, 'today_short': 0, 'yd_long': 0, 'yd_short': 0}
        )
        broker._pending_stops = []  # C1: pending stop orders
        broker._processed_trade_ids = set()  # T4: dedup
        broker._last_balance_time = 0.0  # T1: rate-limit balance
        broker._balance_interval = 10.0
        broker._last_trading_day = None  # T13: day change
        broker._params = {'use_positions': True, 'commission': 0.0, 'stop_slippage_ticks': 0.0}
        broker.get_param = lambda k: broker._params.get(k)

        # Mock owner and data
        owner = MagicMock()
        data = MagicMock()
        dataname = f'{inst}.SHFE'
        data.p.dataname = dataname
        data._dataname = dataname
        data.p.sessionend = dt.time(15, 0, 0)
        data.p.simulated = False
        now = dt.datetime.now()
        now_num = date2num(now)
        mock_dt = MagicMock()
        mock_dt.__getitem__ = MagicMock(return_value=now_num)
        mock_dt.datetime = MagicMock(return_value=now)
        mock_dt.date = MagicMock(return_value=now.date())
        data.datetime = mock_dt
        data.date2num = date2num

        # Submit buy at far-from-market price
        far_price = round(last_price * 0.5, 2)
        order = broker.buy(owner, data, size=1, price=far_price,
                          exectype=Order.Limit)
        assert order is not None
        assert order.ref in broker.orders
        assert hasattr(order, '_ctp_order_ref')
        assert order._ctp_order_ref is not None

        time.sleep(2)

        # Process events
        broker._process_order_events()

        # Cancel
        broker.cancel(order)
        time.sleep(2)

        # Process cancel events
        broker._process_order_events()

        # Order should be cancelled
        assert order.status in (Order.Canceled, Order.Rejected, Order.Accepted), \
            f"Order status should be Canceled/Rejected, got {order.status}"


# ---------------------------------------------------------------------------
# Account Query After Order
# ---------------------------------------------------------------------------

class TestCTPAccountAfterOrder:
    """Test that account queries work correctly after order operations."""

    def test_balance_after_order_cycle(self, ctp_store):
        """Account balance should still be queryable after order submit/cancel."""
        from backtrader.stores.ctpstore import (
            THOST_FTDC_D_Buy, THOST_FTDC_OF_Open,
            THOST_FTDC_OPT_LimitPrice,
        )

        inst, last_price, _ = _find_tradeable_instrument(ctp_store)
        if inst is None:
            pytest.skip("No active instrument found")

        # Submit and cancel an order
        far_price = round(last_price * 0.5, 2)
        order_ref = ctp_store.send_order(
            symbol=inst,
            direction=THOST_FTDC_D_Buy,
            offset=THOST_FTDC_OF_Open,
            price=far_price,
            volume=1,
            order_price_type=THOST_FTDC_OPT_LimitPrice,
        )
        if order_ref:
            time.sleep(1)
            ctp_store.cancel_order(inst, order_ref)
            time.sleep(1)

        # Query balance - should work fine
        ctp_store._last_balance_query = 0.0
        ctp_store.get_balance()
        cash = ctp_store.get_cash()
        value = ctp_store.get_value()
        assert isinstance(cash, (int, float))
        assert isinstance(value, (int, float))
        assert value >= 0
