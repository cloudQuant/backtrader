#!/usr/bin/env python

import backtrader as bt

# Monkey patch all __init__ methods in the MRO to trace calls
original_inits = {}

def trace_init(cls_name, original_init):
    def traced_init(self, *args, **kwargs):
        print(f"CALLING: {cls_name}.__init__ with args={args}, kwargs={kwargs}")
        try:
            result = original_init(self, *args, **kwargs)
            print(f"SUCCESS: {cls_name}.__init__ completed")
            return result
        except Exception as e:
            print(f"ERROR: {cls_name}.__init__ failed with: {e}")
            raise
    return traced_init

# Get the SMA class and trace all __init__ methods in the MRO
sma_cls = bt.indicators.sma.MovingAverageSimple

print("Patching __init__ methods...")
for cls in sma_cls.__mro__:
    if hasattr(cls, '__init__') and cls.__name__ != 'object':
        original_inits[cls.__name__] = cls.__init__
        cls.__init__ = trace_init(cls.__name__, cls.__init__)
        print(f"Patched: {cls.__name__}.__init__")

print("\nTesting SMA creation...")
try:
    data = bt.feeds.BacktraderCSVData(dataname='tests/original_tests/../datas/2006-day-001.txt')
    sma = bt.indicators.SMA(data, period=25)
    print(f"SUCCESS: SMA created: {sma}")
except Exception as e:
    print(f"ERROR: SMA creation failed: {e}")
    import traceback
    traceback.print_exc()

# Restore original __init__ methods
print("\nRestoring original __init__ methods...")
for cls in sma_cls.__mro__:
    if cls.__name__ in original_inits:
        cls.__init__ = original_inits[cls.__name__]
        print(f"Restored: {cls.__name__}.__init__") 