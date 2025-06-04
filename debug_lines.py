#!/usr/bin/env python
# Debug script for lines issue

import backtrader as bt
import backtrader.indicators as btind

try:
    print("Testing SMA indicator lines...")
    sma_cls = btind.SMA
    print(f"SMA class: {sma_cls}")
    print(f"SMA lines: {getattr(sma_cls, 'lines', 'NO_LINES')}")
    print(f"SMA _lines: {getattr(sma_cls, '_lines', 'NO_LINES')}")
    
    if hasattr(sma_cls, 'lines'):
        print(f"Lines type: {type(sma_cls.lines)}")
        if hasattr(sma_cls.lines, '__mro__'):
            print(f"Lines MRO: {sma_cls.lines.__mro__}")
        
        # Check lines instance creation
        print("\nTesting lines instance creation...")
        lines_instance = sma_cls.lines()
        print(f"Lines instance: {lines_instance}")
        print(f"Lines instance type: {type(lines_instance)}")
        print(f"Lines instance.lines: {getattr(lines_instance, 'lines', 'NO_LINES')}")
        print(f"Length of lines: {len(lines_instance.lines) if hasattr(lines_instance, 'lines') else 'NO_LINES'}")
        
        # Check line aliases
        print("\nChecking line aliases...")
        for attr_name in dir(sma_cls):
            attr = getattr(sma_cls, attr_name)
            if hasattr(attr, '__class__') and 'LineAlias' in str(type(attr)):
                print(f"Found LineAlias: {attr_name} -> line {attr.line}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc() 