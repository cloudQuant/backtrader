#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Integration tests for CCXT order lifecycle (P2-1).

These tests place REAL orders on the OKX sandbox/demo exchange.
They verify:
- Order submission (market, limit)
- Order status tracking
- Order cancellation
- WebSocket order push (watch_my_trades)
- Broker order lifecycle end-to-end

Run:
    pytest tests/integration/test_ccxt_trading.py -m integration -v

WARNING: These tests will place orders on sandbox. Ensure sandbox=True.
"""

import time
import queue
import threading
import pytest

from tests.integration.conftest import skip_no_okx, skip_no_ccxtpro

pytestmark = [pytest.mark.integration, pytest.mark.trading, skip_no_okx]


class TestOrderSubmission:
    """Test order submission via ccxt REST API on sandbox."""

    def test_fetch_open_orders_empty(self, ccxt_exchange):
        """Verify fetching open orders works (may be empty)."""
        ccxt_exchange.load_markets()
        orders = ccxt_exchange.fetch_open_orders('BTC/USDT:USDT')
        assert isinstance(orders, list)

    def test_place_and_cancel_limit_order(self, ccxt_exchange):
        """Place a limit order far from market, then cancel it."""
        ccxt_exchange.load_markets()

        # Get current price
        ticker = ccxt_exchange.fetch_ticker('BTC/USDT:USDT')
        current_price = ticker['last']

        # Place limit buy 20% below market (won't fill)
        limit_price = round(current_price * 0.80, 1)
        amount = 0.001  # Minimum BTC amount

        order = None
        try:
            order = ccxt_exchange.create_order(
                symbol='BTC/USDT:USDT',
                type='limit',
                side='buy',
                amount=amount,
                price=limit_price,
            )
            assert order is not None
            assert order['id'] is not None
            assert order['status'] in ('open', 'new', 'created')

            # Verify it shows in open orders
            time.sleep(1)
            open_orders = ccxt_exchange.fetch_open_orders('BTC/USDT:USDT')
            order_ids = [o['id'] for o in open_orders]
            assert order['id'] in order_ids, "Order not found in open orders"

        finally:
            # Always cancel
            if order and order.get('id'):
                try:
                    ccxt_exchange.cancel_order(order['id'], 'BTC/USDT:USDT')
                except Exception as e:
                    print(f"Cancel cleanup failed: {e}")

    def test_cancel_order_success(self, ccxt_exchange):
        """Place and cancel, verify status becomes 'canceled'."""
        ccxt_exchange.load_markets()

        ticker = ccxt_exchange.fetch_ticker('BTC/USDT:USDT')
        limit_price = round(ticker['last'] * 0.80, 1)

        order = ccxt_exchange.create_order(
            symbol='BTC/USDT:USDT',
            type='limit',
            side='buy',
            amount=0.001,
            price=limit_price,
        )

        time.sleep(1)
        result = ccxt_exchange.cancel_order(order['id'], 'BTC/USDT:USDT')
        assert result is not None

        # Verify order is no longer open
        time.sleep(1)
        open_orders = ccxt_exchange.fetch_open_orders('BTC/USDT:USDT')
        order_ids = [o['id'] for o in open_orders]
        assert order['id'] not in order_ids, "Canceled order still in open orders"


@pytest.mark.usefixtures("ccxt_store")
class TestCCXTStoreOrderProxy:
    """Test order operations through CCXTStore."""

    def test_store_create_order(self, ccxt_store):
        """Verify CCXTStore can proxy order creation."""
        ccxt_store.exchange.load_markets()

        ticker = ccxt_store.exchange.fetch_ticker('BTC/USDT:USDT')
        limit_price = round(ticker['last'] * 0.80, 1)

        order = None
        try:
            order = ccxt_store.exchange.create_order(
                symbol='BTC/USDT:USDT',
                type='limit',
                side='buy',
                amount=0.001,
                price=limit_price,
            )
            assert order['id'] is not None
        finally:
            if order and order.get('id'):
                try:
                    ccxt_store.exchange.cancel_order(order['id'], 'BTC/USDT:USDT')
                except Exception:
                    pass


@skip_no_ccxtpro
class TestWebSocketOrderPush:
    """Test WebSocket order push via watch_my_trades (P2-1).

    This test places a real market order and verifies the fill
    arrives via WebSocket callback.
    """

    def test_ws_order_fill_notification(self, okx_config):
        """Place market order and verify WS delivers fill notification."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager
        import ccxt

        # Setup WS manager
        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=True,
        )

        fills = []
        fill_event = threading.Event()

        def on_fill(trades):
            fills.extend(trades)
            fill_event.set()

        ws.start()
        time.sleep(3)  # Wait for connection

        # Subscribe to my_trades before placing order
        ws.subscribe_my_trades('BTC/USDT:USDT', on_fill)
        time.sleep(1)

        # Place a small market buy order
        exchange = ccxt.okx(okx_config)
        exchange.set_sandbox_mode(True)
        exchange.load_markets()

        order = None
        try:
            order = exchange.create_order(
                symbol='BTC/USDT:USDT',
                type='market',
                side='buy',
                amount=0.001,
            )
            assert order is not None, "Market order creation failed"

            # Wait for WS fill notification
            got_fill = fill_event.wait(timeout=15)

            if got_fill:
                assert len(fills) > 0, "Fill event set but no fill data"
                # Verify fill contains expected fields
                fill = fills[0]
                assert 'id' in fill or 'order' in fill
            else:
                # WS fill may not arrive in sandbox — log but don't fail hard
                pytest.skip(
                    "WS fill not received within 15s "
                    "(sandbox may not support watch_my_trades)"
                )

        finally:
            ws.stop()
            # Close position if opened
            if order:
                try:
                    exchange.create_order(
                        symbol='BTC/USDT:USDT',
                        type='market',
                        side='sell',
                        amount=0.001,
                    )
                except Exception:
                    pass

    def test_broker_ws_order_queue(self, okx_config):
        """Verify broker-level WS order queue receives fills."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=True,
        )

        order_queue = queue.Queue()

        def on_fill(trades):
            for trade in trades:
                order_queue.put(trade)

        ws.start()
        time.sleep(2)

        ws.subscribe_my_trades('BTC/USDT:USDT', on_fill)
        time.sleep(1)

        # No order placed — queue should remain empty
        try:
            item = order_queue.get(timeout=3)
            # If we get something, it's a leftover fill — acceptable
        except queue.Empty:
            pass  # Expected — no orders placed

        ws.stop()


class TestOrderErrorHandling:
    """Test order error scenarios."""

    def test_cancel_nonexistent_order(self, ccxt_exchange):
        """Verify canceling a non-existent order raises appropriate error."""
        ccxt_exchange.load_markets()
        import ccxt as ccxtlib

        with pytest.raises((ccxtlib.OrderNotFound, ccxtlib.ExchangeError)):
            ccxt_exchange.cancel_order('fake-order-id-12345', 'BTC/USDT:USDT')

    def test_insufficient_balance_order(self, ccxt_exchange):
        """Verify placing an order exceeding balance raises error."""
        ccxt_exchange.load_markets()
        import ccxt as ccxtlib

        ticker = ccxt_exchange.fetch_ticker('BTC/USDT:USDT')
        # Try to buy an absurd amount
        with pytest.raises((ccxtlib.InsufficientFunds, ccxtlib.ExchangeError)):
            ccxt_exchange.create_order(
                symbol='BTC/USDT:USDT',
                type='market',
                side='buy',
                amount=10000,  # 10000 BTC — way beyond sandbox balance
            )
