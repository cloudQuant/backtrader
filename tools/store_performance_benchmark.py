#!/usr/bin/env python
"""Performance benchmark tool for Store system.

This module provides comprehensive benchmarking capabilities for the backtrader
Store system, measuring singleton creation/access performance, thread safety,
memory usage, method execution time, and parameter access patterns.

The tool uses statistical analysis (mean, median, standard deviation) to provide
reliable performance metrics and identifies potential performance regressions.

Example:
    >>> benchmark = StoreBenchmark()
    >>> results = benchmark.run_all_benchmarks()
    >>> report_file = benchmark.generate_report()
"""

import gc
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import Mock, patch

import psutil

# Mock external dependencies that are not required for benchmarking
sys.modules["oandapy"] = Mock()
sys.modules["ccxt"] = Mock()
sys.modules["ctpbee"] = Mock()
sys.modules["ctpbee.api"] = Mock()
sys.modules["ctpbee.constant"] = Mock()
sys.modules["ctpbee.helpers"] = Mock()

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.stores.ibstore import IBStore


class StoreBenchmark:
    """Performance benchmark tool for Store system.

    Provides comprehensive benchmarking of the Store singleton pattern,
    measuring creation time, access speed, thread safety, memory efficiency,
    method performance, and parameter access patterns.

    Attributes:
        results (dict): Stores all benchmark results organized by category.
            Keys include "singleton_creation", "thread_safety", "memory_usage",
            "method_performance", and "parameter_performance".
        process (psutil.Process): Process object for memory measurements,
            initialized to the current process.

    Example:
        >>> benchmark = StoreBenchmark()
        >>> benchmark.benchmark_singleton_creation()
        >>> benchmark.benchmark_thread_safety()
        >>> results = benchmark.results
    """

    def __init__(self):
        """Initialize the benchmark tool.

        Creates an empty results dictionary and initializes a process object
        for memory measurements. The process object tracks the current Python
        process for memory usage monitoring.
        """
        self.results = {}
        self.process = psutil.Process(os.getpid())

    def reset_stores(self):
        """Reset all store singletons before benchmark runs.

        Resets the IBStore singleton instance and forces garbage collection
        to ensure clean test conditions for each benchmark. This prevents
        state leakage between tests and ensures accurate measurements.

        Note:
            Only resets if IBStore has the _reset_instance method.
        """
        if hasattr(IBStore, "_reset_instance"):
            IBStore._reset_instance()
        gc.collect()

    def measure_time(self, func, iterations=100):
        """Measure execution time of a function with statistical analysis.

        Executes the function multiple times and calculates statistical metrics
        including mean, median, min, max, standard deviation, and total time.

        Args:
            func (callable): Function to benchmark. Should take no arguments.
            iterations (int, optional): Number of times to execute the function.
                Defaults to 100.

        Returns:
            dict: Dictionary containing statistical metrics:
                - mean (float): Average execution time in seconds
                - median (float): Median execution time in seconds
                - min (float): Minimum execution time in seconds
                - max (float): Maximum execution time in seconds
                - stdev (float): Standard deviation in seconds
                - total (float): Total execution time across all iterations
                - iterations (int): Number of iterations performed

        Example:
            >>> def my_function():
            ...     return sum(range(1000))
            >>> metrics = benchmark.measure_time(my_function, iterations=1000)
            >>> print(f"Mean: {metrics['mean']*1000:.3f}ms")
        """
        times = []
        for _ in range(iterations):
            start_time = time.perf_counter()
            result = func()
            end_time = time.perf_counter()
            times.append(end_time - start_time)

        return {
            "mean": statistics.mean(times),
            "median": statistics.median(times),
            "min": min(times),
            "max": max(times),
            "stdev": statistics.stdev(times) if len(times) > 1 else 0,
            "total": sum(times),
            "iterations": len(times),
        }

    def measure_memory(self, func):
        """Measure memory usage of a function.

        Measures RSS (Resident Set Size) memory before and after function execution
        to calculate memory increase. Forces garbage collection before and after
        to ensure accurate measurements.

        Args:
            func (callable): Function to measure. Should take no arguments.

        Returns:
            dict: Dictionary containing memory metrics:
                - initial_mb (float): Initial memory in MB
                - final_mb (float): Final memory in MB
                - increase_mb (float): Memory increase in MB
                - result: Return value of the function

        Note:
            RSS measures the actual physical memory used by the process.
            Garbage collection is performed before and after to minimize
            noise from temporary objects.
        """
        gc.collect()  # Clean up before measurement to get accurate baseline
        initial_memory = self.process.memory_info().rss

        result = func()

        gc.collect()  # Clean up after to measure retained memory
        final_memory = self.process.memory_info().rss

        return {
            "initial_mb": initial_memory / (1024 * 1024),
            "final_mb": final_memory / (1024 * 1024),
            "increase_mb": (final_memory - initial_memory) / (1024 * 1024),
            "result": result,
        }

    def benchmark_singleton_creation(self):
        """Benchmark singleton instance creation and access.

        Measures performance of:
        1. First-time singleton creation (initialization overhead)
        2. Subsequent singleton access (caching effectiveness)

        Calculates speedup ratio to quantify the benefit of singleton caching.

        Prints:
            First creation time, subsequent access time, and speedup ratio.
        """
        print("Benchmarking singleton creation...")

        def create_first_instance():
            """Create first singleton instance - includes initialization."""
            self.reset_stores()
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                return IBStore()

        def create_subsequent_instance():
            """Access existing singleton - should be cached."""
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                return IBStore()

        # Benchmark first creation - measures initialization cost
        first_creation = self.measure_time(create_first_instance, iterations=10)

        # Create initial instance for subsequent tests
        self.reset_stores()
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            IBStore()

        # Benchmark subsequent access - measures cache lookup performance
        subsequent_access = self.measure_time(create_subsequent_instance, iterations=1000)

        self.results["singleton_creation"] = {
            "first_creation": first_creation,
            "subsequent_access": subsequent_access,
            "speedup_ratio": first_creation["mean"] / subsequent_access["mean"],
        }

        print(f"   First creation: {first_creation['mean']*1000:.3f}ms (avg)")
        print(f"   Subsequent access: {subsequent_access['mean']*1000:.6f}ms (avg)")
        print(f"   Speedup ratio: {self.results['singleton_creation']['speedup_ratio']:.1f}x")

    def benchmark_thread_safety(self):
        """Benchmark thread safety performance under concurrent access.

        Tests singleton access with 10 threads performing 50 total operations
        to measure synchronization overhead and detect potential contention.

        Prints:
            Mean, max, and min concurrent access times.

        Note:
            Uses ThreadPoolExecutor for concurrent execution and measures
            individual operation completion times.
        """
        print("Benchmarking thread safety...")

        self.reset_stores()

        def concurrent_access():
            """Perform concurrent singleton access from multiple threads."""
            results = []

            def create_instance():
                with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                    mock_ibopt.ibConnection.return_value = Mock()
                    start_time = time.perf_counter()
                    store = IBStore()
                    end_time = time.perf_counter()
                    return end_time - start_time

            # Test concurrent access with multiple threads
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(create_instance) for _ in range(50)]
                for future in as_completed(futures):
                    results.append(future.result())

            return results

        # Run concurrent access test
        concurrent_times = concurrent_access()

        self.results["thread_safety"] = {
            "mean_concurrent_time": statistics.mean(concurrent_times),
            "max_concurrent_time": max(concurrent_times),
            "min_concurrent_time": min(concurrent_times),
            "concurrent_threads": 10,
            "total_operations": 50,
        }

        print(
            f"   Concurrent access (10 threads, 50 ops): {statistics.mean(concurrent_times)*1000:.3f}ms (avg)"
        )
        print(f"   Max concurrent time: {max(concurrent_times)*1000:.3f}ms")
        print(f"   Min concurrent time: {min(concurrent_times)*1000:.3f}ms")

    def benchmark_memory_usage(self):
        """Benchmark memory usage of singleton pattern.

        Creates 1000 singleton references and measures memory increase.
        Since singleton should return the same instance, memory growth
        should be minimal (only reference storage).

        Prints:
            Initial memory, final memory, total increase, and memory per reference.
        """
        print("Benchmarking memory usage...")

        def create_many_references():
            """Create many references to singleton to test memory efficiency."""
            stores = []
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                for _ in range(1000):
                    stores.append(IBStore())
            return len(stores)

        self.reset_stores()
        memory_result = self.measure_memory(create_many_references)

        self.results["memory_usage"] = memory_result

        print(f"   Initial memory: {memory_result['initial_mb']:.2f}MB")
        print(f"   Final memory: {memory_result['final_mb']:.2f}MB")
        print(f"   Memory increase: {memory_result['increase_mb']:.2f}MB for 1000 references")
        print(f"   Memory per reference: {memory_result['increase_mb']/1000*1024:.1f}KB")

    def benchmark_method_performance(self):
        """Benchmark performance of store methods.

        Measures execution time for commonly used store methods:
        - getdata(): Create data feed from store
        - getbroker(): Create broker from store
        - notifications: Put and get notifications

        Prints:
            Average execution time in microseconds for each method.
        """
        print("Benchmarking method performance...")

        self.reset_stores()
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()

        def test_getdata():
            """Test getdata method performance."""
            return store.getdata()

        def test_getbroker():
            """Test getbroker method performance."""
            return store.getbroker()

        def test_notifications():
            """Test notification system performance."""
            store.put_notification("test message")
            return store.get_notifications()

        # Benchmark different methods with 1000 iterations each
        getdata_perf = self.measure_time(test_getdata, iterations=1000)
        getbroker_perf = self.measure_time(test_getbroker, iterations=1000)
        notifications_perf = self.measure_time(test_notifications, iterations=1000)

        self.results["method_performance"] = {
            "getdata": getdata_perf,
            "getbroker": getbroker_perf,
            "notifications": notifications_perf,
        }

        print(f"   getdata(): {getdata_perf['mean']*1000000:.1f}us (avg)")
        print(f"   getbroker(): {getbroker_perf['mean']*1000000:.1f}us (avg)")
        print(f"   notifications: {notifications_perf['mean']*1000000:.1f}us (avg)")

    def benchmark_parameter_access(self):
        """Benchmark parameter system performance.

        Measures performance of different parameter access patterns:
        - Direct parameter access via .p attribute
        - Legacy .params attribute access

        Prints:
            Average execution time in microseconds for each access pattern.

        Note:
            Tests both the recommended .p access and legacy .params for
            compatibility comparison.
        """
        print("Benchmarking parameter access...")

        self.reset_stores()
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()

        def access_parameters():
            """Access parameters via .p attribute."""
            if hasattr(store, "p"):
                return dict(store.p._getpairs())
            return {}

        def access_params_attr():
            """Access parameters via legacy .params attribute."""
            return getattr(store, "params", None)

        # Benchmark parameter access patterns
        param_access_perf = self.measure_time(access_parameters, iterations=1000)
        param_attr_perf = self.measure_time(access_params_attr, iterations=1000)

        self.results["parameter_performance"] = {
            "parameter_access": param_access_perf,
            "params_attribute": param_attr_perf,
        }

        print(f"   Parameter access: {param_access_perf['mean']*1000000:.1f}us (avg)")
        print(f"   Params attribute: {param_attr_perf['mean']*1000000:.1f}us (avg)")

    def run_all_benchmarks(self):
        """Run all performance benchmarks.

        Executes the complete benchmark suite:
        1. Singleton creation and access
        2. Thread safety under concurrent access
        3. Memory usage patterns
        4. Method execution performance
        5. Parameter access performance

        Prints comprehensive performance summary with all results.

        Returns:
            dict: Complete benchmark results containing all test categories
                with their respective metrics.
        """
        print("\n" + "=" * 80)
        print("Store System Performance Benchmark (Day 19-21)")
        print("=" * 80)

        start_time = time.time()

        # Run all benchmark tests
        self.benchmark_singleton_creation()
        print()
        self.benchmark_thread_safety()
        print()
        self.benchmark_memory_usage()
        print()
        self.benchmark_method_performance()
        print()
        self.benchmark_parameter_access()

        total_time = time.time() - start_time

        print("\n" + "=" * 80)
        print("Performance Summary")
        print("=" * 80)

        # Singleton performance metrics
        singleton_results = self.results["singleton_creation"]
        print(f"Singleton Performance:")
        print(f"   First creation: {singleton_results['first_creation']['mean']*1000:.3f}ms")
        print(f"   Subsequent access: {singleton_results['subsequent_access']['mean']*1000:.6f}ms")
        print(f"   Performance improvement: {singleton_results['speedup_ratio']:.1f}x faster")

        # Memory efficiency metrics
        memory_results = self.results["memory_usage"]
        print(f"\nMemory Efficiency:")
        print(f"   Memory per reference: {memory_results['increase_mb']/1000*1024:.1f}KB")
        print(f"   Total overhead for 1000 refs: {memory_results['increase_mb']:.2f}MB")

        # Thread safety metrics
        thread_results = self.results["thread_safety"]
        print(f"\nThread Safety:")
        print(f"   Concurrent access time: {thread_results['mean_concurrent_time']*1000:.3f}ms")
        print(f"   Threads: {thread_results['concurrent_threads']}")
        print(f"   Total operations: {thread_results['total_operations']}")

        # Method performance metrics
        method_results = self.results["method_performance"]
        print(f"\nMethod Performance:")
        print(f"   getdata(): {method_results['getdata']['mean']*1000000:.1f}us")
        print(f"   getbroker(): {method_results['getbroker']['mean']*1000000:.1f}us")
        print(f"   notifications: {method_results['notifications']['mean']*1000000:.1f}us")

        print(f"\nTotal benchmark time: {total_time:.2f}s")
        print("=" * 80)

        return self.results

    def generate_report(self, filename="store_performance_report.json"):
        """Generate detailed performance report in JSON format.

        Creates a comprehensive report including system information,
        timestamp, and all benchmark results for archival or comparison.

        Args:
            filename (str, optional): Output filename. Defaults to
                "store_performance_report.json".

        Returns:
            str: Absolute path to the saved report file.

        Raises:
            IOError: If unable to write to the specified file.
            TypeError: If results contain non-serializable objects.

        Note:
            Report includes system info (Python version, CPU count, memory)
            for context when comparing results across different machines.
        """
        import json

        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "system_info": {
                "python_version": sys.version,
                "cpu_count": os.cpu_count(),
                "memory_total_mb": psutil.virtual_memory().total / (1024 * 1024),
            },
            "results": self.results,
        }

        with open(filename, "w") as f:
            json.dump(report, f, indent=2)

        print(f"Performance report saved to: {filename}")

        return filename


def main():
    """Main benchmark execution function.

    Creates a StoreBenchmark, runs all benchmarks, generates report,
    and displays summary statistics. Handles exceptions gracefully
    and returns appropriate exit code.

    Returns:
        bool: True if benchmark completed successfully, False otherwise.

    Raises:
        Exception: Propagates any unexpected exceptions during benchmarking.
        Exceptions are caught, logged, and converted to False return.

    Example:
        >>> success = main()
        >>> sys.exit(0 if success else 1)
    """
    benchmark = StoreBenchmark()

    try:
        # Run all benchmark tests
        results = benchmark.run_all_benchmarks()

        # Generate detailed JSON report
        report_file = benchmark.generate_report()

        print(f"\nBenchmark completed successfully!")
        print(f"Results: {len(results)} test categories completed")
        print(f"Report: {report_file}")

        return True

    except Exception as e:
        print(f"\nBenchmark failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
