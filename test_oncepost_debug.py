#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = btind.SMA(self.data, period=5)
        
    def next(self):
        if len(self) < 5:
            # Check the indicator's internal state
            print(f"\n=== Bar {len(self)} ===")
            print(f"data.close[0]={self.data.close[0]:.2f}")
            print(f"sma[0]={self.sma[0]}")
            print(f"len(sma)={len(self.sma)}")
            print(f"sma.idx={self.sma.idx if hasattr(self.sma, 'idx') else 'N/A'}")
            if hasattr(self.sma.lines.sma, 'array'):
                arr = self.sma.lines.sma.array
                print(f"sma.array length={len(arr)}")
                if len(arr) >= 5:
                    print(f"sma.array[0:5]={[arr[i] for i in range(5)]}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 10)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    
    print("\nRunning cerebro...")
    cerebro.run()
    print("Done")
