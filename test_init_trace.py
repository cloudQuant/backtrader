#!/usr/bin/env python
import backtrader.indicators as btind

# Check if SMA.__init__ is patched
print(f"SMA class: {btind.SMA}")
print(f"SMA.__init__: {btind.SMA.__init__}")
print(f"SMA._params: {btind.SMA._params}")

# Try creating with different parameters
print(f"\nCreating SMA with default:")
try:
    sma_default = btind.SMA._params()
    print(f"  Default period: {sma_default.period}")
except Exception as e:
    print(f"  Error: {e}")

print(f"\nCreating SMA with period=5:")
try:
    sma_custom = btind.SMA._params(period=5)
    print(f"  Custom period: {sma_custom.period}")
except Exception as e:
    print(f"  Error: {e}")
