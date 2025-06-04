#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import datetime
import os

# Set up data path
datapath = os.path.join('tests', 'original_tests', '..', 'datas', '2006-day-001.txt')

# Simple indicator
class SimpleMA(bt.IndicatorBase):
    lines = ('sma',)
    params = (('period', 20),)
    
    def __init__(self):
        print(f"SimpleMA.__init__: Creating indicator with period={self.p.period}")
        # Simple moving average calculation would go here
        
    def next(self):
        pass

# Test strategy
class TestStrategy(bt.Strategy):
    params = (
        ('period', 20),
    )
    
    def __init__(self):
        print(f"TestStrategy.__init__: Starting initialization")
        print(f"self.data exists: {hasattr(self, 'data')}")
        print(f"self.p exists: {hasattr(self, 'p')}")
        print(f"self.p.period: {self.p.period}")
        
        # Test direct assignment
        print(f"Testing direct assignment...")
        
        # Create the indicator
        print(f"Creating SimpleMA indicator...")
        sma = SimpleMA(self.data, period=self.p.period)
        print(f"Created indicator: {sma}")
        
        # Try to assign it
        print(f"Assigning to self.ind...")
        self.ind = sma
        print(f"Assignment complete!")
        
        # Check if assignment worked
        if hasattr(self, 'ind'):
            print(f"SUCCESS: self.ind exists: {self.ind}")
        else:
            print(f"FAILURE: self.ind does not exist")
            print(f"Strategy __dict__: {self.__dict__}")
            print(f"Strategy dir: {[attr for attr in dir(self) if not attr.startswith('_')]}")

def main():
    print("=== Testing Strategy Attribute Assignment ===")
    
    # Create cerebro
    cerebro = bt.Cerebro()
    
    # Add data
    data = bt.feeds.BacktraderCSVData(dataname=datapath, 
                                    fromdate=datetime.datetime(2006, 1, 1),
                                    todate=datetime.datetime(2006, 1, 10))
    cerebro.adddata(data)
    
    # Add strategy
    cerebro.addstrategy(TestStrategy, period=25)
    
    # Run (just initialization)
    print("Running cerebro...")
    try:
        results = cerebro.run()
        print("Cerebro run completed successfully")
    except Exception as e:
        print(f"Error during run: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main() 