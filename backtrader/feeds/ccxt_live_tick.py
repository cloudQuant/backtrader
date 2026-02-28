"""CCXT WebSocket live tick data feed.

Provides CCXTLiveTickFeed for streaming real-time trade data from
cryptocurrency exchanges via CCXT Pro WebSocket API. Events are
pushed into a LiveEventQueue for consumption by the strategy engine.

Supports:
    - Automatic reconnection on disconnect
    - Heartbeat monitoring
    - Multiple symbol subscriptions
    - Graceful shutdown

Requirements:
    - ccxt (pip install ccxt)
    - For WebSocket: ccxt[pro] or ccxtpro

Example::

    from backtrader.feeds.ccxt_live_tick import CCXTLiveTickFeed
    from backtrader.channels.live_queue import LiveEventQueue

    queue = LiveEventQueue()
    feed = CCXTLiveTickFeed(
        exchange_id='binance',
        symbol='BTC/USDT',
        event_queue=queue,
    )

    # Run in background thread
    import threading, asyncio
    t = threading.Thread(target=lambda: asyncio.run(feed.start()), daemon=True)
    t.start()

    # Consume events
    while True:
        event = queue.get(timeout=1.0)
        if event:
            print(event.data.price)
"""

import asyncio
import logging
import time
import threading
from typing import Optional

from ..events import TickEvent, OrderBookSnapshot, FundingEvent
from ..channel import Event, EventPriority

logger = logging.getLogger(__name__)

__all__ = ["CCXTLiveTickFeed"]


class CCXTLiveTickFeed:
    """Live tick data feed via CCXT WebSocket.

    Connects to a cryptocurrency exchange using CCXT Pro's WebSocket
    API and streams trade data as TickEvents into a LiveEventQueue.

    Args:
        exchange_id: CCXT exchange identifier (e.g., 'binance', 'okx').
        symbol: Trading pair symbol (e.g., 'BTC/USDT').
        event_queue: LiveEventQueue to push events into.
        exchange_config: Optional dict of exchange constructor kwargs
            (e.g., apiKey, secret, sandbox mode).
        subscribe_orderbook: Also subscribe to order book updates.
        subscribe_funding: Also subscribe to funding rate updates.
        orderbook_depth: Order book depth limit (default: 20).
        reconnect_delay: Seconds to wait before reconnecting (default: 5.0).
        max_reconnects: Maximum consecutive reconnect attempts (default: 50).
        heartbeat_interval: Seconds between heartbeat checks (default: 30.0).
    """

    def __init__(
        self,
        exchange_id,
        symbol,
        event_queue,
        exchange_config=None,
        subscribe_orderbook=False,
        subscribe_funding=False,
        orderbook_depth=20,
        reconnect_delay=5.0,
        max_reconnects=50,
        heartbeat_interval=30.0,
    ):
        """Initialize the CCXT live tick feed.

        Args:
            exchange_id: CCXT exchange identifier (e.g., 'binance', 'okx').
            symbol: Trading pair symbol (e.g., 'BTC/USDT').
            event_queue: LiveEventQueue to push events into.
            exchange_config: Optional dict of exchange constructor kwargs
                (e.g., apiKey, secret, sandbox mode).
            subscribe_orderbook: Also subscribe to order book updates.
            subscribe_funding: Also subscribe to funding rate updates.
            orderbook_depth: Order book depth limit (default: 20).
            reconnect_delay: Seconds to wait before reconnecting (default: 5.0).
            max_reconnects: Maximum consecutive reconnect attempts (default: 50).
            heartbeat_interval: Seconds between heartbeat checks (default: 30.0).
        """
        self.exchange_id = exchange_id
        self.symbol = symbol
        self.event_queue = event_queue
        self.exchange_config = exchange_config or {}
        self.subscribe_orderbook = subscribe_orderbook
        self.subscribe_funding = subscribe_funding
        self.orderbook_depth = orderbook_depth
        self.reconnect_delay = reconnect_delay
        self.max_reconnects = max_reconnects
        self.heartbeat_interval = heartbeat_interval

        self._exchange = None
        self._running = False
        self._connected = False
        self._reconnect_count = 0
        self._last_heartbeat = 0.0
        self._trade_count = 0
        self._ob_count = 0
        self._funding_count = 0
        self._error_count = 0
        self._start_time = 0.0

    async def start(self):
        """Start the WebSocket feed with automatic reconnection.

        This is a coroutine that runs indefinitely until stop() is called.
        It should be run via asyncio.run() or in an event loop.
        """
        self._running = True
        self._start_time = time.time()
        self._reconnect_count = 0

        while self._running and self._reconnect_count < self.max_reconnects:
            try:
                await self._connect()
                self._reconnect_count = 0  # Reset on successful connection
                await self._run_loop()
            except Exception as e:
                self._error_count += 1
                self._connected = False
                if not self._running:
                    break
                self._reconnect_count += 1
                logger.warning(
                    "CCXTLiveTickFeed %s/%s disconnected (%s), reconnecting %d/%d in %.1fs...",
                    self.exchange_id,
                    self.symbol,
                    e,
                    self._reconnect_count,
                    self.max_reconnects,
                    self.reconnect_delay,
                )
                await asyncio.sleep(self.reconnect_delay)
            finally:
                await self._disconnect()

        if self._reconnect_count >= self.max_reconnects:
            logger.error(
                "CCXTLiveTickFeed %s/%s max reconnects (%d) exceeded",
                self.exchange_id,
                self.symbol,
                self.max_reconnects,
            )

    async def _connect(self):
        """Create and initialize the CCXT Pro exchange instance."""
        try:
            import ccxt.pro as ccxtpro
        except ImportError:
            try:
                import ccxtpro
            except ImportError:
                raise ImportError("ccxt[pro] or ccxtpro is required for live tick feeds. Install with: pip install ccxt")

        exchange_class = getattr(ccxtpro, self.exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"Unknown exchange: {self.exchange_id}")

        self._exchange = exchange_class(self.exchange_config)
        self._connected = True
        logger.info("CCXTLiveTickFeed connected to %s for %s", self.exchange_id, self.symbol)

    async def _disconnect(self):
        """Close the exchange connection."""
        if self._exchange is not None:
            try:
                await self._exchange.close()
            except Exception as e:
                logger.debug("Error closing exchange: %s", e)
            self._exchange = None
        self._connected = False

    async def _run_loop(self):
        """Main event loop: subscribe and process WebSocket messages."""
        tasks = [self._watch_trades()]

        if self.subscribe_orderbook:
            tasks.append(self._watch_orderbook())
        if self.subscribe_funding:
            tasks.append(self._watch_funding())

        tasks.append(self._heartbeat_loop())

        await asyncio.gather(*tasks)

    async def _watch_trades(self):
        """Watch trades and push TickEvents."""
        while self._running:
            try:
                trades = await self._exchange.watch_trades(self.symbol)
                for trade in trades:
                    tick = TickEvent(
                        timestamp=trade["timestamp"] / 1000.0,
                        symbol=self.symbol,
                        price=float(trade["price"]),
                        volume=float(trade["amount"]),
                        direction="buy" if trade.get("side") == "buy" else "sell",
                        trade_id=str(trade.get("id", "")),
                    )
                    self.event_queue.put(
                        tick,
                        priority=EventPriority.TICK,
                        channel_type="tick",
                        channel_name=self.symbol,
                        timestamp=tick.timestamp,
                    )
                    self._trade_count += 1
                    self._last_heartbeat = time.time()
            except Exception as e:
                if not self._running:
                    break
                raise

    async def _watch_orderbook(self):
        """Watch order book and push OrderBookSnapshot events."""
        while self._running:
            try:
                ob = await self._exchange.watch_order_book(self.symbol, limit=self.orderbook_depth)
                bids = [(float(p), float(v)) for p, v in ob.get("bids", [])[: self.orderbook_depth]]
                asks = [(float(p), float(v)) for p, v in ob.get("asks", [])[: self.orderbook_depth]]

                snapshot = OrderBookSnapshot(
                    timestamp=ob.get("timestamp", time.time() * 1000) / 1000.0,
                    symbol=self.symbol,
                    bids=bids,
                    asks=asks,
                )
                self.event_queue.put(
                    snapshot,
                    priority=EventPriority.ORDERBOOK,
                    channel_type="orderbook",
                    channel_name=self.symbol,
                    timestamp=snapshot.timestamp,
                )
                self._ob_count += 1
                self._last_heartbeat = time.time()
            except Exception as e:
                if not self._running:
                    break
                raise

    async def _watch_funding(self):
        """Watch funding rate (exchange-dependent)."""
        while self._running:
            try:
                if hasattr(self._exchange, "watch_funding_rate"):
                    funding = await self._exchange.watch_funding_rate(self.symbol)
                    fe = FundingEvent(
                        timestamp=funding.get("timestamp", time.time() * 1000) / 1000.0,
                        symbol=self.symbol,
                        rate=float(funding.get("fundingRate", 0)),
                        mark_price=float(funding.get("markPrice", 0)),
                        next_funding_time=float(funding.get("fundingTimestamp", 0)) / 1000.0,
                    )
                    self.event_queue.put(
                        fe,
                        priority=EventPriority.FUNDING,
                        channel_type="funding",
                        channel_name=self.symbol,
                        timestamp=fe.timestamp,
                    )
                    self._funding_count += 1
                    self._last_heartbeat = time.time()
                else:
                    # Exchange doesn't support funding rate WebSocket
                    logger.info("%s does not support watch_funding_rate, skipping", self.exchange_id)
                    return
            except Exception as e:
                if not self._running:
                    break
                raise

    async def _heartbeat_loop(self):
        """Monitor connection health via heartbeat."""
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            if not self._running:
                break
            elapsed = time.time() - self._last_heartbeat
            if self._last_heartbeat > 0 and elapsed > self.heartbeat_interval * 3:
                logger.warning(
                    "CCXTLiveTickFeed %s/%s no data for %.1fs, possible connection stale",
                    self.exchange_id,
                    self.symbol,
                    elapsed,
                )

    def stop(self):
        """Stop the WebSocket feed gracefully.

        Sets the running flag to False, which will cause the start()
        coroutine to exit its main loop and terminate the connection.
        """
        self._running = False
        logger.info("CCXTLiveTickFeed %s/%s stopping", self.exchange_id, self.symbol)

    @property
    def running(self):
        """Whether the feed is currently running.

        Returns:
            bool: True if the feed is running, False otherwise.
        """
        return self._running

    @property
    def connected(self):
        """Whether the feed is currently connected to the exchange.

        Returns:
            bool: True if connected to the exchange, False otherwise.
        """
        return self._connected

    @property
    def stats(self):
        """Feed statistics."""
        uptime = time.time() - self._start_time if self._start_time else 0
        return {
            "exchange": self.exchange_id,
            "symbol": self.symbol,
            "running": self._running,
            "connected": self._connected,
            "trade_count": self._trade_count,
            "ob_count": self._ob_count,
            "funding_count": self._funding_count,
            "error_count": self._error_count,
            "reconnect_count": self._reconnect_count,
            "uptime_seconds": uptime,
        }

    def __repr__(self):
        """Return a string representation of the feed.

        Returns:
            str: A concise representation showing exchange, symbol,
                trade count, and connection status.
        """
        return (
            f"CCXTLiveTickFeed({self.exchange_id}/{self.symbol}, "
            f"trades={self._trade_count}, connected={self._connected})"
        )
