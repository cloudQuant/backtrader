#!/usr/bin/env python
import sys
sys.path.insert(0, 'tests/original_tests')
import backtrader as bt
import testcommon

# Patch the runonce while loop check
import backtrader.cerebro as cerebro_module
original_runonce = cerebro_module.Cerebro._runonce

iteration = 0
def debug_runonce(self, runstrats):
    global iteration
    
    # Call original once() for all indicators/strategies
    for strat in runstrats:
        strat._once()
        strat.reset()
    
    datas = sorted(self.datas, key=lambda x: (x._timeframe, x._compression))
    
    print(f"Starting runonce loop...")
    
    while True:
        iteration += 1
        try:
            dts = [d.advance_peek() for d in datas]
            dt0 = min(dts)
            
            if iteration <= 25 or dt0 == float("inf") or dt0 <= 0:
                print(f"  Iteration {iteration}: dt0={dt0}, dts={dts[:3]}")
            
            if dt0 == float("inf") or dt0 <= 0:
                print(f"  → BREAK: dt0={dt0}")
                break
            
            for i, dti in enumerate(dts):
                if dti <= dt0:
                    datas[i].advance()
            
            self._check_timers(runstrats, dt0, cheat=True)
            if self.p.cheat_on_open:
                for strat in runstrats:
                    strat._oncepost_open()
                    if self._event_stop:
                        return
            
            self._brokernotify()
            if self._event_stop:
                return
            
            self._check_timers(runstrats, dt0, cheat=False)
            
            for strat in runstrats:
                strat._oncepost(dt0)
                if self._event_stop:
                    return
                self._next_writers(runstrats)
        except Exception as e:
            import traceback
            print(f"Error in runonce: {traceback.format_exc()}")
            return

cerebro_module.Cerebro._runonce = debug_runonce

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.orderid = None
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
    
    def next(self):
        if len(self) == 19 and not self.orderid and self.cross[0] > 0:
            print(f"\n*** BUY order at len={len(self)} ***\n")
            self.orderid = self.buy()

cerebro = bt.Cerebro(runonce=True, preload=True, exactbars=-2)
cerebro.adddata(testcommon.getdata(0))
cerebro.addstrategy(TestStrategy)
cerebro.run()
