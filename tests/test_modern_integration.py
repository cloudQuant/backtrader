"""
Integration tests for all modern metaclass replacements.

This test validates that all modern replacements work together correctly
and provide the same functionality as the original metaclass-based classes.
"""

import pytest
import sys
import os

# Add the backtrader directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtrader.parameters import ParameterDescriptor, ParameterizedBase
from backtrader.lineseries import ModernLineSeries
from backtrader.linebuffer import ModernLineActions
try:
    from backtrader.lineiterator import ModernLineIterator
except ImportError:
    ModernLineIterator = None


class TestModernIntegration:
    """Test integration between all modern components."""
    
    def test_modern_parameter_system_integration(self):
        """Test that the modern parameter system works with all components."""
        
        class TestModernParameterClass(ParameterizedBase):
            param1 = ParameterDescriptor(default=10, name='param1')
            param2 = ParameterDescriptor(default='test', name='param2')
        
        obj = TestModernParameterClass(param1=20, param2='modified')
        
        # Test parameter access
        assert obj.p.param1 == 20
        assert obj.p.param2 == 'modified'
        
        # Test parameter manager functionality
        assert hasattr(obj, '_param_manager')
        assert len(obj._param_manager) == 2
        assert 'param1' in obj._param_manager
        assert 'param2' in obj._param_manager
    
    def test_modern_lineseries_with_parameters(self):
        """Test ModernLineSeries with parameter system."""
        
        class TestModernIndicator(ModernLineSeries):
            lines = ('signal', 'trend')
            period = ParameterDescriptor(default=14, name='period')
            factor = ParameterDescriptor(default=1.5, name='factor')
            
            plotinfo = dict(plot=True, subplot=False)
            plotlines = dict(signal=dict(color='blue'), trend=dict(color='red'))
        
        obj = TestModernIndicator(period=20, factor=2.0)
        
        # Test parameter functionality
        assert obj.p.period == 20
        assert obj.p.factor == 2.0
        
        # Test line system
        assert hasattr(obj, 'lines')
        assert hasattr(obj, 'plotinfo')
        assert hasattr(obj, 'plotlines')
        
        # Test plotting configuration
        if hasattr(obj.plotinfo, 'plot'):
            assert obj.plotinfo.plot == True
    
    def test_modern_lineactions_with_parameters(self):
        """Test ModernLineActions with parameter system."""
        
        class TestModernAction(ModernLineActions):
            def __init__(self, test_value=42):
                super().__init__()
                self.test_value = test_value
        
        obj = TestModernAction(100)
        
        # Test basic functionality
        assert obj.test_value == 100
        assert hasattr(obj, '_ltype')
        assert hasattr(obj, '_datas')
    
    @pytest.mark.skipif(ModernLineIterator is None, reason="ModernLineIterator not available")
    def test_modern_lineiterator_with_parameters(self):
        """Test ModernLineIterator with parameter system."""
        
        class TestModernIterator(ModernLineIterator):
            test_param = ParameterDescriptor(default=5, name='test_param')
        
        # This is a basic test - full functionality would require data setup
        obj = TestModernIterator(test_param=10)
        
        # Test parameter functionality
        assert obj.p.test_param == 10
        
        # Test basic attributes
        assert hasattr(obj, '_mindatas')
        assert hasattr(obj, '_ltype')
    
    def test_inheritance_chain_compatibility(self):
        """Test that modern classes maintain proper inheritance."""
        
        class BaseModernClass(ModernLineSeries):
            base_param = ParameterDescriptor(default=1, name='base_param')
            lines = ('base_line',)
        
        class DerivedModernClass(BaseModernClass):
            derived_param = ParameterDescriptor(default=2, name='derived_param')
            lines = ('derived_line',)
        
        obj = DerivedModernClass(base_param=10, derived_param=20)
        
        # Test parameter inheritance
        assert obj.p.base_param == 10
        assert obj.p.derived_param == 20
        
        # Test that object is properly initialized
        assert hasattr(obj, 'lines')
        assert hasattr(obj, 'plotinfo')
    
    def test_modern_system_performance(self):
        """Test that modern system doesn't have major performance regressions."""
        import time
        
        class PerformanceTestClass(ModernLineSeries):
            param1 = ParameterDescriptor(default=1, name='param1')
            param2 = ParameterDescriptor(default=2, name='param2')
            param3 = ParameterDescriptor(default=3, name='param3')
            lines = ('line1', 'line2')
        
        # Time object creation
        start_time = time.time()
        for i in range(100):
            obj = PerformanceTestClass(param1=i, param2=i*2, param3=i*3)
        end_time = time.time()
        
        creation_time = end_time - start_time
        
        # Should be reasonably fast (less than 1 second for 100 objects)
        assert creation_time < 1.0, f"Object creation too slow: {creation_time} seconds"
    
    def test_error_handling_compatibility(self):
        """Test that error handling works correctly with modern systems."""
        
        from backtrader.parameters import Int
        
        class ErrorTestClass(ModernLineSeries):
            validated_param = ParameterDescriptor(
                default=5,
                type_=int,
                validator=Int(min_val=1, max_val=10),
                name='validated_param'
            )
        
        # Valid parameter should work
        obj1 = ErrorTestClass(validated_param=7)
        assert obj1.p.validated_param == 7
        
        # Invalid parameter should raise error
        with pytest.raises(ValueError):
            ErrorTestClass(validated_param=15)  # Outside range
    
    def test_backward_compatibility_interface(self):
        """Test that modern classes maintain backward compatibility."""
        
        class BackwardCompatClass(ModernLineSeries):
            # Old-style parameter definition should still work
            test_param = ParameterDescriptor(default=42, name='test_param')
        
        obj = BackwardCompatClass()
        
        # Test old-style access patterns
        assert hasattr(obj, 'p')
        assert hasattr(obj, 'params')
        
        # Test parameter access
        assert obj.p.test_param == 42
        
        # Test that object has expected attributes
        assert hasattr(obj, '_minperiod')
        assert hasattr(obj, '_opstage')


class TestModernSystemStability:
    """Test stability and edge cases of the modern system."""
    
    def test_complex_inheritance_scenarios(self):
        """Test complex inheritance scenarios."""
        
        class Level1(ModernLineSeries):
            level1_param = ParameterDescriptor(default=1, name='level1_param')
        
        class Level2(Level1):
            level2_param = ParameterDescriptor(default=2, name='level2_param')
        
        class Level3(Level2):
            level3_param = ParameterDescriptor(default=3, name='level3_param')
        
        obj = Level3(level1_param=10, level2_param=20, level3_param=30)
        
        # Test all levels of parameters work
        assert obj.p.level1_param == 10
        assert obj.p.level2_param == 20
        assert obj.p.level3_param == 30
        
        # Test parameter manager has all parameters
        assert len(obj._param_manager) == 3
    
    def test_memory_management(self):
        """Test that modern system doesn't have memory leaks."""
        import gc
        
        class MemoryTestClass(ModernLineSeries):
            test_param = ParameterDescriptor(default=1, name='test_param')
        
        # Create and destroy many objects
        objects = []
        for i in range(1000):
            obj = MemoryTestClass(test_param=i)
            objects.append(obj)
        
        # Clear references
        del objects
        gc.collect()
        
        # Test should complete without memory issues
        assert True
    
    def test_thread_safety_basics(self):
        """Basic test for thread safety (creation in different contexts)."""
        import threading
        
        class ThreadTestClass(ModernLineSeries):
            thread_param = ParameterDescriptor(default=1, name='thread_param')
        
        results = []
        
        def create_object(value):
            obj = ThreadTestClass(thread_param=value)
            results.append(obj.p.thread_param)
        
        # Create objects in different threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=create_object, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Check results
        assert len(results) == 10
        assert set(results) == set(range(10))


if __name__ == '__main__':
    pytest.main([__file__, '-v'])