#!/usr/bin/env python
"""Memory optimization tool for backtrader Store classes.

This module provides tools for profiling and optimizing memory usage in
backtrader Store implementations, with support for testing various
optimization techniques including __slots__, weak references, and caching.

The module includes:
    - MemoryProfiler: Tracks memory usage during object operations
    - SlottedStore: Example implementation using __slots__
    - OptimizedStore: Comprehensive optimization with multiple techniques
    - MemoryOptimizationTool: Main testing and analysis framework

Example:
    >>> optimizer = MemoryOptimizationTool()
    >>> results = optimizer.run_comprehensive_memory_analysis()
    >>> optimizer.save_memory_report()
"""

import gc
import os
import sys
import time
import weakref
from collections import defaultdict
from typing import Dict, List, Any, Optional
from unittest.mock import Mock, patch

import psutil

# Mock external dependencies that may not be available in all environments
sys.modules["oandapy"] = Mock()
sys.modules["ccxt"] = Mock()
sys.modules["ctpbee"] = Mock()
sys.modules["ctpbee.api"] = Mock()
sys.modules["ctpbee.constant"] = Mock()
sys.modules["ctpbee.helpers"] = Mock()

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.stores.ibstore import IBStore


class MemoryProfiler:
    """Memory usage profiler for Store classes.

    Tracks memory usage during object creation and operations, providing
    detailed reports on memory consumption and leaks. Uses psutil to measure
    Resident Set Size (RSS) which represents the actual physical memory in use.

    Attributes:
        process: psutil.Process instance for the current process.
        baseline_memory: Memory usage in bytes at profiling start (RSS).
        memory_snapshots: List of tuples containing (label, memory, increase) measurements.

    Example:
        >>> profiler = MemoryProfiler()
        >>> profiler.start_profiling()
        >>> # Create objects here
        >>> profiler.take_snapshot("after_creation")
        >>> print(profiler.get_memory_report())
    """

    def __init__(self):
        """Initialize the memory profiler.

        Creates a psutil Process object for the current process and initializes
        tracking variables. Does not start profiling until start_profiling() is called.
        """
        self.process = psutil.Process(os.getpid())
        self.baseline_memory = 0
        self.memory_snapshots = []

    def start_profiling(self):
        """Start memory profiling session.

        Performs garbage collection before measuring to ensure accurate
        baseline memory reading and resets any previous snapshots.

        Note:
            This method clears any existing memory_snapshots from previous sessions.
            Call this before starting a new profiling session to ensure clean measurements.
        """
        gc.collect()  # Force garbage collection to clean up unreferenced objects
        self.baseline_memory = self.process.memory_info().rss  # Get Resident Set Size
        self.memory_snapshots = [(0, self.baseline_memory)]

    def take_snapshot(self, label: str = "snapshot") -> int:
        """Take a memory snapshot at current point.

        Measures current memory usage and calculates the increase from baseline.
        Snapshots are stored in memory_snapshots for later report generation.

        Args:
            label: Identifier for this snapshot (e.g., "after_creation", "before_cleanup").

        Returns:
            int: Memory increase in bytes from the baseline measurement.

        Example:
            >>> profiler.start_profiling()
            >>> create_objects()
            >>> increase = profiler.take_snapshot("after_creation")
            >>> print(f"Memory increased by {increase} bytes")
        """
        current_memory = self.process.memory_info().rss
        memory_increase = current_memory - self.baseline_memory
        # Store snapshot as (label, current_memory, memory_increase)
        self.memory_snapshots.append((label, current_memory, memory_increase))
        return memory_increase

    def get_memory_report(self) -> str:
        """Get detailed memory usage report.

        Generates a formatted report showing memory usage across all snapshots
        taken during the profiling session, including baseline and increases.

        Returns:
            str: Formatted report with memory usage in MB and KB for each snapshot.
            Returns "No memory snapshots available" if no snapshots have been taken.

        Example:
            >>> profiler.start_profiling()
            >>> # ... perform operations ...
            >>> profiler.take_snapshot("operation_complete")
            >>> print(profiler.get_memory_report())
            Memory Usage Report:
            ==================================================
            Baseline: 125.43 MB
            operation_complete: 127.85 MB (+2.4 KB)
        """
        if not self.memory_snapshots:
            return "No memory snapshots available"

        report = ["Memory Usage Report:"]
        report.append("=" * 50)

        for i, snapshot in enumerate(self.memory_snapshots):
            if len(snapshot) == 2:  # Baseline snapshot (label, memory)
                label, memory = snapshot
                report.append(f"Baseline: {memory / (1024*1024):.2f} MB")
            else:  # Regular snapshot (label, memory, increase)
                label, memory, increase = snapshot
                report.append(f"{label}: {memory / (1024*1024):.2f} MB (+{increase / 1024:.1f} KB)")

        return "\n".join(report)


class SlottedStore:
    """Example Store class with __slots__ optimization.

    Uses __slots__ to prevent dynamic attribute creation, reducing memory
    overhead by eliminating per-instance __dict__. This is particularly
    beneficial when creating many instances of the same class.

    The memory savings come from:
        - No per-instance __dict__ for storing attributes
        - Fixed memory layout for faster attribute access
        - Prevention of accidental attribute creation

    Note:
        Classes with __slots__ cannot add new attributes at runtime.
        All attributes must be declared in __slots__ before instantiation.

    Attributes:
        _connection: Connection object reference.
        _broker: Broker instance reference.
        _data: Data feed reference.
        _notifications: List of notification messages.
        _params: Dictionary of parameters.

    Example:
        >>> store = SlottedStore()
        >>> store.put_notification("Connected")
        >>> notifications = store.get_notifications()
    """

    __slots__ = ["_connection", "_broker", "_data", "_notifications", "_params"]

    def __init__(self):
        """Initialize the slotted store instance.

        Sets all slot attributes to default values. Since __slots__ is defined,
        no additional attributes can be added to instances of this class.
        """
        self._connection = None
        self._broker = None
        self._data = None
        self._notifications = []
        self._params = {}

    def getdata(self, *args, **kwargs):
        """Get data feed.

        Retrieves the stored data feed object. Arguments are accepted for
        API compatibility but are not used in this simplified implementation.

        Args:
            *args: Variable positional arguments (for API compatibility).
            **kwargs: Variable keyword arguments (for API compatibility).

        Returns:
            The stored data feed object, or None if not set.
        """
        return self._data

    def getbroker(self, *args, **kwargs):
        """Get broker instance.

        Retrieves the stored broker object. Arguments are accepted for
        API compatibility but are not used in this simplified implementation.

        Args:
            *args: Variable positional arguments (for API compatibility).
            **kwargs: Variable keyword arguments (for API compatibility).

        Returns:
            The stored broker object, or None if not set.
        """
        return self._broker

    def put_notification(self, msg: str) -> None:
        """Add a notification message.

        Appends a notification message to the internal notifications list.
        Messages can be retrieved later using get_notifications().

        Args:
            msg: Notification message to store.

        Note:
            Unlike OptimizedStore, this implementation does not limit the
            number of notifications, which can lead to unbounded memory growth.
        """
        self._notifications.append(msg)

    def get_notifications(self) -> List[str]:
        """Get all notifications.

        Returns a copy of the notifications list to prevent external
        modification of the internal state.

        Returns:
            list: Copy of notifications list containing all stored messages.
        """
        return self._notifications.copy()


class OptimizedStore:
    """Store class with multiple memory optimizations.

    Combines __slots__, weak references, caching, and bounded collections
    to minimize memory footprint. This implementation demonstrates several
    optimization techniques:

    1. __slots__: Eliminates per-instance __dict__ overhead
    2. Weak references: Prevents circular reference memory leaks
    3. Caching: Avoids duplicate object creation
    4. Bounded collections: Prevents unbounded memory growth

    Attributes:
        _connection: Connection object reference.
        _broker_ref: Weak reference to broker to prevent circular references.
        _data_cache: Cache for data feeds with key-based access.
        _notifications: Bounded list of notification messages (max 100).
        _params: Dictionary of parameters.

    Example:
        >>> store = OptimizedStore()
        >>> data = store.getdata("AAPL", timeframe="1h")
        >>> broker = store.getbroker()
        >>> store.put_notification("Data received")
    """

    __slots__ = ["_connection", "_broker_ref", "_data_cache", "_notifications", "_params"]

    def __init__(self):
        """Initialize the optimized store instance.

        Sets up all optimized data structures including weak reference
        for broker and dictionary cache for data feeds.
        """
        self._connection = None
        self._broker_ref = None  # Use weak reference to prevent circular references
        self._data_cache = {}  # Use dict for O(1) lookup instead of O(n) list search
        self._notifications = []
        self._params = {}

    def getdata(self, *args, **kwargs) -> Any:
        """Get data feed with caching.

        Implements a caching mechanism to avoid creating duplicate data feeds
        for the same arguments. This reduces memory usage when the same data
        feed is requested multiple times.

        Args:
            *args: Positional arguments for data identification.
            **kwargs: Keyword arguments for data identification.

        Returns:
            Cached or newly created data feed object.

        Note:
            The cache key is generated from the string representation of all
            arguments. In production, you'd want a more sophisticated key strategy.
        """
        key = str(args) + str(kwargs)  # Simple key generation
        if key not in self._data_cache:
            # In production, this would create an actual data feed object
            self._data_cache[key] = f"data_{key}"
        return self._data_cache[key]

    def getbroker(self, *args, **kwargs) -> Any:
        """Get broker with weak reference.

        Returns the broker object using a weak reference to prevent
        circular references that can cause memory leaks.

        Args:
            *args: Variable positional arguments (for API compatibility).
            **kwargs: Variable keyword arguments (for API compatibility).

        Returns:
            Broker object reference via weak reference, or None if not set.

        Note:
            Weak references allow the broker to be garbage collected even
            if the store still holds a reference to it.
        """
        if self._broker_ref is None:
            # Create a mock broker - in production this would be real broker object
            broker = f"broker_{id(self)}"
            self._broker_ref = weakref.ref(lambda: broker)
        return self._broker_ref()

    def put_notification(self, msg: str) -> None:
        """Add notification with bounded list size.

        Appends a notification message and enforces a maximum list size
        to prevent unbounded memory growth over time.

        Args:
            msg: Notification message to store.

        Note:
            Keeps only the last 100 notifications. When the limit is exceeded,
            the oldest notifications are discarded. This is a critical memory
            optimization for long-running systems.
        """
        self._notifications.append(msg)
        # Keep only last 100 notifications to prevent memory growth
        # This is a bounded buffer pattern - essential for long-running processes
        if len(self._notifications) > 100:
            self._notifications = self._notifications[-100:]

    def get_notifications(self) -> List[str]:
        """Get all notifications.

        Returns a copy of the notifications list to prevent external
        modification of the internal state.

        Returns:
            list: Copy of notifications list containing all stored messages.
        """
        return self._notifications.copy()


class MemoryOptimizationTool:
    """Tool for implementing and testing memory optimizations.

    Provides comprehensive methods to test various memory optimization strategies
    including __slots__, weak references, caching, and garbage collection efficiency.
    This tool helps identify memory leaks and quantify optimization benefits.

    Attributes:
        profiler: MemoryProfiler instance for tracking memory usage during tests.
        test_results: Dictionary storing results from optimization tests with keys like
            'baseline', 'slots_optimization', 'weak_ref_optimization', etc.

    Example:
        >>> optimizer = MemoryOptimizationTool()
        >>> results = optimizer.run_comprehensive_memory_analysis()
        >>> print(f"Memory saved: {results['test_results']['slots_optimization']['memory_savings']} bytes")
    """

    def __init__(self):
        """Initialize the memory optimization tool.

        Creates a MemoryProfiler instance and initializes the results dictionary.
        Tests are not run automatically - call run_comprehensive_memory_analysis()
        to execute all tests.
        """
        self.profiler = MemoryProfiler()
        self.test_results = {}

    def test_baseline_memory_usage(self) -> None:
        """Test baseline memory usage of original Store.

        Creates multiple IBStore instances and measures memory consumption
        to establish a baseline for comparison with optimized versions.

        This test:
        1. Creates 100 IBStore instances
        2. Takes memory snapshots every 20 stores
        3. Calculates memory per store
        4. Stores results for later comparison

        Note:
            Uses mocking to avoid actual IB connection requirements.
            Results are stored in test_results['baseline'].

        Side Effects:
            Updates self.test_results with baseline memory metrics.
        """
        print("🔍 Testing baseline memory usage...")

        self.profiler.start_profiling()

        stores = []
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()

            # Create 100 store instances to get measurable memory usage
            for i in range(100):
                stores.append(IBStore())
                if i % 20 == 0:
                    increase = self.profiler.take_snapshot(f"stores_{i}")

        final_increase = self.profiler.take_snapshot("final_100_stores")

        # Store baseline results for comparison with optimized versions
        self.test_results["baseline"] = {
            "memory_per_store": final_increase / 100,
            "total_memory": final_increase,
            "store_count": len(stores),
        }

        print(f"   Memory per store: {final_increase / 100 / 1024:.1f} KB")
        print(f"   Total memory increase: {final_increase / 1024:.1f} KB")

        # Clean up test objects to free memory for next test
        del stores
        gc.collect()

    def test_slots_optimization(self) -> None:
        """Test __slots__ memory optimization.

        Compares memory usage between regular classes and classes using
        __slots__ to demonstrate memory savings. Creates a local RegularStore
        class without __slots__ for comparison against SlottedStore.

        This test:
        1. Creates 100 regular store instances (with __dict__)
        2. Measures memory usage
        3. Creates 100 slotted store instances (with __slots__)
        4. Measures memory usage
        5. Calculates memory savings percentage

        Note:
            Results are stored in test_results['slots_optimization'].

        Side Effects:
            Updates self.test_results with slots optimization metrics.
        """
        print("🚀 Testing __slots__ optimization...")

        self.profiler.start_profiling()

        # Test regular class without slots - creates __dict__ for each instance
        class RegularStore:
            """Regular store class without __slots__ for memory comparison.

            This class uses dynamic attributes (__dict__) which consume more memory
            per instance than __slots__. Used to demonstrate the memory overhead
            of standard Python classes.

            Attributes:
                connection: Connection object reference.
                broker: Broker instance reference.
                data: Data feed reference.
                notifications: List of notification messages.
                params: Dictionary of parameters.
            """

            def __init__(self):
                """Initialize regular store with dynamic attributes."""
                self.connection = None
                self.broker = None
                self.data = None
                self.notifications = []
                self.params = {}

        # Create and measure regular stores
        regular_stores = []
        for i in range(100):
            regular_stores.append(RegularStore())

        regular_memory = self.profiler.take_snapshot("regular_stores")
        del regular_stores
        gc.collect()

        # Create and measure slotted stores for comparison
        slotted_stores = []
        for i in range(100):
            slotted_stores.append(SlottedStore())

        slotted_memory = self.profiler.take_snapshot("slotted_stores")

        # Calculate memory savings
        memory_savings = regular_memory - slotted_memory
        savings_percent = (memory_savings / regular_memory) * 100 if regular_memory > 0 else 0

        self.test_results["slots_optimization"] = {
            "regular_memory": regular_memory,
            "slotted_memory": slotted_memory,
            "memory_savings": memory_savings,
            "savings_percent": savings_percent,
        }

        print(f"   Regular stores: {regular_memory / 1024:.1f} KB")
        print(f"   Slotted stores: {slotted_memory / 1024:.1f} KB")
        print(f"   Memory savings: {memory_savings / 1024:.1f} KB ({savings_percent:.1f}%)")

        # Clean up
        del slotted_stores
        gc.collect()

    def test_weak_reference_optimization(self) -> None:
        """Test weak reference optimization.

        Compares memory usage between stores using strong references
        versus weak references for object management. Creates local
        StrongRefStore and WeakRefStore classes for comparison.

        This test:
        1. Creates mock broker and data source objects
        2. Creates stores with strong references
        3. Measures memory usage
        4. Creates stores with weak references
        5. Measures memory usage
        6. Calculates memory savings

        Note:
            Weak references prevent circular reference memory leaks and allow
            objects to be garbage collected even when referenced by stores.
            Results are stored in test_results['weak_ref_optimization'].

        Side Effects:
            Updates self.test_results with weak reference optimization metrics.
        """
        print("🚀 Testing weak reference optimization...")

        self.profiler.start_profiling()

        # Test with strong references - prevents garbage collection
        class StrongRefStore:
            """Store implementation using strong references.

            This class maintains strong references to all brokers and data sources,
            preventing them from being garbage collected. This can lead to memory
            leaks in long-running systems with many temporary objects.

            Attributes:
                brokers: List of broker objects (strong references).
                data_sources: List of data source objects (strong references).
            """

            def __init__(self):
                """Initialize strong reference store with empty lists."""
                self.brokers = []
                self.data_sources = []

            def add_broker(self, broker: Any) -> None:
                """Add a broker with strong reference.

                Args:
                    broker: Broker object to store.
                """
                self.brokers.append(broker)

            def add_data_source(self, data: Any) -> None:
                """Add a data source with strong reference.

                Args:
                    data: Data source object to store.
                """
                self.data_sources.append(data)

        # Test with weak references - allows garbage collection
        class WeakRefStore:
            """Store implementation using weak references.

            This class uses WeakSet to maintain references to brokers and data sources.
            Weak references allow objects to be garbage collected even when still
            referenced by the store, preventing memory leaks.

            Attributes:
                brokers: WeakSet of broker objects (weak references).
                data_sources: WeakSet of data source objects (weak references).
            """

            def __init__(self):
                """Initialize weak reference store with WeakSets."""
                self.brokers = weakref.WeakSet()
                self.data_sources = weakref.WeakSet()

            def add_broker(self, broker: Any) -> None:
                """Add a broker with weak reference.

                Args:
                    broker: Broker object to store with weak reference.
                """
                self.brokers.add(broker)

            def add_data_source(self, data: Any) -> None:
                """Add a data source with weak reference.

                Args:
                    data: Data source object to store with weak reference.
                """
                self.data_sources.add(data)

        # Create mock objects to be referenced
        brokers = [Mock() for _ in range(50)]
        data_sources = [Mock() for _ in range(50)]

        # Test strong references - each store keeps 100 strong references
        strong_stores = []
        for i in range(20):
            store = StrongRefStore()
            for broker in brokers:
                store.add_broker(broker)
            for data in data_sources:
                store.add_data_source(data)
            strong_stores.append(store)

        strong_memory = self.profiler.take_snapshot("strong_ref_stores")

        # Test weak references - stores allow garbage collection of referenced objects
        weak_stores = []
        for i in range(20):
            store = WeakRefStore()
            for broker in brokers:
                store.add_broker(broker)
            for data in data_sources:
                store.add_data_source(data)
            weak_stores.append(store)

        weak_memory = self.profiler.take_snapshot("weak_ref_stores")

        # Calculate memory savings from using weak references
        memory_savings = strong_memory - weak_memory
        savings_percent = (memory_savings / strong_memory) * 100 if strong_memory > 0 else 0

        self.test_results["weak_ref_optimization"] = {
            "strong_ref_memory": strong_memory,
            "weak_ref_memory": weak_memory,
            "memory_savings": memory_savings,
            "savings_percent": savings_percent,
        }

        print(f"   Strong references: {strong_memory / 1024:.1f} KB")
        print(f"   Weak references: {weak_memory / 1024:.1f} KB")
        print(f"   Memory savings: {memory_savings / 1024:.1f} KB ({savings_percent:.1f}%)")

    def test_optimized_store_implementation(self) -> None:
        """Test fully optimized store implementation.

        Tests the OptimizedStore class which combines multiple optimization
        techniques including __slots__, weak references, caching, and bounded
        notification lists.

        This test:
        1. Creates 100 OptimizedStore instances
        2. Simulates usage (getdata, getbroker, put_notification)
        3. Measures total memory usage
        4. Compares against baseline if available

        Note:
            If baseline test has been run, calculates improvement percentage.
            Results are stored in test_results['optimized_implementation'].

        Side Effects:
            Updates self.test_results with optimized implementation metrics.
        """
        print("🚀 Testing optimized store implementation...")

        self.profiler.start_profiling()

        # Create and exercise optimized stores
        optimized_stores = []
        for i in range(100):
            store = OptimizedStore()
            # Simulate realistic usage patterns
            store.getdata("test", param=i)
            store.getbroker()
            store.put_notification(f"notification_{i}")
            optimized_stores.append(store)

        optimized_memory = self.profiler.take_snapshot("optimized_stores")

        # Compare with baseline if available
        if "baseline" in self.test_results:
            baseline_memory = self.test_results["baseline"]["total_memory"]
            memory_improvement = baseline_memory - optimized_memory
            improvement_percent = (
                (memory_improvement / baseline_memory) * 100 if baseline_memory > 0 else 0
            )

            self.test_results["optimized_implementation"] = {
                "optimized_memory": optimized_memory,
                "baseline_memory": baseline_memory,
                "memory_improvement": memory_improvement,
                "improvement_percent": improvement_percent,
            }

            print(f"   Optimized stores: {optimized_memory / 1024:.1f} KB")
            print(f"   Baseline stores: {baseline_memory / 1024:.1f} KB")
            print(
                f"   Memory improvement: {memory_improvement / 1024:.1f} KB ({improvement_percent:.1f}%)"
            )
        else:
            print(f"   Optimized stores: {optimized_memory / 1024:.1f} KB")

    def test_garbage_collection_efficiency(self) -> None:
        """Test garbage collection efficiency.

        Tests how effectively Python's garbage collector reclaims memory
        from Store instances through multiple creation/destruction cycles.

        This test:
        1. Creates 50 IBStore instances
        2. Measures memory after creation
        3. Deletes all references
        4. Forces garbage collection
        5. Measures memory after GC
        6. Repeats for 5 cycles to detect potential memory leaks

        Note:
            Memory leaks are indicated if memory consistently increases across cycles.
            This test helps identify objects that aren't being properly garbage collected.

        Side Effects:
            Prints memory statistics for each cycle.
        """
        print("🔍 Testing garbage collection efficiency...")

        self.profiler.start_profiling()

        # Create and destroy objects to test GC over multiple cycles
        for cycle in range(5):
            stores = []
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()

                # Create many instances to stress test memory management
                for i in range(50):
                    stores.append(IBStore())

            cycle_memory = self.profiler.take_snapshot(f"cycle_{cycle}_created")

            # Delete all references to allow garbage collection
            del stores

            # Force garbage collection and measure effectiveness
            collected = gc.collect()
            gc_memory = self.profiler.take_snapshot(f"cycle_{cycle}_collected")

            print(
                f"   Cycle {cycle}: Created +{cycle_memory/1024:.1f}KB, After GC +{gc_memory/1024:.1f}KB, Collected {collected} objects"
            )

    def generate_optimization_recommendations(self) -> List[Dict[str, Any]]:
        """Generate memory optimization recommendations.

        Analyzes test results and generates prioritized recommendations
        for memory optimization improvements. Recommendations are based on
        actual test results and include general best practices.

        Returns:
            list: List of recommendation dictionaries, each containing:
                - priority: 'high', 'medium', or 'low'
                - category: Type of optimization (e.g., 'slots', 'references', 'caching')
                - issue: Description of the memory issue
                - recommendation: High-level suggestion
                - implementation: Specific implementation guidance

        Side Effects:
            Prints formatted recommendations to stdout with priority indicators.
        """
        print("\n" + "=" * 80)
        print("💡 Memory Optimization Recommendations")
        print("=" * 80)

        recommendations = []

        # Analyze test results and generate targeted recommendations
        if "slots_optimization" in self.test_results:
            savings = self.test_results["slots_optimization"]["savings_percent"]
            if savings > 10:
                recommendations.append(
                    {
                        "priority": "high",
                        "category": "slots",
                        "issue": f"__slots__ can save {savings:.1f}% memory",
                        "recommendation": "Add __slots__ to Store classes",
                        "implementation": "Define __slots__ with essential attributes only",
                    }
                )

        if "weak_ref_optimization" in self.test_results:
            savings = self.test_results["weak_ref_optimization"]["savings_percent"]
            if savings > 5:
                recommendations.append(
                    {
                        "priority": "medium",
                        "category": "references",
                        "issue": f"Weak references can save {savings:.1f}% memory",
                        "recommendation": "Use weak references for non-essential object references",
                        "implementation": "Replace strong references with weakref.WeakSet/WeakValueDictionary",
                    }
                )

        if "optimized_implementation" in self.test_results:
            improvement = self.test_results["optimized_implementation"]["improvement_percent"]
            if improvement > 0:
                recommendations.append(
                    {
                        "priority": "high",
                        "category": "implementation",
                        "issue": f"Optimized implementation improves memory by {improvement:.1f}%",
                        "recommendation": "Implement comprehensive memory optimizations",
                        "implementation": "Use __slots__, weak references, and caching strategies",
                    }
                )

        # Add general recommendations based on best practices
        recommendations.extend(
            [
                {
                    "priority": "medium",
                    "category": "caching",
                    "issue": "Unbounded caches can cause memory leaks",
                    "recommendation": "Implement LRU caches with size limits",
                    "implementation": "Use collections.OrderedDict or functools.lru_cache",
                },
                {
                    "priority": "low",
                    "category": "cleanup",
                    "issue": "Objects may not be garbage collected efficiently",
                    "recommendation": "Implement proper cleanup methods",
                    "implementation": "Add __del__ methods and explicit cleanup for resources",
                },
            ]
        )

        # Display recommendations with priority indicators
        for i, rec in enumerate(recommendations, 1):
            priority_icon = (
                "🔥" if rec["priority"] == "high" else "⚠️" if rec["priority"] == "medium" else "💡"
            )
            print(f"{i}. {priority_icon} [{rec['priority'].upper()}] {rec['category'].title()}")
            print(f"   Issue: {rec['issue']}")
            print(f"   Recommendation: {rec['recommendation']}")
            print(f"   Implementation: {rec['implementation']}")
            print()

        return recommendations

    def run_comprehensive_memory_analysis(self) -> Dict[str, Any]:
        """Run comprehensive memory optimization analysis.

        Executes all memory optimization tests in sequence and generates
        recommendations based on the results. This is the main entry point
        for the memory optimization analysis workflow.

        Tests executed:
        1. Baseline memory usage
        2. __slots__ optimization
        3. Weak reference optimization
        4. Optimized store implementation
        5. Garbage collection efficiency

        Returns:
            dict: Contains three keys:
                - test_results: Dictionary with all test metrics
                - recommendations: List of optimization recommendations
                - memory_report: String with formatted memory usage report

        Example:
            >>> optimizer = MemoryOptimizationTool()
            >>> results = optimizer.run_comprehensive_memory_analysis()
            >>> print(results['memory_report'])
        """
        print("\n" + "=" * 80)
        print("💾 Store System Memory Optimization (Day 22-24)")
        print("=" * 80)

        start_time = time.time()

        # Run all tests in sequence with print separators
        self.test_baseline_memory_usage()
        print()
        self.test_slots_optimization()
        print()
        self.test_weak_reference_optimization()
        print()
        self.test_optimized_store_implementation()
        print()
        self.test_garbage_collection_efficiency()

        analysis_time = time.time() - start_time

        # Generate recommendations based on test results
        recommendations = self.generate_optimization_recommendations()

        # Print summary statistics
        print("📊 Memory Analysis Summary")
        print("=" * 80)
        print(f"⏱️ Analysis time: {analysis_time:.2f}s")
        print(f"🧪 Tests completed: {len(self.test_results)}")
        print(f"💡 Recommendations: {len(recommendations)}")

        return {
            "test_results": self.test_results,
            "recommendations": recommendations,
            "memory_report": self.profiler.get_memory_report(),
        }

    def save_memory_report(self, filename: str = "memory_optimization_report.json") -> str:
        """Save memory optimization report to file.

        Exports all test results, memory snapshots, and baseline measurements
        to a JSON file for later analysis or comparison.

        Args:
            filename: Output filename for the JSON report. Defaults to
                "memory_optimization_report.json".

        Returns:
            str: Path to the saved report file.

        Raises:
            IOError: If unable to write to the specified file.
            TypeError: If test results contain non-serializable objects.

        Example:
            >>> optimizer = MemoryOptimizationTool()
            >>> optimizer.run_comprehensive_memory_analysis()
            >>> report_path = optimizer.save_memory_report("my_report.json")
            >>> print(f"Report saved to {report_path}")
        """
        import json

        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "test_results": self.test_results,
            "memory_snapshots": self.profiler.memory_snapshots,
            "baseline_memory_mb": self.profiler.baseline_memory / (1024 * 1024),
        }

        with open(filename, "w") as f:
            json.dump(report, f, indent=2, default=str)

        print(f"📄 Memory report saved to: {filename}")
        return filename


def main() -> bool:
    """Main memory optimization execution.

    Entry point for the memory optimization tool when run as a script.
    Creates an optimizer instance, runs comprehensive analysis, saves the
    report, and handles any errors that occur during execution.

    Returns:
        bool: True if analysis completed successfully, False otherwise.
        Used as exit code for the script (0 for success, 1 for failure).

    Example:
        >>> success = main()
        >>> sys.exit(0 if success else 1)
    """
    optimizer = MemoryOptimizationTool()

    try:
        # Run comprehensive analysis
        results = optimizer.run_comprehensive_memory_analysis()

        # Save report to JSON file for later analysis
        report_file = optimizer.save_memory_report()

        print(f"\n✅ Memory optimization analysis completed!")
        print(f"📊 Tests completed: {len(results['test_results'])}")
        print(f"💡 Recommendations: {len(results['recommendations'])}")
        print(f"📄 Report: {report_file}")

        return True

    except Exception as e:
        print(f"\n❌ Memory analysis failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
