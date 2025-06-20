"""
Simple debug test for Modern indicators
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from backtrader.parameters import ParameterDescriptor, Int
from backtrader.lineseries import ModernLineSeries

print("Testing ModernLineSeries...")

class SimpleModernSMA(ModernLineSeries):
    lines = ('sma',)
    
    period = ParameterDescriptor(
        default=20,
        type_=int,
        validator=Int(min_val=1, max_val=100),
        name='period'
    )
    
    def __init__(self, **kwargs):
        print(f"SimpleModernSMA.__init__ called with: {kwargs}")
        super().__init__(**kwargs)
        print(f"After super(), period = {self.p.period}")

try:
    print("Creating with default parameters...")
    sma1 = SimpleModernSMA()
    print("SUCCESS!")
    
    print("Creating with custom period...")
    sma2 = SimpleModernSMA(period=30)
    print("SUCCESS!")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()