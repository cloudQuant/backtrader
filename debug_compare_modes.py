import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

class TestStrategy(bt.Strategy):
    params = (('period', 15), ('stocklike', False))
    
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        self.orderid = None
        self.buy_signals = []
    
    def next(self):
        if self.orderid:
            return
        
        if not self.position.size:
            if self.cross > 0.0:
                self.buy_signals.append((len(self), self.data.close[0]))
                self.orderid = self.buy()
        elif self.cross < 0.0:
            self.orderid = self.close()
    
    def notify_order(self, order):
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Expired]:
            self.orderid = None
    
    def start(self):
        if not self.p.stocklike:
            self.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)
    
    def stop(self):
        print(f"  Buy signals: {[f'bar{b}={v:.2f}' for b,v in self.buy_signals[:8]]}")

# Test working config
print("Config A: preload=True, runonce=True, exactbars=False (WORKS)")
cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy, stocklike=False)
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.run()
print(f"  Final value: {cerebro.broker.getvalue():.2f}\n")

# Test failing config
print("Config B: preload=True, runonce=False, exactbars=False (FAILS)")
cerebro = bt.Cerebro(runonce=False, preload=True, exactbars=False)
cerebro.addstrategy(TestStrategy, stocklike=False)
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.run()
print(f"  Final value: {cerebro.broker.getvalue():.2f}\n")
