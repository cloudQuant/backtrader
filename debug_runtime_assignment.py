#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import datetime
import os

# Set up data path
datapath = os.path.join('tests', 'original_tests', '..', 'datas', '2006-day-001.txt')

# Test strategy
class TestStrategy(bt.Strategy):
    def __init__(self):
        print(f"TestStrategy.__init__: Creating strategy")
        # This assignment works now (confirmed above)
        self.ind = bt.indicators.SMA(self.data, period=15)
        print(f"TestStrategy.__init__: self.ind assigned successfully")
        
    def nextstart(self):
        print(f"TestStrategy.nextstart: Entering nextstart method")
        print(f"TestStrategy.nextstart: len(self) = {len(self)}")
        
        # This is where the problem occurs - test this assignment
        print(f"TestStrategy.nextstart: Attempting to assign self.chkmin...")
        try:
            self.chkmin = len(self)
            print(f"TestStrategy.nextstart: SUCCESS - self.chkmin = {self.chkmin}")
        except Exception as e:
            print(f"TestStrategy.nextstart: ERROR during assignment: {e}")
            print(f"TestStrategy.nextstart: Error type: {type(e)}")
            import traceback
            traceback.print_exc()
            
        # Test other assignments
        print(f"TestStrategy.nextstart: Testing other assignments...")
        try:
            self.test_attr = 123
            print(f"TestStrategy.nextstart: self.test_attr = {self.test_attr}")
        except Exception as e:
            print(f"TestStrategy.nextstart: ERROR with test_attr: {e}")
            
        # Check what __setattr__ method is being used
        print(f"TestStrategy.nextstart: Strategy class MRO: {self.__class__.__mro__}")
        for cls in self.__class__.__mro__:
            if hasattr(cls, '__setattr__') and '__setattr__' in cls.__dict__:
                print(f"TestStrategy.nextstart: Found __setattr__ in {cls}: {cls.__dict__['__setattr__']}")
        
        super(TestStrategy, self).nextstart()

def main():
    print("=== Testing Runtime Attribute Assignment ===")
    
    # Create cerebro
    cerebro = bt.Cerebro()
    
    # Add data
    data = bt.feeds.BacktraderCSVData(dataname=datapath, 
                                    fromdate=datetime.datetime(2006, 1, 1),
                                    todate=datetime.datetime(2006, 3, 31))  # Run longer period
    cerebro.adddata(data)
    
    # Add strategy
    cerebro.addstrategy(TestStrategy)
    
    # Run
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