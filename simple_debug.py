#!/usr/bin/env python

print("Starting simple debug...")

try:
    print("Step 1: Import backtrader")
    import backtrader as bt
    print("Step 1: OK")
    
    print("Step 2: Import indicators")
    import backtrader.indicators as btind
    print("Step 2: OK")
    
    print("Step 3: Create SMA")
    sma = btind.SMA()
    print("Step 3: OK - SMA created")
    
    print("Step 4: Check SMA state")
    print(f"SMA type: {type(sma)}")
    print(f"SMA has data: {hasattr(sma, 'data')}")
    print(f"SMA.data: {sma.data}")
    print(f"SMA has lines: {hasattr(sma, 'lines')}")
    print(f"SMA.lines type: {type(sma.lines)}")
    print(f"SMA has _lineiterators: {hasattr(sma, '_lineiterators')}")
    if hasattr(sma, '_lineiterators'):
        print(f"SMA._lineiterators: {dict(sma._lineiterators)}")
    print("Step 4: OK")
    
    print("Step 5: Test SMA with manual data")
    # Instead of running cerebro, let's manually test the SMA
    print("Testing if we can manually call SMA methods...")
    
    # Test forward
    print("Calling sma.forward()")
    sma.forward()
    print(f"After forward: sma len = {len(sma)}")
    
    # Test _next
    print("Testing _next call manually")
    try:
        sma._next()
        print("_next call completed")
        print(f"After _next: sma len = {len(sma)}")
    except Exception as e:
        print(f"_next failed: {e}")
    
    print("Manual test completed successfully")
    
except Exception as e:
    print(f"ERROR at some step: {e}")
    import traceback
    traceback.print_exc()

print("Simple debug completed.") 