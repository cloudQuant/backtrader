#!/usr/bin/env python
import backtrader.indicators as btind

# Test parameter creation directly
print("Testing parameter system...")
SMA = btind.MovingAverageSimple
print(f"SMA class: {SMA}")
print(f"SMA._params: {SMA._params}")

# Try creating a parameter instance directly
print("\nCreating parameter instance with period=5:")
try:
    params = SMA._params(period=5)
    print(f"  Success! params.period = {params.period}")
except Exception as e:
    print(f"  Failed: {e}")

# Check if SMA has proper parameter attributes
print(f"\nSMA has params attr? {hasattr(SMA, 'params')}")
print(f"SMA.params: {getattr(SMA, 'params', 'NOT FOUND')}")

# Check default period
if hasattr(SMA, 'params'):
    print(f"\nChecking default period from params class...")
    if hasattr(SMA.params, '_getpairs'):
        print(f"  _getpairs: {SMA.params._getpairs()}")
    if hasattr(SMA.params, 'period'):
        print(f"  params.period: {SMA.params.period}")
