#!/usr/bin/env python

import sys
sys.path.insert(0, '../..')

import backtrader as bt

# Simple test to understand the issue
if __name__ == '__main__':
    print("Testing direct indicator creation like in the test:")
    
    # Create the indicator like the test does: chkind[0](self.data, **self.p.chkargs)
    # where chkind[0] is bt.indicators.SMA
    try:
        # Create a strategy first to get self.data
        class TestStrategy(bt.Strategy):
            def __init__(self):
                print(f"TestStrategy.__init__: hasattr(self, 'data') = {hasattr(self, 'data')}")
                print(f"TestStrategy.__init__: type(self.data) = {type(self.data) if hasattr(self, 'data') else 'NO DATA'}")
                
                if hasattr(self, 'data'):
                    # This is the actual call that's failing
                    print("Attempting to create SMA with self.data...")
                    try:
                        sma = bt.indicators.SMA(self.data)
                        print("SUCCESS: SMA created in strategy!")
                    except Exception as e:
                        print(f"ERROR in strategy: {type(e).__name__}: {e}")
                        import traceback
                        traceback.print_exc()
                else:
                    print("No self.data available in strategy")

        # Set up cerebro like the test does
        cerebro = bt.Cerebro()
        # Use the same data file as the actual tests
        data = bt.feeds.BacktraderCSVData(dataname='../datas/2006-day-001.txt')
        cerebro.adddata(data)
        cerebro.addstrategy(TestStrategy)
        cerebro.run()
        
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc() 