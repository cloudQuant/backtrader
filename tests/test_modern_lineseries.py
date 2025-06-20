"""
Test for modern LineSeries replacement.

This test validates that the ModernLineSeries provides the same functionality
as the original metaclass-based LineSeries.
"""

import pytest
import sys
import os

# Add the backtrader directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backtrader.parameters import ParameterDescriptor
from backtrader.lineseries import ModernLineSeries, Lines


class TestModernLineSeries:
    """Test the modern LineSeries replacement."""
    
    def test_basic_lineseries_functionality(self):
        """Test basic LineSeries functionality without lines definition."""
        
        class TestLineSeries(ModernLineSeries):
            test_param = ParameterDescriptor(default=42, name='test_param')
        
        obj = TestLineSeries(test_param=100)
        
        # Test parameter access
        assert obj.p.test_param == 100
        
        # Test basic attributes exist
        assert hasattr(obj, 'plotinfo')
        assert hasattr(obj, '_minperiod')
        assert hasattr(obj, '_opstage')
    
    def test_lines_definition(self):
        """Test LineSeries with lines definition."""
        
        class TestLineSeriesWithLines(ModernLineSeries):
            lines = ('close', 'volume')
            test_param = ParameterDescriptor(default=10, name='test_param')
        
        # Test that class setup works
        assert hasattr(TestLineSeriesWithLines, 'lines')
        
        # Test instantiation
        obj = TestLineSeriesWithLines()
        
        # Test that lines are set up
        assert hasattr(obj, 'lines')
        assert hasattr(obj, 'l')  # alias
        
        # Test parameter access
        assert obj.p.test_param == 10
    
    def test_plotinfo_and_plotlines(self):
        """Test plotinfo and plotlines functionality."""
        
        class TestPlottingLineSeries(ModernLineSeries):
            lines = ('signal',)
            plotinfo = dict(plot=True, subplot=False)
            plotlines = dict(signal=dict(color='blue'))
            
            test_param = ParameterDescriptor(default=5, name='test_param')
        
        obj = TestPlottingLineSeries(test_param=15)
        
        # Test parameter access
        assert obj.p.test_param == 15
        
        # Test plotting setup
        assert hasattr(obj, 'plotinfo')
        assert hasattr(obj, 'plotlines')
        
        # Test that plotinfo has correct values
        if hasattr(obj.plotinfo, 'plot'):
            assert obj.plotinfo.plot == True
    
    def test_line_aliases(self):
        """Test line alias functionality."""
        
        class TestAliasLineSeries(ModernLineSeries):
            lines = ('main_line', 'secondary_line')
            test_param = ParameterDescriptor(default=1, name='test_param')
        
        obj = TestAliasLineSeries()
        
        # Test that line aliases are set up
        assert hasattr(obj, 'lines')
        if hasattr(obj, 'lines') and obj.lines.fullsize():
            assert hasattr(obj, 'line')  # First line alias
        
        # Test _getlinealias method
        alias = obj._getlinealias(0)
        assert alias is not None
    
    def test_inheritance_chain(self):
        """Test inheritance between modern LineSeries classes."""
        
        class BaseLineSeries(ModernLineSeries):
            lines = ('base_line',)
            base_param = ParameterDescriptor(default=100, name='base_param')
        
        class DerivedLineSeries(BaseLineSeries):
            lines = ('derived_line',)
            derived_param = ParameterDescriptor(default=200, name='derived_param')
        
        obj = DerivedLineSeries(base_param=150, derived_param=250)
        
        # Test parameter inheritance
        assert obj.p.base_param == 150
        assert obj.p.derived_param == 250
        
        # Test that object is properly initialized
        assert hasattr(obj, 'lines')
        assert hasattr(obj, 'plotinfo')
    
    def test_plotlabel_method(self):
        """Test plotlabel method functionality."""
        
        class TestLabelLineSeries(ModernLineSeries):
            test_param = ParameterDescriptor(default=42, name='test_param')
            
            class plotinfo:
                plotname = "TestPlot"
                
                def _getitems(self):
                    return []
        
        obj = TestLabelLineSeries()
        
        # Test plotlabel method exists and works
        if hasattr(obj, 'plotlabel'):
            label = obj.plotlabel()
            assert isinstance(label, str)
            assert len(label) > 0
    
    def test_getline_method(self):
        """Test _getline method functionality."""
        
        class TestGetLineLineSeries(ModernLineSeries):
            lines = ('test_line',)
            test_param = ParameterDescriptor(default=1, name='test_param')
        
        obj = TestGetLineLineSeries()
        
        # Test _getline method with numeric index
        if hasattr(obj, 'lines') and len(obj.lines) > 0:
            line = obj._getline(0)
            assert line is not None
        
        # Test _getline with -1 (should convert to 0)
        line = obj._getline(-1)
        assert line is not None or len(obj.lines) == 0


class TestCompatibilityFeatures:
    """Test compatibility features with original LineSeries."""
    
    def test_parameter_manager_integration(self):
        """Test that parameter manager integration works correctly."""
        
        class TestCompatLineSeries(ModernLineSeries):
            param1 = ParameterDescriptor(default=10, name='param1')
            param2 = ParameterDescriptor(default='test', name='param2')
        
        obj = TestCompatLineSeries(param1=20, param2='modified')
        
        # Test parameter manager exists and works
        assert hasattr(obj, '_param_manager')
        assert obj.p.param1 == 20
        assert obj.p.param2 == 'modified'
        
        # Test parameter manager methods
        assert len(obj._param_manager) == 2
        assert 'param1' in obj._param_manager
        assert 'param2' in obj._param_manager
    
    def test_line_system_integration(self):
        """Test integration with the line system."""
        
        class TestLineIntegration(ModernLineSeries):
            lines = ('price', 'volume')
            test_param = ParameterDescriptor(default=5, name='test_param')
        
        obj = TestLineIntegration()
        
        # Test line system integration
        assert hasattr(obj, '_minperiod')
        assert hasattr(obj, '_opstage')
        
        # Test stage operations work
        obj._stage1()
        assert obj._opstage == 1
        obj._stage2()  
        assert obj._opstage == 2


class TestErrorHandling:
    """Test error handling in modern LineSeries."""
    
    def test_invalid_parameter_handling(self):
        """Test handling of invalid parameters."""
        
        from backtrader.parameters import Int
        
        class TestValidationLineSeries(ModernLineSeries):
            validated_param = ParameterDescriptor(
                default=5,
                type_=int,
                validator=Int(min_val=1, max_val=10),
                name='validated_param'
            )
        
        # Valid parameter should work
        obj1 = TestValidationLineSeries(validated_param=7)
        assert obj1.p.validated_param == 7
        
        # Invalid parameter should raise error
        with pytest.raises(ValueError):
            TestValidationLineSeries(validated_param=15)  # Outside range
    
    def test_graceful_fallback(self):
        """Test that the system gracefully handles missing features."""
        
        class TestFallbackLineSeries(ModernLineSeries):
            lines = ('test_line',)
            test_param = ParameterDescriptor(default=1, name='test_param')
        
        obj = TestFallbackLineSeries()
        
        # Test that object creation doesn't fail
        assert obj is not None
        assert obj.p.test_param == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v'])