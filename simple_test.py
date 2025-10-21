#!/usr/bin/env python
import backtrader as bt
import datetime

class SimpleStrategy(bt.Strategy):
    def __init__(self):
        print(f"SimpleStrategy.__init__: self.datas = {self.datas}")
        print(f"SimpleStrategy.__init__: self.data = {self.data}")
        
    def start(self):
        print(f"SimpleStrategy.start: Called")
        
    def next(self):
        if len(self) % 10 == 0:
            print(f"SimpleStrategy.next: Bar {len(self)}, close={self.data.close[0]:.2f}, position={self.position.size}")
        
        if not self.position and len(self) == 20:
            print(f"SimpleStrategy.next: BUYING at bar {len(self)}")
            order = self.buy()
            print(f"SimpleStrategy.next: buy() returned {order}")
            
    def notify_order(self, order):
        print(f"SimpleStrategy.notify_order: order status={order.status}, size={order.size if hasattr(order, 'size') else 'N/A'}")
        
    def stop(self):
        print(f"SimpleStrategy.stop: Final value={self.broker.getvalue():.2f}")

if __name__ == '__main__':
    cerebro = bt.Cerebro()
    
    datapath = 'tests/original_tests/../datas/2006-day-001.txt'
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 3, 31)
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SimpleStrategy)
    
    print(f"Starting value: {cerebro.broker.getvalue():.2f}")
    cerebro.run()
    print(f"Final value: {cerebro.broker.getvalue():.2f}")
