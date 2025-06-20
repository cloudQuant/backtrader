"""
Test the modern replacement base classes without metaclasses.

This test validates that the modern replacements for ParamsBase and LineRoot
work correctly and provide the same functionality as the original metaclass-based classes.
"""

import pytest
import sys
import os

# Add the backtrader directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtrader.parameters import ParameterDescriptor
from backtrader.metabase import ModernParamsBase, ParamsBase
from backtrader.lineroot import ModernLineRoot, LineRoot


class TestModernParamsBase:
    """Test the modern replacement for ParamsBase."""
    
    def test_basic_parameter_functionality(self):
        """Test that ModernParamsBase works like ParamsBase for basic parameters."""
        
        # Define a test class using modern system
        class ModernTestClass(ModernParamsBase):
            param1 = ParameterDescriptor(default=10, name='param1')
            param2 = ParameterDescriptor(default='test', name='param2')
        
        # Create instance
        obj = ModernTestClass(param1=20)
        
        # Test parameter access
        assert obj.p.param1 == 20
        assert obj.p.param2 == 'test'
        assert obj.params.param1 == 20
        assert obj.params.param2 == 'test'
    
    def test_parameter_inheritance(self):
        """Test that parameter inheritance works correctly."""
        
        class BaseClass(ModernParamsBase):
            base_param = ParameterDescriptor(default=100, name='base_param')
        
        class DerivedClass(BaseClass):
            derived_param = ParameterDescriptor(default=200, name='derived_param')
        
        obj = DerivedClass(base_param=150, derived_param=250)
        
        assert obj.p.base_param == 150
        assert obj.p.derived_param == 250
    
    def test_packages_handling(self):
        """Test that packages and frompackages are handled correctly."""
        
        class TestClassWithPackages(ModernParamsBase):
            packages = (('collections', 'collections'),)
            frompackages = (('math', ('sqrt', 'sin')),)
            
            test_param = ParameterDescriptor(default=42, name='test_param')
        
        obj = TestClassWithPackages()
        
        # The packages should be imported during initialization
        # We can't test the actual import easily, but we can test that it doesn't crash
        assert obj.p.test_param == 42


class TestModernLineRoot:
    """Test the modern replacement for LineRoot."""
    
    def test_basic_line_functionality(self):
        """Test that ModernLineRoot works like LineRoot for basic functionality."""
        
        class TestLine(ModernLineRoot):
            test_param = ParameterDescriptor(default=5, name='test_param')
        
        obj = TestLine(test_param=10)
        
        # Test basic attributes
        assert obj._minperiod == 1
        assert obj._opstage == 1
        assert obj.p.test_param == 10
    
    def test_stage_operations(self):
        """Test stage operations work correctly."""
        
        class TestLine(ModernLineRoot):
            pass
        
        obj = TestLine()
        
        # Test stage changes
        assert obj._opstage == 1
        obj._stage2()
        assert obj._opstage == 2
        obj._stage1()
        assert obj._opstage == 1
    
    def test_minperiod_setting(self):
        """Test minimum period setting."""
        
        class TestLine(ModernLineRoot):
            pass
        
        obj = TestLine()
        
        assert obj._minperiod == 1
        obj.setminperiod(5)
        assert obj._minperiod == 5
        obj.setminperiod(3)  # Should not decrease
        assert obj._minperiod == 5
    
    def test_operator_overloads(self):
        """Test that operator overloads are available."""
        
        class TestLine(ModernLineRoot):
            def _operation_stage1(self, other, operation, r=False, intify=False):
                # Mock implementation for testing
                return f"stage1_{operation.__name__}"
            
            def _operation_stage2(self, other, operation, r=False):
                # Mock implementation for testing  
                return f"stage2_{operation.__name__}"
            
            def _roperation(self, other, operation):
                # Mock implementation for testing
                return f"r_{operation.__name__}"
            
            def _operationown_stage1(self, operation):
                # Mock implementation for testing
                return f"own_stage1_{operation.__name__}"
            
            def _operationown_stage2(self, operation):
                # Mock implementation for testing
                return f"own_stage2_{operation.__name__}"
        
        obj = TestLine()
        
        # Test that operators call the right methods
        result = obj + 5
        assert "add" in result
        
        result = obj - 5  
        assert "sub" in result
        
        result = abs(obj)
        assert "abs" in result


class TestCompatibility:
    """Test compatibility between old and new systems."""
    
    def test_parameter_compatibility(self):
        """Test that both systems can coexist and provide similar functionality."""
        
        # Note: We can't directly compare with ParamsBase since it would require
        # setting up the full metaclass system, but we can test that our modern
        # system provides the expected interface
        
        class ModernTest(ModernParamsBase):
            param1 = ParameterDescriptor(default=42, name='param1')
            param2 = ParameterDescriptor(default='hello', name='param2')
        
        obj = ModernTest(param1=100)
        
        # Test that it has the same interface as expected from ParamsBase
        assert hasattr(obj, 'p')
        assert hasattr(obj, 'params')
        assert obj.p.param1 == 100
        assert obj.p.param2 == 'hello'
        assert obj.params.param1 == 100
        assert obj.params.param2 == 'hello'
    
    def test_line_compatibility(self):
        """Test that ModernLineRoot provides the same interface as LineRoot."""
        
        class ModernTest(ModernLineRoot):
            test_param = ParameterDescriptor(default=10, name='test_param')
        
        obj = ModernTest()
        
        # Test that it has the same interface as expected from LineRoot
        assert hasattr(obj, '_minperiod')
        assert hasattr(obj, '_opstage')
        assert hasattr(obj, '_OwnerCls')
        assert hasattr(obj, 'setminperiod')
        assert hasattr(obj, '_stage1')
        assert hasattr(obj, '_stage2')
        
        # Test that operator methods exist
        assert hasattr(obj, '__add__')
        assert hasattr(obj, '__sub__')
        assert hasattr(obj, '__mul__')
        assert hasattr(obj, '__abs__')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])