#!/usr/bin/env python
"""WebSocket Module - Real-time data streaming via CCXT Pro.

This module provides WebSocket-based real-time data streaming using
CCXT Pro library for low-latency market data.

Classes:
    CCXTWebSocketManager: WebSocket connection and subscription manager.

Example:
    >>> manager = CCXTWebSocketManager('binance', config)
    >>> manager.start()
    >>> await manager.subscribe_ohlcv('BTC/USDT', '1m', callback)

Note:
    Requires ccxt.pro package: pip install ccxtpro
"""

import asyncio
import logging
import threading
from typing import Callable, Dict, List

logger = logging.getLogger(__name__)

# Try to import ccxt.pro
try:
    import ccxt.pro as ccxtpro

    HAS_CCXT_PRO = True
except ImportError:
    HAS_CCXT_PRO = False
    ccxtpro = None


class CCXTWebSocketManager:
    """CCXT WebSocket connection manager.

    Manages WebSocket connections using CCXT Pro for real-time
    market data streaming.

    Attributes:
        exchange_id: Exchange identifier (e.g., 'binance').
        config: Exchange configuration dictionary.
        exchange: CCXT Pro exchange instance.
    """

    # Market type mapping
    MARKET_TYPES = {
        "spot": "SPOT",  # Spot trading
        "swap": "SWAP",  # Perpetual futures
        "future": "FUTURES",  # Delivery futures
        "option": "OPTION",  # Options
    }

    def __init__(self, exchange_id: str, config: dict, markets: dict = None, sandbox: bool = False):
        """Initialize the WebSocket manager.

        Args:
            exchange_id: Exchange ID (e.g., 'binance', 'okx').
            config: Exchange configuration with API keys, etc.
            markets: Pre-loaded markets dict from store (optional, avoids REST call).
            sandbox: If True, use exchange's sandbox/demo mode (default: False).

        Raises:
            ImportError: If ccxt.pro is not installed.
        """
        if not HAS_CCXT_PRO:
            raise ImportError("ccxt.pro is required for WebSocket support. Install with: pip install ccxtpro")

        self.exchange_id = exchange_id
        self.config = config
        self.exchange = None
        self._sandbox = sandbox
        self._loop = None
        self._thread = None
        self._running = False
        self._subscriptions: Dict[str, Callable] = {}
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._connected = False
        self._subscribed_symbols = set()  # Subscribed trading pairs
        self._preloaded_markets = markets  # Pre-loaded markets from store
        self._reconnecting = False  # Prevent multiple watch loops from triggering reconnect simultaneously
        # C14: Reconnect callbacks — callers can register to do REST backfill
        self._reconnect_callbacks: List[Callable] = []

    def _detect_market_type(self, symbol: str) -> str:
        """Detect market type based on trading pair format.

        Args:
            symbol: Trading pair symbol such as 'BTC/USDT', 'BTC/USDT:USDT',
                or 'BTC/USDT:USDT-240329'.

        Returns:
            Market type: 'spot', 'swap', 'future', or 'option'.
        """
        # Format: BASE/QUOTE[:SETTLE]
        # Examples: BTC/USDT (spot), BTC/USDT:USDT (perpetual swap),
        #           BTC/USDT:USDT-240329 (delivery futures)

        parts = symbol.split(":")
        if len(parts) == 1:
            # No settlement currency, it's spot
            return "spot"
        elif len(parts) == 2:
            settle_currency = parts[1]
            # Check for date suffix (e.g., USDT-240329)
            if "-" in settle_currency:
                return "future"  # Delivery futures
            else:
                return "swap"  # Perpetual swap
        return "spot"  # Default to spot

    def _get_required_market_types(self) -> set:
        """Get the market types required for current subscriptions.

        Returns:
            set: Set of market types needed (defaults to {'spot'} if none).
        """
        market_types = set()
        for key in self._subscriptions.keys():
            parts = key.split(":")
            if len(parts) >= 2:
                symbol = parts[1] if parts[0] == "ticker" else parts[1]
                market_type = self._detect_market_type(symbol)
                market_types.add(market_type)
        return market_types if market_types else {"spot"}  # Default to spot at minimum

    def start(self) -> None:
        """Start the WebSocket thread and event loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the WebSocket thread and close connections."""
        self._running = False

        # Clear subscriptions to stop watch loops
        self._subscriptions.clear()

        if self._loop and not self._loop.is_closed():
            # Cancel all pending tasks
            try:
                pending = asyncio.all_tasks(self._loop)
                for task in pending:
                    task.cancel()
            except Exception:
                pass

            # Stop the event loop
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                print("[WS] Warning: WebSocket thread did not stop cleanly")
            self._thread = None

    def is_connected(self) -> bool:
        """Check if WebSocket is connected.

        Returns:
            bool: True if connected.
        """
        return self._connected

    def _run_loop(self) -> None:
        """Run the asyncio event loop in a separate thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            # Attempt initial connection
            self._loop.run_until_complete(self._connect())
            # After successful connection, run forever
            self._loop.run_forever()
        except Exception as e:
            print(f"WebSocket initial connection failed: {e}")
            # Trigger reconnection mechanism
            if self._running:
                asyncio.run_coroutine_threadsafe(self._handle_reconnect(), self._loop)
                self._loop.run_forever()
        finally:
            # Cleanup - close exchange and event loop
            self._cleanup_resources()

    def _cleanup_resources(self) -> None:
        """Clean up asyncio resources properly."""
        if self._loop is None or self._loop.is_closed():
            return

        # Run cleanup in the event loop
        async def _cleanup():
            try:
                # Close the exchange connection
                if self.exchange:
                    await self.exchange.close()
                    self.exchange = None
            except Exception as e:
                print(f"[WS] Error closing exchange: {e}")

            # Close any open HTTP sessions
            try:
                # ccxt may have aiohttp session
                if hasattr(self.exchange, "session"):
                    await self.exchange.session.close()
            except Exception:
                pass

        # Run cleanup
        try:
            self._loop.run_until_complete(_cleanup())
        except Exception as e:
            print(f"[WS] Error during cleanup: {e}")

        # Close the event loop
        try:
            self._loop.close()
        except Exception:
            pass

    async def _connect(self) -> None:
        """Establish WebSocket connection."""
        try:
            exchange_class = getattr(ccxtpro, self.exchange_id)
            self.exchange = exchange_class(self.config)

            # Enable sandbox/demo mode if requested
            if self._sandbox:
                self.exchange.set_sandbox_mode(True)

            # Load markets — always use ccxt's own load_markets to build
            # proper internal indices (markets_by_id, etc.)
            # Pre-loaded markets from store are no longer manually injected
            # because ccxt uses list-based markets_by_id that manual copy breaks.
            try:
                await asyncio.wait_for(self.exchange.load_markets(), timeout=15.0)
                print(f"[WS] Markets loaded successfully ({len(self.exchange.markets or {})} markets)")
            except Exception as e:
                print(f"[WS] load_markets failed: {e}")
                # Fallback: try pre-loaded markets with ccxt's set_markets if available
                if self._preloaded_markets:
                    try:
                        self.exchange.set_markets(list(self._preloaded_markets.values()))
                        print(f"[WS] Using {len(self.exchange.markets)} pre-loaded markets from store")
                    except (AttributeError, TypeError):
                        # set_markets not available, manually set minimal markets
                        self.exchange.markets = self._preloaded_markets.copy()
                        self.exchange.markets_by_id = {}
                        print(f"[WS] Fallback: manually set {len(self.exchange.markets)} markets")
                else:
                    print("[WS] Will create market entries on demand")
                    if self.exchange.markets is None:
                        self.exchange.markets = {}
                    if not hasattr(self.exchange, "markets_by_id") or self.exchange.markets_by_id is None:
                        self.exchange.markets_by_id = {}

            self._connected = True
            self._reconnect_delay = 1.0  # Reset delay on successful connect
            logger.info(f"[WS] Connected to {self.exchange_id}")
        except Exception as e:
            print(f"WebSocket connection error: {e}")
            self._connected = False
            raise

    async def _load_market_for_symbol(self, symbol: str) -> None:
        """Load market info for a single trading pair on demand.

        Args:
            symbol: Trading pair symbol such as 'BTC/USDT' or 'BTC/USDT:USDT'.

        Note:
            WebSocket watch methods require market metadata.
            We create a minimal market entry to avoid blocking HTTP requests.
            If the exchange has special requirements, the watch methods will
            fetch additional data as needed.
        """
        # Check if already loaded
        if self.exchange.markets and symbol in self.exchange.markets:
            return

        # For OKX, create minimal market entry to avoid HTTP requests
        if self.exchange_id.lower() == "okx":
            if self.exchange.markets is None:
                self.exchange.markets = {}
            if not hasattr(self.exchange, "markets_by_id") or self.exchange.markets_by_id is None:
                self.exchange.markets_by_id = {}

            # Parse symbol
            if "/" in symbol:
                base = symbol.split("/")[0]  # e.g., BTC
                rest = symbol.split("/")[1]  # e.g., USDT:USDT
                if ":" in rest:
                    quote = rest.split(":")[0]  # e.g., USDT
                    settle = rest.split(":")[1]  # e.g., USDT
                else:
                    quote = rest
                    settle = rest
            else:
                base = "BTC"
                quote = "USDT"
                settle = "USDT"

            # OKX instId format: BTC-USDT-SWAP (perpetual swap)
            inst_id = f"{base}-{quote}-SWAP"

            # Create complete market entry (CCXT requires multiple fields)
            market = {
                "id": inst_id,  # OKX uses inst_id as market id
                "symbol": symbol,
                "base": base,
                "quote": quote,
                "settle": settle,
                "baseId": base,
                "quoteId": quote,
                "settleId": settle,
                "type": "swap",
                "spot": False,
                "margin": False,
                "swap": True,
                "future": False,
                "option": False,
                "contract": True,
                "linear": True,
                "inverse": False,
                "contractSize": 1,
                "active": True,
                "info": {
                    "instId": inst_id,
                    "instType": "SWAP",
                    "ctType": "linear",
                    "baseCcy": base,
                    "quoteCcy": quote,
                    "settleCcy": settle,
                },
            }

            # Register to markets and markets_by_id
            self.exchange.markets[symbol] = market
            self.exchange.markets_by_id[inst_id] = market
            return

        # For other exchanges, try quick load (with timeout)
        try:
            await asyncio.wait_for(self.exchange.load_markets(), timeout=3.0)
        except Exception:
            # Continue even if load fails, WebSocket may still work
            pass

    def subscribe_ticker(self, symbol: str, callback: Callable) -> None:
        """Subscribe to real-time ticker updates.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT').
            callback: Function to call with ticker data.
        """
        key = f"ticker:{symbol}"
        self._subscriptions[key] = callback

        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(self._watch_ticker(symbol, callback), self._loop)

    def subscribe_ohlcv(self, symbol: str, timeframe: str, callback: Callable) -> None:
        """Subscribe to real-time OHLCV (candlestick) updates.

        Args:
            symbol: Trading pair symbol.
            timeframe: Timeframe string (e.g., '1m', '1h').
            callback: Function to call with OHLCV data.
        """
        key = f"ohlcv:{symbol}:{timeframe}"
        self._subscriptions[key] = callback

        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(self._watch_ohlcv(symbol, timeframe, callback), self._loop)

    def subscribe_trades(self, symbol: str, callback: Callable) -> None:
        """Subscribe to real-time trade updates.

        Args:
            symbol: Trading pair symbol.
            callback: Function to call with trade data.
        """
        key = f"trades:{symbol}"
        self._subscriptions[key] = callback

        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(self._watch_trades(symbol, callback), self._loop)

    def subscribe_orderbook(self, symbol: str, callback: Callable, limit: int = 20) -> None:
        """Subscribe to real-time order book updates.

        Args:
            symbol: Trading pair symbol.
            callback: Function to call with order book data.
            limit: Depth of order book to fetch.
        """
        key = f"orderbook:{symbol}"
        self._subscriptions[key] = callback

        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(self._watch_orderbook(symbol, callback, limit), self._loop)

    def subscribe_my_trades(self, symbol: str, callback: Callable) -> None:
        """Subscribe to user's trade updates (requires auth).

        Args:
            symbol: Trading pair symbol.
            callback: Function to call with trade data.
        """
        key = f"mytrades:{symbol}"
        self._subscriptions[key] = callback

        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(self._watch_my_trades(symbol, callback), self._loop)

    def subscribe_funding_rate(self, symbol: str, callback: Callable) -> None:
        """Subscribe to funding rate updates for perpetual futures.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT').
            callback: Function to call with funding rate data.

        Example:
            >>> def on_funding(data):
            ...     print(f"Rate: {data.get('rate')}, Next: {data.get('nextFundingTime')}")
            >>> manager.subscribe_funding_rate('BTC/USDT:USDT', on_funding)
        """
        key = f"funding_rate:{symbol}"
        self._subscriptions[key] = callback

        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(self._watch_funding_rate(symbol, callback), self._loop)

    def subscribe_mark_price(self, symbol: str, callback: Callable) -> None:
        """Subscribe to mark price updates for perpetual futures.

        Args:
            symbol: Trading pair symbol.
            callback: Function to call with mark price data.
        """
        key = f"mark_price:{symbol}"
        self._subscriptions[key] = callback

        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(self._watch_mark_price(symbol, callback), self._loop)

    def unsubscribe(self, channel: str) -> None:
        """Unsubscribe from a channel.

        Args:
            channel: Channel key to unsubscribe from.
        """
        self._subscriptions.pop(channel, None)

    async def _watch_ticker(self, symbol: str, callback: Callable) -> None:
        """Watch ticker updates."""
        while self._running and f"ticker:{symbol}" in self._subscriptions:
            try:
                ticker = await self.exchange.watch_ticker(symbol)
                callback(ticker)
            except Exception as e:
                print(f"Ticker watch error for {symbol}: {e}")
                await self._handle_reconnect()

    async def _watch_ohlcv(self, symbol: str, timeframe: str, callback: Callable) -> None:
        """Watch OHLCV updates."""
        key = f"ohlcv:{symbol}:{timeframe}"
        consecutive_errors = 0
        max_consecutive_errors = 5

        # Load markets before entering watch loop (OKX requires this)
        if self.exchange_id.lower() == "okx":
            try:
                await self._load_market_for_symbol(symbol)
            except Exception as e:
                if self._running:
                    print(f"[WS] Warning: Could not load markets for {symbol}: {e}")

        while self._running and key in self._subscriptions:
            try:
                ohlcv = await self.exchange.watch_ohlcv(symbol, timeframe)
                if ohlcv:
                    callback(ohlcv)
                consecutive_errors = 0  # Reset error counter on success
            except asyncio.CancelledError:
                # Task was cancelled, exit gracefully
                break
            except Exception as e:
                consecutive_errors += 1
                print(f"OHLCV watch error for {symbol} (error {consecutive_errors}/{max_consecutive_errors}): {e}")

                if consecutive_errors >= max_consecutive_errors:
                    print("Too many consecutive errors, attempting reconnect...")
                    consecutive_errors = 0
                    await self._handle_reconnect()
                else:
                    # Brief delay before retry
                    await asyncio.sleep(1)

    async def _watch_trades(self, symbol: str, callback: Callable) -> None:
        """Watch trade updates."""
        while self._running and f"trades:{symbol}" in self._subscriptions:
            try:
                trades = await self.exchange.watch_trades(symbol)
                callback(trades)
            except Exception as e:
                print(f"Trades watch error for {symbol}: {e}")
                await self._handle_reconnect()

    async def _watch_orderbook(self, symbol: str, callback: Callable, limit: int) -> None:
        """Watch order book updates."""
        while self._running and f"orderbook:{symbol}" in self._subscriptions:
            try:
                orderbook = await self.exchange.watch_order_book(symbol, limit)
                callback(orderbook)
            except Exception as e:
                print(f"Orderbook watch error for {symbol}: {e}")
                await self._handle_reconnect()

    async def _watch_my_trades(self, symbol: str, callback: Callable) -> None:
        """Watch user's trade updates."""
        while self._running and f"mytrades:{symbol}" in self._subscriptions:
            try:
                trades = await self.exchange.watch_my_trades(symbol)
                callback(trades)
            except Exception as e:
                print(f"My trades watch error for {symbol}: {e}")
                await self._handle_reconnect()

    async def _watch_funding_rate(self, symbol: str, callback: Callable) -> None:
        """Watch funding rate updates for perpetual futures.

        CCXT Pro supports watch_funding_rate for:
        - Binance (via watch_mark_price)
        - OKX (native funding rate channel)
        - Bybit (via ticker info)
        - and more...
        """
        key = f"funding_rate:{symbol}"
        consecutive_errors = 0
        max_consecutive_errors = 5

        # Load markets before entering watch loop (OKX requires this)
        if self.exchange_id.lower() == "okx":
            try:
                await self._load_market_for_symbol(symbol)
            except Exception as e:
                if self._running:
                    print(f"[WS] Warning: Could not load markets for {symbol}: {e}")

        while self._running and key in self._subscriptions:
            try:
                # Try native watch_funding_rate first (ccxt.pro 4.x+)
                if hasattr(self.exchange, "watch_funding_rate"):
                    funding_data = await self.exchange.watch_funding_rate(symbol)
                else:
                    # Fallback to watch_mark_price which contains funding rate info
                    funding_data = await self.exchange.watch_mark_price(symbol)

                if funding_data:
                    callback(funding_data)
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                print(
                    f"Funding rate watch error for {symbol} (error {consecutive_errors}/{max_consecutive_errors}): {e}"
                )

                if consecutive_errors >= max_consecutive_errors:
                    print("Too many consecutive errors, attempting reconnect...")
                    consecutive_errors = 0
                    await self._handle_reconnect()
                else:
                    await asyncio.sleep(1)

    async def _watch_mark_price(self, symbol: str, callback: Callable) -> None:
        """Watch mark price updates (includes funding rate for some exchanges)."""
        key = f"mark_price:{symbol}"
        consecutive_errors = 0
        max_consecutive_errors = 5

        # Load markets before entering watch loop (OKX requires this)
        if self.exchange_id.lower() == "okx":
            try:
                await self._load_market_for_symbol(symbol)
            except Exception as e:
                if self._running:
                    print(f"[WS] Warning: Could not load markets for {symbol}: {e}")

        while self._running and key in self._subscriptions:
            try:
                mark_price_data = await self.exchange.watch_mark_price(symbol)
                if mark_price_data:
                    callback(mark_price_data)
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                print(f"Mark price watch error for {symbol} (error {consecutive_errors}/{max_consecutive_errors}): {e}")

                if consecutive_errors >= max_consecutive_errors:
                    consecutive_errors = 0
                    await self._handle_reconnect()
                else:
                    await asyncio.sleep(1)

    async def _handle_reconnect(self) -> None:
        """Handle reconnection with exponential backoff.

        Only one reconnection attempt at a time - other watch loops wait.
        """
        # Prevent multiple simultaneous reconnection attempts
        if self._reconnecting:
            # Wait for ongoing reconnection to complete
            while self._reconnecting and self._running:
                await asyncio.sleep(0.5)
            return

        self._reconnecting = True
        self._connected = False
        delay = self._reconnect_delay

        try:
            while self._running:
                try:
                    logger.info(f"[WS] Reconnecting in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    await self._connect()

                    # Restore subscriptions
                    await self._restore_subscriptions()
                    # C14: Notify reconnect callbacks (e.g. for REST backfill)
                    for cb in self._reconnect_callbacks:
                        try:
                            cb()
                        except Exception as cb_err:
                            logger.error(f"[WS] Reconnect callback error: {cb_err}")
                    break

                except Exception as e:
                    logger.warning(f"[WS] Reconnect failed: {e}")
                    delay = min(delay * 2, self._max_reconnect_delay)
        finally:
            self._reconnecting = False

    async def _restore_subscriptions(self) -> None:
        """Restore all subscriptions after reconnect."""
        for key, callback in list(self._subscriptions.items()):
            parts = key.split(":")
            channel_type = parts[0]

            if channel_type == "ticker":
                asyncio.create_task(self._watch_ticker(parts[1], callback))
            elif channel_type == "ohlcv":
                asyncio.create_task(self._watch_ohlcv(parts[1], parts[2], callback))
            elif channel_type == "trades":
                asyncio.create_task(self._watch_trades(parts[1], callback))
            elif channel_type == "orderbook":
                asyncio.create_task(self._watch_orderbook(parts[1], callback, 20))
            elif channel_type == "mytrades":
                asyncio.create_task(self._watch_my_trades(parts[1], callback))
            elif channel_type == "funding_rate":
                asyncio.create_task(self._watch_funding_rate(parts[1], callback))
            elif channel_type == "mark_price":
                asyncio.create_task(self._watch_mark_price(parts[1], callback))
