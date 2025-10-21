#!/usr/bin/env python
import backtrader as bt
import backtrader.indicators as btind
import datetime

class TestCrossStrategy(bt.Strategy):
    params = (('period', 15),)

    def __init__(self):
        print(f"TestCrossStrategy.__init__")
        self.sma = btind.SMA(self.data, period=self.p.period)
        self.cross = btind.CrossOver(self.data.close, self.sma, plot=True)
        self.order = None
        
    def next(self):
        bar = len(self)
        cross_val = self.cross[0]
        close = self.data.close[0]
        sma_val = self.sma[0]
        
        if bar % 20 == 0 or cross_val != 0:
            print(f"Bar {bar}: close={close:.2f}, sma={sma_val:.2f}, cross={cross_val}, pos={self.position.size}")
        
        if self.order:
            return
            
        if not self.position.size:
            if cross_val > 0.0:
                print(f"  -> BUY SIGNAL at bar {bar}")
                self.order = self.buy()
        elif cross_val < 0.0:
            print(f"  -> SELL SIGNAL at bar {bar}")
            self.order = self.close()
    
    def notify_order(self, order):
        if order.status == order.Completed:
            self.order = None
            print(f"  -> Order completed at bar {len(self)}")
        
    def stop(self):
        print(f"Final value: {self.broker.getvalue():.2f}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestCrossStrategy)
    cerebro.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)
    
    print(f"Starting value: {cerebro.broker.getvalue():.2f}")
    cerebro.run()
    print(f"Final value: {cerebro.broker.getvalue():.2f}")
