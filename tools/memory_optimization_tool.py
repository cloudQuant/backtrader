#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import gc
import sys
import psutil
import os
import weakref
import time
from collections import defaultdict
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


class MemoryProfiler:
    """Memory usage profiler for Store classes."""
    
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.baseline_memory = 0
        self.memory_snapshots = []
        
    def start_profiling(self):
        """Start memory profiling."""
        gc.collect()  # Clean up before measuring
        self.baseline_memory = self.process.memory_info().rss
        self.memory_snapshots = [(0, self.baseline_memory)]
        
    def take_snapshot(self, label="snapshot"):
        """Take a memory snapshot."""
        current_memory = self.process.memory_info().rss
        memory_increase = current_memory - self.baseline_memory
        self.memory_snapshots.append((label, current_memory, memory_increase))
        return memory_increase
        
    def get_memory_report(self):
        """Get detailed memory usage report."""
        if not self.memory_snapshots:
            return "No memory snapshots available"
            
        report = ["Memory Usage Report:"]
        report.append("=" * 50)
        
        for i, snapshot in enumerate(self.memory_snapshots):
            if len(snapshot) == 2:  # Baseline
                label, memory = snapshot
                report.append(f"Baseline: {memory / (1024*1024):.2f} MB")
            else:  # Regular snapshot
                label, memory, increase = snapshot
                report.append(f"{label}: {memory / (1024*1024):.2f} MB (+{increase / 1024:.1f} KB)")
                
        return "\n".join(report)


class SlottedStore:
    """Example Store class with __slots__ optimization."""
    
    __slots__ = ['_connection', '_broker', '_data', '_notifications', '_params']
    
    def __init__(self):
        self._connection = None
        self._broker = None
        self._data = None
        self._notifications = []
        self._params = {}
        
    def getdata(self, *args, **kwargs):
        """Get data."""
        return self._data
        
    def getbroker(self, *args, **kwargs):
        """Get broker."""
        return self._broker
        
    def put_notification(self, msg):
        """Put notification."""
        self._notifications.append(msg)
        
    def get_notifications(self):
        """Get notifications."""
        return self._notifications.copy()


class OptimizedStore:
    """Store class with multiple memory optimizations."""
    
    __slots__ = ['_connection', '_broker_ref', '_data_cache', '_notifications', '_params']
    
    def __init__(self):
        self._connection = None
        self._broker_ref = None  # Use weak reference for broker
        self._data_cache = {}  # Use dict instead of list for better access patterns
        self._notifications = []
        self._params = {}
        
    def getdata(self, *args, **kwargs):
        """Get data with caching."""
        key = str(args) + str(kwargs)
        if key not in self._data_cache:
            # Simulate data creation
            self._data_cache[key] = f"data_{key}"
        return self._data_cache[key]
        
    def getbroker(self, *args, **kwargs):
        """Get broker with weak reference."""
        if self._broker_ref is None:
            broker = f"broker_{id(self)}"
            self._broker_ref = weakref.ref(lambda: broker)
        return self._broker_ref()
        
    def put_notification(self, msg):
        """Put notification with size limit."""
        self._notifications.append(msg)
        # Keep only last 100 notifications to prevent memory growth
        if len(self._notifications) > 100:
            self._notifications = self._notifications[-100:]
            
    def get_notifications(self):
        """Get notifications."""
        return self._notifications.copy()


class MemoryOptimizationTool:
    """Tool for implementing and testing memory optimizations."""
    
    def __init__(self):
        self.profiler = MemoryProfiler()
        self.test_results = {}
        
    def test_baseline_memory_usage(self):
        """Test baseline memory usage of original Store."""
        print("🔍 Testing baseline memory usage...")
        
        self.profiler.start_profiling()
        
        stores = []
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            # Create 100 store instances
            for i in range(100):
                stores.append(IBStore())
                if i % 20 == 0:
                    increase = self.profiler.take_snapshot(f"stores_{i}")
                    
        final_increase = self.profiler.take_snapshot("final_100_stores")
        
        self.test_results['baseline'] = {
            'memory_per_store': final_increase / 100,
            'total_memory': final_increase,
            'store_count': len(stores)
        }
        
        print(f"   Memory per store: {final_increase / 100 / 1024:.1f} KB")
        print(f"   Total memory increase: {final_increase / 1024:.1f} KB")
        
        # Clean up
        del stores
        gc.collect()
        
    def test_slots_optimization(self):
        """Test __slots__ memory optimization."""
        print("🚀 Testing __slots__ optimization...")
        
        self.profiler.start_profiling()
        
        # Test regular class without slots
        class RegularStore:
            def __init__(self):
                self.connection = None
                self.broker = None
                self.data = None
                self.notifications = []
                self.params = {}
                
        regular_stores = []
        for i in range(100):
            regular_stores.append(RegularStore())
            
        regular_memory = self.profiler.take_snapshot("regular_stores")
        del regular_stores
        gc.collect()
        
        # Test slotted class
        slotted_stores = []
        for i in range(100):
            slotted_stores.append(SlottedStore())
            
        slotted_memory = self.profiler.take_snapshot("slotted_stores")
        
        memory_savings = regular_memory - slotted_memory
        savings_percent = (memory_savings / regular_memory) * 100 if regular_memory > 0 else 0
        
        self.test_results['slots_optimization'] = {
            'regular_memory': regular_memory,
            'slotted_memory': slotted_memory,
            'memory_savings': memory_savings,
            'savings_percent': savings_percent
        }
        
        print(f"   Regular stores: {regular_memory / 1024:.1f} KB")
        print(f"   Slotted stores: {slotted_memory / 1024:.1f} KB")
        print(f"   Memory savings: {memory_savings / 1024:.1f} KB ({savings_percent:.1f}%)")
        
        del slotted_stores
        gc.collect()
        
    def test_weak_reference_optimization(self):
        """Test weak reference optimization."""
        print("🚀 Testing weak reference optimization...")
        
        self.profiler.start_profiling()
        
        # Test with strong references
        class StrongRefStore:
            def __init__(self):
                self.brokers = []
                self.data_sources = []
                
            def add_broker(self, broker):
                self.brokers.append(broker)
                
            def add_data_source(self, data):
                self.data_sources.append(data)
                
        # Test with weak references
        class WeakRefStore:
            def __init__(self):
                self.brokers = weakref.WeakSet()
                self.data_sources = weakref.WeakSet()
                
            def add_broker(self, broker):
                self.brokers.add(broker)
                
            def add_data_source(self, data):
                self.data_sources.add(data)
        
        # Create mock objects
        brokers = [Mock() for _ in range(50)]
        data_sources = [Mock() for _ in range(50)]
        
        # Test strong references
        strong_stores = []
        for i in range(20):
            store = StrongRefStore()
            for broker in brokers:
                store.add_broker(broker)
            for data in data_sources:
                store.add_data_source(data)
            strong_stores.append(store)
            
        strong_memory = self.profiler.take_snapshot("strong_ref_stores")
        
        # Test weak references
        weak_stores = []
        for i in range(20):
            store = WeakRefStore()
            for broker in brokers:
                store.add_broker(broker)
            for data in data_sources:
                store.add_data_source(data)
            weak_stores.append(store)
            
        weak_memory = self.profiler.take_snapshot("weak_ref_stores")
        
        memory_savings = strong_memory - weak_memory
        savings_percent = (memory_savings / strong_memory) * 100 if strong_memory > 0 else 0
        
        self.test_results['weak_ref_optimization'] = {
            'strong_ref_memory': strong_memory,
            'weak_ref_memory': weak_memory,
            'memory_savings': memory_savings,
            'savings_percent': savings_percent
        }
        
        print(f"   Strong references: {strong_memory / 1024:.1f} KB")
        print(f"   Weak references: {weak_memory / 1024:.1f} KB")
        print(f"   Memory savings: {memory_savings / 1024:.1f} KB ({savings_percent:.1f}%)")
        
    def test_optimized_store_implementation(self):
        """Test fully optimized store implementation."""
        print("🚀 Testing optimized store implementation...")
        
        self.profiler.start_profiling()
        
        # Test optimized stores
        optimized_stores = []
        for i in range(100):
            store = OptimizedStore()
            # Simulate some usage
            store.getdata("test", param=i)
            store.getbroker()
            store.put_notification(f"notification_{i}")
            optimized_stores.append(store)
            
        optimized_memory = self.profiler.take_snapshot("optimized_stores")
        
        # Compare with baseline if available
        if 'baseline' in self.test_results:
            baseline_memory = self.test_results['baseline']['total_memory']
            memory_improvement = baseline_memory - optimized_memory
            improvement_percent = (memory_improvement / baseline_memory) * 100 if baseline_memory > 0 else 0
            
            self.test_results['optimized_implementation'] = {
                'optimized_memory': optimized_memory,
                'baseline_memory': baseline_memory,
                'memory_improvement': memory_improvement,
                'improvement_percent': improvement_percent
            }
            
            print(f"   Optimized stores: {optimized_memory / 1024:.1f} KB")
            print(f"   Baseline stores: {baseline_memory / 1024:.1f} KB")
            print(f"   Memory improvement: {memory_improvement / 1024:.1f} KB ({improvement_percent:.1f}%)")
        else:
            print(f"   Optimized stores: {optimized_memory / 1024:.1f} KB")
            
    def test_garbage_collection_efficiency(self):
        """Test garbage collection efficiency."""
        print("🔍 Testing garbage collection efficiency...")
        
        self.profiler.start_profiling()
        
        # Create and destroy objects to test GC
        for cycle in range(5):
            stores = []
            with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                
                # Create many instances
                for i in range(50):
                    stores.append(IBStore())
                    
            cycle_memory = self.profiler.take_snapshot(f"cycle_{cycle}_created")
            
            # Delete references
            del stores
            
            # Force garbage collection
            collected = gc.collect()
            gc_memory = self.profiler.take_snapshot(f"cycle_{cycle}_collected")
            
            print(f"   Cycle {cycle}: Created +{cycle_memory/1024:.1f}KB, After GC +{gc_memory/1024:.1f}KB, Collected {collected} objects")
            
    def generate_optimization_recommendations(self):
        """Generate memory optimization recommendations."""
        print("\n" + "="*80)
        print("💡 Memory Optimization Recommendations")
        print("="*80)
        
        recommendations = []
        
        # Analyze test results and generate recommendations
        if 'slots_optimization' in self.test_results:
            savings = self.test_results['slots_optimization']['savings_percent']
            if savings > 10:
                recommendations.append({
                    'priority': 'high',
                    'category': 'slots',
                    'issue': f"__slots__ can save {savings:.1f}% memory",
                    'recommendation': "Add __slots__ to Store classes",
                    'implementation': "Define __slots__ with essential attributes only"
                })
                
        if 'weak_ref_optimization' in self.test_results:
            savings = self.test_results['weak_ref_optimization']['savings_percent']
            if savings > 5:
                recommendations.append({
                    'priority': 'medium',
                    'category': 'references',
                    'issue': f"Weak references can save {savings:.1f}% memory",
                    'recommendation': "Use weak references for non-essential object references",
                    'implementation': "Replace strong references with weakref.WeakSet/WeakValueDictionary"
                })
                
        if 'optimized_implementation' in self.test_results:
            improvement = self.test_results['optimized_implementation']['improvement_percent']
            if improvement > 0:
                recommendations.append({
                    'priority': 'high',
                    'category': 'implementation',
                    'issue': f"Optimized implementation improves memory by {improvement:.1f}%",
                    'recommendation': "Implement comprehensive memory optimizations",
                    'implementation': "Use __slots__, weak references, and caching strategies"
                })
                
        # Add general recommendations
        recommendations.extend([
            {
                'priority': 'medium',
                'category': 'caching',
                'issue': "Unbounded caches can cause memory leaks",
                'recommendation': "Implement LRU caches with size limits",
                'implementation': "Use collections.OrderedDict or functools.lru_cache"
            },
            {
                'priority': 'low',
                'category': 'cleanup',
                'issue': "Objects may not be garbage collected efficiently",
                'recommendation': "Implement proper cleanup methods",
                'implementation': "Add __del__ methods and explicit cleanup for resources"
            }
        ])
        
        # Display recommendations
        for i, rec in enumerate(recommendations, 1):
            priority_icon = "🔥" if rec['priority'] == 'high' else "⚠️" if rec['priority'] == 'medium' else "💡"
            print(f"{i}. {priority_icon} [{rec['priority'].upper()}] {rec['category'].title()}")
            print(f"   Issue: {rec['issue']}")
            print(f"   Recommendation: {rec['recommendation']}")
            print(f"   Implementation: {rec['implementation']}")
            print()
            
        return recommendations
        
    def run_comprehensive_memory_analysis(self):
        """Run comprehensive memory optimization analysis."""
        print("\n" + "="*80)
        print("💾 Store System Memory Optimization (Day 22-24)")
        print("="*80)
        
        start_time = time.time()
        
        # Run all tests
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
        
        # Generate recommendations
        recommendations = self.generate_optimization_recommendations()
        
        # Print summary
        print("📊 Memory Analysis Summary")
        print("="*80)
        print(f"⏱️ Analysis time: {analysis_time:.2f}s")
        print(f"🧪 Tests completed: {len(self.test_results)}")
        print(f"💡 Recommendations: {len(recommendations)}")
        
        return {
            'test_results': self.test_results,
            'recommendations': recommendations,
            'memory_report': self.profiler.get_memory_report()
        }
        
    def save_memory_report(self, filename="memory_optimization_report.json"):
        """Save memory optimization report."""
        import json
        
        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'test_results': self.test_results,
            'memory_snapshots': self.profiler.memory_snapshots,
            'baseline_memory_mb': self.profiler.baseline_memory / (1024 * 1024)
        }
        
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
            
        print(f"📄 Memory report saved to: {filename}")
        return filename


def main():
    """Main memory optimization execution."""
    optimizer = MemoryOptimizationTool()
    
    try:
        # Run comprehensive analysis
        results = optimizer.run_comprehensive_memory_analysis()
        
        # Save report
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


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 