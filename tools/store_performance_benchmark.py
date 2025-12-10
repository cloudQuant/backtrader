#!/usr/bin/env python

import gc
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import Mock, patch

import psutil

# Mock dependencies
sys.modules["oandapy"] = Mock()
sys.modules["ccxt"] = Mock()
sys.modules["ctpbee"] = Mock()
sys.modules["ctpbee.api"] = Mock()
sys.modules["ctpbee.constant"] = Mock()
sys.modules["ctpbee.helpers"] = Mock()

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.stores.ibstore import IBStore


class StoreBenchmark:
    """Performance benchmark tool for Store system."""

    def __init__(self):
        self.results = {}
        self.process = psutil.Process(os.getpid())

    def reset_stores(self):
        """Reset all store singletons."""
        if hasattr(IBStore, "_reset_instance"):
            IBStore._reset_instance()
        gc.collect()

    def measure_time(self, func, iterations=100):
        """Measure execution time of a function."""
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
        """Measure memory usage of a function."""
        gc.collect()  # Clean up before measurement
        initial_memory = self.process.memory_info().rss

        result = func()

        gc.collect()  # Clean up after
        final_memory = self.process.memory_info().rss

        return {
            "initial_mb": initial_memory / (1024 * 1024),
            "final_mb": final_memory / (1024 * 1024),
            "increase_mb": (final_memory - initial_memory) / (1024 * 1024),
            "result": result,
        }

    def benchmark_singleton_creation(self):
        """Benchmark singleton instance creation."""
        print("🔍 Benchmarking singleton creation...")

        def create_first_instance():
            self.reset_stores()
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                return IBStore()

        def create_subsequent_instance():
            with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                return IBStore()

        # Benchmark first creation
        first_creation = self.measure_time(create_first_instance, iterations=10)

        # Create initial instance for subsequent tests
        self.reset_stores()
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            IBStore()

        # Benchmark subsequent access
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
        """Benchmark thread safety performance."""
        print("🔍 Benchmarking thread safety...")

        self.reset_stores()

        def concurrent_access():
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
        """Benchmark memory usage of singleton pattern."""
        print("🔍 Benchmarking memory usage...")

        def create_many_references():
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
        """Benchmark performance of store methods."""
        print("🔍 Benchmarking method performance...")

        self.reset_stores()
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()

        def test_getdata():
            return store.getdata()

        def test_getbroker():
            return store.getbroker()

        def test_notifications():
            store.put_notification("test message")
            return store.get_notifications()

        # Benchmark different methods
        getdata_perf = self.measure_time(test_getdata, iterations=1000)
        getbroker_perf = self.measure_time(test_getbroker, iterations=1000)
        notifications_perf = self.measure_time(test_notifications, iterations=1000)

        self.results["method_performance"] = {
            "getdata": getdata_perf,
            "getbroker": getbroker_perf,
            "notifications": notifications_perf,
        }

        print(f"   getdata(): {getdata_perf['mean']*1000000:.1f}μs (avg)")
        print(f"   getbroker(): {getbroker_perf['mean']*1000000:.1f}μs (avg)")
        print(f"   notifications: {notifications_perf['mean']*1000000:.1f}μs (avg)")

    def benchmark_parameter_access(self):
        """Benchmark parameter system performance."""
        print("🔍 Benchmarking parameter access...")

        self.reset_stores()
        with patch("backtrader.stores.ibstore.ibopt") as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()

        def access_parameters():
            if hasattr(store, "p"):
                return dict(store.p._getpairs())
            return {}

        def access_params_attr():
            return getattr(store, "params", None)

        # Benchmark parameter access
        param_access_perf = self.measure_time(access_parameters, iterations=1000)
        param_attr_perf = self.measure_time(access_params_attr, iterations=1000)

        self.results["parameter_performance"] = {
            "parameter_access": param_access_perf,
            "params_attribute": param_attr_perf,
        }

        print(f"   Parameter access: {param_access_perf['mean']*1000000:.1f}μs (avg)")
        print(f"   Params attribute: {param_attr_perf['mean']*1000000:.1f}μs (avg)")

    def run_all_benchmarks(self):
        """Run all performance benchmarks."""
        print("\n" + "=" * 80)
        print("🚀 Store System Performance Benchmark (Day 19-21)")
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
        print("📊 Performance Summary")
        print("=" * 80)

        # Singleton performance
        singleton_results = self.results["singleton_creation"]
        print(f"🔄 Singleton Performance:")
        print(f"   First creation: {singleton_results['first_creation']['mean']*1000:.3f}ms")
        print(f"   Subsequent access: {singleton_results['subsequent_access']['mean']*1000:.6f}ms")
        print(f"   Performance improvement: {singleton_results['speedup_ratio']:.1f}x faster")

        # Memory efficiency
        memory_results = self.results["memory_usage"]
        print(f"\n💾 Memory Efficiency:")
        print(f"   Memory per reference: {memory_results['increase_mb']/1000*1024:.1f}KB")
        print(f"   Total overhead for 1000 refs: {memory_results['increase_mb']:.2f}MB")

        # Thread safety
        thread_results = self.results["thread_safety"]
        print(f"\n🔒 Thread Safety:")
        print(f"   Concurrent access time: {thread_results['mean_concurrent_time']*1000:.3f}ms")
        print(f"   Threads: {thread_results['concurrent_threads']}")
        print(f"   Total operations: {thread_results['total_operations']}")

        # Method performance
        method_results = self.results["method_performance"]
        print(f"\n⚡ Method Performance:")
        print(f"   getdata(): {method_results['getdata']['mean']*1000000:.1f}μs")
        print(f"   getbroker(): {method_results['getbroker']['mean']*1000000:.1f}μs")
        print(f"   notifications: {method_results['notifications']['mean']*1000000:.1f}μs")

        print(f"\n⏱️ Total benchmark time: {total_time:.2f}s")
        print("=" * 80)

        return self.results

    def generate_report(self, filename="store_performance_report.json"):
        """Generate detailed performance report."""
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

        print(f"📄 Performance report saved to: {filename}")

        return filename


def main():
    """Main benchmark execution."""
    benchmark = StoreBenchmark()

    try:
        # Run all benchmarks
        results = benchmark.run_all_benchmarks()

        # Generate report
        report_file = benchmark.generate_report()

        print(f"\n✅ Benchmark completed successfully!")
        print(f"📊 Results: {len(results)} test categories completed")
        print(f"📄 Report: {report_file}")

        return True

    except Exception as e:
        print(f"\n❌ Benchmark failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
