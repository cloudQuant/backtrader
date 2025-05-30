#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import unittest
import threading
import time
import gc
import sys
from unittest.mock import Mock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor, as_completed
import weakref

# Mock dependencies to avoid import errors
sys.modules['oandapy'] = Mock()
sys.modules['ccxt'] = Mock() 
sys.modules['ctpbee'] = Mock()
sys.modules['ctpbee.api'] = Mock()
sys.modules['ctpbee.constant'] = Mock()
sys.modules['ctpbee.helpers'] = Mock()

# Import our refactored stores
from backtrader.stores.ibstore import IBStore
from backtrader.mixins import ParameterizedSingletonMixin


class TestStoreSingletonBehavior(unittest.TestCase):
    """Test singleton behavior of refactored Store classes."""
    
    def setUp(self):
        """Reset singleton instances before each test."""
        # Reset all store instances
        if hasattr(IBStore, '_reset_instance'):
            IBStore._reset_instance()
            
    def tearDown(self):
        """Clean up after each test."""
        gc.collect()
        
    def test_ibstore_singleton_behavior(self):
        """Test IBStore singleton behavior."""
        # Mock IB dependencies
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            # Create multiple instances
            store1 = IBStore()
            store2 = IBStore()
            
            # Should be the same instance
            self.assertIs(store1, store2)
            self.assertEqual(id(store1), id(store2))
            
    def test_singleton_thread_safety(self):
        """Test singleton creation is thread-safe."""
        instances = []
        
        def create_instance():
            with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
                mock_ibopt.ibConnection.return_value = Mock()
                instance = IBStore()
                instances.append(instance)
                
        # Create instances from multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=create_instance)
            threads.append(thread)
            
        # Start all threads
        for thread in threads:
            thread.start()
            
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
            
        # All instances should be the same
        first_instance = instances[0]
        for instance in instances[1:]:
            self.assertIs(instance, first_instance)
            
    def test_singleton_memory_management(self):
        """Test singleton memory management."""
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            # Create instance and get weak reference
            store = IBStore()
            store_id = id(store)
            weak_ref = weakref.ref(store)
            
            # Delete the reference
            del store
            
            # Create new instance - should reuse the same one due to singleton
            store2 = IBStore()
            self.assertEqual(id(store2), store_id)
            self.assertIsNotNone(weak_ref())


class TestStoreThreadSafety(unittest.TestCase):
    """Test thread safety of Store operations."""
    
    def setUp(self):
        """Reset singleton instances before each test."""
        if hasattr(IBStore, '_reset_instance'):
            IBStore._reset_instance()
            
    def test_concurrent_access(self):
        """Test concurrent access to store methods."""
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            store = IBStore()
            results = []
            
            def access_store(thread_id):
                """Access store methods concurrently."""
                try:
                    # Test various store operations
                    store.getdata()  # Should not crash
                    store.getbroker()  # Should not crash
                    results.append(f"Thread {thread_id}: Success")
                except Exception as e:
                    results.append(f"Thread {thread_id}: Error - {str(e)}")
                    
            # Run concurrent access test
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(access_store, i) for i in range(10)]
                for future in as_completed(futures):
                    future.result()  # Wait for completion
                    
            # Check that all operations succeeded
            success_count = sum(1 for result in results if "Success" in result)
            self.assertEqual(success_count, 10, f"Results: {results}")
            
    def test_parameter_thread_safety(self):
        """Test parameter access thread safety."""
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            store = IBStore()
            parameter_values = []
            
            def access_parameters(thread_id):
                """Access store parameters concurrently."""
                try:
                    # Access parameter system
                    if hasattr(store, 'p'):
                        param_dict = dict(store.p._getpairs())
                        parameter_values.append(param_dict)
                    else:
                        parameter_values.append({})
                except Exception as e:
                    self.fail(f"Thread {thread_id} failed to access parameters: {e}")
                    
            # Run concurrent parameter access
            threads = []
            for i in range(5):
                thread = threading.Thread(target=access_parameters, args=(i,))
                threads.append(thread)
                
            for thread in threads:
                thread.start()
                
            for thread in threads:
                thread.join()
                
            # All parameter accesses should succeed
            self.assertEqual(len(parameter_values), 5)


class TestStorePerformance(unittest.TestCase):
    """Test performance of refactored stores."""
    
    def setUp(self):
        """Set up performance testing environment."""
        if hasattr(IBStore, '_reset_instance'):
            IBStore._reset_instance()
            
    def test_singleton_creation_performance(self):
        """Test singleton instance creation performance."""
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            # Measure time for first instance creation
            start_time = time.time()
            store1 = IBStore()
            first_creation_time = time.time() - start_time
            
            # Measure time for subsequent instance access
            times = []
            for _ in range(100):
                start_time = time.time()
                store = IBStore()
                times.append(time.time() - start_time)
                
            avg_access_time = sum(times) / len(times)
            
            # Subsequent accesses should be much faster
            self.assertLess(avg_access_time, first_creation_time)
            self.assertLess(avg_access_time, 0.001)  # Should be sub-millisecond
            
    def test_memory_usage(self):
        """Test memory usage of singleton pattern."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            # Create many "instances" (should all be the same singleton)
            stores = []
            for _ in range(1000):
                stores.append(IBStore())
                
            final_memory = process.memory_info().rss
            memory_increase = final_memory - initial_memory
            
            # Memory increase should be minimal (just references)
            # Allow for some overhead but should be much less than 1000 separate instances
            max_acceptable_increase = 1024 * 1024  # 1MB
            self.assertLess(memory_increase, max_acceptable_increase,
                          f"Memory increased by {memory_increase} bytes, expected < {max_acceptable_increase}")


class TestStoreIntegration(unittest.TestCase):
    """Test integration of refactored stores with backtrader components."""
    
    def setUp(self):
        """Set up integration testing environment."""
        if hasattr(IBStore, '_reset_instance'):
            IBStore._reset_instance()
            
    def test_parameter_system_integration(self):
        """Test integration with backtrader parameter system."""
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            store = IBStore()
            
            # Test parameter access
            self.assertTrue(hasattr(store, 'params'))
            
            # Test parameter inheritance
            self.assertTrue(isinstance(store, ParameterizedSingletonMixin))
            
    def test_data_broker_integration(self):
        """Test integration with data and broker classes."""
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            store = IBStore()
            
            # Test class methods exist
            self.assertTrue(hasattr(store, 'getdata'))
            self.assertTrue(hasattr(store, 'getbroker'))
            self.assertTrue(callable(store.getdata))
            self.assertTrue(callable(store.getbroker))
            
            # Test class attributes
            self.assertTrue(hasattr(store, 'BrokerCls'))
            self.assertTrue(hasattr(store, 'DataCls'))


class TestStoreMigrationCompatibility(unittest.TestCase):
    """Test backward compatibility after migration."""
    
    def setUp(self):
        """Set up compatibility testing environment."""
        if hasattr(IBStore, '_reset_instance'):
            IBStore._reset_instance()
            
    def test_api_compatibility(self):
        """Test that all public APIs remain unchanged."""
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            store = IBStore()
            
            # Test essential methods exist
            essential_methods = [
                'getdata', 'getbroker', 'start', 'stop',
                'put_notification', 'get_notifications'
            ]
            
            for method_name in essential_methods:
                self.assertTrue(hasattr(store, method_name),
                              f"Missing method: {method_name}")
                self.assertTrue(callable(getattr(store, method_name)),
                              f"Method not callable: {method_name}")
                              
    def test_inheritance_chain(self):
        """Test that inheritance chain is correct."""
        with patch('backtrader.stores.ibstore.ibopt') as mock_ibopt:
            mock_ibopt.ibConnection.return_value = Mock()
            
            store = IBStore()
            
            # Test MRO includes our mixins
            mro_classes = [cls.__name__ for cls in store.__class__.__mro__]
            self.assertIn('ParameterizedSingletonMixin', mro_classes)
            self.assertIn('MetaParams', mro_classes)


def run_store_system_tests():
    """Run all store system tests."""
    print("\n" + "="*80)
    print("🧪 Running Store System Tests (Day 19-21)")
    print("="*80)
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test classes
    test_classes = [
        TestStoreSingletonBehavior,
        TestStoreThreadSafety, 
        TestStorePerformance,
        TestStoreIntegration,
        TestStoreMigrationCompatibility
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print("\n" + "-"*80)
    print(f"📊 Test Results Summary:")
    print(f"   Tests run: {result.testsRun}")
    print(f"   Failures: {len(result.failures)}")
    print(f"   Errors: {len(result.errors)}")
    print(f"   Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    
    if result.failures:
        print(f"   ❌ Failures: {[test.id() for test, _ in result.failures]}")
        
    if result.errors:
        print(f"   🚨 Errors: {[test.id() for test, _ in result.errors]}")
    
    print("-"*80)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_store_system_tests()
    sys.exit(0 if success else 1) 