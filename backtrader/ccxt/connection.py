#!/usr/bin/env python
"""Connection Management Module - Auto-reconnect and recovery.

This module provides connection management with automatic reconnection
and data recovery after disconnection.

Classes:
    ConnectionManager: Manages connection state and recovery.

Example:
    >>> manager = ConnectionManager(store)
    >>> manager.on_disconnect(lambda: print("Disconnected"))
    >>> manager.on_reconnect(lambda: print("Reconnected"))
"""

import time
import threading
from typing import Callable, List, Optional
from datetime import datetime


class ConnectionManager:
    """Connection manager with auto-reconnect capability.
    
    Monitors connection health, handles disconnections, and manages
    automatic reconnection with data backfill.
    
    Attributes:
        store: CCXTStore instance for API access.
        is_connected: Current connection status.
    """
    
    def __init__(self, store, health_check_interval: float = 30.0):
        """Initialize the connection manager.
        
        Args:
            store: CCXTStore instance.
            health_check_interval: Seconds between health checks.
        """
        self.store = store
        self.health_check_interval = health_check_interval
        self._connected = True
        self._disconnect_callbacks: List[Callable] = []
        self._reconnect_callbacks: List[Callable] = []
        self._thread = None
        self._running = False
        self._last_success_time = time.time()
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._lock = threading.Lock()
    
    def on_disconnect(self, callback: Callable) -> None:
        """Register a callback for disconnect events.
        
        Args:
            callback: Function to call on disconnect.
        """
        self._disconnect_callbacks.append(callback)
    
    def on_reconnect(self, callback: Callable) -> None:
        """Register a callback for reconnect events.
        
        Args:
            callback: Function to call on successful reconnect.
        """
        self._reconnect_callbacks.append(callback)
    
    def is_connected(self) -> bool:
        """Check if currently connected.
        
        Returns:
            bool: True if connected.
        """
        with self._lock:
            return self._connected
    
    def start_monitoring(self) -> None:
        """Start the connection health monitoring thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
    
    def stop_monitoring(self) -> None:
        """Stop the connection monitoring thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
    
    def reconnect(self) -> bool:
        """Attempt to reconnect.
        
        Returns:
            bool: True if reconnection successful.
        """
        delay = self._reconnect_delay
        
        while self._running:
            try:
                # Try a simple API call to test connection
                self.store.exchange.fetch_time()
                
                with self._lock:
                    self._connected = True
                    self._last_success_time = time.time()
                    self._reconnect_delay = 1.0  # Reset delay
                
                # Notify reconnect callbacks
                for callback in self._reconnect_callbacks:
                    try:
                        callback()
                    except Exception as e:
                        print(f"Reconnect callback error: {e}")
                
                return True
                
            except Exception as e:
                print(f"Reconnect attempt failed: {e}")
                time.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)
        
        return False
    
    def get_missed_data(
        self, 
        symbol: str, 
        timeframe: str,
        since: int,
        limit: int = 1000
    ) -> List:
        """Fetch data that was missed during disconnection.
        
        Args:
            symbol: Trading pair symbol.
            timeframe: Timeframe string.
            since: Unix timestamp (ms) to start from.
            limit: Maximum bars to fetch.
            
        Returns:
            List of OHLCV data.
        """
        try:
            return self.store.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=since,
                limit=limit
            )
        except Exception as e:
            print(f"Failed to fetch missed data: {e}")
            return []
    
    def mark_success(self) -> None:
        """Mark a successful API call (for external use)."""
        with self._lock:
            self._last_success_time = time.time()
            self._connected = True
    
    def mark_failure(self) -> None:
        """Mark a failed API call (for external use)."""
        with self._lock:
            # Don't immediately mark as disconnected
            # Wait for health check to confirm
            pass
    
    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                time.sleep(self.health_check_interval)
                
                if not self._running:
                    break
                
                # Check connection health
                try:
                    self.store.exchange.fetch_time()
                    self.mark_success()
                    
                except Exception as e:
                    print(f"Health check failed: {e}")
                    
                    was_connected = self._connected
                    with self._lock:
                        self._connected = False
                    
                    # Notify disconnect if state changed
                    if was_connected:
                        for callback in self._disconnect_callbacks:
                            try:
                                callback()
                            except Exception as cb_err:
                                print(f"Disconnect callback error: {cb_err}")
                    
                    # Attempt reconnection
                    self.reconnect()
                    
            except Exception as e:
                print(f"Connection monitor error: {e}")


class ConnectionState:
    """Connection state tracker with history.
    
    Tracks connection state changes and provides statistics.
    """
    
    def __init__(self, max_history: int = 100):
        """Initialize state tracker.
        
        Args:
            max_history: Maximum state changes to keep in history.
        """
        self.max_history = max_history
        self._history: List[dict] = []
        self._current_state = "connected"
        self._lock = threading.Lock()
    
    def update(self, state: str, reason: str = "") -> None:
        """Update connection state.
        
        Args:
            state: New state ('connected', 'disconnected', 'reconnecting').
            reason: Optional reason for state change.
        """
        with self._lock:
            entry = {
                'timestamp': datetime.now().isoformat(),
                'from_state': self._current_state,
                'to_state': state,
                'reason': reason
            }
            self._history.append(entry)
            
            # Trim history
            if len(self._history) > self.max_history:
                self._history = self._history[-self.max_history:]
            
            self._current_state = state
    
    @property
    def current(self) -> str:
        """Get current state."""
        with self._lock:
            return self._current_state
    
    @property
    def history(self) -> List[dict]:
        """Get state change history."""
        with self._lock:
            return list(self._history)
    
    def get_uptime_stats(self) -> dict:
        """Get connection uptime statistics.
        
        Returns:
            dict with uptime stats.
        """
        with self._lock:
            if not self._history:
                return {
                    'total_disconnects': 0,
                    'last_disconnect': None,
                    'avg_disconnect_duration': 0
                }
            
            disconnects = [h for h in self._history if h['to_state'] == 'disconnected']
            
            return {
                'total_disconnects': len(disconnects),
                'last_disconnect': disconnects[-1]['timestamp'] if disconnects else None,
                'history_size': len(self._history)
            }
