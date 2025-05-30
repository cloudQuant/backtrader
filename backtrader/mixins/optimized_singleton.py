#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import threading
import weakref
import time
from collections import defaultdict


class OptimizedSingletonMixin:
    """Optimized singleton mixin with performance enhancements."""
    
    # Class-level cache for instances
    _instances = {}
    # Thread lock for instance creation
    _lock = threading.RLock()
    # Performance tracking
    _access_stats = defaultdict(int)
    _creation_times = {}
    
    def __new__(cls, *args, **kwargs):
        """Create or return cached singleton instance with optimization."""
        
        # Generate unique key for this class and parameters
        cache_key = cls._generate_cache_key(args, kwargs)
        instance_key = (cls, cache_key)
        
        # Fast path: check if instance exists without locking
        # This optimizes the common case of accessing existing singletons
        if instance_key in cls._instances:
            cls._access_stats[instance_key] += 1
            return cls._instances[instance_key]
        
        # Slow path: need to create instance with lock
        with cls._lock:
            # Double-check pattern: instance might have been created 
            # by another thread while we were waiting for the lock
            if instance_key in cls._instances:
                cls._access_stats[instance_key] += 1
                return cls._instances[instance_key]
            
            # Create new instance and track creation time
            creation_start = time.perf_counter()
            instance = super().__new__(cls)
            creation_time = time.perf_counter() - creation_start
            
            # Cache the instance
            cls._instances[instance_key] = instance
            cls._creation_times[instance_key] = creation_time
            cls._access_stats[instance_key] = 1
            
            return instance
    
    @classmethod
    def _generate_cache_key(cls, args, kwargs):
        """Generate cache key from constructor arguments."""
        # Create a deterministic key from arguments
        key_parts = []
        
        # Add positional arguments
        for arg in args:
            key_parts.append(str(arg))
        
        # Add keyword arguments (sorted for consistency)
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}={v}")
        
        # Return tuple for immutability
        return tuple(key_parts) if key_parts else None
    
    @classmethod
    def _reset_instance(cls, *args, **kwargs):
        """Reset specific instance (useful for testing)."""
        cache_key = cls._generate_cache_key(args, kwargs)
        instance_key = (cls, cache_key)
        
        with cls._lock:
            cls._instances.pop(instance_key, None)
            cls._access_stats.pop(instance_key, None)
            cls._creation_times.pop(instance_key, None)
    
    @classmethod
    def _reset_all_instances(cls):
        """Reset all instances of this class."""
        with cls._lock:
            # Only remove instances of this specific class
            keys_to_remove = [key for key in cls._instances.keys() if key[0] == cls]
            for key in keys_to_remove:
                cls._instances.pop(key, None)
                cls._access_stats.pop(key, None)
                cls._creation_times.pop(key, None)
    
    @classmethod
    def get_singleton_stats(cls):
        """Get performance statistics for singleton usage."""
        with cls._lock:
            # Filter stats for this specific class
            class_keys = [key for key in cls._instances.keys() if key[0] == cls]
            
            total_accesses = sum(cls._access_stats[key] for key in class_keys)
            total_instances = len(class_keys)
            
            avg_creation_time = 0
            if class_keys:
                creation_times = [cls._creation_times.get(key, 0) for key in class_keys]
                avg_creation_time = sum(creation_times) / len(creation_times)
            
            return {
                'total_instances': total_instances,
                'total_accesses': total_accesses,
                'avg_accesses_per_instance': total_accesses / total_instances if total_instances > 0 else 0,
                'avg_creation_time_ms': avg_creation_time * 1000,
                'instance_keys': [key[1] for key in class_keys]  # Just the cache keys
            }


class WeakReferenceSingletonMixin:
    """Singleton mixin using weak references for memory optimization."""
    
    # Use WeakValueDictionary to allow garbage collection
    _instances = weakref.WeakValueDictionary()
    _lock = threading.RLock()
    _stats = defaultdict(int)
    
    def __new__(cls, *args, **kwargs):
        """Create or return cached instance with weak reference optimization."""
        
        cache_key = cls._generate_cache_key(args, kwargs)
        instance_key = (cls.__name__, cache_key)  # Use class name for weak refs
        
        with cls._lock:
            # Try to get existing instance
            instance = cls._instances.get(instance_key)
            if instance is not None:
                cls._stats['cache_hits'] += 1
                return instance
            
            # Create new instance
            cls._stats['cache_misses'] += 1
            instance = super().__new__(cls)
            
            # Store with weak reference
            cls._instances[instance_key] = instance
            
            return instance
    
    @classmethod
    def _generate_cache_key(cls, args, kwargs):
        """Generate cache key from constructor arguments."""
        key_parts = []
        
        for arg in args:
            # Handle common immutable types
            if isinstance(arg, (str, int, float, bool, tuple)):
                key_parts.append(str(arg))
            else:
                # For complex objects, use their string representation
                key_parts.append(str(type(arg).__name__))
        
        for k, v in sorted(kwargs.items()):
            if isinstance(v, (str, int, float, bool, tuple)):
                key_parts.append(f"{k}={v}")
            else:
                key_parts.append(f"{k}={type(v).__name__}")
        
        return tuple(key_parts) if key_parts else None
    
    @classmethod
    def get_memory_stats(cls):
        """Get memory usage statistics."""
        with cls._lock:
            return {
                'active_instances': len(cls._instances),
                'cache_hits': cls._stats['cache_hits'],
                'cache_misses': cls._stats['cache_misses'],
                'hit_ratio': cls._stats['cache_hits'] / (cls._stats['cache_hits'] + cls._stats['cache_misses']) if cls._stats['cache_hits'] + cls._stats['cache_misses'] > 0 else 0
            }


class ParameterizedOptimizedSingletonMixin(OptimizedSingletonMixin):
    """Optimized singleton mixin specifically for parameterized classes."""
    
    @classmethod
    def _generate_cache_key(cls, args, kwargs):
        """Enhanced cache key generation for parameterized classes."""
        key_parts = []
        
        # Include class name to avoid collisions between different classes
        key_parts.append(cls.__name__)
        
        # Add positional arguments
        for arg in args:
            if hasattr(arg, '_name'):  # Handle named parameters
                key_parts.append(f"arg_{arg._name}={arg}")
            else:
                key_parts.append(str(arg))
        
        # Add keyword arguments with special handling for common parameter types
        for k, v in sorted(kwargs.items()):
            if hasattr(v, '__dict__'):
                # For complex objects, create a hash from their attributes
                attrs = sorted(v.__dict__.items()) if hasattr(v, '__dict__') else []
                key_parts.append(f"{k}={type(v).__name__}({attrs})")
            else:
                key_parts.append(f"{k}={v}")
        
        return tuple(key_parts) if key_parts else None


# Performance monitoring utilities
class SingletonPerformanceMonitor:
    """Monitor singleton performance across the application."""
    
    @staticmethod
    def get_global_stats():
        """Get performance stats for all singleton classes."""
        stats = {}
        
        # Collect stats from OptimizedSingletonMixin classes
        for cls_key, instance in OptimizedSingletonMixin._instances.items():
            cls = cls_key[0]
            if cls not in stats:
                stats[cls.__name__] = cls.get_singleton_stats()
        
        return stats
    
    @staticmethod
    def print_performance_report():
        """Print a comprehensive performance report."""
        print("\n" + "="*60)
        print("🔍 Singleton Performance Report")
        print("="*60)
        
        global_stats = SingletonPerformanceMonitor.get_global_stats()
        
        if not global_stats:
            print("No singleton usage data available.")
            return
        
        total_instances = 0
        total_accesses = 0
        
        for class_name, stats in global_stats.items():
            print(f"\n📊 {class_name}:")
            print(f"   Instances: {stats['total_instances']}")
            print(f"   Total accesses: {stats['total_accesses']}")
            print(f"   Avg accesses per instance: {stats['avg_accesses_per_instance']:.1f}")
            print(f"   Avg creation time: {stats['avg_creation_time_ms']:.3f}ms")
            
            total_instances += stats['total_instances']
            total_accesses += stats['total_accesses']
        
        print(f"\n📈 Global Summary:")
        print(f"   Total singleton instances: {total_instances}")
        print(f"   Total singleton accesses: {total_accesses}")
        print(f"   Average efficiency: {total_accesses / total_instances:.1f} accesses per instance" if total_instances > 0 else "   No instances")
        print("="*60)


# Utility function for migration
def optimize_singleton_class(cls):
    """Decorator to easily add optimization to existing singleton classes."""
    
    # Create optimized version dynamically
    class OptimizedClass(ParameterizedOptimizedSingletonMixin, cls):
        pass
    
    # Copy class metadata
    OptimizedClass.__name__ = cls.__name__
    OptimizedClass.__module__ = cls.__module__
    OptimizedClass.__qualname__ = getattr(cls, '__qualname__', cls.__name__)
    
    return OptimizedClass 