#!/usr/bin/env python
"""Cache Optimization Tool for Backtrader Store System.

This module provides comprehensive caching mechanisms and optimization tools for
improving the performance of the Backtrader store system, particularly focusing
on singleton pattern implementations and method-level caching.

The module includes:
- LRUCache: Thread-safe Least Recently Used cache implementation
- MethodCache: Decorator for method-level caching with TTL support
- SingletonCache: Enhanced singleton pattern with performance tracking
- OptimizedParameterizedSingletonMixin: Optimized mixin for parameterized singletons
- CacheOptimizationTool: Comprehensive testing and benchmarking tool

Example usage:
    >>> from tools.cache_optimization_tool import CacheOptimizationTool
    >>> optimizer = CacheOptimizationTool()
    >>> results = optimizer.run_comprehensive_optimization()
    >>> optimizer.save_optimization_report()
"""

import functools
import gc
import sys
import threading
import time
import weakref
from collections import OrderedDict, defaultdict
from typing import Any, Callable, Dict, Optional, Tuple
from unittest.mock import Mock, patch

# Mock dependencies
sys.modules["oandapy"] = Mock()
sys.modules["ccxt"] = Mock()
sys.modules["ctpbee"] = Mock()
sys.modules["ctpbee.api"] = Mock()
sys.modules["ctpbee.constant"] = Mock()
sys.modules["ctpbee.helpers"] = Mock()

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.stores.ibstore import IBStore


class LRUCache:
    """Thread-safe Least Recently Used (LRU) cache implementation.

    This cache automatically evicts the least recently used items when the
    maximum size is reached. It uses OrderedDict for O(1) access and eviction,
    and threading.RLock for thread safety.

    Attributes:
        maxsize: Maximum number of items the cache can hold.
        cache: OrderedDict storing cache entries.
        lock: Threading lock for thread-safe operations.

    Example:
        >>> cache = LRUCache(maxsize=10)
        >>> cache.put("key1", "value1")
        >>> value = cache.get("key1")
        >>> print(value)  # "value1"
    """

    def __init__(self, maxsize: int = 128):
        """Initialize the LRU cache.

        Args:
            maxsize: Maximum number of items to store in the cache. Defaults to 128.
        """
        self.maxsize = maxsize
        self.cache = OrderedDict()
        self.lock = threading.RLock()

    def get(self, key):
        """Get item from cache and mark as recently used.

        If the key exists in the cache, it is moved to the end of the OrderedDict
        to mark it as most recently used.

        Args:
            key: The cache key to retrieve.

        Returns:
            The cached value if found, None otherwise.
        """
        with self.lock:
            if key in self.cache:
                # Move to end (most recently used)
                value = self.cache.pop(key)
                self.cache[key] = value
                return value
            return None

    def put(self, key, value):
        """Put item in cache, evicting LRU item if necessary.

        If the key already exists, it is updated and moved to the end.
        If the cache is full, the least recently used item is evicted.

        Args:
            key: The cache key to store.
            value: The value to cache.
        """
        with self.lock:
            if key in self.cache:
                # Update existing
                self.cache.pop(key)
            elif len(self.cache) >= self.maxsize:
                # Remove least recently used
                self.cache.popitem(last=False)
            self.cache[key] = value

    def clear(self):
        """Clear all items from the cache."""
        with self.lock:
            self.cache.clear()

    def info(self):
        """Get cache statistics and utilization information.

        Returns:
            A dictionary containing cache statistics with keys:
            - size: Current number of items in cache
            - maxsize: Maximum cache capacity
            - utilization: Ratio of size to maxsize (0.0 to 1.0)
        """
        with self.lock:
            return {
                "size": len(self.cache),
                "maxsize": self.maxsize,
                "utilization": len(self.cache) / self.maxsize if self.maxsize > 0 else 0,
            }


class MethodCache:
    """Method-level caching decorator with LRU eviction and TTL support.

    This decorator class provides caching for method calls with configurable
    maximum size and time-to-live (TTL) for cache entries. It tracks cache
    hits/misses and provides statistics for performance analysis.

    Attributes:
        maxsize: Maximum number of cached entries.
        ttl: Time-to-live in seconds for cache entries (None for no expiration).
        cache: LRUCache instance for storing cached values.
        timestamps: Dictionary tracking when entries were cached (for TTL).
        hits: Number of cache hits.
        misses: Number of cache misses.
        lock: Threading lock for thread-safe operations.

    Example:
        >>> @MethodCache(maxsize=64, ttl=60.0)
        >>> def expensive_function(x, y):
        ...     return x + y
        >>> result = expensive_function(1, 2)  # Computed
        >>> result = expensive_function(1, 2)  # Cached
        >>> print(expensive_function.cache_info())
    """

    def __init__(self, maxsize: int = 128, ttl: Optional[float] = None):
        """Initialize the method cache decorator.

        Args:
            maxsize: Maximum number of entries to cache. Defaults to 128.
            ttl: Time-to-live in seconds for cache entries. None means no expiration.
                Defaults to None.
        """
        self.maxsize = maxsize
        self.ttl = ttl
        self.cache = LRUCache(maxsize)
        self.timestamps = {} if ttl else None
        self.hits = 0
        self.misses = 0
        self.lock = threading.RLock()

    def __call__(self, func):
        """Decorator implementation for caching method calls.

        Args:
            func: The function to decorate with caching.

        Returns:
            The wrapped function with caching capabilities. The wrapper has
            additional attributes: cache_info() and cache_clear().
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key
            key = self._make_key(func, args, kwargs)

            with self.lock:
                # Check if cached and valid
                cached_value = self.cache.get(key)
                if cached_value is not None:
                    if self.ttl is None or self._is_valid(key):
                        self.hits += 1
                        return cached_value

                # Cache miss - compute value
                self.misses += 1
                result = func(*args, **kwargs)

                # Store in cache
                self.cache.put(key, result)
                if self.timestamps is not None:
                    self.timestamps[key] = time.time()

                return result

        wrapper.cache_info = self.cache_info
        wrapper.cache_clear = self.cache_clear
        return wrapper

    def _make_key(self, func, args, kwargs):
        """Create cache key from function arguments.

        Args:
            func: The function being called.
            args: Positional arguments passed to the function.
            kwargs: Keyword arguments passed to the function.

        Returns:
            A tuple representing the cache key.
        """
        # Simple key generation - can be improved for complex objects
        key_parts = [func.__name__]
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return tuple(key_parts)

    def _is_valid(self, key):
        """Check if cached item is still valid based on TTL.

        Args:
            key: The cache key to validate.

        Returns:
            True if the cached item is still valid (not expired), False otherwise.
        """
        if self.timestamps is None:
            return True
        timestamp = self.timestamps.get(key)
        if timestamp is None:
            return False
        return (time.time() - timestamp) <= self.ttl

    def cache_info(self):
        """Get cache statistics including hits, misses, and hit rate.

        Returns:
            A dictionary containing:
            - hits: Number of cache hits
            - misses: Number of cache misses
            - hit_rate: Ratio of hits to total calls (0.0 to 1.0)
            - cache_size: Current number of cached entries
            - max_size: Maximum cache capacity
        """
        total_calls = self.hits + self.misses
        hit_rate = self.hits / total_calls if total_calls > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": hit_rate,
            "cache_size": self.cache.info()["size"],
            "max_size": self.maxsize,
        }

    def cache_clear(self):
        """Clear all cached entries and reset statistics."""
        with self.lock:
            self.cache.clear()
            if self.timestamps:
                self.timestamps.clear()
            self.hits = 0
            self.misses = 0


class SingletonCache:
    """Enhanced singleton cache with performance optimizations and tracking.

    This cache manages singleton instances with thread-safe double-checked locking
    for optimal performance. It tracks access patterns and creation times for
    performance analysis.

    Attributes:
        _instances: Dictionary mapping cache keys to singleton instances.
        _lock: Threading lock for thread-safe instance creation.
        _access_count: Dictionary tracking access counts per instance.
        _creation_times: Dictionary tracking instance creation times.

    Example:
        >>> cache = SingletonCache()
        >>> instance = cache.get_instance(MyClass)
        >>> stats = cache.get_stats()
        >>> print(stats['instance_count'])
    """

    def __init__(self):
        """Initialize the singleton cache."""
        self._instances = {}
        self._lock = threading.RLock()
        self._access_count = defaultdict(int)
        self._creation_times = {}

    def get_instance(self, cls, key=None):
        """Get singleton instance with optimized fast-path access.

        Uses double-checked locking for optimal performance: first checks without
        a lock for existing instances (fast path), then uses lock for creation
        (slow path).

        Args:
            cls: The class to instantiate.
            key: Optional key for parameterized singletons. Defaults to None.

        Returns:
            The singleton instance, creating it if necessary.
        """
        cache_key = (cls, key) if key else (cls,)

        # Fast path for existing instances (no lock needed)
        if cache_key in self._instances:
            self._access_count[cache_key] += 1
            return self._instances[cache_key]

        # Slow path for new instances (need lock)
        with self._lock:
            # Double-check pattern
            if cache_key in self._instances:
                self._access_count[cache_key] += 1
                return self._instances[cache_key]

            # Create new instance
            start_time = time.perf_counter()
            instance = cls()
            creation_time = time.perf_counter() - start_time

            self._instances[cache_key] = instance
            self._creation_times[cache_key] = creation_time
            self._access_count[cache_key] = 1

            return instance

    def reset_instance(self, cls, key=None):
        """Reset specific singleton instance from cache.

        Args:
            cls: The class whose instance should be reset.
            key: Optional key for parameterized singletons. Defaults to None.
        """
        cache_key = (cls, key) if key else (cls,)
        with self._lock:
            self._instances.pop(cache_key, None)
            self._access_count.pop(cache_key, None)
            self._creation_times.pop(cache_key, None)

    def get_stats(self):
        """Get cache statistics including instance counts and access patterns.

        Returns:
            A dictionary containing:
            - instance_count: Number of cached instances
            - total_accesses: Total number of accesses across all instances
            - access_distribution: Dictionary of access counts per instance
            - creation_times: Dictionary of creation times per instance
            - avg_creation_time: Average time to create instances
        """
        with self._lock:
            return {
                "instance_count": len(self._instances),
                "total_accesses": sum(self._access_count.values()),
                "access_distribution": dict(self._access_count),
                "creation_times": dict(self._creation_times),
                "avg_creation_time": (
                    sum(self._creation_times.values()) / len(self._creation_times)
                    if self._creation_times
                    else 0
                ),
            }


class OptimizedParameterizedSingletonMixin:
    """Optimized version of ParameterizedSingletonMixin with enhanced caching.

    This mixin provides a singleton pattern for classes that need parameterized
    instances based on constructor arguments. It uses the SingletonCache for
    efficient instance management and performance tracking.

    Attributes:
        _cache: Shared SingletonCache instance across all subclasses.

    Example:
        >>> class MyClass(OptimizedParameterizedSingletonMixin):
        ...     pass
        >>> instance1 = MyClass(param1="value1")
        >>> instance2 = MyClass(param1="value1")
        >>> assert instance1 is instance2  # Same instance
    """

    _cache = SingletonCache()

    def __new__(cls, *args, **kwargs):
        """Create or return cached singleton instance.

        Args:
            *args: Positional arguments passed to class constructor.
            **kwargs: Keyword arguments passed to class constructor.

        Returns:
            The singleton instance, creating it if necessary with the given parameters.
        """
        # Generate cache key from parameters
        cache_key = cls._generate_cache_key(args, kwargs)
        return cls._cache.get_instance(cls, cache_key)

    @classmethod
    def _generate_cache_key(cls, args, kwargs):
        """Generate cache key from constructor parameters.

        Args:
            args: Positional arguments from constructor.
            kwargs: Keyword arguments from constructor.

        Returns:
            A tuple representing the cache key, or None for default instances.
        """
        # Simple implementation - can be enhanced for complex parameters
        key_parts = []
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return tuple(key_parts) if key_parts else None

    @classmethod
    def _reset_instance(cls, *args, **kwargs):
        """Reset specific singleton instance for testing purposes.

        This allows clearing specific parameterized instances from the cache,
        primarily useful for testing scenarios.

        Args:
            *args: Positional arguments matching the instance to reset.
            **kwargs: Keyword arguments matching the instance to reset.
        """
        cache_key = cls._generate_cache_key(args, kwargs)
        cls._cache.reset_instance(cls, cache_key)

    @classmethod
    def get_cache_stats(cls):
        """Get singleton cache statistics for this class.

        Returns:
            A dictionary containing cache statistics from the underlying SingletonCache.
        """
        return cls._cache.get_stats()


class CacheOptimizationTool:
    """Tool for implementing and testing cache optimizations in the store system.

    This comprehensive tool provides methods to test, implement, and benchmark various
    caching strategies including method-level caching, singleton pattern optimization,
    and memory optimization using weak references.

    Attributes:
        test_results: Dictionary storing baseline performance test results.
        optimization_results: Dictionary storing optimization benchmark results.

    Example:
        >>> optimizer = CacheOptimizationTool()
        >>> results = optimizer.run_comprehensive_optimization()
        >>> optimizer.save_optimization_report("my_report.json")
    """

    def __init__(self):
        """Initialize the cache optimization tool."""
        self.test_results = {}
        self.optimization_results = {}

    def test_original_performance(self):
        """Test performance of original singleton implementation.

        Benchmarks the first creation time and subsequent access times for the
        original IBStore singleton implementation. Results are stored in
        test_results["original"].

        The test uses mocking to avoid actual network connections and measures:
        - Average first creation time across 10 iterations
        - Average subsequent access time across 1000 iterations
        """
        print("Testing original singleton performance...")

        # Reset environment
        if hasattr(IBStore, "_reset_instance"):
            IBStore._reset_instance()
        gc.collect()

        # Test first creation
        times = []
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()

            for _ in range(10):
                if hasattr(IBStore, "_reset_instance"):
                    IBStore._reset_instance()

                start_time = time.perf_counter()
                store = IBStore()
                end_time = time.perf_counter()
                times.append(end_time - start_time)

        first_creation_avg = sum(times) / len(times)

        # Test subsequent access
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()  # Create initial instance

            times = []
            for _ in range(1000):
                start_time = time.perf_counter()
                store = IBStore()
                end_time = time.perf_counter()
                times.append(end_time - start_time)

        subsequent_access_avg = sum(times) / len(times)

        self.test_results["original"] = {
            "first_creation_avg": first_creation_avg,
            "subsequent_access_avg": subsequent_access_avg,
        }

        print(f"   First creation: {first_creation_avg*1000:.3f}ms avg")
        print(f"   Subsequent access: {subsequent_access_avg*1000000:.1f}μs avg")

    def implement_method_caching(self):
        """Implement method-level caching optimizations.

        Creates cached versions of common store methods (getdata, getbroker,
        get_notifications) and benchmarks their performance against uncached versions.

        Results are stored in optimization_results["method_caching"] including:
        - method_results: Average execution times for each method
        - cache_stats: Cache hit/miss statistics for each cached method
        """
        print("Implementing method caching optimizations...")

        # Create cached versions of common methods
        @MethodCache(maxsize=64, ttl=60.0)  # 1 minute TTL
        def cached_getdata(self, *args, **kwargs):
            """Cached version of getdata method."""
            return self.getdata(*args, **kwargs)

        @MethodCache(maxsize=32)
        def cached_getbroker(self, *args, **kwargs):
            """Cached version of getbroker method."""
            return self.getbroker(*args, **kwargs)

        @MethodCache(maxsize=128, ttl=30.0)  # 30 second TTL
        def cached_get_notifications(self):
            """Cached version of get_notifications method."""
            return self.get_notifications()

        # Test method caching performance
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()

            # Bind cached methods
            store.cached_getdata = cached_getdata.__get__(store, IBStore)
            store.cached_getbroker = cached_getbroker.__get__(store, IBStore)
            store.cached_get_notifications = cached_get_notifications.__get__(store, IBStore)

            # Test cached method performance
            methods_to_test = [
                ("getdata", lambda: store.getdata()),
                ("cached_getdata", lambda: store.cached_getdata()),
                ("getbroker", lambda: store.getbroker()),
                ("cached_getbroker", lambda: store.cached_getbroker()),
                ("get_notifications", lambda: store.get_notifications()),
                ("cached_get_notifications", lambda: store.cached_get_notifications()),
            ]

            method_results = {}
            for method_name, method_func in methods_to_test:
                times = []
                for _ in range(100):
                    start_time = time.perf_counter()
                    method_func()
                    end_time = time.perf_counter()
                    times.append(end_time - start_time)

                avg_time = sum(times) / len(times)
                method_results[method_name] = avg_time
                print(f"   {method_name}(): {avg_time*1000000:.1f}μs avg")

            # Get cache statistics
            cache_stats = {
                "getdata_cache": cached_getdata.cache_info(),
                "getbroker_cache": cached_getbroker.cache_info(),
                "notifications_cache": cached_get_notifications.cache_info(),
            }

            self.optimization_results["method_caching"] = {
                "method_results": method_results,
                "cache_stats": cache_stats,
            }

    def implement_singleton_optimization(self):
        """Implement singleton-level optimizations.

        Creates an optimized version of IBStore using OptimizedParameterizedSingletonMixin
        and benchmarks its performance against the original implementation.

        Results are stored in optimization_results["singleton_optimization"] including:
        - first_creation_avg: Average time for first instance creation
        - subsequent_access_avg: Average time for subsequent access
        - cache_stats: Statistics from the SingletonCache
        """
        print("Implementing singleton optimizations...")

        # Test optimized singleton implementation
        class OptimizedIBStore(OptimizedParameterizedSingletonMixin, IBStore):
            """IBStore with optimized singleton caching."""

            pass

        # Reset and test optimized version
        gc.collect()

        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()

            # Test first creation
            times = []
            for _ in range(10):
                OptimizedIBStore._reset_instance()
                start_time = time.perf_counter()
                store = OptimizedIBStore()
                end_time = time.perf_counter()
                times.append(end_time - start_time)

            optimized_first_creation = sum(times) / len(times)

            # Test subsequent access
            store = OptimizedIBStore()  # Create initial instance
            times = []
            for _ in range(1000):
                start_time = time.perf_counter()
                store = OptimizedIBStore()
                end_time = time.perf_counter()
                times.append(end_time - start_time)

            optimized_subsequent_access = sum(times) / len(times)

            # Get cache statistics
            cache_stats = OptimizedIBStore.get_cache_stats()

            self.optimization_results["singleton_optimization"] = {
                "first_creation_avg": optimized_first_creation,
                "subsequent_access_avg": optimized_subsequent_access,
                "cache_stats": cache_stats,
            }

            print(f"   Optimized first creation: {optimized_first_creation*1000:.3f}ms avg")
            print(
                f"   Optimized subsequent access: {optimized_subsequent_access*1000000:.1f}μs avg"
            )

    def implement_memory_optimization(self):
        """Implement memory usage optimizations using weak references.

        Creates a weak-reference based singleton implementation and compares
        memory usage against the regular implementation. Weak references allow
        instances to be garbage collected when no longer referenced elsewhere.

        Results are stored in optimization_results["memory_optimization"] including:
        - regular_memory_usage: Memory used by regular implementation
        - optimized_memory_usage: Memory used by weak reference implementation
        - memory_savings: Absolute memory savings in bytes
        - memory_savings_percent: Percentage of memory saved

        Note:
            This test requires the psutil package for memory measurement.
        """
        print("Implementing memory optimizations...")

        # Test weak reference caching
        class WeakRefOptimizedStore:
            """Store implementation with weak reference-based singleton optimization.

            This class implements a singleton pattern using Python's WeakValueDictionary,
            which allows instances to be automatically garbage collected when they are no
            longer referenced elsewhere in the application. This provides memory efficiency
            for store instances that may be created temporarily but don't need to persist
            for the entire application lifetime.

            The weak reference pattern is particularly useful for:
            - Reducing memory footprint in long-running applications
            - Allowing garbage collection of unused store instances
            - Testing scenarios where instance lifecycle needs to be controlled

            Attributes:
                _instances: WeakValueDictionary mapping cache keys to store instances.
                    Unlike regular dictionaries, weak references allow entries to be
                    automatically removed when no other references exist.
                _lock: Threading.RLock for thread-safe instance creation and access.

            Example:
                >>> store1 = WeakRefOptimizedStore()
                >>> store2 = WeakRefOptimizedStore()
                >>> assert store1 is store2  # Same instance
                >>> del store1
                >>> del store2
                >>> # Instance may be garbage collected if no other references exist

            Note:
                This is a demonstration class for memory optimization testing.
                In production, use OptimizedParameterizedSingletonMixin instead.
            """

            _instances = weakref.WeakValueDictionary()
            _lock = threading.RLock()

            def __new__(cls, *args, **kwargs):
                """Create or return cached singleton instance using weak references.

                Implements the singleton pattern with weak references. If an instance
                with the same parameters exists and is still referenced elsewhere, it
                is returned. Otherwise, a new instance is created and cached.

                The weak reference allows the instance to be garbage collected when
                no longer referenced outside the cache, providing automatic memory cleanup.

                Args:
                    *args: Positional arguments for instance construction.
                        Used to generate the cache key.
                    **kwargs: Keyword arguments for instance construction.
                        Used to generate the cache key.

                Returns:
                    The singleton instance, either from cache or newly created.
                    If the cached instance was garbage collected, a new one is created.

                Note:
                    The cache key is generated by converting args and sorted kwargs
                    to strings. This simple approach works for basic types but may
                    have collisions with complex objects.
                """
                # Generate cache key from constructor arguments
                # String conversion is simple but may have collisions for complex objects
                cache_key = str(args) + str(sorted(kwargs.items()))

                with cls._lock:
                    # Check if instance exists in cache and is still alive (not GC'd)
                    instance = cls._instances.get(cache_key)
                    if instance is not None:
                        # Instance found - return cached singleton
                        return instance

                    # No instance exists (or was GC'd) - create new one
                    # Use super().__new__ to create instance without calling __init__
                    instance = super().__new__(cls)
                    cls._instances[cache_key] = instance
                    return instance

        # Test memory efficiency
        import os
        import psutil

        process = psutil.Process(os.getpid())

        # Test regular implementation
        initial_memory = process.memory_info().rss
        regular_stores = []

        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()

            for _ in range(100):
                regular_stores.append(IBStore())

        regular_memory = process.memory_info().rss
        regular_memory_usage = regular_memory - initial_memory

        # Clean up
        del regular_stores
        gc.collect()

        # Test optimized implementation
        initial_memory = process.memory_info().rss
        optimized_stores = []

        for _ in range(100):
            optimized_stores.append(WeakRefOptimizedStore())

        optimized_memory = process.memory_info().rss
        optimized_memory_usage = optimized_memory - initial_memory

        self.optimization_results["memory_optimization"] = {
            "regular_memory_usage": regular_memory_usage,
            "optimized_memory_usage": optimized_memory_usage,
            "memory_savings": regular_memory_usage - optimized_memory_usage,
            "memory_savings_percent": (
                ((regular_memory_usage - optimized_memory_usage) / regular_memory_usage) * 100
                if regular_memory_usage > 0
                else 0
            ),
        }

        print(f"   Regular memory usage: {regular_memory_usage/1024:.1f}KB")
        print(f"   Optimized memory usage: {optimized_memory_usage/1024:.1f}KB")
        print(
            f"   Memory savings: {(regular_memory_usage - optimized_memory_usage)/1024:.1f}KB ({self.optimization_results['memory_optimization']['memory_savings_percent']:.1f}%)"
        )

    def run_comprehensive_optimization(self):
        """Run comprehensive cache optimization analysis.

        Executes all optimization tests and benchmarks in sequence:
        1. Test original baseline performance
        2. Implement and test method caching
        3. Implement and test singleton optimization
        4. Implement and test memory optimization
        5. Generate performance comparison report

        Returns:
            A dictionary containing:
            - test_results: Baseline performance test results
            - optimization_results: All optimization benchmark results
        """
        print("\n" + "=" * 80)
        print("Store System Cache Optimization (Day 22-24)")
        print("=" * 80)

        start_time = time.time()

        # Test original performance
        self.test_original_performance()
        print()

        # Implement optimizations
        self.implement_method_caching()
        print()
        self.implement_singleton_optimization()
        print()
        self.implement_memory_optimization()

        optimization_time = time.time() - start_time

        # Generate performance comparison
        self.generate_performance_report()

        print(f"\nTotal optimization time: {optimization_time:.2f}s")

        return {
            "test_results": self.test_results,
            "optimization_results": self.optimization_results,
        }

    def generate_performance_report(self):
        """Generate comprehensive performance report.

        Prints a detailed comparison of baseline vs optimized performance including:
        - Singleton performance improvements (creation and access times)
        - Method caching performance improvements
        - Cache hit rates for all cached methods
        - Memory optimization savings

        The report is printed to stdout in a formatted table.
        """
        print("\n" + "=" * 80)
        print("Performance Optimization Report")
        print("=" * 80)

        # Singleton performance comparison
        if (
            "original" in self.test_results
            and "singleton_optimization" in self.optimization_results
        ):
            original = self.test_results["original"]
            optimized = self.optimization_results["singleton_optimization"]

            first_improvement = (
                (original["first_creation_avg"] - optimized["first_creation_avg"])
                / original["first_creation_avg"]
                * 100
            )
            subsequent_improvement = (
                (original["subsequent_access_avg"] - optimized["subsequent_access_avg"])
                / original["subsequent_access_avg"]
                * 100
            )

            print("Singleton Performance Improvements:")
            print(f"   First creation: {first_improvement:.1f}% faster")
            print(f"   Subsequent access: {subsequent_improvement:.1f}% faster")

        # Method caching improvements
        if "method_caching" in self.optimization_results:
            method_results = self.optimization_results["method_caching"]["method_results"]
            cache_stats = self.optimization_results["method_caching"]["cache_stats"]

            print("\nMethod Caching Performance:")
            for method in ["getdata", "getbroker", "get_notifications"]:
                if method in method_results and f"cached_{method}" in method_results:
                    original_time = method_results[method]
                    cached_time = method_results[f"cached_{method}"]
                    improvement = (original_time - cached_time) / original_time * 100
                    print(f"   {method}(): {improvement:.1f}% improvement with caching")

            print("\nCache Hit Rates:")
            for cache_name, stats in cache_stats.items():
                print(f"   {cache_name}: {stats['hit_rate']*100:.1f}% hit rate")

        # Memory optimization results
        if "memory_optimization" in self.optimization_results:
            memory_results = self.optimization_results["memory_optimization"]
            print(f"\nMemory Optimization:")
            print(f"   Memory savings: {memory_results['memory_savings_percent']:.1f}%")
            print(f"   Reduced usage: {memory_results['memory_savings']/1024:.1f}KB")

    def save_optimization_report(self, filename="cache_optimization_report.json"):
        """Save optimization results to JSON file.

        Args:
            filename: Path to the output JSON file. Defaults to
                "cache_optimization_report.json".

        Returns:
            The filename that was written to.
        """
        import json

        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "test_results": self.test_results,
            "optimization_results": self.optimization_results,
        }

        # Make cache stats serializable
        for key, value in report["optimization_results"].items():
            if "cache_stats" in value:
                # Convert any non-serializable objects to strings
                for cache_key, cache_value in value["cache_stats"].items():
                    if isinstance(cache_value, dict):
                        value["cache_stats"][cache_key] = {
                            k: str(v) for k, v in cache_value.items()
                        }

        with open(filename, "w") as f:
            json.dump(report, f, indent=2, default=str)

        print(f"Optimization report saved to: {filename}")
        return filename


def main():
    """Main optimization execution function.

    Creates a CacheOptimizationTool, runs comprehensive optimization tests,
    generates reports, and saves results to a JSON file.

    Returns:
        True if optimization completed successfully, False if an exception occurred.

    Raises:
        Exception: Any exception during optimization is caught and printed.
    """
    optimizer = CacheOptimizationTool()

    try:
        # Run comprehensive optimization
        results = optimizer.run_comprehensive_optimization()

        # Save report
        report_file = optimizer.save_optimization_report()

        print(f"\nCache optimization completed!")
        print(f"Optimizations tested: {len(results['optimization_results'])}")
        print(f"Report: {report_file}")

        return True

    except Exception as e:
        print(f"\nOptimization failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
