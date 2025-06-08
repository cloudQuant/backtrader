#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import time
import sys
import subprocess
import psutil
import os
from contextlib import contextmanager


class PerformanceBenchmark:
    """Performance benchmarking tool for backtrader optimizations"""
    
    def __init__(self):
        self.results = {}
        self.process = psutil.Process(os.getpid())
        
    @contextmanager
    def measure_performance(self, test_name):
        """Context manager to measure execution time and memory usage"""
        # Get initial memory
        initial_memory = self.process.memory_info().rss / (1024 * 1024)  # MB
        
        # Start timing
        start_time = time.perf_counter()
        
        try:
            yield
        finally:
            # End timing
            end_time = time.perf_counter()
            
            # Get final memory
            final_memory = self.process.memory_info().rss / (1024 * 1024)  # MB
            
            # Store results
            self.results[test_name] = {
                'execution_time': end_time - start_time,
                'memory_used': final_memory - initial_memory,
                'initial_memory': initial_memory,
                'final_memory': final_memory
            }
    
    def run_test_suite(self):
        """Run the full test suite and measure performance"""
        print("🚀 Running performance benchmark for test suite...")
        
        with self.measure_performance('full_test_suite'):
            result = subprocess.run(['./install_unix.sh'], 
                                  capture_output=True, 
                                  text=True, 
                                  cwd='.')
            
        # Parse test results
        output = result.stdout
        if "passed" in output:
            # Extract test count and time
            lines = output.split('\n')
            for line in lines:
                if "passed" in line and "warnings" in line:
                    # Extract execution time
                    if " in " in line:
                        time_str = line.split(" in ")[-1].strip()
                        if time_str.endswith('s'):
                            try:
                                test_time = float(time_str[:-1])
                                self.results['full_test_suite']['test_execution_time'] = test_time
                            except:
                                pass
                    break
        
        return result.returncode == 0
    
    def benchmark_sma_calculation(self):
        """Benchmark SMA calculation performance"""
        print("📊 Benchmarking SMA calculation performance...")
        
        # Import backtrader
        import backtrader as bt
        import pandas as pd
        import numpy as np
        
        # Create test data
        dates = pd.date_range('2020-01-01', periods=1000, freq='D')
        prices = 100 + np.cumsum(np.random.randn(1000) * 0.01)
        
        data_feed = bt.feeds.PandasData(
            dataname=pd.DataFrame({
                'open': prices,
                'high': prices * 1.01,
                'low': prices * 0.99,
                'close': prices,
                'volume': np.random.randint(1000, 10000, 1000)
            }, index=dates)
        )
        
        class SMABenchmarkStrategy(bt.Strategy):
            def __init__(self):
                self.sma = bt.indicators.SMA(self.data.close, period=20)
                self.calculation_times = []
                
            def next(self):
                start_time = time.perf_counter()
                sma_value = self.sma[0]  # Access SMA value
                end_time = time.perf_counter()
                self.calculation_times.append(end_time - start_time)
        
        with self.measure_performance('sma_benchmark'):
            cerebro = bt.Cerebro()
            cerebro.adddata(data_feed)
            strategy = cerebro.addstrategy(SMABenchmarkStrategy)
            results = cerebro.run()
            
            if results and results[0].calculation_times:
                avg_sma_time = sum(results[0].calculation_times) / len(results[0].calculation_times)
                self.results['sma_benchmark']['avg_sma_access_time'] = avg_sma_time
                self.results['sma_benchmark']['total_sma_calculations'] = len(results[0].calculation_times)
    
    def benchmark_strategy_execution(self):
        """Benchmark strategy execution performance"""
        print("⚡ Benchmarking strategy execution performance...")
        
        import backtrader as bt
        import pandas as pd
        import numpy as np
        
        # Create larger test data
        dates = pd.date_range('2020-01-01', periods=5000, freq='D')
        prices = 100 + np.cumsum(np.random.randn(5000) * 0.01)
        
        data_feed = bt.feeds.PandasData(
            dataname=pd.DataFrame({
                'open': prices,
                'high': prices * 1.01,
                'low': prices * 0.99,
                'close': prices,
                'volume': np.random.randint(1000, 10000, 5000)
            }, index=dates)
        )
        
        class PerformanceTestStrategy(bt.Strategy):
            def __init__(self):
                self.sma_short = bt.indicators.SMA(self.data.close, period=10)
                self.sma_long = bt.indicators.SMA(self.data.close, period=50)
                self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)
                self.order_count = 0
                
            def next(self):
                if self.crossover > 0 and not self.position:
                    self.buy()
                    self.order_count += 1
                elif self.crossover < 0 and self.position:
                    self.sell()
                    self.order_count += 1
        
        with self.measure_performance('strategy_execution'):
            cerebro = bt.Cerebro()
            cerebro.adddata(data_feed)
            strategy = cerebro.addstrategy(PerformanceTestStrategy)
            results = cerebro.run()
            
            if results:
                self.results['strategy_execution']['orders_generated'] = results[0].order_count
    
    def print_results(self):
        """Print benchmark results"""
        print("\n" + "="*80)
        print("📈 PERFORMANCE BENCHMARK RESULTS")
        print("="*80)
        
        for test_name, data in self.results.items():
            print(f"\n🔧 {test_name.replace('_', ' ').title()}:")
            print(f"   ⏱️  Execution time: {data['execution_time']:.2f}s")
            print(f"   💾 Memory used: {data['memory_used']:.2f}MB")
            
            if 'test_execution_time' in data:
                print(f"   🧪 Test suite time: {data['test_execution_time']:.2f}s")
                
            if 'avg_sma_access_time' in data:
                print(f"   📊 Avg SMA access: {data['avg_sma_access_time']*1000000:.1f}μs")
                print(f"   🔢 Total SMA calcs: {data['total_sma_calculations']}")
                
            if 'orders_generated' in data:
                print(f"   📈 Orders generated: {data['orders_generated']}")
        
        # Calculate overall performance metrics
        total_time = sum(data['execution_time'] for data in self.results.values())
        total_memory = sum(data['memory_used'] for data in self.results.values())
        
        print(f"\n📊 OVERALL PERFORMANCE:")
        print(f"   ⏱️  Total benchmark time: {total_time:.2f}s")
        print(f"   💾 Total memory usage: {total_memory:.2f}MB")
        
        # Performance targets
        print(f"\n🎯 PERFORMANCE TARGET ANALYSIS:")
        if 'full_test_suite' in self.results:
            test_time = self.results['full_test_suite'].get('test_execution_time', 0)
            if test_time > 0:
                target_time = 30.0  # Target: <30 seconds
                if test_time <= target_time:
                    print(f"   ✅ Test suite time: {test_time:.1f}s (Target: ≤{target_time}s)")
                else:
                    print(f"   ❌ Test suite time: {test_time:.1f}s (Target: ≤{target_time}s)")
                    improvement_needed = test_time - target_time
                    print(f"      Need {improvement_needed:.1f}s improvement ({improvement_needed/test_time*100:.1f}%)")
        
        if 'sma_benchmark' in self.results:
            sma_time = self.results['sma_benchmark'].get('avg_sma_access_time', 0)
            if sma_time > 0:
                target_sma_time = 0.000001  # Target: <1μs
                if sma_time <= target_sma_time:
                    print(f"   ✅ SMA access time: {sma_time*1000000:.1f}μs (Target: ≤{target_sma_time*1000000:.1f}μs)")
                else:
                    print(f"   ⚠️  SMA access time: {sma_time*1000000:.1f}μs (Target: ≤{target_sma_time*1000000:.1f}μs)")
    
    def run_full_benchmark(self):
        """Run complete performance benchmark"""
        print("🚀 Starting comprehensive performance benchmark...")
        print("="*80)
        
        # Run test suite
        success = self.run_test_suite()
        if not success:
            print("❌ Test suite failed, skipping other benchmarks")
            return False
        
        # Run specific benchmarks
        try:
            self.benchmark_sma_calculation()
        except Exception as e:
            print(f"⚠️  SMA benchmark failed: {e}")
        
        try:
            self.benchmark_strategy_execution()
        except Exception as e:
            print(f"⚠️  Strategy benchmark failed: {e}")
        
        # Print results
        self.print_results()
        
        return True


if __name__ == "__main__":
    benchmark = PerformanceBenchmark()
    benchmark.run_full_benchmark() 