#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

import backtrader as bt
import datetime
import os.path
import sys
import numpy as np

# Create a Strategy
class TestStrategy(bt.Strategy):
    params = (('fast', 10), ('slow', 30), ('printlog', False),)
    
    def log(self, txt, dt=None, doprint=False):
        if self.params.printlog or doprint:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()}, {txt}')
            
    def __init__(self):
        # Access data 
        self.data_close = self.datas[0].close

        # Debug info about the data
        print(f"Strategy.__init__: Data series has len={len(self.data_close)}")
        print(f"Strategy.__init__: Data minperiod={self.data._minperiod}, idx={self.data._idx}")
        
        # Create SMA indicators with correct periods from params
        self.sma1 = bt.indicators.SimpleMovingAverage(
            self.data_close, 
            period=self.p.fast
        )
        self.sma2 = bt.indicators.SimpleMovingAverage(
            self.data_close, 
            period=self.p.slow
        )
        
        # Print indicator info
        print(f"SMA1: minperiod={self.sma1._minperiod}, period={self.p.fast}")
        print(f"SMA2: minperiod={self.sma2._minperiod}, period={self.p.slow}")
        
        # Debug prints to check if attributes exist
        print(f"SMA1 has _idx: {hasattr(self.sma1, '_idx')}")
        print(f"SMA2 has _idx: {hasattr(self.sma2, '_idx')}")
        
        # Create CrossOver indicator
        self.crossover = bt.indicators.CrossOver(self.sma1, self.sma2)
        print(f"CrossOver: minperiod={self.crossover._minperiod}")
        
        # Debug from indicator values
        print(f"Strategy.__init__: Created SMA1 with period={self.p.fast}, SMA2 with period={self.p.slow}")
    def notify_order(self, order):
        if order.status in [order.Completed]:
            pass
            
    def notify_trade(self, trade):
        if not trade.isclosed:
            return
    
    def nextstart(self):
        print(f"DEBUG: TestStrategy.nextstart() - Set chkmin = {len(self.data)}")
        
    def next(self):
        # Get current data values 
        price = self.data_close[0]
        
        # Check if we have reached the minimum periods for indicators
        if len(self) < max(self.p.sma1_period, self.p.sma2_period):
            date = self.datas[0].datetime.date(0)
            print(f"Date: {date}, Close: {price:.2f} - Not enough data for indicators yet ({len(self)}/{max(self.p.sma1_period, self.p.sma2_period)})")
            return
        
        # Get indicator values
        sma1_val = self.sma1[0]
        sma2_val = self.sma2[0]
        crossover_val = self.crossover[0]
        
        # Check if values are finite (not NaN)
        sma1_valid = not np.isnan(sma1_val) and np.isfinite(sma1_val)
        sma2_valid = not np.isnan(sma2_val) and np.isfinite(sma2_val)
        
        # Calculate expected crossover value for verification
        expected_crossover = None
        if sma1_valid and sma2_valid:
            # Check if we have previous values
            if len(self.sma1) > 1 and len(self.sma2) > 1:
                prev_sma1 = self.sma1[-1]
                prev_sma2 = self.sma2[-1]
                prev_sma1_valid = not np.isnan(prev_sma1) and np.isfinite(prev_sma1)
                prev_sma2_valid = not np.isnan(prev_sma2) and np.isfinite(prev_sma2)
                
                if prev_sma1_valid and prev_sma2_valid:
                    # Check for crossover
                    if prev_sma1 <= prev_sma2 and sma1_val > sma2_val:
                        expected_crossover = 1.0  # Bullish crossover
                    elif prev_sma1 >= prev_sma2 and sma1_val < sma2_val:
                        expected_crossover = -1.0  # Bearish crossover
                    else:
                        expected_crossover = 0.0  # No crossover
        
        date = self.datas[0].datetime.date(0)
        sma1_display = f"{sma1_val:.2f}" if sma1_valid else "nan"
        sma2_display = f"{sma2_val:.2f}" if sma2_valid else "nan"
        cross_display = f"{crossover_val:.2f}" if not np.isnan(crossover_val) else "nan"
        print(f"Date: {date}, Close: {price:.2f}, SMA1: {sma1_display}, SMA2: {sma2_display}, CrossOver: {cross_display}, Expected: {expected_crossover}")

# Monkey-patch SimpleMovingAverage to add debugging
original_init = bt.indicators.SimpleMovingAverage.__init__

def patched_sma_init(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    print(f"SMA.__init__: Initialized with period={self.p.period}")
    # Make sure array is initialized
    import array
    if not hasattr(self, 'array'):
        self.array = array.array(str('d'), [0.0] * 1000)

# Apply the monkey patch
bt.indicators.SimpleMovingAverage.__init__ = patched_sma_init

# Create a cerebro entity
cerebro = bt.Cerebro()

# Add a strategy
cerebro.addstrategy(TestStrategy)

# Get a data path
modpath = os.path.dirname(os.path.abspath(sys.argv[0]))
datapath = os.path.join(modpath, 'tests/datas/orcl-1995-2014.txt')

# Make sure data file exists
if not os.path.exists(datapath):
    print(f"ERROR: Data file not found: {datapath}")
    print("Available data files:")
    data_dir = os.path.join(modpath, 'tests/datas')
    if os.path.exists(data_dir):
        print("\n".join(os.listdir(data_dir)))
    sys.exit(1)

print(f"Using data file: {datapath}")

# Create a Data Feed with explicit format specification
print(f"Loading data from: {datapath}")

# Check the first few lines of data file
import subprocess
print("First few lines of data file:")
result = subprocess.run(['head', '-n', '5', datapath], capture_output=True, text=True)
print(result.stdout)

# Create a Data Feed with BacktraderCSVData - proper configuration for Yahoo Finance format
data = bt.feeds.BacktraderCSVData(
    dataname=datapath,
    # Match date range to available data (1995-2014 according to filename)
    fromdate=datetime.datetime(1995, 1, 1),  # Start from beginning of dataset
    todate=datetime.datetime(2014, 12, 31),  # Go to end of dataset
    # Properly handle the file format
    datetime=0,         # First column (0) is date
    open=1,             # Second column (1) is open
    high=2,             # Third column (2) is high
    low=3,              # Fourth column (3) is low
    close=4,            # Fifth column (4) is close
    adjclose=5,         # Sixth column (5) is adjusted close
    volume=6,           # Seventh column (6) is volume
    dtformat='%Y-%m-%d',# Date format explicit for parsing
    headers=True,       # File has headers
)

# Add debug info for data
print(f"Data feed created with parameters:")
print(f"  Date format: %Y-%m-%d")
print(f"  From date: {datetime.datetime(2006, 5, 1)}")
print(f"  To date: {datetime.datetime(2006, 12, 31)}")
print(f"  CSV structure: Date,Open,High,Low,Close,AdjClose,Volume")


# Add the data
cerebro.adddata(data)

# Set our desired cash start
cerebro.broker.setcash(100000.0)

# Run the strategy
print("Starting strategy run...")
cerebro.run()
print("结束_runonce")

if __name__ == "__main__":
    print("Running test script directly...")
    # main() function has been integrated into the main body of the script
