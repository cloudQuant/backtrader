#!/usr/bin/env python
"""Threading Module - Multi-threaded data and order management.

This module provides threaded managers for non-blocking data updates
and order status checking.

Classes:
    DataUpdate: Data class for update messages.
    ThreadedDataManager: Multi-threaded data fetching.
    ThreadedOrderManager: Multi-threaded order status checking.

Example:
    >>> manager = ThreadedDataManager(store)
    >>> manager.add_symbol('BTC/USDT', '1h')
    >>> manager.start()
    >>> update = manager.get_update(timeout=1.0)
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from backtrader.utils.py3 import queue


@dataclass
class DataUpdate:
    """Data update message from threaded manager.
    
    Attributes:
        symbol: Trading pair symbol (e.g., 'BTC/USDT').
        timestamp: Unix timestamp in milliseconds.
        data: The actual data (OHLCV list, ticker dict, etc.).
        data_type: Type of data ('ohlcv', 'ticker', 'trade', 'orderbook').
    """
    symbol: str
    timestamp: int
    data: Any
    data_type: str


@dataclass
class OrderUpdate:
    """Order status update message.
    
    Attributes:
        order_id: Exchange order ID.
        status: New order status.
        filled: Filled quantity.
        remaining: Remaining quantity.
        average: Average fill price.
        timestamp: Update timestamp.
    """
    order_id: str
    status: str
    filled: float
    remaining: float
    average: float
    timestamp: int


class ThreadedDataManager:
    """Multi-threaded data manager for non-blocking updates.
    
    Fetches market data in a background thread to avoid blocking
    the main strategy loop.
    
    Attributes:
        store: CCXTStore instance for API access.
        update_interval: Seconds between data fetches.
    """
    
    def __init__(self, store, update_interval: float = 1.0):
        """Initialize the threaded data manager.
        
        Args:
            store: CCXTStore instance.
            update_interval: Seconds between update cycles.
        """
        self.store = store
        self.update_interval = update_interval
        self._queue = queue.Queue(maxsize=1000)
        self._thread = None
        self._running = False
        self._symbols: List[str] = []
        self._timeframes: Dict[str, str] = {}
        self._lock = threading.Lock()
    
    def add_symbol(self, symbol: str, timeframe: str) -> None:
        """Add a symbol to monitor.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT').
            timeframe: Timeframe string (e.g., '1h', '5m').
        """
        with self._lock:
            if symbol not in self._symbols:
                self._symbols.append(symbol)
            self._timeframes[symbol] = timeframe
    
    def remove_symbol(self, symbol: str) -> None:
        """Remove a symbol from monitoring.
        
        Args:
            symbol: Symbol to remove.
        """
        with self._lock:
            if symbol in self._symbols:
                self._symbols.remove(symbol)
            self._timeframes.pop(symbol, None)
    
    def start(self) -> None:
        """Start the data fetching thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop the data fetching thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
    
    def get_update(self, timeout: Optional[float] = None) -> Optional[DataUpdate]:
        """Get next data update from queue.
        
        Args:
            timeout: Maximum seconds to wait (None for non-blocking).
            
        Returns:
            DataUpdate or None if no update available.
        """
        try:
            return self._queue.get(block=timeout is not None, timeout=timeout)
        except queue.Empty:
            return None
    
    def is_running(self) -> bool:
        """Check if the manager is running.
        
        Returns:
            bool: True if running.
        """
        return self._running
    
    def _update_loop(self) -> None:
        """Main update loop running in background thread."""
        while self._running:
            try:
                with self._lock:
                    symbols = list(self._symbols)
                    timeframes = dict(self._timeframes)
                
                for symbol in symbols:
                    if not self._running:
                        break
                    
                    timeframe = timeframes.get(symbol, '1h')
                    
                    try:
                        ohlcv = self.store.fetch_ohlcv(
                            symbol,
                            timeframe=timeframe,
                            since=None,
                            limit=1
                        )
                        
                        if ohlcv and len(ohlcv) > 0:
                            update = DataUpdate(
                                symbol=symbol,
                                timestamp=ohlcv[-1][0],
                                data=ohlcv[-1],
                                data_type='ohlcv'
                            )
                            self._put_update(update)
                            
                    except Exception as e:
                        print(f"Data update error for {symbol}: {e}")
                
                time.sleep(self.update_interval)
                
            except Exception as e:
                print(f"Data manager error: {e}")
                time.sleep(self.update_interval)
    
    def _put_update(self, update: DataUpdate) -> None:
        """Put an update into the queue, dropping old if full."""
        try:
            self._queue.put_nowait(update)
        except queue.Full:
            # Drop oldest and add new
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(update)
            except queue.Empty:
                pass


class ThreadedOrderManager:
    """Multi-threaded order status manager.
    
    Checks order status in a background thread to avoid blocking
    the main strategy loop.
    
    Attributes:
        store: CCXTStore instance for API access.
        check_interval: Seconds between status checks.
    """
    
    def __init__(self, store, check_interval: float = 3.0):
        """Initialize the threaded order manager.
        
        Args:
            store: CCXTStore instance.
            check_interval: Seconds between order status checks.
        """
        self.store = store
        self.check_interval = check_interval
        self._queue = queue.Queue(maxsize=1000)
        self._thread = None
        self._running = False
        self._orders: Dict[str, dict] = {}  # order_id -> order_info
        self._lock = threading.Lock()
    
    def add_order(self, order_id: str, symbol: str, **order_info) -> None:
        """Add an order to monitor.
        
        Args:
            order_id: Exchange order ID.
            symbol: Trading pair symbol.
            **order_info: Additional order information.
        """
        with self._lock:
            self._orders[order_id] = {
                'symbol': symbol,
                'last_status': None,
                'last_filled': 0.0,
                **order_info
            }
    
    def remove_order(self, order_id: str) -> None:
        """Remove an order from monitoring.
        
        Args:
            order_id: Order ID to remove.
        """
        with self._lock:
            self._orders.pop(order_id, None)
    
    def start(self) -> None:
        """Start the order checking thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._check_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop the order checking thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
    
    def get_updates(self) -> List[OrderUpdate]:
        """Get all pending order updates.
        
        Returns:
            List of OrderUpdate objects.
        """
        updates = []
        while True:
            try:
                updates.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return updates
    
    def is_running(self) -> bool:
        """Check if the manager is running."""
        return self._running
    
    def _check_loop(self) -> None:
        """Main order checking loop."""
        while self._running:
            try:
                with self._lock:
                    orders = dict(self._orders)
                
                for order_id, order_info in orders.items():
                    if not self._running:
                        break
                    
                    try:
                        # Fetch order status from exchange
                        order = self.store.fetch_order(order_id, order_info['symbol'])
                        if order is None:
                            continue
                        
                        # Check for status change
                        status = order.get('status')
                        filled = float(order.get('filled', 0))
                        
                        if (status != order_info.get('last_status') or 
                            filled != order_info.get('last_filled', 0)):
                            
                            update = OrderUpdate(
                                order_id=order_id,
                                status=status,
                                filled=filled,
                                remaining=float(order.get('remaining', 0)),
                                average=float(order.get('average', 0) or 0),
                                timestamp=int(datetime.now().timestamp() * 1000)
                            )
                            
                            self._queue.put_nowait(update)
                            
                            # Update cached status
                            with self._lock:
                                if order_id in self._orders:
                                    self._orders[order_id]['last_status'] = status
                                    self._orders[order_id]['last_filled'] = filled
                            
                            # Remove completed orders
                            if status in ('closed', 'canceled', 'expired', 'rejected'):
                                self.remove_order(order_id)
                                
                    except Exception as e:
                        print(f"Order check error for {order_id}: {e}")
                
                time.sleep(self.check_interval)
                
            except Exception as e:
                print(f"Order manager error: {e}")
                time.sleep(self.check_interval)
