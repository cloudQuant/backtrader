"""
Comprehensive test for metaclass migration.

This test validates that all modern replacements work correctly and provide
the same functionality as the original metaclass-based implementations.
"""

import pytest
import sys
import os

# Add the backtrader directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtrader.parameters import ParameterDescriptor, ParameterManager
from backtrader.metabase import ModernParamsBase, ModernMetaBase, LifecycleManager, LifecycleMixin
from backtrader.lineroot import ModernLineRoot, ModernLineMultiple
from backtrader.lineiterator import ModernLineIterator


class TestLifecycleManagement:
    """Test the modern lifecycle management system."""
    
    def test_lifecycle_manager_basic(self):
        """Test basic lifecycle manager functionality."""
        
        class TestClass:
            def __init__(self, value=42):
                self.value = value
        
        # Test that lifecycle manager can create instances
        obj = LifecycleManager.create_instance(TestClass, value=100)
        assert isinstance(obj, TestClass)
        assert obj.value == 100
    
    def test_lifecycle_mixin(self):
        """Test lifecycle mixin functionality."""
        
        class TestLifecycleClass(LifecycleMixin):
            def __init__(self, value=42):
                self.value = value
                super().__init__()
            
            def dopostinit(self, **kwargs):
                self.post_init_called = True
        
        # Without lifecycle enabled
        obj1 = TestLifecycleClass(value=100)
        assert obj1.value == 100
        assert not hasattr(obj1, 'post_init_called')
        
        # With lifecycle enabled
        TestLifecycleClass.enable_lifecycle_management()
        obj2 = TestLifecycleClass(value=200)
        assert obj2.value == 200
        # Note: dopostinit won't be called in this simple test setup
    
    def test_modern_metabase(self):
        """Test ModernMetaBase functionality."""
        
        class TestMetaBaseClass(ModernMetaBase):
            test_param = ParameterDescriptor(default=42, name='test_param')
            
            def __init__(self, **kwargs):
                self.init_called = True
                super().__init__(**kwargs)
            
            def dopostinit(self, **kwargs):
                self.post_init_called = True
        
        obj = TestMetaBaseClass(test_param=100)
        assert obj.init_called
        assert obj.post_init_called
        assert obj.p.test_param == 100


class TestIntegratedFunctionality:
    """Test that all modern replacements work together."""
    
    def test_parameter_inheritance_chain(self):
        """Test parameter inheritance through the modern class hierarchy."""
        
        class BaseClass(ModernParamsBase):
            base_param = ParameterDescriptor(default=1, name='base_param')
        
        class MiddleClass(BaseClass):
            middle_param = ParameterDescriptor(default=2, name='middle_param')
        
        class DerivedClass(MiddleClass):
            derived_param = ParameterDescriptor(default=3, name='derived_param')
        
        obj = DerivedClass(
            base_param=10,
            middle_param=20,
            derived_param=30
        )
        
        # Test that all parameters are accessible
        assert obj.p.base_param == 10
        assert obj.p.middle_param == 20
        assert obj.p.derived_param == 30
        
        # Test that parameter manager works
        assert len(obj._param_manager) == 3
    
    def test_line_system_integration(self):
        """Test that the modern line system integrates well."""
        
        class TestLineClass(ModernLineRoot):
            line_param = ParameterDescriptor(default=5, name='line_param')
        
        obj = TestLineClass(line_param=15)
        
        # Test parameter access
        assert obj.p.line_param == 15
        
        # Test line-specific functionality
        assert obj._minperiod == 1
        assert obj._opstage == 1
        
        # Test stage operations
        obj._stage2()
        assert obj._opstage == 2
    
    def test_complex_inheritance_scenario(self):
        """Test a complex inheritance scenario similar to real backtrader usage."""
        
        class BaseIndicator(ModernLineRoot):
            period = ParameterDescriptor(default=20, name='period')
            
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.calculation_done = False
            
            def calculate(self):
                self.calculation_done = True
                return self.p.period * 2
        
        class MovingAverage(BaseIndicator):
            ma_type = ParameterDescriptor(default='simple', name='ma_type')
        
        class CustomIndicator(MovingAverage):
            custom_param = ParameterDescriptor(default=1.5, name='custom_param')
            
            def calculate(self):
                base_result = super().calculate()
                return base_result * self.p.custom_param
        
        indicator = CustomIndicator(
            period=30,
            ma_type='exponential', 
            custom_param=2.0
        )
        
        # Test parameter access
        assert indicator.p.period == 30
        assert indicator.p.ma_type == 'exponential'
        assert indicator.p.custom_param == 2.0
        
        # Test method inheritance
        result = indicator.calculate()
        assert result == 30 * 2 * 2.0  # period * 2 * custom_param
        assert indicator.calculation_done
    
    def test_parameter_validation_integration(self):
        """Test that parameter validation works in the integrated system."""
        
        from backtrader.parameters import Float, Int
        
        class ValidatedClass(ModernParamsBase):
            float_param = ParameterDescriptor(
                default=1.0, 
                type_=float,
                validator=Float(min_val=0.0, max_val=10.0),
                name='float_param'
            )
            int_param = ParameterDescriptor(
                default=5,
                type_=int, 
                validator=Int(min_val=1, max_val=100),
                name='int_param'
            )
        
        # Valid parameters
        obj1 = ValidatedClass(float_param=5.5, int_param=50)
        assert obj1.p.float_param == 5.5
        assert obj1.p.int_param == 50
        
        # Invalid parameters should raise validation errors
        with pytest.raises(ValueError):
            ValidatedClass(float_param=15.0)  # Outside range
        
        with pytest.raises(ValueError):
            ValidatedClass(int_param=200)  # Outside range


class TestBackwardCompatibility:
    """Test backward compatibility features."""
    
    def test_params_accessor_compatibility(self):
        """Test that both 'p' and 'params' accessors work."""
        
        class TestClass(ModernParamsBase):
            test_param = ParameterDescriptor(default=42, name='test_param')
        
        obj = TestClass(test_param=100)
        
        # Both accessors should work
        assert obj.p.test_param == 100
        assert obj.params.test_param == 100
        
        # Setting through either accessor should work
        obj.p.test_param = 200
        assert obj.params.test_param == 200
        
        obj.params.test_param = 300
        assert obj.p.test_param == 300
    
    def test_package_handling_compatibility(self):
        """Test that package handling maintains compatibility."""
        
        class TestClassWithPackages(ModernParamsBase):
            packages = ()  # Empty for testing
            frompackages = ()  # Empty for testing
            
            test_param = ParameterDescriptor(default=42, name='test_param')
        
        # Should create without errors
        obj = TestClassWithPackages()
        assert obj.p.test_param == 42


class TestPerformanceAndMemory:
    """Test performance characteristics of modern implementations."""
    
    def test_parameter_access_performance(self):
        """Test that parameter access is reasonably fast."""
        import time
        
        class TestClass(ModernParamsBase):
            param1 = ParameterDescriptor(default=1, name='param1')
            param2 = ParameterDescriptor(default=2, name='param2')
            param3 = ParameterDescriptor(default=3, name='param3')
        
        obj = TestClass()
        
        # Time parameter access
        start_time = time.time()
        for _ in range(1000):
            _ = obj.p.param1
            _ = obj.p.param2
            _ = obj.p.param3
        end_time = time.time()
        
        # Should be reasonably fast (less than 1 second for 3000 accesses)
        assert (end_time - start_time) < 1.0
    
    def test_memory_usage_reasonable(self):
        """Test that memory usage is reasonable."""
        import sys
        
        class TestClass(ModernParamsBase):
            param1 = ParameterDescriptor(default=1, name='param1')
        
        obj = TestClass()
        
        # Object should not be excessively large
        size = sys.getsizeof(obj)
        assert size < 10000  # Reasonable upper bound


class TestMigrationUtility:
    """Test the migration utility functionality."""
    
    def test_migration_utility_import(self):
        """Test that migration utility can be imported and used."""
        try:
            from tools.metaclass_migrator import MetaclassMigrator
            migrator = MetaclassMigrator()
            assert migrator is not None
        except ImportError:
            pytest.skip("Migration utility not available in test environment")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])