#!/usr/bin/env python

import backtrader as bt

# Test parameter system with debugging
print("Testing parameter system with debugging...")

class DebugSMA(bt.indicators.sma.MovingAverageSimple):
    """Debug version of SMA to trace method calls"""
    
    def __init__(self, *args, **kwargs):
        print(f"DebugSMA.__init__ called with args={args}, kwargs={kwargs}")
        print(f"DebugSMA MRO: {self.__class__.__mro__}")
        
        # Let's trace each step in the inheritance chain
        for i, cls in enumerate(self.__class__.__mro__):
            if hasattr(cls, '__init__') and cls.__name__ != 'object':
                print(f"  MRO[{i}]: {cls.__name__} has __init__")
                
        print("Calling super().__init__()...")
        try:
            super().__init__()  # This should eventually call LineIterator.__init__
        except Exception as e:
            print(f"Error in super().__init__(): {e}")
            
            # Let's try calling LineIterator.__init__ directly
            print("Trying LineIterator.__init__ directly...")
            try:
                bt.lineiterator.LineIterator.__init__(self, *args, **kwargs)
                print("LineIterator.__init__ succeeded!")
            except Exception as e2:
                print(f"LineIterator.__init__ also failed: {e2}")
                raise e

# Test debugging
try:
    print("Creating data...")
    data = bt.feeds.BacktraderCSVData(dataname='tests/original_tests/../datas/2006-day-001.txt')
    
    print("\nTesting DebugSMA creation...")
    debug_sma = DebugSMA(data, period=25)
    print(f"DebugSMA created successfully: {debug_sma}")
        
except Exception as e:
    print(f"Error in testing: {e}")
    import traceback
    traceback.print_exc()