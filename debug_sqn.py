#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import backtrader as bt
import backtrader.indicators as btind

# Add testcommon path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tests', 'original_tests'))
import testcommon

class DebugSQN(bt.analyzers.SQN):
    def notify_trade(self, trade):
        print(f"DEBUG SQN: notify_trade called, isclosed={trade.isclosed}, pnl={trade.pnl if trade.isclosed else 'N/A'}")
        super().notify_trade(trade)
        if trade.isclosed:
            print(f"  After processing: trades={self.rets.trades}, sqn={self.rets.sqn}")

class RunStrategy(bt.Strategy):
    params = (
        ('period', 15),
        ('maxtrades', None),
    )

    def notify_trade(self, trade):
        print(f"STRATEGY: notify_trade called, justopened={trade.justopened}, isclosed={trade.isclosed}")
        if trade.isclosed:
            print(f"  Trade closed, PnL={trade.pnl}")
            self.tradecount += 1

    def __init__(self):
        self.orderid = None
        self.sma = btind.SMA(self.data, period=self.p.period)
        print(f"DEBUG: SMA created, type={type(self.sma)}")
        print(f"DEBUG: SMA has _owner: {hasattr(self.sma, '_owner')}, _owner is: {getattr(self.sma, '_owner', None)}")
        print(f"DEBUG: Strategy _lineiterators: {self._lineiterators if hasattr(self, '_lineiterators') else 'N/A'}")
        self.cross = btind.CrossOver(self.data.close, self.sma, plot=False)
        self.tradecount = 0

    def start(self):
        self.broker.setcommission(commission=2.0, mult=10.0, margin=1000.0)
        self.next_count = 0
        print(f"\nDEBUG START: Strategy _lineiterators after start:")
        for key, items in self._lineiterators.items():
            print(f"  Type {key}: {len(items)} items - {[type(x).__name__ for x in items]}")
    
    def stop(self):
        print(f"\nSTRATEGY STOPPED: next() called {self.next_count} times, {self.tradecount} trades")
        print(f"SMA has {len(self.sma)} values")
        print(f"Sample SMA values: {[self.sma[-i] if i < len(self.sma) else 'N/A' for i in range(min(5, len(self.sma)))[::-1]]}")
        print(f"SMA type: {type(self.sma)}")
        print(f"SMA lines: {self.sma.lines if hasattr(self.sma, 'lines') else 'No lines attr'}")

    def next(self):
        self.next_count += 1
        # Debug: print cross value occasionally
        if len(self) == 15 or len(self) == 20 or len(self) == 30:
            try:
                print(f"Bar {len(self)}: close={self.data.close[0]:.2f}")
                print(f"  SMA obj: {self.sma}")
                print(f"  SMA len: {len(self.sma)}")
                print(f"  SMA lines: {self.sma.lines}")
                if hasattr(self.sma.lines, 'sma'):
                    print(f"  SMA lines.sma: {self.sma.lines.sma}")
                    print(f"  SMA lines.sma[0]: {self.sma.lines.sma[0]}")
                sma_val = self.sma[0]
                cross_val = self.cross[0]
                print(f"  sma={sma_val:.2f}, cross={cross_val:.2f}")
            except Exception as e:
                import traceback
                print(f"Bar {len(self)}: ERROR: {e}")
                traceback.print_exc()
        
        if self.orderid:
            return

        if not self.position.size:
            if self.p.maxtrades is None or self.tradecount < self.p.maxtrades:
                if self.cross > 0.0:
                    print(f"BUY ORDER at {self.data.datetime.date(0)}, cross={self.cross[0]}")
                    self.orderid = self.buy()
        elif self.cross < 0.0:
            print(f"SELL ORDER at {self.data.datetime.date(0)}, cross={self.cross[0]}")
            self.orderid = self.close()

    def notify_order(self, order):
        if order.status == order.Completed:
            print(f"ORDER COMPLETED: {'BUY' if order.isbuy() else 'SELL'} at {order.executed.price}")
        if order.status in [order.Completed, order.Expired, order.Canceled, order.Margin]:
            self.orderid = None

# Run test
cerebro = bt.Cerebro(runonce=False)  # Disable runonce to match test
data = testcommon.getdata(0)
cerebro.adddata(data)
cerebro.addstrategy(RunStrategy)
cerebro.addanalyzer(DebugSQN)

print("Running backtest with runonce=False...")
result = cerebro.run()
strat = result[0]
analyzer = strat.analyzers[0]
analysis = analyzer.get_analysis()

print("\n=== FINAL RESULTS ===")
print(f"Analysis: {analysis}")
print(f"SQN: {analysis.sqn}")
print(f"Trades: {analysis.trades}")
