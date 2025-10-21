#!/usr/bin/env python
import backtrader.indicators as btind

# Check if __init__ is patched for MovingAverageSimple
print(f"MovingAverageSimple class: {btind.MovingAverageSimple}")
print(f"MovingAverageSimple.__init__: {btind.MovingAverageSimple.__init__}")
print(f"MovingAverageSimple.__init__ is function? {hasattr(btind.MovingAverageSimple.__init__, '__call__')}")

# Check if MovingAverageSimple has its own __init__ defined
for cls in btind.MovingAverageSimple.__mro__:
    if '__init__' in cls.__dict__:
        print(f"  {cls.__name__} has __init__ in __dict__: {cls.__dict__['__init__']}")
        
print("\nTrying to create SMA with period=5...")
try:
    sma = btind.MovingAverageSimple(period=5)
    print(f"Success! SMA created with period={sma.p.period}")
except Exception as e:
    print(f"Failed: {e}")
