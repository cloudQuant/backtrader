#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

# Override the patched_init temporarily to add more debug
orig_sma_init = btind.MovingAverageSimple.__init__

def debug_init(self, *args, **kwargs):
    print(f"\n=== DEBUG SMA INIT ===")
    print(f"  args: {args}")
    print(f"  kwargs: {kwargs}")
    print(f"  cls._params: {self.__class__._params}")
    
    # Check parameter state before
    print(f"  Before: hasattr(self, 'p'): {hasattr(self, 'p')}")
    if hasattr(self, 'p'):
        print(f"  Before: self.p = {self.p}")
        print(f"  Before: self.p.period = {getattr(self.p, 'period', 'N/A')}")
    
    # Call original
    result = orig_sma_init(self, *args, **kwargs)
    
    # Check parameter state after
    print(f"  After: hasattr(self, 'p'): {hasattr(self, 'p')}")
    if hasattr(self, 'p'):
        print(f"  After: self.p = {self.p}")
        print(f"  After: self.p.period = {getattr(self.p, 'period', 'N/A')}")
    
    print(f"=== END DEBUG SMA INIT ===\n")
    return result

btind.MovingAverageSimple.__init__ = debug_init

# Now test
print("Creating SMA with period=5...")
sma = btind.MovingAverageSimple(period=5)
print(f"Final result: sma.p.period = {sma.p.period}")
