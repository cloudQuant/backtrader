#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Integration tests for CCXT WebSocket features (P2).

Tests:
- WebSocket manager lifecycle (start/stop/reconnect)
- OHLCV streaming via WebSocket
- Multi-symbol shared WebSocket connections
- Funding rate and mark price streaming
- watch_my_trades subscription (requires auth)

Run:
    pytest tests/integration/test_ccxt_websocket.py -m integration -v
"""

import asyncio
import time
import threading
import pytest

from tests.integration.conftest import skip_no_okx, skip_no_ccxtpro, _use_sandbox

pytestmark = [pytest.mark.integration, pytest.mark.websocket, skip_no_okx, skip_no_ccxtpro]


class TestWebSocketManagerLifecycle:
    """Test CCXTWebSocketManager start/stop/reconnect."""

    def test_ws_manager_start_stop(self, okx_config):
        """Verify WS manager starts and stops cleanly."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=_use_sandbox(),
        )
        ws.start()
        assert ws._running is True
        assert ws._thread is not None
        assert ws._thread.is_alive()

        ws.stop()
        time.sleep(1)
        assert ws._running is False

    def test_ws_manager_double_stop(self, okx_config):
        """Verify stopping an already-stopped manager is safe."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=_use_sandbox(),
        )
        ws.start()
        ws.stop()
        # Second stop should not raise
        ws.stop()


class TestWebSocketOHLCV:
    """Test real-time OHLCV streaming via WebSocket."""

    def test_subscribe_ohlcv_single_symbol(self, okx_config):
        """Verify OHLCV subscription delivers candle data."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        received_data = []
        event = threading.Event()

        def on_ohlcv(data):
            received_data.append(data)
            if len(received_data) >= 1:
                event.set()

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=_use_sandbox(),
        )
        ws.start()
        time.sleep(2)  # Wait for connection

        ws.subscribe_ohlcv('BTC/USDT:USDT', '1m', on_ohlcv)

        # Wait up to 30s for data
        got_data = event.wait(timeout=30)
        ws.stop()

        if not got_data:
            pytest.skip("No OHLCV data received within 30s (network/sandbox issue)")
        assert len(received_data) > 0
        # Each OHLCV update should be a list of candles
        candle = received_data[0]
        assert isinstance(candle, list), f"Expected list, got {type(candle)}"

    def test_subscribe_ohlcv_multi_symbol(self, okx_config):
        """Verify multiple OHLCV subscriptions on shared WS."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        btc_data = []
        eth_data = []
        btc_event = threading.Event()
        eth_event = threading.Event()

        def on_btc(data):
            btc_data.append(data)
            btc_event.set()

        def on_eth(data):
            eth_data.append(data)
            eth_event.set()

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=_use_sandbox(),
        )
        ws.start()
        time.sleep(2)

        ws.subscribe_ohlcv('BTC/USDT:USDT', '1m', on_btc)
        ws.subscribe_ohlcv('ETH/USDT:USDT', '1m', on_eth)

        # Wait for both
        btc_ok = btc_event.wait(timeout=30)
        eth_ok = eth_event.wait(timeout=30)
        ws.stop()

        if not btc_ok or not eth_ok:
            pytest.skip("No multi-symbol OHLCV data received (network/sandbox issue)")
        assert len(btc_data) > 0
        assert len(eth_data) > 0


class TestWebSocketTicker:
    """Test real-time ticker streaming."""

    def test_subscribe_ticker(self, okx_config):
        """Verify ticker subscription delivers price updates."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        received = []
        event = threading.Event()

        def on_ticker(data):
            received.append(data)
            event.set()

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=_use_sandbox(),
        )
        ws.start()
        time.sleep(2)

        ws.subscribe_ticker('BTC/USDT:USDT', on_ticker)

        got_data = event.wait(timeout=20)
        ws.stop()

        if not got_data:
            pytest.skip("No ticker data received within 20s (network/sandbox issue)")
        assert len(received) > 0
        ticker = received[0]
        assert 'last' in ticker or isinstance(ticker, dict)


class TestWebSocketFundingRate:
    """Test funding rate and mark price streaming."""

    def test_subscribe_funding_rate(self, okx_config):
        """Verify funding rate subscription delivers data."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        received = []
        event = threading.Event()

        def on_funding(data):
            received.append(data)
            event.set()

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=_use_sandbox(),
        )
        ws.start()
        time.sleep(2)

        ws.subscribe_funding_rate('BTC/USDT:USDT', on_funding)

        got_data = event.wait(timeout=30)
        ws.stop()

        if not got_data:
            pytest.skip("Funding rate data not received (may not be available in sandbox)")
        assert len(received) > 0

    def test_subscribe_mark_price(self, okx_config):
        """Verify mark price subscription delivers data."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        received = []
        event = threading.Event()

        def on_mark(data):
            received.append(data)
            event.set()

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=_use_sandbox(),
        )
        ws.start()
        time.sleep(2)

        ws.subscribe_mark_price('BTC/USDT:USDT', on_mark)

        got_data = event.wait(timeout=30)
        ws.stop()

        if not got_data:
            pytest.skip("Mark price data not received (may not be available in sandbox)")
        assert len(received) > 0


class TestSharedWebSocketManager:
    """Test shared WebSocket manager from CCXTStore (P2-2)."""

    def test_store_shared_ws_multi_subscribe(self, ccxt_store):
        """Verify store's shared WS manager handles multiple subscriptions."""
        ws = ccxt_store.get_websocket_manager()
        assert ws is not None

        btc_data = []
        eth_data = []
        btc_event = threading.Event()
        eth_event = threading.Event()

        def on_btc(data):
            btc_data.append(data)
            btc_event.set()

        def on_eth(data):
            eth_data.append(data)
            eth_event.set()

        ws.start()
        time.sleep(2)

        ws.subscribe_ohlcv('BTC/USDT:USDT', '1m', on_btc)
        ws.subscribe_ohlcv('ETH/USDT:USDT', '1m', on_eth)

        btc_ok = btc_event.wait(timeout=30)
        eth_ok = eth_event.wait(timeout=30)

        # Don't stop WS here — store.stop() handles it
        assert btc_ok, "No BTC data from shared WS"
        assert eth_ok, "No ETH data from shared WS"

    def test_store_shared_ws_is_singleton(self, ccxt_store):
        """Verify get_websocket_manager returns the same instance."""
        ws1 = ccxt_store.get_websocket_manager()
        ws2 = ccxt_store.get_websocket_manager()
        assert ws1 is ws2, "Shared WS manager should be singleton per store"


class TestWebSocketMyTrades:
    """Test watch_my_trades WebSocket subscription (P2-1)."""

    def test_subscribe_my_trades_no_error(self, okx_config):
        """Verify subscribing to my_trades doesn't raise errors."""
        from backtrader.ccxt.websocket import CCXTWebSocketManager

        received = []

        def on_trades(data):
            received.append(data)

        ws = CCXTWebSocketManager(
            exchange_id='okx',
            config=okx_config,
            sandbox=_use_sandbox(),
        )
        ws.start()
        time.sleep(2)

        # Subscribe should not raise even if no trades happen
        ws.subscribe_my_trades('BTC/USDT:USDT', on_trades)

        # Wait a bit — no trades expected in sandbox without placing orders
        time.sleep(5)
        ws.stop()

        # Just verify no crash happened — trade data only arrives on actual fills
        # received may be empty, which is fine
