#!/usr/bin/env python
"""Performance bottleneck analyzer for the Store system.

This module provides comprehensive profiling and analysis tools to identify
performance bottlenecks in the backtrader Store system, with particular focus
on singleton pattern implementation, thread contention, method performance,
and memory usage patterns.

The analyzer uses cProfile, tracemalloc, and psutil to collect detailed metrics
about execution time, memory consumption, and resource utilization during various
operations.

Example:
    >>> analyzer = PerformanceBottleneckAnalyzer()
    >>> results = analyzer.run_full_analysis()
    >>> analyzer.save_analysis_report()
"""

import cProfile
import gc
import io
import os
import pstats
import sys
import threading
import time
import tracemalloc
from collections import defaultdict
from contextlib import contextmanager
from unittest.mock import Mock, patch

import psutil

# Mock external dependencies that are not required for analysis
sys.modules["oandapy"] = Mock()
sys.modules["ccxt"] = Mock()
sys.modules["ctpbee"] = Mock()
sys.modules["ctpbee.api"] = Mock()
sys.modules["ctpbee.constant"] = Mock()
sys.modules["ctpbee.helpers"] = Mock()

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.stores.ibstore import IBStore


class PerformanceBottleneckAnalyzer:
    """Analyze performance bottlenecks in Store system.

    This class provides comprehensive analysis tools to identify performance
    bottlenecks in singleton creation, thread contention, method execution,
    and memory usage patterns within the backtrader Store system.

    Attributes:
        profiling_results (dict): Stores detailed profiling data for each operation.
            Keys are operation names, values are dicts containing execution_time,
            memory_increase, memory_trace, and profiler_stats.
        memory_snapshots (list): List of (iteration, memory_mb) tuples tracking
            memory usage over time during operations.
        timing_data (defaultdict): Dictionary mapping operation names to lists
            of execution times for statistical analysis.
        bottlenecks (list): List of detected bottleneck dictionaries, each
            containing type, operation, time/memory metrics, and severity level.

    Example:
        >>> analyzer = PerformanceBottleneckAnalyzer()
        >>> analyzer.analyze_singleton_creation_bottlenecks()
        >>> analyzer.analyze_thread_contention()
        >>> recommendations = analyzer.generate_optimization_recommendations()
    """

    def __init__(self):
        """Initialize the performance bottleneck analyzer.

        Creates empty data structures to store profiling results, memory snapshots,
        timing data, and detected bottlenecks.
        """
        self.profiling_results = {}
        self.memory_snapshots = []
        self.timing_data = defaultdict(list)
        self.bottlenecks = []

    def reset_environment(self):
        """Reset test environment between analysis runs.

        Resets the IBStore singleton instance and forces garbage collection
        to ensure clean test conditions for each profiling operation.
        This prevents state leakage between tests and ensures accurate measurements.

        Raises:
            AttributeError: If IBStore doesn't have _reset_instance method.
        """
        if hasattr(IBStore, "_reset_instance"):
            IBStore._reset_instance()
        gc.collect()

    @contextmanager
    def profile_execution(self, operation_name):
        """Profile code execution with detailed timing and memory tracking.

        Context manager that enables profiling for a block of code, collecting
        execution time, memory usage, and cProfile statistics. Results are
        automatically stored in profiling_results and timing_data.

        Args:
            operation_name (str): Name/identifier for the operation being profiled.
                Used as key in profiling_results and timing_data dictionaries.

        Yields:
            None: Context manager for use with 'with' statement.

        Example:
            >>> with analyzer.profile_execution("test_operation"):
            ...     # Code to profile
            ...     perform_operation()
            >>> results = analyzer.profiling_results["test_operation"]

        Note:
            Starts tracemalloc and cProfile before executing the code block,
            and captures both timing and memory metrics upon completion.
        """
        # Start memory tracking to measure allocation changes
        tracemalloc.start()
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss

        # Start profiling to capture function-level timing
        profiler = cProfile.Profile()
        start_time = time.perf_counter()

        profiler.enable()
        try:
            yield
        finally:
            profiler.disable()
            end_time = time.perf_counter()

            # Capture final memory state and take snapshot
            current_memory = process.memory_info().rss
            memory_trace = tracemalloc.take_snapshot()
            tracemalloc.stop()

            # Calculate metrics and store results
            execution_time = end_time - start_time
            memory_increase = current_memory - initial_memory

            self.profiling_results[operation_name] = {
                "execution_time": execution_time,
                "memory_increase": memory_increase,
                "memory_trace": memory_trace,
                "profiler_stats": profiler,
            }

            self.timing_data[operation_name].append(execution_time)

    def analyze_singleton_creation_bottlenecks(self):
        """Analyze bottlenecks in singleton creation and access.

        Tests both first-time singleton creation and subsequent accesses to
        identify initialization overhead and caching effectiveness. Compares
        timing against thresholds to detect slow initialization or access patterns.

        The analysis identifies two types of bottlenecks:
        - Slow initialization: First creation takes > 5ms
        - Slow access: Subsequent access takes > 0.1ms

        Prints:
            Timing results for first creation and subsequent access (100 iterations).

        Note:
            Uses mocked ibopt to avoid actual network connections during testing.
        """
        print("Analyzing singleton creation bottlenecks...")

        # Test first creation - measures initialization overhead
        self.reset_environment()
        with self.profile_execution("first_creation"):
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                store = IBStore()

        # Test subsequent access - measures singleton retrieval performance
        with self.profile_execution("subsequent_access"):
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                for _ in range(100):
                    store = IBStore()

        # Analyze results and identify performance issues
        first_time = self.profiling_results["first_creation"]["execution_time"]
        subsequent_avg = sum(self.timing_data["subsequent_access"]) / len(
            self.timing_data["subsequent_access"]
        )

        print(f"   First creation: {first_time*1000:.3f}ms")
        print(f"   Subsequent access (100x): {subsequent_avg*1000000:.1f}us avg")

        # Flag bottlenecks if thresholds exceeded
        if first_time > 0.005:  # > 5ms indicates slow initialization
            self.bottlenecks.append(
                {
                    "type": "slow_initialization",
                    "operation": "first_creation",
                    "time": first_time,
                    "severity": "high" if first_time > 0.01 else "medium",
                }
            )

        if subsequent_avg > 0.0001:  # > 0.1ms indicates slow access
            self.bottlenecks.append(
                {
                    "type": "slow_access",
                    "operation": "subsequent_access",
                    "time": subsequent_avg,
                    "severity": "medium",
                }
            )

    def analyze_thread_contention(self):
        """Analyze thread contention and synchronization bottlenecks.

        Tests concurrent singleton access with increasing thread counts (1, 2, 5, 10, 20)
        to identify lock contention and synchronization overhead. Compares actual
        execution time against expected linear scaling to detect contention.

        A bottleneck is flagged when execution time exceeds 1.5x the expected
        linear scaling, indicating significant thread contention.

        Prints:
            Execution times for each thread count tested.

        Note:
            Creates multiple threads that simultaneously attempt to access
            the singleton, measuring total completion time.
        """
        print("Analyzing thread contention...")

        self.reset_environment()
        contention_times = []

        def concurrent_access():
            """Access singleton concurrently - used as thread target."""
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                start_time = time.perf_counter()
                store = IBStore()
                end_time = time.perf_counter()
                contention_times.append(end_time - start_time)

        # Test with increasing thread counts to find contention threshold
        for thread_count in [1, 2, 5, 10, 20]:
            test_times = []

            with self.profile_execution(f"threads_{thread_count}"):
                threads = []
                for _ in range(thread_count):
                    thread = threading.Thread(target=concurrent_access)
                    threads.append(thread)

                # Start all threads and measure total time
                start_time = time.perf_counter()
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                end_time = time.perf_counter()

                test_times.append(end_time - start_time)

            avg_time = sum(test_times) / len(test_times) if test_times else 0
            print(f"   {thread_count} threads: {avg_time*1000:.3f}ms total")

            # Detect contention if time scales worse than 1.5x linear
            if (
                thread_count > 1
                and avg_time > (test_times[0] if test_times else 0) * thread_count * 1.5
            ):
                self.bottlenecks.append(
                    {
                        "type": "thread_contention",
                        "operation": f"threads_{thread_count}",
                        "time": avg_time,
                        "severity": "high" if avg_time > 0.1 else "medium",
                    }
                )

    def analyze_method_performance(self):
        """Analyze performance of Store methods.

        Benchmarks commonly used Store methods (getdata, getbroker, put_notification,
        get_notifications) with 1000 iterations each to identify slow method implementations.

        Methods taking > 0.1ms per call on average are flagged as bottlenecks.

        Prints:
            Average execution time in microseconds for each method tested.

        Note:
            All methods are tested in isolation to identify their individual
            performance characteristics.
        """
        print("Analyzing method performance...")

        self.reset_environment()
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()

        # Define methods to test with their callables
        methods_to_test = [
            ("getdata", lambda: store.getdata()),
            ("getbroker", lambda: store.getbroker()),
            ("put_notification", lambda: store.put_notification("test")),
            ("get_notifications", lambda: store.get_notifications()),
        ]

        for method_name, method_func in methods_to_test:
            with self.profile_execution(f"method_{method_name}"):
                for _ in range(1000):
                    method_func()

            avg_time = sum(self.timing_data[f"method_{method_name}"]) / len(
                self.timing_data[f"method_{method_name}"]
            )
            print(f"   {method_name}(): {avg_time*1000000:.1f}us per call")

            # Flag methods that are slower than 0.1ms threshold
            if avg_time > 0.0001:  # > 0.1ms per call
                self.bottlenecks.append(
                    {
                        "type": "slow_method",
                        "operation": method_name,
                        "time": avg_time,
                        "severity": "medium",
                    }
                )

    def analyze_memory_usage_patterns(self):
        """Analyze memory usage patterns and potential leaks.

        Creates 1000 singleton references and samples memory every 100 iterations
        to track memory growth. Calculates memory per reference and flags inefficient
        memory usage patterns.

        Memory usage > 10KB per reference is flagged as a bottleneck.

        Prints:
            Memory per reference in KB and total memory growth in MB.

        Note:
            Since singleton pattern should return same instance, minimal memory
            growth is expected. Significant growth indicates reference leaks or
            inefficient caching.
        """
        print("Analyzing memory usage patterns...")

        self.reset_environment()

        # Test memory scaling with multiple references
        with self.profile_execution("memory_scaling"):
            stores = []
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                for i in range(1000):
                    stores.append(IBStore())

                    # Sample memory every 100 iterations
                    if i % 100 == 0:
                        process = psutil.Process(os.getpid())
                        memory_mb = process.memory_info().rss / (1024 * 1024)
                        self.memory_snapshots.append((i, memory_mb))

        # Analyze memory growth pattern
        if len(self.memory_snapshots) >= 2:
            initial_memory = self.memory_snapshots[0][1]
            final_memory = self.memory_snapshots[-1][1]
            memory_per_ref = (final_memory - initial_memory) / 1000

            print(f"   Memory per reference: {memory_per_ref*1024:.1f}KB")
            print(f"   Total memory growth: {final_memory - initial_memory:.2f}MB")

            # Flag inefficient memory usage
            if memory_per_ref > 0.01:  # > 10KB per reference
                self.bottlenecks.append(
                    {
                        "type": "memory_inefficiency",
                        "operation": "multiple_references",
                        "memory_per_ref": memory_per_ref,
                        "severity": "high" if memory_per_ref > 0.1 else "medium",
                    }
                )

    def analyze_profiling_data(self):
        """Analyze detailed profiling data to find function-level hotspots.

        Processes cProfile statistics from all profiled operations to identify
        specific functions that consume significant execution time. Focuses on
        magic methods (__new__, __init__, __call__) which are common bottlenecks
        in metaclass-based systems.

        Functions with cumulative time > 1ms are flagged as bottlenecks.

        Prints:
            Top 10 time-consuming functions for each operation.
        """
        print("Analyzing detailed profiling data...")

        for operation, data in self.profiling_results.items():
            print(f"\n   {operation}:")

            # Extract top time-consuming functions from cProfile data
            profiler_stats = data["profiler_stats"]
            stats_stream = io.StringIO()
            stats = pstats.Stats(profiler_stats, stream=stats_stream)
            stats.sort_stats("cumulative")
            stats.print_stats(10)  # Top 10 functions by cumulative time

            profile_output = stats_stream.getvalue()

            # Parse profile output for magic method bottlenecks
            lines = profile_output.split("\n")
            for line in lines:
                if "seconds" in line and any(
                    keyword in line for keyword in ["__new__", "__init__", "__call__"]
                ):
                    # Extract timing information from profile output
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            cumtime = float(parts[3])
                            if cumtime > 0.001:  # > 1ms threshold
                                self.bottlenecks.append(
                                    {
                                        "type": "function_bottleneck",
                                        "operation": operation,
                                        "function": line.strip(),
                                        "time": cumtime,
                                        "severity": "high" if cumtime > 0.01 else "medium",
                                    }
                                )
                        except (ValueError, IndexError):
                            continue

    def generate_optimization_recommendations(self):
        """Generate specific optimization recommendations based on detected bottlenecks.

        Analyzes all detected bottlenecks and generates actionable recommendations
        with implementation guidance. Recommendations are categorized by type
        (initialization, access, concurrency, methods, memory) and prioritized.

        Returns:
            list: List of recommendation dictionaries, each containing:
                - priority (str): "high", "medium", or "low"
                - category (str): Category of the issue
                - issue (str): Description of the problem
                - recommendation (str): High-level recommendation
                - implementation (str): Specific implementation guidance

        Prints:
            Formatted recommendations sorted by priority with visual indicators.
        """
        print("\n" + "=" * 80)
        print("Optimization Recommendations")
        print("=" * 80)

        recommendations = []

        # Generate recommendations for each bottleneck type
        for bottleneck in self.bottlenecks:
            if bottleneck["type"] == "slow_initialization":
                recommendations.append(
                    {
                        "priority": "high",
                        "category": "initialization",
                        "issue": f"Slow singleton initialization ({bottleneck['time']*1000:.1f}ms)",
                        "recommendation": "Optimize __init__ method, lazy load heavy components",
                        "implementation": "Move expensive operations to first method call",
                    }
                )

            elif bottleneck["type"] == "slow_access":
                recommendations.append(
                    {
                        "priority": "medium",
                        "category": "access",
                        "issue": f"Slow singleton access ({bottleneck['time']*1000000:.1f}us)",
                        "recommendation": "Optimize singleton lookup mechanism",
                        "implementation": "Cache instance reference, reduce lock overhead",
                    }
                )

            elif bottleneck["type"] == "thread_contention":
                recommendations.append(
                    {
                        "priority": "high",
                        "category": "concurrency",
                        "issue": f"Thread contention in {bottleneck['operation']}",
                        "recommendation": "Reduce lock granularity, use read-write locks",
                        "implementation": "Implement double-checked locking pattern",
                    }
                )

            elif bottleneck["type"] == "slow_method":
                recommendations.append(
                    {
                        "priority": "medium",
                        "category": "methods",
                        "issue": f"Slow method: {bottleneck['operation']}",
                        "recommendation": "Profile and optimize method implementation",
                        "implementation": "Add caching, reduce object creation",
                    }
                )

            elif bottleneck["type"] == "memory_inefficiency":
                recommendations.append(
                    {
                        "priority": "high",
                        "category": "memory",
                        "issue": f"High memory usage per reference ({bottleneck['memory_per_ref']*1024:.1f}KB)",
                        "recommendation": "Optimize object structure, use __slots__",
                        "implementation": "Reduce instance variables, use weak references",
                    }
                )

        # Sort recommendations by priority (high > medium > low)
        priority_order = {"high": 3, "medium": 2, "low": 1}
        recommendations.sort(key=lambda x: priority_order[x["priority"]], reverse=True)

        # Display formatted recommendations
        for i, rec in enumerate(recommendations, 1):
            priority_icon = (
                "HIGH" if rec["priority"] == "high" else "MED" if rec["priority"] == "medium" else "LOW"
            )
            print(f"{i}. [{priority_icon}] {rec['category'].title()}")
            print(f"   Issue: {rec['issue']}")
            print(f"   Recommendation: {rec['recommendation']}")
            print(f"   Implementation: {rec['implementation']}")
            print()

        return recommendations

    def run_full_analysis(self):
        """Run complete performance bottleneck analysis.

        Executes all analysis methods in sequence:
        1. Singleton creation bottlenecks
        2. Thread contention analysis
        3. Method performance analysis
        4. Memory usage patterns
        5. Detailed profiling data analysis

        Generates and displays optimization recommendations based on findings.

        Returns:
            dict: Complete analysis results containing:
                - bottlenecks (list): All detected bottlenecks
                - recommendations (list): Generated optimization recommendations
                - profiling_results (dict): Raw profiling data
                - timing_data (dict): Timing statistics for all operations

        Prints:
            Comprehensive analysis report with timing, memory usage, bottleneck count,
            and priority breakdown.
        """
        print("\n" + "=" * 80)
        print("Store System Performance Bottleneck Analysis (Day 22-24)")
        print("=" * 80)

        start_time = time.time()

        # Run all analysis methods
        self.analyze_singleton_creation_bottlenecks()
        print()
        self.analyze_thread_contention()
        print()
        self.analyze_method_performance()
        print()
        self.analyze_memory_usage_patterns()
        print()
        self.analyze_profiling_data()

        analysis_time = time.time() - start_time

        # Generate optimization recommendations
        recommendations = self.generate_optimization_recommendations()

        # Display summary statistics
        print("Analysis Summary")
        print("=" * 80)
        print(f"Analysis time: {analysis_time:.2f}s")
        print(f"Bottlenecks found: {len(self.bottlenecks)}")
        print(f"Recommendations generated: {len(recommendations)}")

        # Categorize bottlenecks by severity
        high_priority = sum(1 for b in self.bottlenecks if b.get("severity") == "high")
        medium_priority = sum(1 for b in self.bottlenecks if b.get("severity") == "medium")

        print(f"High priority issues: {high_priority}")
        print(f"Medium priority issues: {medium_priority}")

        return {
            "bottlenecks": self.bottlenecks,
            "recommendations": recommendations,
            "profiling_results": self.profiling_results,
            "timing_data": dict(self.timing_data),
        }

    def save_analysis_report(self, filename="bottleneck_analysis_report.json"):
        """Save analysis results to JSON file.

        Creates a comprehensive report including bottlenecks, timing summaries,
        and memory snapshots in JSON format for external analysis or archival.

        Args:
            filename (str, optional): Output filename. Defaults to
                "bottleneck_analysis_report.json".

        Returns:
            str: Absolute path to the saved report file.

        Raises:
            IOError: If unable to write to the specified file.
            TypeError: If data contains non-serializable objects.

        Note:
            Memory trace objects are excluded from JSON output as they are
            not serializable. Use analyze_profiling_data() for detailed analysis.
        """
        import json

        # Prepare serializable data structure
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "bottlenecks": self.bottlenecks,
            "timing_summary": {
                op: {
                    "count": len(times),
                    "total": sum(times),
                    "average": sum(times) / len(times) if times else 0,
                    "min": min(times) if times else 0,
                    "max": max(times) if times else 0,
                }
                for op, times in self.timing_data.items()
            },
            "memory_snapshots": self.memory_snapshots,
        }

        with open(filename, "w") as f:
            json.dump(report, f, indent=2)

        print(f"Analysis report saved to: {filename}")
        return filename


def main():
    """Main analysis execution function.

    Creates a PerformanceBottleneckAnalyzer, runs full analysis, saves report,
    and displays summary statistics. Handles exceptions gracefully and returns
    appropriate exit code.

    Returns:
        bool: True if analysis completed successfully, False otherwise.

    Raises:
        Exception: Propagates any unexpected exceptions during analysis.
        Exceptions are caught, logged, and converted to False return.

    Example:
        >>> success = main()
        >>> sys.exit(0 if success else 1)
    """
    analyzer = PerformanceBottleneckAnalyzer()

    try:
        # Run full bottleneck analysis
        results = analyzer.run_full_analysis()

        # Save detailed report to file
        report_file = analyzer.save_analysis_report()

        print(f"\nBottleneck analysis completed!")
        print(f"Results: {len(results['bottlenecks'])} bottlenecks identified")
        print(f"Recommendations: {len(results['recommendations'])} optimization suggestions")
        print(f"Report: {report_file}")

        return True

    except Exception as e:
        print(f"\nAnalysis failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
