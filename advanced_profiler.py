#!/usr/bin/env python3
"""
Advanced Performance Profiler for Backtrader - Phase 3 Optimization
Identifies remaining bottlenecks and optimization opportunities
"""

import cProfile
import pstats
import io
import time
import subprocess
import sys
import tracemalloc
import psutil
import os
from pathlib import Path

class AdvancedProfiler:
    def __init__(self):
        self.results = {}
        
    def profile_test_suite(self):
        """Profile the complete test suite execution"""
        print("🔍 Phase 3: Advanced profiling analysis...")
        print("=" * 80)
        
        # Start memory tracking
        tracemalloc.start()
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Profile test execution
        pr = cProfile.Profile()
        start_time = time.perf_counter()
        
        pr.enable()
        
        # Run a subset of critical tests for profiling
        try:
            result = subprocess.run([
                'python', '-m', 'pytest', 
                'tests/original_tests/test_strategy_unoptimized.py',
                'tests/original_tests/test_strategy_optimized.py', 
                'tests/original_tests/test_ind_sma.py',
                'tests/original_tests/test_analyzer-sqn.py',
                'tests/original_tests/test_analyzer-timereturn.py',
                '-v', '--tb=short'
            ], capture_output=True, text=True, timeout=120)
            
        except subprocess.TimeoutExpired:
            print("⚠️  Profiling timeout - tests took too long")
            result = None
            
        pr.disable()
        end_time = time.perf_counter()
        
        # Memory analysis
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        execution_time = end_time - start_time
        
        # Analyze profiling results
        s = io.StringIO()
        ps = pstats.Stats(pr, stream=s)
        ps.sort_stats('cumulative')
        ps.print_stats(30)  # Top 30 functions
        
        profile_output = s.getvalue()
        
        # Store results
        self.results['execution_time'] = execution_time
        self.results['memory_used'] = final_memory - initial_memory
        self.results['peak_memory'] = peak / 1024 / 1024  # MB
        self.results['profile_output'] = profile_output
        self.results['test_success'] = result.returncode == 0 if result else False
        
        return self.results
    
    def analyze_hotspots(self):
        """Analyze performance hotspots and suggest optimizations"""
        if 'profile_output' not in self.results:
            return []
            
        lines = self.results['profile_output'].split('\n')
        hotspots = []
        suggestions = []
        
        # Look for expensive function calls
        for line in lines:
            if any(keyword in line.lower() for keyword in ['next', 'once', 'calculate', '__init__', '__getitem__']):
                if 'seconds' in line and any(char.isdigit() for char in line):
                    hotspots.append(line.strip())
        
        # Generate optimization suggestions
        if any('next' in spot for spot in hotspots):
            suggestions.append("📈 Optimize next() methods with vectorization or caching")
            
        if any('__init__' in spot for spot in hotspots):
            suggestions.append("🔧 Reduce object initialization overhead with object pooling")
            
        if any('__getitem__' in spot for spot in hotspots):
            suggestions.append("⚡ Optimize data access patterns with better indexing")
            
        if self.results['memory_used'] > 50:  # MB
            suggestions.append("💾 Implement memory pooling to reduce allocation overhead")
            
        if self.results['execution_time'] > 25:  # seconds
            suggestions.append("🚀 Consider parallel processing for independent calculations")
            
        return hotspots, suggestions
    
    def benchmark_specific_operations(self):
        """Benchmark specific operations for targeted optimization"""
        print("\n🎯 Benchmarking specific operations...")
        
        benchmarks = {}
        
        # Benchmark SMA calculation
        try:
            import backtrader as bt
            import numpy as np
            
            # Create test data
            test_data = [100 + i * 0.1 + (i % 7) * 0.5 for i in range(1000)]
            
            # Benchmark manual SMA calculation
            start_time = time.perf_counter()
            for i in range(100):  # 100 iterations
                period = 20
                if len(test_data) >= period:
                    sma = sum(test_data[-period:]) / period
            manual_time = time.perf_counter() - start_time
            
            # Benchmark numpy SMA calculation  
            start_time = time.perf_counter()
            for i in range(100):  # 100 iterations
                period = 20
                if len(test_data) >= period:
                    sma = np.mean(test_data[-period:])
            numpy_time = time.perf_counter() - start_time
            
            benchmarks['sma_manual'] = manual_time
            benchmarks['sma_numpy'] = numpy_time
            benchmarks['sma_speedup'] = manual_time / numpy_time if numpy_time > 0 else 1
            
        except Exception as e:
            benchmarks['sma_error'] = str(e)
        
        # Benchmark data structure operations
        start_time = time.perf_counter()
        test_list = []
        for i in range(10000):
            test_list.append(i)
            if len(test_list) > 100:
                test_list.pop(0)
        list_time = time.perf_counter() - start_time
        
        from collections import deque
        start_time = time.perf_counter()
        test_deque = deque(maxlen=100)
        for i in range(10000):
            test_deque.append(i)
        deque_time = time.perf_counter() - start_time
        
        benchmarks['list_operations'] = list_time
        benchmarks['deque_operations'] = deque_time
        benchmarks['deque_speedup'] = list_time / deque_time if deque_time > 0 else 1
        
        return benchmarks
    
    def generate_optimization_report(self):
        """Generate comprehensive optimization report"""
        print("\n📊 Phase 3 Optimization Analysis Report")
        print("=" * 80)
        
        # Performance metrics
        print(f"⏱️  Test execution time: {self.results.get('execution_time', 0):.2f} seconds")
        print(f"💾 Memory usage: {self.results.get('memory_used', 0):.2f} MB")
        print(f"🔺 Peak memory: {self.results.get('peak_memory', 0):.2f} MB")
        print(f"✅ Test success: {self.results.get('test_success', False)}")
        
        # Hotspot analysis
        hotspots, suggestions = self.analyze_hotspots()
        
        if hotspots:
            print(f"\n🔥 Performance Hotspots (Top {len(hotspots)}):")
            for i, hotspot in enumerate(hotspots[:10], 1):  # Top 10
                print(f"  {i}. {hotspot}")
        
        if suggestions:
            print(f"\n💡 Phase 3 Optimization Suggestions:")
            for i, suggestion in enumerate(suggestions, 1):
                print(f"  {i}. {suggestion}")
        
        # Benchmark results
        benchmarks = self.benchmark_specific_operations()
        print(f"\n⚡ Operation Benchmarks:")
        
        if 'sma_speedup' in benchmarks:
            print(f"  📈 SMA calculation: {benchmarks['sma_speedup']:.2f}x faster with numpy")
            
        if 'deque_speedup' in benchmarks:
            print(f"  📊 Data structures: {benchmarks['deque_speedup']:.2f}x faster with deque")
        
        # Overall assessment
        current_time = self.results.get('execution_time', 0)
        target_time = 25  # New target: under 25 seconds
        
        print(f"\n🎯 Phase 3 Performance Assessment:")
        if current_time < target_time:
            print(f"  ✅ EXCELLENT: {current_time:.1f}s < {target_time}s target")
            print(f"  🏆 Consider this optimization complete!")
        else:
            improvement_needed = ((current_time - target_time) / current_time) * 100
            print(f"  📈 {improvement_needed:.1f}% additional improvement needed for {target_time}s target")
            
        return {
            'hotspots': hotspots,
            'suggestions': suggestions,
            'benchmarks': benchmarks,
            'performance_grade': 'A+' if current_time < target_time else 'A' if current_time < 30 else 'B+'
        }

def main():
    """Run advanced profiling analysis"""
    print("🚀 Starting Phase 3 Advanced Performance Analysis...")
    
    profiler = AdvancedProfiler()
    
    # Run profiling
    results = profiler.profile_test_suite()
    
    # Generate comprehensive report  
    report = profiler.generate_optimization_report()
    
    # Summary
    print(f"\n" + "=" * 80)
    print(f"📋 PHASE 3 ANALYSIS COMPLETE")
    print(f"Performance Grade: {report['performance_grade']}")
    print(f"Execution Time: {results.get('execution_time', 0):.2f}s")
    print(f"Ready for Phase 3 optimizations: {len(report['suggestions'])} opportunities identified")
    print("=" * 80)

if __name__ == "__main__":
    main() 