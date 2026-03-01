"""Unit tests for backtrader/feeds/ccxt_live_tick.py - CCXTLiveTickFeed.

Uses mocks to avoid real exchange connections.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backtrader.feeds.ccxt_live_tick import CCXTLiveTickFeed
from backtrader.channels.live_queue import LiveEventQueue
from backtrader.channel import EventPriority


class TestCCXTLiveTickFeedUnit:
    """Unit tests for CCXTLiveTickFeed using mocked exchange connections.

    All tests use mocks to avoid real network connections to cryptocurrency
    exchanges, ensuring fast and reliable test execution.
    """

    def test_basic_creation(self):
        """Test basic CCXTLiveTickFeed instantiation.

        Verifies that a feed can be created with exchange and symbol
        parameters and initializes with correct default values.
        """
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q)
        assert feed.exchange_id == 'binance'
        assert feed.symbol == 'BTC/USDT'
        assert feed.running is False
        assert feed.connected is False

    def test_stats_initial(self):
        """Test initial statistics report for a newly created feed.

        Verifies the stats dictionary contains correct exchange, symbol,
        and initial counters before any data is received.
        """
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q)
        stats = feed.stats
        assert stats['exchange'] == 'binance'
        assert stats['symbol'] == 'BTC/USDT'
        assert stats['trade_count'] == 0
        assert stats['running'] is False

    def test_repr(self):
        """Test string representation of the feed.

        Verifies that repr() includes the exchange ID and trading symbol
        for debugging and logging purposes.
        """
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q)
        r = repr(feed)
        assert 'binance' in r
        assert 'BTC/USDT' in r

    def test_stop(self):
        """Test stopping the feed sets running flag to False.

        Verifies that calling stop() correctly sets the internal running
        flag to signal data loops to terminate.
        """
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q)
        feed._running = True
        feed.stop()
        assert feed.running is False

    def test_config_params(self):
        """Test configuration parameters are properly stored.

        Verifies that optional parameters for orderbook subscription,
        funding rate subscription, depth, reconnection settings, and
        heartbeat interval are correctly applied.
        """
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed(
            'okx', 'ETH/USDT', q,
            subscribe_orderbook=True,
            subscribe_funding=True,
            orderbook_depth=10,
            reconnect_delay=2.0,
            max_reconnects=10,
            heartbeat_interval=15.0,
        )
        assert feed.subscribe_orderbook is True
        assert feed.subscribe_funding is True
        assert feed.orderbook_depth == 10
        assert feed.reconnect_delay == 2.0
        assert feed.max_reconnects == 10

    @pytest.mark.asyncio
    async def test_connect_unknown_exchange(self):
        """Test that unknown exchange raises ValueError."""
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('nonexistent_exchange_xyz', 'BTC/USDT', q)

        # Directly mock the import inside _connect by patching at module level
        import types
        mock_ccxtpro = types.ModuleType('ccxt.pro')
        # Module has no 'nonexistent_exchange_xyz' attribute → getattr returns None

        import sys
        old = sys.modules.get('ccxt.pro')
        sys.modules['ccxt.pro'] = mock_ccxtpro
        try:
            with pytest.raises(ValueError, match="Unknown exchange"):
                await feed._connect()
        finally:
            if old is not None:
                sys.modules['ccxt.pro'] = old
            else:
                sys.modules.pop('ccxt.pro', None)

    @pytest.mark.asyncio
    async def test_watch_trades_pushes_events(self):
        """Test that watch_trades correctly creates TickEvents."""
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q)

        mock_exchange = AsyncMock()
        mock_exchange.watch_trades = AsyncMock(side_effect=[
            [
                {'timestamp': 100000, 'price': 50000.0, 'amount': 1.5,
                 'side': 'buy', 'id': 't1'},
                {'timestamp': 100001, 'price': 50001.0, 'amount': 0.5,
                 'side': 'sell', 'id': 't2'},
            ],
            asyncio.CancelledError(),  # Stop after first batch
        ])
        feed._exchange = mock_exchange
        feed._running = True

        with pytest.raises(asyncio.CancelledError):
            await feed._watch_trades()

        assert feed._trade_count == 2
        assert q.size == 2

        e1 = q.get(timeout=0)
        assert e1.data.price == 50000.0
        assert e1.data.volume == 1.5
        assert e1.data.direction == 'buy'
        assert e1.channel_type == 'tick'

        e2 = q.get(timeout=0)
        assert e2.data.price == 50001.0
        assert e2.data.direction == 'sell'

    @pytest.mark.asyncio
    async def test_watch_orderbook_pushes_events(self):
        """Test that watch_order_book correctly creates OB snapshots."""
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q,
                                subscribe_orderbook=True, orderbook_depth=5)

        mock_exchange = AsyncMock()
        mock_exchange.watch_order_book = AsyncMock(side_effect=[
            {
                'timestamp': 100000,
                'bids': [[50000, 1.0], [49999, 2.0]],
                'asks': [[50001, 1.5], [50002, 2.5]],
            },
            asyncio.CancelledError(),
        ])
        feed._exchange = mock_exchange
        feed._running = True

        with pytest.raises(asyncio.CancelledError):
            await feed._watch_orderbook()

        assert feed._ob_count == 1
        assert q.size == 1

        e = q.get(timeout=0)
        assert e.channel_type == 'orderbook'
        assert e.data.bids == [(50000, 1.0), (49999, 2.0)]

    @pytest.mark.asyncio
    async def test_watch_funding_pushes_events(self):
        """Test funding rate subscription."""
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q,
                                subscribe_funding=True)

        mock_exchange = AsyncMock()
        mock_exchange.watch_funding_rate = AsyncMock(side_effect=[
            {
                'timestamp': 100000,
                'fundingRate': 0.0001,
                'markPrice': 50000.0,
                'fundingTimestamp': 200000,
            },
            asyncio.CancelledError(),
        ])
        feed._exchange = mock_exchange
        feed._running = True

        with pytest.raises(asyncio.CancelledError):
            await feed._watch_funding()

        assert feed._funding_count == 1
        e = q.get(timeout=0)
        assert e.channel_type == 'funding'
        assert e.data.rate == 0.0001

    @pytest.mark.asyncio
    async def test_watch_funding_no_support(self):
        """Test graceful handling when exchange doesn't support funding WS.

        Verifies that the feed handles exchanges without funding rate
        WebSocket support without crashing, gracefully returning when
        the watch_funding_rate method is not available.
        """
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q,
                                subscribe_funding=True)

        mock_exchange = MagicMock()
        # Remove watch_funding_rate attribute
        if hasattr(mock_exchange, 'watch_funding_rate'):
            delattr(mock_exchange, 'watch_funding_rate')
        feed._exchange = mock_exchange
        feed._running = True

        # Should return gracefully without error
        await feed._watch_funding()
        assert feed._funding_count == 0

    @pytest.mark.asyncio
    async def test_stop_during_watch(self):
        """Test that stop() breaks the watch loop."""
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q)

        mock_exchange = AsyncMock()
        call_count = 0

        async def mock_watch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                feed.stop()
                raise Exception("stopped")
            return [{'timestamp': 100000, 'price': 50000.0, 'amount': 1.0,
                     'side': 'buy', 'id': 't1'}]

        mock_exchange.watch_trades = mock_watch
        feed._exchange = mock_exchange
        feed._running = True

        # Should exit after stop
        try:
            await feed._watch_trades()
        except Exception:
            pass
        assert feed.running is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnect closes exchange."""
        q = LiveEventQueue()
        feed = CCXTLiveTickFeed('binance', 'BTC/USDT', q)

        mock_exchange = AsyncMock()
        feed._exchange = mock_exchange
        feed._connected = True

        await feed._disconnect()
        mock_exchange.close.assert_awaited_once()
        assert feed._exchange is None
        assert feed.connected is False
