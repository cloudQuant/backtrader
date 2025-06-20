"""
Debug script for ModernLineSeries parameter handling
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from backtrader.parameters import ParameterDescriptor, Int
from backtrader.lineseries import ModernLineSeries

class TestModernIndicator(ModernLineSeries):
    """Test indicator for debugging."""
    
    lines = ('test_line',)
    
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=100),
        name='period'
    )
    
    def __init__(self, **kwargs):
        print(f"TestModernIndicator.__init__ called with kwargs: {kwargs}")
        super().__init__(**kwargs)
        print(f"After super().__init__, self.p.period = {self.p.period}")

def test_basic_creation():
    """Test basic creation."""
    print("Testing basic creation...")
    try:
        indicator = TestModernIndicator()
        print(f"Success! Default period: {indicator.p.period}")
    except Exception as e:
        print(f"Failed: {e}")

def test_parameter_passing():
    """Test parameter passing."""
    print("Testing parameter passing...")
    try:
        indicator = TestModernIndicator(period=30)
        print(f"Success! Period: {indicator.p.period}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == '__main__':
    test_basic_creation()
    test_parameter_passing()