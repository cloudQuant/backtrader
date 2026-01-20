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
import threading
from typing import Callable, Dict, Optional, Any

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
    
    def __init__(self, exchange_id: str, config: dict):
        """Initialize the WebSocket manager.
        
        Args:
            exchange_id: Exchange ID (e.g., 'binance', 'okx').
            config: Exchange configuration with API keys, etc.
            
        Raises:
            ImportError: If ccxt.pro is not installed.
        """
        if not HAS_CCXT_PRO:
            raise ImportError(
                "ccxt.pro is required for WebSocket support. "
                "Install with: pip install ccxtpro"
            )
        
        self.exchange_id = exchange_id
        self.config = config
        self.exchange = None
        self._loop = None
        self._thread = None
        self._running = False
        self._subscriptions: Dict[str, Callable] = {}
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._connected = False
    
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
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5.0)
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
            self._loop.run_until_complete(self._connect())
            self._loop.run_forever()
        except Exception as e:
            print(f"WebSocket loop error: {e}")
        finally:
            # Cleanup
            if self.exchange:
                try:
                    self._loop.run_until_complete(self.exchange.close())
                except:
                    pass
            self._loop.close()
    
    async def _connect(self) -> None:
        """Establish WebSocket connection."""
        try:
            exchange_class = getattr(ccxtpro, self.exchange_id)
            self.exchange = exchange_class(self.config)
            await self.exchange.load_markets()
            self._connected = True
            self._reconnect_delay = 1.0  # Reset delay on successful connect
            print(f"WebSocket connected to {self.exchange_id}")
        except Exception as e:
            print(f"WebSocket connection error: {e}")
            self._connected = False
            raise
    
    def subscribe_ticker(self, symbol: str, callback: Callable) -> None:
        """Subscribe to real-time ticker updates.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT').
            callback: Function to call with ticker data.
        """
        key = f"ticker:{symbol}"
        self._subscriptions[key] = callback
        
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._watch_ticker(symbol, callback),
                self._loop
            )
    
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
            asyncio.run_coroutine_threadsafe(
                self._watch_ohlcv(symbol, timeframe, callback),
                self._loop
            )
    
    def subscribe_trades(self, symbol: str, callback: Callable) -> None:
        """Subscribe to real-time trade updates.
        
        Args:
            symbol: Trading pair symbol.
            callback: Function to call with trade data.
        """
        key = f"trades:{symbol}"
        self._subscriptions[key] = callback
        
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._watch_trades(symbol, callback),
                self._loop
            )
    
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
            asyncio.run_coroutine_threadsafe(
                self._watch_orderbook(symbol, callback, limit),
                self._loop
            )
    
    def subscribe_my_trades(self, symbol: str, callback: Callable) -> None:
        """Subscribe to user's trade updates (requires auth).
        
        Args:
            symbol: Trading pair symbol.
            callback: Function to call with trade data.
        """
        key = f"mytrades:{symbol}"
        self._subscriptions[key] = callback
        
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._watch_my_trades(symbol, callback),
                self._loop
            )
    
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
        while self._running and key in self._subscriptions:
            try:
                ohlcv = await self.exchange.watch_ohlcv(symbol, timeframe)
                callback(ohlcv)
            except Exception as e:
                print(f"OHLCV watch error for {symbol}: {e}")
                await self._handle_reconnect()
    
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
    
    async def _handle_reconnect(self) -> None:
        """Handle reconnection with exponential backoff."""
        self._connected = False
        delay = self._reconnect_delay
        
        while self._running:
            try:
                print(f"Reconnecting in {delay:.1f}s...")
                await asyncio.sleep(delay)
                await self._connect()
                
                # Restore subscriptions
                await self._restore_subscriptions()
                break
                
            except Exception as e:
                print(f"Reconnect failed: {e}")
                delay = min(delay * 2, self._max_reconnect_delay)
    
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
