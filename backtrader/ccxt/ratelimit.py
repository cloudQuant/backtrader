#!/usr/bin/env python
"""Rate Limiting Module - API call frequency control.

This module provides intelligent rate limiting for API calls to avoid
hitting exchange rate limits.

Classes:
    RateLimiter: Manages API call frequency with automatic waiting.

Functions:
    retry_with_backoff: Decorator for exponential backoff retry logic.

Example:
    >>> limiter = RateLimiter(requests_per_minute=1200)
    >>> limiter.acquire()  # Blocks if rate limit reached
    >>> # Make API call here
"""

import time
import threading
from functools import wraps
from typing import Callable, Tuple, Type


class RateLimiter:
    """API rate limiter with automatic waiting.
    
    Tracks API call frequency and automatically waits when approaching
    the rate limit to avoid hitting exchange restrictions.
    
    Attributes:
        rpm: Requests per minute limit.
        request_times: List of recent request timestamps.
    """
    
    def __init__(self, requests_per_minute: int = 1200):
        """Initialize the rate limiter.
        
        Args:
            requests_per_minute: Maximum allowed requests per minute.
        """
        self.rpm = requests_per_minute
        self.request_times = []
        self._lock = threading.Lock()
    
    def acquire(self) -> None:
        """Acquire permission to make an API call.
        
        Blocks until it's safe to make an API call without hitting
        the rate limit. Thread-safe.
        """
        with self._lock:
            now = time.time()
            
            # Clear records older than 1 minute
            cutoff = now - 60
            self.request_times = [t for t in self.request_times if t > cutoff]
            
            # Check if we need to wait
            if len(self.request_times) >= self.rpm:
                wait_time = 60 - (now - self.request_times[0])
                if wait_time > 0:
                    time.sleep(wait_time)
                    now = time.time()
                    self.request_times = []
            
            # Record this request
            self.request_times.append(now)
    
    def get_wait_time(self) -> float:
        """Get recommended wait time before next call.
        
        Returns:
            float: Seconds to wait (0 if no wait needed).
        """
        with self._lock:
            now = time.time()
            cutoff = now - 60
            self.request_times = [t for t in self.request_times if t > cutoff]
            
            if len(self.request_times) >= self.rpm:
                return 60 - (now - self.request_times[0])
            return 0.0
    
    def reset(self) -> None:
        """Reset the rate limiter, clearing all recorded requests."""
        with self._lock:
            self.request_times = []
    
    @property
    def current_usage(self) -> int:
        """Get current number of requests in the time window.
        
        Returns:
            int: Number of requests made in the last minute.
        """
        with self._lock:
            now = time.time()
            cutoff = now - 60
            self.request_times = [t for t in self.request_times if t > cutoff]
            return len(self.request_times)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
) -> Callable:
    """Decorator for retry with exponential backoff.
    
    Automatically retries failed function calls with increasing delay
    between attempts.
    
    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds between retries.
        max_delay: Maximum delay in seconds between retries.
        exceptions: Tuple of exception types that trigger a retry.
        
    Returns:
        Callable: Decorated function with retry logic.
        
    Example:
        >>> @retry_with_backoff(max_retries=3, base_delay=1.0)
        ... def fetch_data():
        ...     # API call that might fail
        ...     pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries - 1:
                        raise
                    
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    print(f"Retry {attempt + 1}/{max_retries} after {delay:.2f}s: {e}")
                    time.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


class AdaptiveRateLimiter(RateLimiter):
    """Adaptive rate limiter that adjusts based on API responses.
    
    Extends RateLimiter to dynamically adjust limits based on
    response headers or error rates from the exchange.
    """
    
    def __init__(self, requests_per_minute: int = 1200, safety_factor: float = 0.9):
        """Initialize adaptive rate limiter.
        
        Args:
            requests_per_minute: Initial maximum requests per minute.
            safety_factor: Fraction of limit to use (0.9 = 90% of limit).
        """
        super().__init__(int(requests_per_minute * safety_factor))
        self._base_rpm = requests_per_minute
        self._safety_factor = safety_factor
        self._error_count = 0
        self._success_count = 0
    
    def on_success(self) -> None:
        """Record a successful API call."""
        with self._lock:
            self._success_count += 1
            # Gradually increase limit after consecutive successes
            if self._success_count >= 100 and self.rpm < self._base_rpm * self._safety_factor:
                self.rpm = min(self.rpm + 10, int(self._base_rpm * self._safety_factor))
                self._success_count = 0
    
    def on_rate_limit_error(self) -> None:
        """Record a rate limit error, reducing the limit."""
        with self._lock:
            self._error_count += 1
            # Reduce limit on rate limit errors
            self.rpm = max(10, int(self.rpm * 0.8))
            self._success_count = 0
    
    def on_response_headers(self, headers: dict) -> None:
        """Update limits based on response headers.
        
        Args:
            headers: Response headers that may contain rate limit info.
        """
        # Common header patterns for rate limit info
        remaining = headers.get('X-RateLimit-Remaining') or headers.get('x-mbx-used-weight')
        limit = headers.get('X-RateLimit-Limit')
        
        if remaining is not None:
            try:
                remaining = int(remaining)
                if remaining < 10:
                    # Very close to limit, add extra delay
                    time.sleep(1.0)
            except (ValueError, TypeError):
                pass
