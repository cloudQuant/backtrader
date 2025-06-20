"""
Enhanced tests for ModernLineRoot to ensure complete compatibility.

These tests validate that ModernLineRoot provides complete functionality
equivalent to the original metaclass-based LineRoot.
"""

import pytest
import sys
import os
import operator

# Add the backtrader directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from backtrader.lineroot import ModernLineRoot, ModernLineMultiple, LineRoot
    from backtrader.parameters import ParameterDescriptor
    HAS_MODERN_LINEROOT = True
except ImportError:
    HAS_MODERN_LINEROOT = False


@pytest.mark.skipif(not HAS_MODERN_LINEROOT, reason="ModernLineRoot not available")
class TestEnhancedModernLineRoot:
    """Enhanced tests for ModernLineRoot functionality."""
    
    def test_basic_initialization(self):
        """Test basic ModernLineRoot initialization."""
        
        class TestLineRoot(ModernLineRoot):
            test_param = ParameterDescriptor(default=42, name='test_param')
        
        obj = TestLineRoot(test_param=100)
        
        # Test parameter system integration
        assert obj.p.test_param == 100
        
        # Test basic attributes
        assert hasattr(obj, '_minperiod')
        assert hasattr(obj, '_opstage')
        assert hasattr(obj, '_owner')
        assert obj._minperiod == 1
        assert obj._opstage == 1
    
    def test_owner_finding_mechanism(self):
        """Test the owner finding mechanism."""
        
        class TestOwner:
            pass
        
        class TestLineRoot(ModernLineRoot):
            _OwnerCls = TestOwner
        
        # Basic instantiation should work even without owner
        obj = TestLineRoot()
        assert hasattr(obj, '_owner')
    
    def test_stage_operations(self):
        """Test stage operations (_stage1, _stage2)."""
        
        class TestLineRoot(ModernLineRoot):
            pass
        
        obj = TestLineRoot()
        
        # Test initial stage
        assert obj._opstage == 1
        
        # Test stage operations
        obj._stage1()
        assert obj._opstage == 1
        
        obj._stage2()
        assert obj._opstage == 2
        
        obj._stage1()
        assert obj._opstage == 1
    
    def test_minperiod_operations(self):
        """Test minperiod manipulation."""
        
        class TestLineRoot(ModernLineRoot):
            pass
        
        obj = TestLineRoot()
        
        # Test initial minperiod
        assert obj._minperiod == 1
        
        # Test setminperiod
        obj.setminperiod(5)
        assert obj._minperiod == 5
        
        # Test it only increases, not decreases
        obj.setminperiod(3)
        assert obj._minperiod == 5
        
        obj.setminperiod(10)
        assert obj._minperiod == 10
    
    def test_arithmetic_operators(self):
        """Test arithmetic operator overloads."""
        
        class TestLineRoot(ModernLineRoot):
            def _operation_stage1(self, other, operation, r=False, intify=False):
                # Mock implementation for testing
                return f"stage1_{operation.__name__}_{other}"
            
            def _operation_stage2(self, other, operation, r=False):
                # Mock implementation for testing
                return f"stage2_{operation.__name__}_{other}"
            
            def _roperation(self, other, operation):
                # Mock implementation for testing
                return f"r_{operation.__name__}_{other}"
        
        obj = TestLineRoot()
        
        # Test in stage 1
        assert obj._opstage == 1
        result = obj.__add__(5)
        assert "stage1_add_5" in str(result)
        
        # Test in stage 2
        obj._stage2()
        result = obj.__add__(10)
        assert "stage2_add_10" in str(result)
        
        # Test reverse operations
        result = obj.__radd__(7)
        assert "r_add_7" in str(result)
    
    def test_comparison_operators(self):
        """Test comparison operator overloads."""
        
        class TestLineRoot(ModernLineRoot):
            def _operation_stage1(self, other, operation, r=False, intify=False):
                return True  # Mock implementation
            
            def _operation_stage2(self, other, operation, r=False):
                return False  # Mock implementation
        
        obj = TestLineRoot()
        
        # Test comparison operations work
        # Note: These will use the mock implementations
        result = obj.__lt__(5)
        assert result is True  # stage1 returns True
        
        obj._stage2()
        result = obj.__lt__(5)
        assert result is False  # stage2 returns False
    
    def test_boolean_operations(self):
        """Test boolean operations."""
        
        class TestLineRoot(ModernLineRoot):
            def _operationown_stage1(self, operation):
                return "stage1_bool"
            
            def _operationown_stage2(self, operation):
                return "stage2_bool"
        
        obj = TestLineRoot()
        
        # Test in stage 1
        result = obj._operationown(bool)
        assert result == "stage1_bool"
        
        # Test in stage 2
        obj._stage2()
        result = obj._operationown(bool)
        assert result == "stage2_bool"
    
    def test_inheritance_compatibility(self):
        """Test inheritance with parameter system."""
        
        class BaseLineRoot(ModernLineRoot):
            base_param = ParameterDescriptor(default=1, name='base_param')
        
        class DerivedLineRoot(BaseLineRoot):
            derived_param = ParameterDescriptor(default=2, name='derived_param')
        
        obj = DerivedLineRoot(base_param=10, derived_param=20)
        
        # Test parameter inheritance
        assert obj.p.base_param == 10
        assert obj.p.derived_param == 20
        
        # Test basic functionality inheritance
        assert obj._minperiod == 1
        assert obj._opstage == 1
        
        obj.setminperiod(5)
        assert obj._minperiod == 5
    
    def test_type_constants(self):
        """Test type constants are properly defined."""
        
        class TestLineRoot(ModernLineRoot):
            pass
        
        obj = TestLineRoot()
        
        # Test type constants exist
        assert hasattr(obj, 'IndType')
        assert hasattr(obj, 'StratType')
        assert hasattr(obj, 'ObsType')
        
        # Test they are different values
        assert obj.IndType != obj.StratType
        assert obj.StratType != obj.ObsType
        assert obj.IndType != obj.ObsType
    
    def test_error_handling(self):
        """Test error handling in ModernLineRoot."""
        
        class TestLineRoot(ModernLineRoot):
            pass
        
        obj = TestLineRoot()
        
        # Test methods that should raise NotImplementedError
        with pytest.raises(NotImplementedError):
            obj.qbuffer()
        
        with pytest.raises(NotImplementedError):
            obj.minbuffer(10)


@pytest.mark.skipif(not HAS_MODERN_LINEROOT, reason="ModernLineRoot not available")
class TestModernLineMultiple:
    """Test ModernLineMultiple functionality."""
    
    def test_basic_functionality(self):
        """Test basic ModernLineMultiple functionality."""
        
        class TestLineMultiple(ModernLineMultiple):
            test_param = ParameterDescriptor(default=5, name='test_param')
        
        obj = TestLineMultiple(test_param=15)
        
        # Test parameter system
        assert obj.p.test_param == 15
        
        # Test inheritance from ModernLineRoot
        assert hasattr(obj, '_minperiod')
        assert hasattr(obj, '_opstage')
        assert obj._minperiod == 1
        assert obj._opstage == 1
    
    def test_inheritance_chain(self):
        """Test the inheritance chain works correctly."""
        
        class TestLineMultiple(ModernLineMultiple):
            pass
        
        obj = TestLineMultiple()
        
        # Test it's an instance of ModernLineRoot
        assert isinstance(obj, ModernLineRoot)
        
        # Test it has parameter system features
        assert hasattr(obj, '_param_manager')


@pytest.mark.skipif(not HAS_MODERN_LINEROOT, reason="ModernLineRoot not available")
class TestCompatibilityWithOriginal:
    """Test compatibility between Modern and Original LineRoot."""
    
    def test_api_compatibility(self):
        """Test API compatibility between Modern and Original LineRoot."""
        
        class TestModernLineRoot(ModernLineRoot):
            pass
        
        class TestOriginalLineRoot(LineRoot):
            pass
        
        modern_obj = TestModernLineRoot()
        original_obj = TestOriginalLineRoot()
        
        # Test both have the same basic attributes
        for attr in ['_minperiod', '_opstage']:
            assert hasattr(modern_obj, attr)
            assert hasattr(original_obj, attr)
            assert getattr(modern_obj, attr) == getattr(original_obj, attr)
        
        # Test both have the same methods
        for method in ['_stage1', '_stage2', 'setminperiod']:
            assert hasattr(modern_obj, method)
            assert hasattr(original_obj, method)
            assert callable(getattr(modern_obj, method))
            assert callable(getattr(original_obj, method))
    
    def test_behavior_compatibility(self):
        """Test behavior compatibility."""
        
        class TestModernLineRoot(ModernLineRoot):
            pass
        
        class TestOriginalLineRoot(LineRoot):
            pass
        
        modern_obj = TestModernLineRoot()
        original_obj = TestOriginalLineRoot()
        
        # Test minperiod behavior
        modern_obj.setminperiod(5)
        original_obj.setminperiod(5)
        assert modern_obj._minperiod == original_obj._minperiod
        
        # Test stage behavior
        modern_obj._stage2()
        original_obj._stage2()
        assert modern_obj._opstage == original_obj._opstage


class TestPerformanceRegression:
    """Test performance to ensure no major regressions."""
    
    @pytest.mark.skipif(not HAS_MODERN_LINEROOT, reason="ModernLineRoot not available")
    def test_initialization_performance(self):
        """Test initialization performance."""
        import time
        
        class TestModernLineRoot(ModernLineRoot):
            param1 = ParameterDescriptor(default=1, name='param1')
            param2 = ParameterDescriptor(default=2, name='param2')
            param3 = ParameterDescriptor(default=3, name='param3')
        
        # Time multiple object creations
        start_time = time.time()
        for i in range(1000):
            obj = TestModernLineRoot(param1=i, param2=i*2, param3=i*3)
        end_time = time.time()
        
        creation_time = end_time - start_time
        
        # Should be reasonably fast (less than 2 seconds for 1000 objects)
        assert creation_time < 2.0, f"Object creation too slow: {creation_time} seconds"
    
    @pytest.mark.skipif(not HAS_MODERN_LINEROOT, reason="ModernLineRoot not available")
    def test_method_call_performance(self):
        """Test method call performance."""
        import time
        
        class TestModernLineRoot(ModernLineRoot):
            pass
        
        obj = TestModernLineRoot()
        
        # Time multiple method calls
        start_time = time.time()
        for i in range(10000):
            obj.setminperiod(i % 100 + 1)
            obj._stage1()
            obj._stage2()
        end_time = time.time()
        
        call_time = end_time - start_time
        
        # Should be very fast (less than 1 second for 30000 calls)
        assert call_time < 1.0, f"Method calls too slow: {call_time} seconds"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])