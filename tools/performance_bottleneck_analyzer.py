#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import time
import cProfile
import pstats
import io
import gc
import sys
import tracemalloc
import psutil
import os
import threading
from collections import defaultdict
from contextlib import contextmanager
from unittest.mock import Mock, patch

# Mock dependencies
sys.modules['oandapy'] = Mock()
sys.modules['ccxt'] = Mock()
sys.modules['ctpbee'] = Mock()
sys.modules['ctpbee.api'] = Mock()
sys.modules['ctpbee.constant'] = Mock()
sys.modules['ctpbee.helpers'] = Mock()

from backtrader.stores.ibstore import IBStore
from backtrader.mixins import ParameterizedSingletonMixin


class PerformanceBottleneckAnalyzer:
    """Analyze performance bottlenecks in Store system."""
    
    def __init__(self):
        self.profiling_results = {}
        self.memory_snapshots = []
        self.timing_data = defaultdict(list)
        self.bottlenecks = []
        
    def reset_environment(self):
        """Reset test environment."""
        if hasattr(IBStore, '_reset_instance'):
            IBStore._reset_instance()
        gc.collect()
        
    @contextmanager
    def profile_execution(self, operation_name):
        """Profile code execution with detailed timing."""
        # Start memory tracking
        tracemalloc.start()
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Start profiling
        profiler = cProfile.Profile()
        start_time = time.perf_counter()
        
        profiler.enable()
        try:
            yield
        finally:
            profiler.disable()
            end_time = time.perf_counter()
            
            # Get memory snapshot
            current_memory = process.memory_info().rss
            memory_trace = tracemalloc.take_snapshot()
            tracemalloc.stop()
            
            # Store results
            execution_time = end_time - start_time
            memory_increase = current_memory - initial_memory
            
            self.profiling_results[operation_name] = {
                'execution_time': execution_time,
                'memory_increase': memory_increase,
                'memory_trace': memory_trace,
                'profiler_stats': profiler
            }
            
            self.timing_data[operation_name].append(execution_time)
            
    def analyze_singleton_creation_bottlenecks(self):
        """Analyze bottlenecks in singleton creation."""
        print("🔍 Analyzing singleton creation bottlenecks...")
        
        # Test first creation
        self.reset_environment()
        with self.profile_execution('first_creation'):
            with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                store = IBStore()
                
        # Test subsequent access
        with self.profile_execution('subsequent_access'):
            with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                for _ in range(100):
                    store = IBStore()
                    
        # Analyze results
        first_time = self.profiling_results['first_creation']['execution_time']
        subsequent_avg = sum(self.timing_data['subsequent_access']) / len(self.timing_data['subsequent_access'])
        
        print(f"   First creation: {first_time*1000:.3f}ms")
        print(f"   Subsequent access (100x): {subsequent_avg*1000000:.1f}μs avg")
        
        # Identify bottlenecks
        if first_time > 0.005:  # > 5ms
            self.bottlenecks.append({
                'type': 'slow_initialization',
                'operation': 'first_creation',
                'time': first_time,
                'severity': 'high' if first_time > 0.01 else 'medium'
            })
            
        if subsequent_avg > 0.0001:  # > 0.1ms
            self.bottlenecks.append({
                'type': 'slow_access',
                'operation': 'subsequent_access',
                'time': subsequent_avg,
                'severity': 'medium'
            })
            
    def analyze_thread_contention(self):
        """Analyze thread contention and synchronization bottlenecks."""
        print("🔍 Analyzing thread contention...")
        
        self.reset_environment()
        contention_times = []
        
        def concurrent_access():
            with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                start_time = time.perf_counter()
                store = IBStore()
                end_time = time.perf_counter()
                contention_times.append(end_time - start_time)
                
        # Test with increasing thread counts
        for thread_count in [1, 2, 5, 10, 20]:
            test_times = []
            
            with self.profile_execution(f'threads_{thread_count}'):
                threads = []
                for _ in range(thread_count):
                    thread = threading.Thread(target=concurrent_access)
                    threads.append(thread)
                    
                start_time = time.perf_counter()
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                end_time = time.perf_counter()
                
                test_times.append(end_time - start_time)
                
            avg_time = sum(test_times) / len(test_times) if test_times else 0
            print(f"   {thread_count} threads: {avg_time*1000:.3f}ms total")
            
            # Check for contention
            if thread_count > 1 and avg_time > (test_times[0] if test_times else 0) * thread_count * 1.5:
                self.bottlenecks.append({
                    'type': 'thread_contention',
                    'operation': f'threads_{thread_count}',
                    'time': avg_time,
                    'severity': 'high' if avg_time > 0.1 else 'medium'
                })
                
    def analyze_method_performance(self):
        """Analyze performance of Store methods."""
        print("🔍 Analyzing method performance...")
        
        self.reset_environment()
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            store = IBStore()
            
        # Test different methods
        methods_to_test = [
            ('getdata', lambda: store.getdata()),
            ('getbroker', lambda: store.getbroker()),
            ('put_notification', lambda: store.put_notification("test")),
            ('get_notifications', lambda: store.get_notifications()),
        ]
        
        for method_name, method_func in methods_to_test:
            with self.profile_execution(f'method_{method_name}'):
                for _ in range(1000):
                    method_func()
                    
            avg_time = sum(self.timing_data[f'method_{method_name}']) / len(self.timing_data[f'method_{method_name}'])
            print(f"   {method_name}(): {avg_time*1000000:.1f}μs per call")
            
            # Check for slow methods
            if avg_time > 0.0001:  # > 0.1ms per call
                self.bottlenecks.append({
                    'type': 'slow_method',
                    'operation': method_name,
                    'time': avg_time,
                    'severity': 'medium'
                })
                
    def analyze_memory_usage_patterns(self):
        """Analyze memory usage patterns and leaks."""
        print("🔍 Analyzing memory usage patterns...")
        
        self.reset_environment()
        
        # Test memory growth with multiple references
        with self.profile_execution('memory_scaling'):
            stores = []
            with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                for i in range(1000):
                    stores.append(IBStore())
                    
                    # Sample memory every 100 iterations
                    if i % 100 == 0:
                        process = psutil.Process(os.getpid())
                        memory_mb = process.memory_info().rss / (1024 * 1024)
                        self.memory_snapshots.append((i, memory_mb))
                        
        # Analyze memory growth
        if len(self.memory_snapshots) >= 2:
            initial_memory = self.memory_snapshots[0][1]
            final_memory = self.memory_snapshots[-1][1]
            memory_per_ref = (final_memory - initial_memory) / 1000
            
            print(f"   Memory per reference: {memory_per_ref*1024:.1f}KB")
            print(f"   Total memory growth: {final_memory - initial_memory:.2f}MB")
            
            # Check for memory inefficiency
            if memory_per_ref > 0.01:  # > 10KB per reference
                self.bottlenecks.append({
                    'type': 'memory_inefficiency',
                    'operation': 'multiple_references',
                    'memory_per_ref': memory_per_ref,
                    'severity': 'high' if memory_per_ref > 0.1 else 'medium'
                })
                
    def analyze_profiling_data(self):
        """Analyze detailed profiling data to find hotspots."""
        print("🔍 Analyzing detailed profiling data...")
        
        for operation, data in self.profiling_results.items():
            print(f"\n   📊 {operation}:")
            
            # Get top time-consuming functions
            profiler_stats = data['profiler_stats']
            stats_stream = io.StringIO()
            stats = pstats.Stats(profiler_stats, stream=stats_stream)
            stats.sort_stats('cumulative')
            stats.print_stats(10)  # Top 10 functions
            
            profile_output = stats_stream.getvalue()
            
            # Parse for potential bottlenecks
            lines = profile_output.split('\n')
            for line in lines:
                if 'seconds' in line and any(keyword in line for keyword in ['__new__', '__init__', '__call__']):
                    # Extract timing info
                    parts = line.split()
                    if len(parts) >= 4:
                        try:
                            cumtime = float(parts[3])
                            if cumtime > 0.001:  # > 1ms
                                self.bottlenecks.append({
                                    'type': 'function_bottleneck',
                                    'operation': operation,
                                    'function': line.strip(),
                                    'time': cumtime,
                                    'severity': 'high' if cumtime > 0.01 else 'medium'
                                })
                        except (ValueError, IndexError):
                            continue
                            
    def generate_optimization_recommendations(self):
        """Generate specific optimization recommendations."""
        print("\n" + "="*80)
        print("💡 Optimization Recommendations")
        print("="*80)
        
        recommendations = []
        
        # Analyze bottlenecks and generate recommendations
        for bottleneck in self.bottlenecks:
            if bottleneck['type'] == 'slow_initialization':
                recommendations.append({
                    'priority': 'high',
                    'category': 'initialization',
                    'issue': f"Slow singleton initialization ({bottleneck['time']*1000:.1f}ms)",
                    'recommendation': "Optimize __init__ method, lazy load heavy components",
                    'implementation': "Move expensive operations to first method call"
                })
                
            elif bottleneck['type'] == 'slow_access':
                recommendations.append({
                    'priority': 'medium',
                    'category': 'access',
                    'issue': f"Slow singleton access ({bottleneck['time']*1000000:.1f}μs)",
                    'recommendation': "Optimize singleton lookup mechanism",
                    'implementation': "Cache instance reference, reduce lock overhead"
                })
                
            elif bottleneck['type'] == 'thread_contention':
                recommendations.append({
                    'priority': 'high',
                    'category': 'concurrency',
                    'issue': f"Thread contention in {bottleneck['operation']}",
                    'recommendation': "Reduce lock granularity, use read-write locks",
                    'implementation': "Implement double-checked locking pattern"
                })
                
            elif bottleneck['type'] == 'slow_method':
                recommendations.append({
                    'priority': 'medium',
                    'category': 'methods',
                    'issue': f"Slow method: {bottleneck['operation']}",
                    'recommendation': "Profile and optimize method implementation",
                    'implementation': "Add caching, reduce object creation"
                })
                
            elif bottleneck['type'] == 'memory_inefficiency':
                recommendations.append({
                    'priority': 'high',
                    'category': 'memory',
                    'issue': f"High memory usage per reference ({bottleneck['memory_per_ref']*1024:.1f}KB)",
                    'recommendation': "Optimize object structure, use __slots__",
                    'implementation': "Reduce instance variables, use weak references"
                })
                
        # Sort by priority
        priority_order = {'high': 3, 'medium': 2, 'low': 1}
        recommendations.sort(key=lambda x: priority_order[x['priority']], reverse=True)
        
        # Display recommendations
        for i, rec in enumerate(recommendations, 1):
            priority_icon = "🔥" if rec['priority'] == 'high' else "⚠️" if rec['priority'] == 'medium' else "💡"
            print(f"{i}. {priority_icon} [{rec['priority'].upper()}] {rec['category'].title()}")
            print(f"   Issue: {rec['issue']}")
            print(f"   Recommendation: {rec['recommendation']}")
            print(f"   Implementation: {rec['implementation']}")
            print()
            
        return recommendations
        
    def run_full_analysis(self):
        """Run complete performance bottleneck analysis."""
        print("\n" + "="*80)
        print("🔍 Store System Performance Bottleneck Analysis (Day 22-24)")
        print("="*80)
        
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
        
        # Generate recommendations
        recommendations = self.generate_optimization_recommendations()
        
        # Summary
        print("📊 Analysis Summary")
        print("="*80)
        print(f"⏱️ Analysis time: {analysis_time:.2f}s")
        print(f"🔍 Bottlenecks found: {len(self.bottlenecks)}")
        print(f"💡 Recommendations generated: {len(recommendations)}")
        
        # Categorize bottlenecks
        high_priority = sum(1 for b in self.bottlenecks if b.get('severity') == 'high')
        medium_priority = sum(1 for b in self.bottlenecks if b.get('severity') == 'medium')
        
        print(f"🔥 High priority issues: {high_priority}")
        print(f"⚠️ Medium priority issues: {medium_priority}")
        
        return {
            'bottlenecks': self.bottlenecks,
            'recommendations': recommendations,
            'profiling_results': self.profiling_results,
            'timing_data': dict(self.timing_data)
        }
        
    def save_analysis_report(self, filename="bottleneck_analysis_report.json"):
        """Save analysis results to file."""
        import json
        
        # Prepare serializable data
        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'bottlenecks': self.bottlenecks,
            'timing_summary': {
                op: {
                    'count': len(times),
                    'total': sum(times),
                    'average': sum(times) / len(times) if times else 0,
                    'min': min(times) if times else 0,
                    'max': max(times) if times else 0
                }
                for op, times in self.timing_data.items()
            },
            'memory_snapshots': self.memory_snapshots
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)
            
        print(f"📄 Analysis report saved to: {filename}")
        return filename


def main():
    """Main analysis execution."""
    analyzer = PerformanceBottleneckAnalyzer()
    
    try:
        # Run full analysis
        results = analyzer.run_full_analysis()
        
        # Save report
        report_file = analyzer.save_analysis_report()
        
        print(f"\n✅ Bottleneck analysis completed!")
        print(f"📊 Results: {len(results['bottlenecks'])} bottlenecks identified")
        print(f"💡 Recommendations: {len(results['recommendations'])} optimization suggestions")
        print(f"📄 Report: {report_file}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Analysis failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 