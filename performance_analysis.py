#!/usr/bin/env python3
"""
Performance Analysis Script for Backtrader
Identifies optimization opportunities and performance bottlenecks
"""

import cProfile
import pstats
import io
import sys
import time
from pathlib import Path
import tracemalloc
import gc
import os
import subprocess
import importlib

class PerformanceAnalyzer:
    def __init__(self):
        self.results = {}
        self.baseline_metrics = {}
        
    def analyze_imports(self):
        """Analyze import performance and identify slow imports"""
        print("🔍 Analyzing import performance...")
        import_times = {}
        
        # Key modules to analyze
        modules_to_test = [
            'backtrader',
            'backtrader.indicators',
            'backtrader.strategies',
            'backtrader.feeds',
            'backtrader.brokers',
            'backtrader.analyzers'
        ]
        
        for module_name in modules_to_test:
            start_time = time.perf_counter()
            try:
                importlib.import_module(module_name)
                import_time = time.perf_counter() - start_time
                import_times[module_name] = import_time
            except ImportError as e:
                import_times[module_name] = f"Import Error: {e}"
        
        self.results['import_times'] = import_times
        return import_times
    
    def analyze_memory_usage(self):
        """Analyze memory usage patterns"""
        print("🧠 Analyzing memory usage...")
        tracemalloc.start()
        
        # Import backtrader and create basic objects
        import backtrader as bt
        
        # Take snapshot after imports
        snapshot1 = tracemalloc.take_snapshot()
        
        # Create some basic objects
        cerebro = bt.Cerebro()
        data = bt.feeds.GenericCSVData(dataname=None)  # Mock data
        
        # Add a simple strategy
        class TestStrategy(bt.Strategy):
            def next(self):
                pass
        
        cerebro.addstrategy(TestStrategy)
        
        # Take another snapshot
        snapshot2 = tracemalloc.take_snapshot()
        
        # Compare snapshots
        top_stats = snapshot2.compare_to(snapshot1, 'lineno')
        
        memory_stats = []
        for stat in top_stats[:10]:  # Top 10 memory allocations
            memory_stats.append({
                'traceback': str(stat.traceback),
                'size_diff': stat.size_diff,
                'count_diff': stat.count_diff
            })
        
        tracemalloc.stop()
        self.results['memory_usage'] = memory_stats
        return memory_stats
    
    def profile_test_suite(self):
        """Profile the test suite to identify slow tests"""
        print("🧪 Profiling test suite...")
        
        # Profile test execution
        pr = cProfile.Profile()
        pr.enable()
        
        # Run a subset of tests
        start_time = time.perf_counter()
        try:
            result = subprocess.run(
                ['python', '-m', 'pytest', 'tests/original_tests/test_ind_sma.py', '-v', '--tb=short'],
                capture_output=True,
                text=True,
                timeout=60
            )
            test_time = time.perf_counter() - start_time
            test_success = result.returncode == 0
        except subprocess.TimeoutExpired:
            test_time = 60
            test_success = False
        
        pr.disable()
        
        # Analyze profile
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
        ps.print_stats(20)  # Top 20 functions
        profile_output = s.getvalue()
        
        self.results['test_profile'] = {
            'execution_time': test_time,
            'success': test_success,
            'profile_data': profile_output
        }
        
        return self.results['test_profile']
    
    def analyze_indicator_performance(self):
        """Analyze performance of key indicators"""
        print("📊 Analyzing indicator performance...")
        
        try:
            import backtrader as bt
            import numpy as np
            
            # Create test data
            data_length = 1000
            test_data = np.random.randn(data_length).cumsum() + 100
            
            indicator_times = {}
            
            # Test SMA performance
            start_time = time.perf_counter()
            try:
                from backtrader.indicators import SimpleMovingAverage
                # Create mock data feed
                class MockData:
                    def __init__(self, data):
                        self.close = data
                        self.lines = type('Lines', (), {'close': data})()
                
                mock_data = MockData(test_data)
                sma = SimpleMovingAverage(mock_data, period=20)
                sma_time = time.perf_counter() - start_time
                indicator_times['SMA'] = sma_time
            except Exception as e:
                indicator_times['SMA'] = f"Error: {e}"
            
            # Test other indicators if available
            indicators_to_test = ['EMA', 'MACD', 'RSI', 'BollingerBands']
            for indicator_name in indicators_to_test:
                try:
                    indicator_class = getattr(bt.indicators, indicator_name, None)
                    if indicator_class:
                        start_time = time.perf_counter()
                        indicator = indicator_class(mock_data)
                        indicator_time = time.perf_counter() - start_time
                        indicator_times[indicator_name] = indicator_time
                except Exception as e:
                    indicator_times[indicator_name] = f"Error: {e}"
            
            self.results['indicator_performance'] = indicator_times
            return indicator_times
            
        except Exception as e:
            error_result = {'error': str(e), 'traceback': traceback.format_exc()}
            self.results['indicator_performance'] = error_result
            return error_result
    
    def identify_optimization_opportunities(self):
        """Identify specific optimization opportunities"""
        print("🎯 Identifying optimization opportunities...")
        
        opportunities = []
        
        # Check import times
        if 'import_times' in self.results:
            for module, time_val in self.results['import_times'].items():
                if isinstance(time_val, float) and time_val > 0.1:  # Slow import
                    opportunities.append({
                        'type': 'slow_import',
                        'module': module,
                        'time': time_val,
                        'suggestion': 'Consider lazy loading or module restructuring'
                    })
        
        # Check memory usage
        if 'memory_usage' in self.results:
            for stat in self.results['memory_usage'][:3]:  # Top 3 memory consumers
                if stat['size_diff'] > 1024 * 1024:  # More than 1MB
                    opportunities.append({
                        'type': 'high_memory_usage',
                        'location': stat['traceback'][:100],  # First 100 chars
                        'size_diff': stat['size_diff'],
                        'suggestion': 'Review memory allocation patterns'
                    })
        
        # Check test performance
        if 'test_profile' in self.results:
            if self.results['test_profile']['execution_time'] > 10:  # Slow tests
                opportunities.append({
                    'type': 'slow_tests',
                    'time': self.results['test_profile']['execution_time'],
                    'suggestion': 'Optimize test execution or use parallel testing'
                })
        
        self.results['optimization_opportunities'] = opportunities
        return opportunities
    
    def generate_report(self):
        """Generate a comprehensive performance report"""
        print("\n" + "="*60)
        print("🚀 BACKTRADER PERFORMANCE ANALYSIS REPORT")
        print("="*60)
        
        # Import performance
        if 'import_times' in self.results:
            print("\n📦 IMPORT PERFORMANCE:")
            for module, time_val in self.results['import_times'].items():
                if isinstance(time_val, float):
                    status = "⚠️ SLOW" if time_val > 0.1 else "✅ FAST"
                    print(f"  {module}: {time_val:.4f}s {status}")
                else:
                    print(f"  {module}: {time_val}")
        
        # Memory usage
        if 'memory_usage' in self.results:
            print("\n🧠 TOP MEMORY ALLOCATIONS:")
            for i, stat in enumerate(self.results['memory_usage'][:5], 1):
                size_mb = stat['size_diff'] / (1024 * 1024)
                print(f"  {i}. {size_mb:.2f} MB - {stat['traceback'][:80]}...")
        
        # Test performance
        if 'test_profile' in self.results:
            test_data = self.results['test_profile']
            status = "✅ PASSED" if test_data['success'] else "❌ FAILED"
            print(f"\n🧪 TEST PERFORMANCE:")
            print(f"  Execution time: {test_data['execution_time']:.2f}s")
            print(f"  Status: {status}")
        
        # Indicator performance
        if 'indicator_performance' in self.results:
            print("\n📊 INDICATOR PERFORMANCE:")
            perf_data = self.results['indicator_performance']
            if 'error' not in perf_data:
                for indicator, time_val in perf_data.items():
                    if isinstance(time_val, float):
                        print(f"  {indicator}: {time_val:.4f}s")
                    else:
                        print(f"  {indicator}: {time_val}")
            else:
                print(f"  Error: {perf_data['error']}")
        
        # Optimization opportunities
        if 'optimization_opportunities' in self.results:
            print("\n🎯 OPTIMIZATION OPPORTUNITIES:")
            opportunities = self.results['optimization_opportunities']
            if opportunities:
                for i, opp in enumerate(opportunities, 1):
                    print(f"  {i}. {opp['type'].upper()}")
                    print(f"     Suggestion: {opp['suggestion']}")
                    if 'time' in opp:
                        print(f"     Current time: {opp['time']:.2f}s")
                    if 'size_diff' in opp:
                        print(f"     Memory usage: {opp['size_diff']/(1024*1024):.2f} MB")
                    print()
            else:
                print("  ✅ No major optimization opportunities identified!")
        
        print("\n" + "="*60)
        print("Analysis complete! Review the suggestions above.")
        print("="*60)

def main():
    """Main analysis function"""
    analyzer = PerformanceAnalyzer()
    
    print("🚀 Starting Backtrader Performance Analysis...")
    print("This may take a few minutes...\n")
    
    # Run all analyses
    analyzer.analyze_imports()
    analyzer.analyze_memory_usage()
    analyzer.profile_test_suite()
    analyzer.analyze_indicator_performance()
    analyzer.identify_optimization_opportunities()
    
    # Generate report
    analyzer.generate_report()
    
    return analyzer.results

if __name__ == "__main__":
    main() 