#!/usr/bin/env python3
"""
Performance benchmark tool - Establish performance baseline for metaprogramming removal project.
"""

import gc
import sys
import time
from pathlib import Path

import memory_profiler
import psutil

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

import backtrader as bt


class PerformanceBenchmark:
    """Performance benchmark testing."""

    def __init__(self):
        self.results = {}
        self.memory_baseline = None

    def measure_memory_start(self):
        """Start memory measurement."""
        gc.collect()
        process = psutil.Process()
        self.memory_baseline = process.memory_info().rss / 1024 / 1024  # MB

    def measure_memory_end(self, operation_name):
        """End memory measurement."""
        gc.collect()
        process = psutil.Process()
        current_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_used = current_memory - self.memory_baseline
        return memory_used

    def benchmark_strategy_creation(self, iterations=1000):
        """Strategy creation performance benchmark."""
        print("Testing strategy creation performance...")

        class TestStrategy(bt.Strategy):
            params = (
                ("period", 14),
                ("matype", bt.indicators.MovAv.Simple),
            )

            def __init__(self):
                self.sma = bt.indicators.SimpleMovingAverage(
                    self.data.close, period=self.params.period
                )

            def next(self):
                pass

        self.measure_memory_start()
        start_time = time.time()

        strategies = []
        for _ in range(iterations):
            # Simulate strategy creation process
            cerebro = bt.Cerebro()
            cerebro.addstrategy(TestStrategy)
            strategies.append(cerebro)

        end_time = time.time()
        memory_used = self.measure_memory_end("strategy_creation")

        total_time = end_time - start_time
        avg_time = total_time / iterations * 1000  # ms

        self.results["strategy_creation"] = {
            "total_time": total_time,
            "avg_time_ms": avg_time,
            "memory_mb": memory_used,
            "iterations": iterations,
        }

        print(f"  - Total time: {total_time:.4f}s")
        print(f"  - Average time: {avg_time:.4f}ms/iteration")
        print(f"  - Memory usage: {memory_used:.2f}MB")

        # Cleanup
        del strategies
        gc.collect()

    def benchmark_indicator_calculation(self, data_points=10000):
        """Indicator calculation performance benchmark."""
        print("Testing indicator calculation performance...")

        # Generate test data
        dates = pd.date_range("2020-01-01", periods=data_points, freq="D")
        prices = 100 + np.cumsum(np.random.randn(data_points) * 0.01)

        data = bt.feeds.PandasData(
            dataname=pd.DataFrame(
                {
                    "open": prices,
                    "high": prices * 1.01,
                    "low": prices * 0.99,
                    "close": prices,
                    "volume": np.random.randint(1000, 10000, data_points),
                },
                index=dates,
            )
        )

        class IndicatorTestStrategy(bt.Strategy):
            def __init__(self):
                # Test multiple indicators
                self.sma = bt.indicators.SimpleMovingAverage(self.data.close, period=20)
                self.ema = bt.indicators.ExponentialMovingAverage(self.data.close, period=20)
                self.rsi = bt.indicators.RSI(self.data.close, period=14)
                self.macd = bt.indicators.MACD(self.data.close)

            def next(self):
                pass

        self.measure_memory_start()
        start_time = time.time()

        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(IndicatorTestStrategy)
        cerebro.run()

        end_time = time.time()
        memory_used = self.measure_memory_end("indicator_calculation")

        total_time = end_time - start_time
        points_per_second = data_points / total_time

        self.results["indicator_calculation"] = {
            "total_time": total_time,
            "data_points": data_points,
            "points_per_second": points_per_second,
            "memory_mb": memory_used,
        }

        print(f"  - Total time: {total_time:.4f}s")
        print(f"  - Data points: {data_points}")
        print(f"  - Processing speed: {points_per_second:.0f} points/sec")
        print(f"  - Memory usage: {memory_used:.2f}MB")

    def benchmark_data_access(self, iterations=100000):
        """Data access performance benchmark."""
        print("Testing data access performance...")

        # Create test data
        dates = pd.date_range("2020-01-01", periods=1000, freq="D")
        prices = 100 + np.cumsum(np.random.randn(1000) * 0.01)

        data_feed = bt.feeds.PandasData(
            dataname=pd.DataFrame(
                {
                    "open": prices,
                    "high": prices * 1.01,
                    "low": prices * 0.99,
                    "close": prices,
                    "volume": np.random.randint(1000, 10000, 1000),
                },
                index=dates,
            )
        )

        class DataAccessStrategy(bt.Strategy):
            def __init__(self):
                self.access_times = []

            def next(self):
                # Test various data access methods
                start = time.time()

                # Line access
                close = self.data.close[0]
                open_price = self.data.open[0]
                high = self.data.high[0]
                low = self.data.low[0]

                # Historical data access
                close_1 = self.data.close[-1] if len(self.data) > 1 else 0
                close_5 = self.data.close[-5] if len(self.data) > 5 else 0

                end = time.time()
                self.access_times.append((end - start) * 1000000)  # microseconds

        cerebro = bt.Cerebro()
        cerebro.adddata(data_feed)
        strategies = cerebro.addstrategy(DataAccessStrategy)

        self.measure_memory_start()
        start_time = time.time()

        cerebro.run()

        end_time = time.time()
        memory_used = self.measure_memory_end("data_access")

        strategy_instance = strategies[0]
        if hasattr(strategy_instance, "access_times") and strategy_instance.access_times:
            avg_access_time = np.mean(strategy_instance.access_times)
        else:
            avg_access_time = 0

        self.results["data_access"] = {
            "total_time": end_time - start_time,
            "avg_access_time_us": avg_access_time,
            "memory_mb": memory_used,
            "data_points": 1000,
        }

        print(f"  - Total time: {end_time - start_time:.4f}s")
        print(f"  - Average access time: {avg_access_time:.2f}μs")
        print(f"  - Memory usage: {memory_used:.2f}MB")

    def benchmark_parameter_access(self, iterations=1000000):
        """Parameter access performance benchmark."""
        print("Testing parameter access performance...")

        class ParamTestStrategy(bt.Strategy):
            params = (
                ("period", 14),
                ("threshold", 0.02),
                ("enable_feature", True),
                ("multiplier", 2.5),
            )

        strategy = ParamTestStrategy()

        self.measure_memory_start()
        start_time = time.time()

        for _ in range(iterations):
            # Test parameter access
            period = strategy.params.period
            threshold = strategy.params.threshold
            enabled = strategy.params.enable_feature
            mult = strategy.params.multiplier

        end_time = time.time()
        memory_used = self.measure_memory_end("parameter_access")

        total_time = end_time - start_time
        avg_time = total_time / iterations * 1000000  # microseconds

        self.results["parameter_access"] = {
            "total_time": total_time,
            "avg_time_us": avg_time,
            "memory_mb": memory_used,
            "iterations": iterations,
        }

        print(f"  - Total time: {total_time:.4f}s")
        print(f"  - Average time: {avg_time:.4f}μs/iteration")
        print(f"  - Memory usage: {memory_used:.2f}MB")

    def run_all_benchmarks(self):
        """Run all benchmarks."""
        print("=" * 60)
        print("BACKTRADER PERFORMANCE BENCHMARK")
        print("=" * 60)
        print(f"Python version: {sys.version}")
        print(f"System: {psutil.Platform}")
        print(f"CPU cores: {psutil.cpu_count()}")
        print(f"Memory: {psutil.virtual_memory().total / 1024 / 1024 / 1024:.1f}GB")
        print("=" * 60)

        try:
            self.benchmark_strategy_creation()
            print()
            self.benchmark_indicator_calculation()
            print()
            self.benchmark_data_access()
            print()
            self.benchmark_parameter_access()
            print()

        except Exception as e:
            print(f"Benchmark error: {e}")
            import traceback

            traceback.print_exc()

    def save_results(self, filename="performance_baseline.json"):
        """Save results to file."""
        import json

        # Add system information
        self.results["system_info"] = {
            "python_version": sys.version,
            "cpu_count": psutil.cpu_count(),
            "memory_gb": psutil.virtual_memory().total / 1024 / 1024 / 1024,
            "timestamp": time.time(),
        }

        with open(filename, "w") as f:
            json.dump(self.results, f, indent=2)

        print(f"Benchmark results saved to: {filename}")

    def print_summary(self):
        """Print results summary."""
        print("=" * 60)
        print("Performance Benchmark Results Summary")
        print("=" * 60)

        if "strategy_creation" in self.results:
            r = self.results["strategy_creation"]
            print(f"Strategy creation: {r['avg_time_ms']:.2f}ms/iteration")

        if "indicator_calculation" in self.results:
            r = self.results["indicator_calculation"]
            print(f"Indicator calculation: {r['points_per_second']:.0f} points/sec")

        if "data_access" in self.results:
            r = self.results["data_access"]
            print(f"Data access: {r['avg_access_time_us']:.2f}μs/access")

        if "parameter_access" in self.results:
            r = self.results["parameter_access"]
            print(f"Parameter access: {r['avg_time_us']:.4f}μs/access")


def main():
    """Main function."""
    benchmark = PerformanceBenchmark()
    benchmark.run_all_benchmarks()
    benchmark.print_summary()
    benchmark.save_results()


if __name__ == "__main__":
    main()
