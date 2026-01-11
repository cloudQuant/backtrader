#!/usr/bin/env python3
"""
Performance Benchmark Tool for Backtrader.

This module provides comprehensive performance benchmarking capabilities for the
Backtrader framework, specifically designed to establish performance baselines
for the metaprogramming removal project. It measures key performance metrics
including strategy creation, indicator calculation, data access, and parameter
access patterns.

The benchmark tool helps track performance regressions and improvements during
the refactoring process from metaclass-based to explicit initialization patterns.

Example:
    >>> from tools.performance_benchmark import PerformanceBenchmark
    >>> benchmark = PerformanceBenchmark()
    >>> benchmark.run_all_benchmarks()
    >>> benchmark.print_summary()
    >>> benchmark.save_results('my_benchmark.json')
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
    """Comprehensive performance benchmarking tool for Backtrader framework.

    This class provides methods to benchmark various aspects of Backtrader's
    performance, including strategy creation, indicator calculations, data access
    patterns, and parameter access. It measures both execution time and memory
    usage to provide a complete performance profile.

    Attributes:
        results (dict): Dictionary storing benchmark results for all tests.
            Keys are benchmark names, values are dictionaries containing metrics.
        memory_baseline (float): Baseline memory usage in MB before benchmark
            execution. Used to calculate memory deltas.

    Example:
        >>> benchmark = PerformanceBenchmark()
        >>> benchmark.benchmark_strategy_creation(iterations=100)
        >>> benchmark.print_summary()
    """

    def __init__(self):
        """Initialize the PerformanceBenchmark instance.

        Creates an empty results dictionary and initializes the memory baseline
        to None. The baseline will be set when measure_memory_start() is called.
        """
        self.results = {}
        self.memory_baseline = None

    def measure_memory_start(self):
        """Start memory measurement for benchmarking.

        Forces garbage collection to minimize noise and records the current
        process memory usage as a baseline. This should be called before
        executing the code to be benchmarked.

        The memory baseline is stored in self.memory_baseline in megabytes (MB).

        Example:
            >>> benchmark = PerformanceBenchmark()
            >>> benchmark.measure_memory_start()
            >>> # ... run benchmarked code ...
            >>> memory_used = benchmark.measure_memory_end('test')
        """
        gc.collect()
        process = psutil.Process()
        self.memory_baseline = process.memory_info().rss / 1024 / 1024  # MB

    def measure_memory_end(self, operation_name):
        """End memory measurement and calculate memory usage.

        Forces garbage collection and calculates the memory delta from the
        baseline established by measure_memory_start(). The result represents
        the actual memory used by the benchmarked operation.

        Args:
            operation_name (str): Name of the operation being measured.
                This parameter is currently not used but maintained for
                potential future logging functionality.

        Returns:
            float: Memory used during the benchmark in megabytes (MB).
                Calculated as current memory minus baseline memory.

        Example:
            >>> benchmark.measure_memory_start()
            >>> # ... run code ...
            >>> memory_mb = benchmark.measure_memory_end('my_operation')
            >>> print(f"Used {memory_mb:.2f} MB")
        """
        gc.collect()
        process = psutil.Process()
        current_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_used = current_memory - self.memory_baseline
        return memory_used

    def benchmark_strategy_creation(self, iterations=1000):
        """Benchmark strategy creation performance.

        Tests the performance of creating multiple strategy instances by
        simulating the Cerebro engine initialization process. This measures
        the overhead of strategy object instantiation, which is critical
        during the metaprogramming removal refactoring.

        The test creates a simple strategy with an SMA indicator and measures
        the time and memory required to create multiple Cerebro instances with
        the strategy attached.

        Args:
            iterations (int): Number of strategy creation cycles to perform.
                Defaults to 1000. Higher values provide more accurate averages
                but take longer to execute.

        Stores results in self.results['strategy_creation'] with keys:
            - total_time: Total execution time in seconds
            - avg_time_ms: Average time per iteration in milliseconds
            - memory_mb: Total memory used in megabytes
            - iterations: Number of iterations performed

        Example:
            >>> benchmark = PerformanceBenchmark()
            >>> benchmark.benchmark_strategy_creation(iterations=500)
            >>> print(benchmark.results['strategy_creation']['avg_time_ms'])
        """
        print("Testing strategy creation performance...")

        # Define test strategy with SMA indicator for realistic benchmarking
        class TestStrategy(bt.Strategy):
            """Test strategy for benchmarking strategy creation performance.

            This strategy uses a Simple Moving Average (SMA) indicator to
            simulate a realistic scenario where strategies need to initialize
            indicators during instantiation.

            Attributes:
                params (tuple): Strategy parameters including period and MA type.
                sma (bt.indicators.SimpleMovingAverage): SMA indicator instance.
            """

            params = (
                ("period", 14),
                ("matype", bt.indicators.MovAv.Simple),
            )

            def __init__(self):
                """Initialize the test strategy with SMA indicator.

                Creates an SMA indicator to measure the overhead of indicator
                initialization during strategy creation. This is a common pattern
                in real trading strategies.
                """
                # Initialize SMA indicator with configurable period
                self.sma = bt.indicators.SimpleMovingAverage(
                    self.data.close, period=self.params.period
                )

            def next(self):
                """Empty next method - no trading logic needed for benchmarking.

                This benchmark focuses on creation overhead, not execution logic.
                """
                pass

        # Start memory measurement and timing
        self.measure_memory_start()
        start_time = time.time()

        # Create multiple Cerebro instances with strategy to measure creation overhead
        strategies = []
        for _ in range(iterations):
            # Simulate strategy creation process
            cerebro = bt.Cerebro()
            cerebro.addstrategy(TestStrategy)
            strategies.append(cerebro)

        # Calculate total time and average time per iteration
        end_time = time.time()
        memory_used = self.measure_memory_end("strategy_creation")

        total_time = end_time - start_time
        avg_time = total_time / iterations * 1000  # Convert to milliseconds

        # Store results for later analysis
        self.results["strategy_creation"] = {
            "total_time": total_time,
            "avg_time_ms": avg_time,
            "memory_mb": memory_used,
            "iterations": iterations,
        }

        # Display benchmark results
        print(f"  - Total time: {total_time:.4f}s")
        print(f"  - Average time: {avg_time:.4f}ms/iteration")
        print(f"  - Memory usage: {memory_used:.2f}MB")

        # Cleanup to free memory for next benchmark
        del strategies
        gc.collect()

    def benchmark_indicator_calculation(self, data_points=10000):
        """Benchmark indicator calculation performance.

        Tests the performance of calculating multiple technical indicators
        (SMA, EMA, RSI, MACD) over a dataset. This measures the computational
        efficiency of indicator updates during backtesting, which is one of
        the most performance-critical aspects of the framework.

        The test generates synthetic price data and runs a complete backtest
        with a strategy that calculates four common indicators simultaneously.

        Args:
            data_points (int): Number of data points to generate for testing.
                Defaults to 10000. More points provide better accuracy for
                throughput measurements but take longer to execute.

        Stores results in self.results['indicator_calculation'] with keys:
            - total_time: Total execution time in seconds
            - data_points: Number of data points processed
            - points_per_second: Processing speed in data points per second
            - memory_mb: Total memory used in megabytes

        Example:
            >>> benchmark = PerformanceBenchmark()
            >>> benchmark.benchmark_indicator_calculation(data_points=5000)
            >>> speed = benchmark.results['indicator_calculation']['points_per_second']
            >>> print(f"Processing speed: {speed:.0f} points/sec")
        """
        print("Testing indicator calculation performance...")

        # Generate synthetic test data with random walk for price simulation
        dates = pd.date_range("2020-01-01", periods=data_points, freq="D")
        # Create price series using random walk starting at 100
        prices = 100 + np.cumsum(np.random.randn(data_points) * 0.01)

        # Create PandasData feed with OHLCV data
        data = bt.feeds.PandasData(
            dataname=pd.DataFrame(
                {
                    "open": prices,
                    "high": prices * 1.01,  # Simulate 1% above open
                    "low": prices * 0.99,   # Simulate 1% below open
                    "close": prices,
                    "volume": np.random.randint(1000, 10000, data_points),
                },
                index=dates,
            )
        )

        # Strategy that calculates multiple indicators to stress-test the system
        class IndicatorTestStrategy(bt.Strategy):
            """Test strategy for benchmarking indicator calculation performance.

            This strategy initializes four common technical indicators to measure
            the computational overhead of indicator calculations during backtesting.

            Attributes:
                sma (bt.indicators.SimpleMovingAverage): Simple moving average.
                ema (bt.indicators.ExponentialMovingAverage): Exponential moving average.
                rsi (bt.indicators.RSI): Relative Strength Index.
                macd (bt.indicators.MACD): Moving Average Convergence Divergence.
            """

            def __init__(self):
                """Initialize multiple technical indicators for benchmarking.

                Creates four different indicator types to test various calculation
                patterns:
                - SMA: Simple average with equal weights
                - EMA: Exponential weighted average
                - RSI: Momentum oscillator requiring intermediate calculations
                - MACD: Composite indicator with multiple internal lines
                """
                # Test multiple indicators with different calculation complexities
                self.sma = bt.indicators.SimpleMovingAverage(self.data.close, period=20)
                self.ema = bt.indicators.ExponentialMovingAverage(self.data.close, period=20)
                self.rsi = bt.indicators.RSI(self.data.close, period=14)
                self.macd = bt.indicators.MACD(self.data.close)

            def next(self):
                """Empty next method - focus is on indicator calculation, not trading logic.

                Indicators are automatically calculated on each bar before next() is called,
                so we don't need any explicit logic here to trigger calculations.
                """
                pass

        # Start memory measurement and timing
        self.measure_memory_start()
        start_time = time.time()

        # Run backtest with indicators
        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(IndicatorTestStrategy)
        cerebro.run()

        # Calculate metrics
        end_time = time.time()
        memory_used = self.measure_memory_end("indicator_calculation")

        total_time = end_time - start_time
        points_per_second = data_points / total_time

        # Store results for later analysis
        self.results["indicator_calculation"] = {
            "total_time": total_time,
            "data_points": data_points,
            "points_per_second": points_per_second,
            "memory_mb": memory_used,
        }

        # Display benchmark results
        print(f"  - Total time: {total_time:.4f}s")
        print(f"  - Data points: {data_points}")
        print(f"  - Processing speed: {points_per_second:.0f} points/sec")
        print(f"  - Memory usage: {memory_used:.2f}MB")

    def benchmark_data_access(self, iterations=100000):
        """Benchmark data access performance within strategy execution.

        Tests the speed of various data access patterns that are commonly
        used in trading strategies, including current bar access (close[0])
        and historical data access (close[-1], close[-5]). This measures
        the efficiency of the line buffer system for data retrieval.

        The test runs a backtest and measures the time taken for each
        data access operation during the strategy's next() method execution.

        Args:
            iterations (int): This parameter is currently unused but maintained
                for potential future expansion where the number of access
                operations per bar could be varied. Defaults to 100000.

        Stores results in self.results['data_access'] with keys:
            - total_time: Total execution time in seconds
            - avg_access_time_us: Average access time in microseconds
            - memory_mb: Total memory used in megabytes
            - data_points: Number of data points processed

        Note:
            The iterations parameter is not currently used in the benchmark
            logic but is maintained for API compatibility and future enhancements.

        Example:
            >>> benchmark = PerformanceBenchmark()
            >>> benchmark.benchmark_data_access()
            >>> avg_time = benchmark.results['data_access']['avg_access_time_us']
            >>> print(f"Average access time: {avg_time:.2f} microseconds")
        """
        print("Testing data access performance...")

        # Create test data with fixed size for consistent benchmarking
        dates = pd.date_range("2020-01-01", periods=1000, freq="D")
        prices = 100 + np.cumsum(np.random.randn(1000) * 0.01)

        # Create PandasData feed with OHLCV data
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

        # Strategy that measures data access timing
        class DataAccessStrategy(bt.Strategy):
            """Test strategy for benchmarking data access performance.

            This strategy measures the time required to access current and
            historical OHLCV data during backtesting, which is critical for
            understanding line buffer performance.

            Attributes:
                access_times (list): List storing access times in microseconds
                    for each bar's next() call.
            """

            def __init__(self):
                """Initialize the data access benchmark strategy.

                Sets up an empty list to store timing measurements for each
                data access operation during the backtest.
                """
                self.access_times = []

            def next(self):
                """Execute data access timing measurements on each bar.

                Measures the time required to access:
                - Current bar data (index 0): close, open, high, low
                - Historical data (negative indices): close[-1], close[-5]

                The timing is done in microseconds to capture small differences
                in access performance that could accumulate over many bars.
                """
                # Start timing for data access operations
                start = time.time()

                # Line access - current bar data
                close = self.data.close[0]
                open_price = self.data.open[0]
                high = self.data.high[0]
                low = self.data.low[0]

                # Historical data access - previous bars
                # Use conditional to avoid index errors on early bars
                close_1 = self.data.close[-1] if len(self.data) > 1 else 0
                close_5 = self.data.close[-5] if len(self.data) > 5 else 0

                # Calculate and store access time in microseconds
                end = time.time()
                self.access_times.append((end - start) * 1000000)  # microseconds

        # Set up cerebro with data and strategy
        cerebro = bt.Cerebro()
        cerebro.adddata(data_feed)
        strategies = cerebro.addstrategy(DataAccessStrategy)

        # Start memory measurement and timing
        self.measure_memory_start()
        start_time = time.time()

        # Run backtest to collect access timing data
        cerebro.run()

        # Calculate metrics
        end_time = time.time()
        memory_used = self.measure_memory_end("data_access")

        # Extract strategy instance to access collected timing data
        strategy_instance = strategies[0]
        if hasattr(strategy_instance, "access_times") and strategy_instance.access_times:
            avg_access_time = np.mean(strategy_instance.access_times)
        else:
            avg_access_time = 0

        # Store results for later analysis
        self.results["data_access"] = {
            "total_time": end_time - start_time,
            "avg_access_time_us": avg_access_time,
            "memory_mb": memory_used,
            "data_points": 1000,
        }

        # Display benchmark results
        print(f"  - Total time: {end_time - start_time:.4f}s")
        print(f"  - Average access time: {avg_access_time:.2f}μs")
        print(f"  - Memory usage: {memory_used:.2f}MB")

    def benchmark_parameter_access(self, iterations=1000000):
        """Benchmark parameter access performance.

        Tests the speed of accessing strategy parameters through the
        params attribute. Parameter access is a frequent operation in
        strategy logic, so its performance is important for overall
        backtesting speed.

        The test creates a strategy with multiple parameters and measures
        the time required to access each parameter repeatedly. This helps
        identify any overhead in the parameter system implementation.

        Args:
            iterations (int): Number of parameter access iterations to perform.
                Defaults to 1000000. Higher values provide more accurate
                measurements of access time overhead.

        Stores results in self.results['parameter_access'] with keys:
            - total_time: Total execution time in seconds
            - avg_time_us: Average access time in microseconds
            - memory_mb: Total memory used in megabytes
            - iterations: Number of iterations performed

        Example:
            >>> benchmark = PerformanceBenchmark()
            >>> benchmark.benchmark_parameter_access(iterations=500000)
            >>> avg_time = benchmark.results['parameter_access']['avg_time_us']
            >>> print(f"Parameter access: {avg_time:.4f} microseconds")
        """
        print("Testing parameter access performance...")

        # Define strategy with multiple parameter types
        class ParamTestStrategy(bt.Strategy):
            """Test strategy for benchmarking parameter access performance.

            This strategy defines multiple parameters of different types
            (int, float, bool) to measure parameter access overhead across
            various data types.

            Attributes:
                params (tuple): Strategy parameters including period (int),
                    threshold (float), enable_feature (bool), and multiplier (float).
            """

            params = (
                ("period", 14),
                ("threshold", 0.02),
                ("enable_feature", True),
                ("multiplier", 2.5),
            )

        # Create strategy instance for parameter access testing
        strategy = ParamTestStrategy()

        # Start memory measurement and timing
        self.measure_memory_start()
        start_time = time.time()

        # Repeatedly access parameters to measure access time overhead
        for _ in range(iterations):
            # Test parameter access for different types
            period = strategy.params.period
            threshold = strategy.params.threshold
            enabled = strategy.params.enable_feature
            mult = strategy.params.multiplier

        # Calculate metrics
        end_time = time.time()
        memory_used = self.measure_memory_end("parameter_access")

        total_time = end_time - start_time
        avg_time = total_time / iterations * 1000000  # Convert to microseconds

        # Store results for later analysis
        self.results["parameter_access"] = {
            "total_time": total_time,
            "avg_time_us": avg_time,
            "memory_mb": memory_used,
            "iterations": iterations,
        }

        # Display benchmark results
        print(f"  - Total time: {total_time:.4f}s")
        print(f"  - Average time: {avg_time:.4f}μs/iteration")
        print(f"  - Memory usage: {memory_used:.2f}MB")

    def run_all_benchmarks(self):
        """Execute all performance benchmarks in sequence.

        Runs the complete benchmark suite including strategy creation,
        indicator calculation, data access, and parameter access tests.
        Displays system information at the start and handles errors gracefully.

        Before running benchmarks, displays system information:
            - Python version
            - System platform
            - CPU core count
            - Total system memory

        The benchmarks are executed in a fixed order:
            1. Strategy creation benchmark
            2. Indicator calculation benchmark
            3. Data access benchmark
            4. Parameter access benchmark

        Note:
            If any benchmark raises an exception, the error is caught and
            printed, but remaining benchmarks continue to execute.

        Example:
            >>> benchmark = PerformanceBenchmark()
            >>> benchmark.run_all_benchmarks()
            >>> # All results are now in benchmark.results
        """
        # Display benchmark header and system information
        print("=" * 60)
        print("BACKTRADER PERFORMANCE BENCHMARK")
        print("=" * 60)
        print(f"Python version: {sys.version}")
        print(f"System: {psutil.Platform}")
        print(f"CPU cores: {psutil.cpu_count()}")
        print(f"Memory: {psutil.virtual_memory().total / 1024 / 1024 / 1024:.1f}GB")
        print("=" * 60)

        # Execute all benchmarks in sequence
        try:
            self.benchmark_strategy_creation()
            print()
            self.benchmark_indicator_calculation()
            print()
            self.benchmark_data_access()
            print()
            self.benchmark_parameter_access()
            print()

        # Handle errors gracefully - continue with remaining benchmarks
        except Exception as e:
            print(f"Benchmark error: {e}")
            import traceback

            traceback.print_exc()

    def save_results(self, filename="performance_baseline.json"):
        """Save benchmark results to a JSON file.

        Writes all benchmark results to a JSON file for later analysis and
        comparison. Adds system information including Python version, CPU count,
        total memory, and timestamp to provide context for the results.

        The saved JSON includes all results from self.results plus system_info:
            - python_version: Full Python version string
            - cpu_count: Number of CPU cores available
            - memory_gb: Total system memory in GB
            - timestamp: Unix timestamp of when results were saved

        Args:
            filename (str): Path to the output JSON file. Defaults to
                'performance_baseline.json'. Can include relative or absolute path.

        Example:
            >>> benchmark = PerformanceBenchmark()
            >>> benchmark.run_all_benchmarks()
            >>> benchmark.save_results('my_results.json')
            Benchmark results saved to: my_results.json
        """
        import json

        # Add system information to results for context
        self.results["system_info"] = {
            "python_version": sys.version,
            "cpu_count": psutil.cpu_count(),
            "memory_gb": psutil.virtual_memory().total / 1024 / 1024 / 1024,
            "timestamp": time.time(),
        }

        # Write results to JSON file with pretty formatting
        with open(filename, "w") as f:
            json.dump(self.results, f, indent=2)

        print(f"Benchmark results saved to: {filename}")

    def print_summary(self):
        """Print a formatted summary of benchmark results.

        Displays a concise summary of all benchmark results in a human-readable
        format. Shows the key metric for each benchmark type:
            - Strategy creation: Average time per iteration (ms)
            - Indicator calculation: Processing speed (points/sec)
            - Data access: Average access time (microseconds)
            - Parameter access: Average access time (microseconds)

        Only prints results for benchmarks that have been executed. If a benchmark
        hasn't been run, it is silently skipped.

        Example:
            >>> benchmark = PerformanceBenchmark()
            >>> benchmark.run_all_benchmarks()
            >>> benchmark.print_summary()
            ============================================================
            Performance Benchmark Results Summary
            ============================================================
            Strategy creation: 2.45ms/iteration
            Indicator calculation: 15234 points/sec
            Data access: 12.34μs/access
            Parameter access: 0.1234μs/access
        """
        # Display summary header
        print("=" * 60)
        print("Performance Benchmark Results Summary")
        print("=" * 60)

        # Print each benchmark result if available
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
    """Main entry point for the performance benchmark tool.

    Creates a PerformanceBenchmark instance, executes all benchmarks,
    prints a summary of results, and saves them to a JSON file.

    This function allows the module to be run directly as a script:
        $ python tools/performance_benchmark.py

    The results will be saved to 'performance_baseline.json' in the
    current directory by default.

    Example:
        Running from command line:
        $ cd /path/to/backtrader
        $ python tools/performance_benchmark.py

        This will:
        1. Display system information
        2. Run all four benchmark tests
        3. Print a summary of results
        4. Save results to performance_baseline.json
    """
    # Create benchmark instance
    benchmark = PerformanceBenchmark()

    # Execute all benchmark tests
    benchmark.run_all_benchmarks()

    # Display results summary
    benchmark.print_summary()

    # Save results to JSON file for later analysis
    benchmark.save_results()


if __name__ == "__main__":
    main()
