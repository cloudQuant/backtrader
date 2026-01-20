#!/usr/bin/env python
"""CCXT Enhanced Module - Advanced features for cryptocurrency trading.

This module provides enhanced functionality for CCXT-based trading including:
- WebSocket real-time data streaming
- Multi-threaded data and order management
- Rate limiting and retry mechanisms
- Bracket order support
- Exchange-specific configurations

Example:
    >>> from backtrader.ccxt import RateLimiter, ThreadedDataManager
    >>> limiter = RateLimiter(requests_per_minute=1200)
    >>> limiter.acquire()  # Wait if rate limit reached
"""

from .ratelimit import RateLimiter, retry_with_backoff
from .threading import ThreadedDataManager, ThreadedOrderManager, DataUpdate
from .config import ExchangeConfig
from .connection import ConnectionManager

# Optional WebSocket support (requires ccxt.pro)
try:
    from .websocket import CCXTWebSocketManager
except ImportError:
    CCXTWebSocketManager = None

# Bracket orders
from .orders import BracketOrderManager, BracketOrder, BracketState

__all__ = [
    'RateLimiter',
    'retry_with_backoff',
    'ThreadedDataManager',
    'ThreadedOrderManager',
    'DataUpdate',
    'ExchangeConfig',
    'ConnectionManager',
    'CCXTWebSocketManager',
    'BracketOrderManager',
    'BracketOrder',
    'BracketState',
]
