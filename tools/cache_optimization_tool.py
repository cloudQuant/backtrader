#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import time
import threading
import weakref
import functools
import gc
import sys
from collections import OrderedDict, defaultdict
from typing import Any, Optional, Dict, Callable, Tuple
from unittest.mock import Mock, patch

# Mock dependencies
sys.modules['oandapy'] = Mock()
sys.modules['ccxt'] = Mock()
sys.modules['ctpbee'] = Mock()
sys.modules['ctpbee.api'] = Mock()
sys.modules['ctpbee.constant'] = Mock()
sys.modules['ctpbee.helpers'] = Mock()

from backtrader.stores.ibstore import IBStore
from backtrader.mixins import ParameterizedSingletonMixin


class LRUCache:
    """Least Recently Used cache implementation."""
    
    def __init__(self, maxsize: int = 128):
        self.maxsize = maxsize
        self.cache = OrderedDict()
        self.lock = threading.RLock()
        
    def get(self, key):
        """Get item from cache."""
        with self.lock:
            if key in self.cache:
                # Move to end (most recently used)
                value = self.cache.pop(key)
                self.cache[key] = value
                return value
            return None
            
    def put(self, key, value):
        """Put item in cache."""
        with self.lock:
            if key in self.cache:
                # Update existing
                self.cache.pop(key)
            elif len(self.cache) >= self.maxsize:
                # Remove least recently used
                self.cache.popitem(last=False)
            self.cache[key] = value
            
    def clear(self):
        """Clear cache."""
        with self.lock:
            self.cache.clear()
            
    def info(self):
        """Get cache info."""
        with self.lock:
            return {
                'size': len(self.cache),
                'maxsize': self.maxsize,
                'utilization': len(self.cache) / self.maxsize if self.maxsize > 0 else 0
            }


class MethodCache:
    """Method-level caching decorator."""
    
    def __init__(self, maxsize: int = 128, ttl: Optional[float] = None):
        self.maxsize = maxsize
        self.ttl = ttl
        self.cache = LRUCache(maxsize)
        self.timestamps = {} if ttl else None
        self.hits = 0
        self.misses = 0
        self.lock = threading.RLock()
        
    def __call__(self, func):
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
        """Create cache key from function arguments."""
        # Simple key generation - can be improved for complex objects
        key_parts = [func.__name__]
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return tuple(key_parts)
        
    def _is_valid(self, key):
        """Check if cached item is still valid (TTL check)."""
        if self.timestamps is None:
            return True
        timestamp = self.timestamps.get(key)
        if timestamp is None:
            return False
        return (time.time() - timestamp) <= self.ttl
        
    def cache_info(self):
        """Get cache statistics."""
        total_calls = self.hits + self.misses
        hit_rate = self.hits / total_calls if total_calls > 0 else 0
        return {
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'cache_size': self.cache.info()['size'],
            'max_size': self.maxsize
        }
        
    def cache_clear(self):
        """Clear cache."""
        with self.lock:
            self.cache.clear()
            if self.timestamps:
                self.timestamps.clear()
            self.hits = 0
            self.misses = 0


class SingletonCache:
    """Enhanced singleton cache with performance optimizations."""
    
    def __init__(self):
        self._instances = {}
        self._lock = threading.RLock()
        self._access_count = defaultdict(int)
        self._creation_times = {}
        
    def get_instance(self, cls, key=None):
        """Get singleton instance with optimized access."""
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
        """Reset specific singleton instance."""
        cache_key = (cls, key) if key else (cls,)
        with self._lock:
            self._instances.pop(cache_key, None)
            self._access_count.pop(cache_key, None)
            self._creation_times.pop(cache_key, None)
            
    def get_stats(self):
        """Get cache statistics."""
        with self._lock:
            return {
                'instance_count': len(self._instances),
                'total_accesses': sum(self._access_count.values()),
                'access_distribution': dict(self._access_count),
                'creation_times': dict(self._creation_times),
                'avg_creation_time': sum(self._creation_times.values()) / len(self._creation_times) if self._creation_times else 0
            }


class OptimizedParameterizedSingletonMixin:
    """Optimized version of ParameterizedSingletonMixin with caching."""
    
    _cache = SingletonCache()
    
    def __new__(cls, *args, **kwargs):
        """Create or return cached instance."""
        # Generate cache key from parameters
        cache_key = cls._generate_cache_key(args, kwargs)
        return cls._cache.get_instance(cls, cache_key)
        
    @classmethod
    def _generate_cache_key(cls, args, kwargs):
        """Generate cache key from parameters."""
        # Simple implementation - can be enhanced for complex parameters
        key_parts = []
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return tuple(key_parts) if key_parts else None
        
    @classmethod
    def _reset_instance(cls, *args, **kwargs):
        """Reset specific instance for testing."""
        cache_key = cls._generate_cache_key(args, kwargs)
        cls._cache.reset_instance(cls, cache_key)
        
    @classmethod
    def get_cache_stats(cls):
        """Get singleton cache statistics."""
        return cls._cache.get_stats()


class CacheOptimizationTool:
    """Tool for implementing and testing cache optimizations."""
    
    def __init__(self):
        self.test_results = {}
        self.optimization_results = {}
        
    def test_original_performance(self):
        """Test performance of original implementation."""
        print("🔍 Testing original singleton performance...")
        
        # Reset environment
        if hasattr(IBStore, '_reset_instance'):
            IBStore._reset_instance()
        gc.collect()
        
        # Test first creation
        times = []
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            for _ in range(10):
                if hasattr(IBStore, '_reset_instance'):
                    IBStore._reset_instance()
                    
                start_time = time.perf_counter()
                store = IBStore()
                end_time = time.perf_counter()
                times.append(end_time - start_time)
                
        first_creation_avg = sum(times) / len(times)
        
        # Test subsequent access
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()  # Create initial instance
            
            times = []
            for _ in range(1000):
                start_time = time.perf_counter()
                store = IBStore()
                end_time = time.perf_counter()
                times.append(end_time - start_time)
                
        subsequent_access_avg = sum(times) / len(times)
        
        self.test_results['original'] = {
            'first_creation_avg': first_creation_avg,
            'subsequent_access_avg': subsequent_access_avg
        }
        
        print(f"   First creation: {first_creation_avg*1000:.3f}ms avg")
        print(f"   Subsequent access: {subsequent_access_avg*1000000:.1f}μs avg")
        
    def implement_method_caching(self):
        """Implement method-level caching optimizations."""
        print("🚀 Implementing method caching optimizations...")
        
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
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()
            
            # Bind cached methods
            store.cached_getdata = cached_getdata.__get__(store, IBStore)
            store.cached_getbroker = cached_getbroker.__get__(store, IBStore)
            store.cached_get_notifications = cached_get_notifications.__get__(store, IBStore)
            
            # Test cached method performance
            methods_to_test = [
                ('getdata', lambda: store.getdata()),
                ('cached_getdata', lambda: store.cached_getdata()),
                ('getbroker', lambda: store.getbroker()),
                ('cached_getbroker', lambda: store.cached_getbroker()),
                ('get_notifications', lambda: store.get_notifications()),
                ('cached_get_notifications', lambda: store.cached_get_notifications()),
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
                'getdata_cache': cached_getdata.cache_info(),
                'getbroker_cache': cached_getbroker.cache_info(),
                'notifications_cache': cached_get_notifications.cache_info()
            }
            
            self.optimization_results['method_caching'] = {
                'method_results': method_results,
                'cache_stats': cache_stats
            }
            
    def implement_singleton_optimization(self):
        """Implement singleton-level optimizations."""
        print("🚀 Implementing singleton optimizations...")
        
        # Test optimized singleton implementation
        class OptimizedIBStore(OptimizedParameterizedSingletonMixin, IBStore):
            """IBStore with optimized singleton caching."""
            pass
            
        # Reset and test optimized version
        gc.collect()
        
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
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
            
            self.optimization_results['singleton_optimization'] = {
                'first_creation_avg': optimized_first_creation,
                'subsequent_access_avg': optimized_subsequent_access,
                'cache_stats': cache_stats
            }
            
            print(f"   Optimized first creation: {optimized_first_creation*1000:.3f}ms avg")
            print(f"   Optimized subsequent access: {optimized_subsequent_access*1000000:.1f}μs avg")
            
    def implement_memory_optimization(self):
        """Implement memory usage optimizations."""
        print("🚀 Implementing memory optimizations...")
        
        # Test weak reference caching
        class WeakRefOptimizedStore:
            """Store with weak reference optimization."""
            
            _instances = weakref.WeakValueDictionary()
            _lock = threading.RLock()
            
            def __new__(cls, *args, **kwargs):
                cache_key = str(args) + str(sorted(kwargs.items()))
                
                with cls._lock:
                    instance = cls._instances.get(cache_key)
                    if instance is not None:
                        return instance
                        
                    # Create new instance
                    instance = super().__new__(cls)
                    cls._instances[cache_key] = instance
                    return instance
                    
        # Test memory efficiency
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        
        # Test regular implementation
        initial_memory = process.memory_info().rss
        regular_stores = []
        
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
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
        
        self.optimization_results['memory_optimization'] = {
            'regular_memory_usage': regular_memory_usage,
            'optimized_memory_usage': optimized_memory_usage,
            'memory_savings': regular_memory_usage - optimized_memory_usage,
            'memory_savings_percent': ((regular_memory_usage - optimized_memory_usage) / regular_memory_usage) * 100 if regular_memory_usage > 0 else 0
        }
        
        print(f"   Regular memory usage: {regular_memory_usage/1024:.1f}KB")
        print(f"   Optimized memory usage: {optimized_memory_usage/1024:.1f}KB")
        print(f"   Memory savings: {(regular_memory_usage - optimized_memory_usage)/1024:.1f}KB ({self.optimization_results['memory_optimization']['memory_savings_percent']:.1f}%)")
        
    def run_comprehensive_optimization(self):
        """Run comprehensive cache optimization analysis."""
        print("\n" + "="*80)
        print("🚀 Store System Cache Optimization (Day 22-24)")
        print("="*80)
        
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
        
        print(f"\n⏱️ Total optimization time: {optimization_time:.2f}s")
        
        return {
            'test_results': self.test_results,
            'optimization_results': self.optimization_results
        }
        
    def generate_performance_report(self):
        """Generate comprehensive performance report."""
        print("\n" + "="*80)
        print("📊 Performance Optimization Report")
        print("="*80)
        
        # Singleton performance comparison
        if 'original' in self.test_results and 'singleton_optimization' in self.optimization_results:
            original = self.test_results['original']
            optimized = self.optimization_results['singleton_optimization']
            
            first_improvement = (original['first_creation_avg'] - optimized['first_creation_avg']) / original['first_creation_avg'] * 100
            subsequent_improvement = (original['subsequent_access_avg'] - optimized['subsequent_access_avg']) / original['subsequent_access_avg'] * 100
            
            print("🔄 Singleton Performance Improvements:")
            print(f"   First creation: {first_improvement:.1f}% faster")
            print(f"   Subsequent access: {subsequent_improvement:.1f}% faster")
            
        # Method caching improvements
        if 'method_caching' in self.optimization_results:
            method_results = self.optimization_results['method_caching']['method_results']
            cache_stats = self.optimization_results['method_caching']['cache_stats']
            
            print("\n⚡ Method Caching Performance:")
            for method in ['getdata', 'getbroker', 'get_notifications']:
                if method in method_results and f'cached_{method}' in method_results:
                    original_time = method_results[method]
                    cached_time = method_results[f'cached_{method}']
                    improvement = (original_time - cached_time) / original_time * 100
                    print(f"   {method}(): {improvement:.1f}% improvement with caching")
                    
            print("\n📈 Cache Hit Rates:")
            for cache_name, stats in cache_stats.items():
                print(f"   {cache_name}: {stats['hit_rate']*100:.1f}% hit rate")
                
        # Memory optimization results
        if 'memory_optimization' in self.optimization_results:
            memory_results = self.optimization_results['memory_optimization']
            print(f"\n💾 Memory Optimization:")
            print(f"   Memory savings: {memory_results['memory_savings_percent']:.1f}%")
            print(f"   Reduced usage: {memory_results['memory_savings']/1024:.1f}KB")
            
    def save_optimization_report(self, filename="cache_optimization_report.json"):
        """Save optimization results to file."""
        import json
        
        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'test_results': self.test_results,
            'optimization_results': self.optimization_results
        }
        
        # Make cache stats serializable
        for key, value in report['optimization_results'].items():
            if 'cache_stats' in value:
                # Convert any non-serializable objects to strings
                for cache_key, cache_value in value['cache_stats'].items():
                    if isinstance(cache_value, dict):
                        value['cache_stats'][cache_key] = {k: str(v) for k, v in cache_value.items()}
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
            
        print(f"📄 Optimization report saved to: {filename}")
        return filename


def main():
    """Main optimization execution."""
    optimizer = CacheOptimizationTool()
    
    try:
        # Run comprehensive optimization
        results = optimizer.run_comprehensive_optimization()
        
        # Save report
        report_file = optimizer.save_optimization_report()
        
        print(f"\n✅ Cache optimization completed!")
        print(f"📊 Optimizations tested: {len(results['optimization_results'])}")
        print(f"📄 Report: {report_file}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Optimization failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 