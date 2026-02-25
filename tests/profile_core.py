"""Profile script to identify actual hot-path bottlenecks."""
import cProfile
import pstats
import datetime
import random
import sys
import os
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class BenchFeed(bt.feeds.DataBase):
    params = (("num_bars", 2000),)

    def __init__(self):
        super().__init__()
        random.seed(42)
        self._bars = []
        base = 100.0
        base_date = datetime.datetime(2020, 1, 1, 9, 0, 0)
        for i in range(self.p.num_bars):
            change = random.uniform(-2, 2)
            base = max(50, base + change)
            o = base + random.uniform(-1, 1)
            h = max(o, base) + random.uniform(0, 2)
            l = min(o, base) - random.uniform(0, 2)
            c = base + random.uniform(-1, 1)
            h = max(h, o, c)
            l = min(l, o, c)
            self._bars.append((base_date + datetime.timedelta(minutes=i), o, h, l, c,
                               random.randint(1000, 9999), 0))
        self._idx = 0

    def start(self):
        super().start()
        self._idx = 0

    def _load(self):
        if self._idx >= len(self._bars):
            return False
        dt, o, h, l, c, v, oi = self._bars[self._idx]
        self.lines.datetime[0] = bt.date2num(dt)
        self.lines.open[0] = o
        self.lines.high[0] = h
        self.lines.low[0] = l
        self.lines.close[0] = c
        self.lines.volume[0] = v
        self.lines.openinterest[0] = oi
        self._idx += 1
        return True


class BenchStrategy(bt.Strategy):
    def __init__(self):
        self.sma5 = bt.indicators.SMA(self.data.close, period=5)
        self.sma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ema10 = bt.indicators.EMA(self.data.close, period=10)
        self.atr = bt.indicators.ATR(self.data, period=14)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20)
        self.macd = bt.indicators.MACD(self.data.close)
        self.cross = bt.indicators.CrossOver(self.sma5, self.sma20)

    def next(self):
        c = self.data.close[0]
        o = self.data.open[0]
        h = self.data.high[0]
        l = self.data.low[0]
        sma = self.sma5[0]
        rsi = self.rsi[0]
        if not self.position:
            if self.cross > 0 and rsi < 70:
                self.buy()
        else:
            if self.cross < 0 or rsi > 80:
                self.sell()


def run():
    cerebro = bt.Cerebro()
    cerebro.adddata(BenchFeed(num_bars=2000))
    cerebro.addstrategy(BenchStrategy)
    cerebro.run(runonce=True)


if __name__ == "__main__":
    profiler = cProfile.Profile()
    profiler.enable()
    run()
    profiler.disable()

    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats("cumulative")
    ps.print_stats(40)
    print(s.getvalue())

    print("\n" + "=" * 60)
    print("TOP functions by TOTAL TIME:")
    print("=" * 60)
    s2 = io.StringIO()
    ps2 = pstats.Stats(profiler, stream=s2).sort_stats("tottime")
    ps2.print_stats(30)
    print(s2.getvalue())

    # Count specific function calls
    print("\n" + "=" * 60)
    print("KEY FUNCTION CALL COUNTS:")
    print("=" * 60)
    for key, (cc, nc, tt, ct, callers) in profiler.stats.items():
        fname = key[2]
        if fname in ("__getattr__", "__setattr__", "__getitem__", "__len__",
                      "forward", "hasattr", "__setitem__", "next", "_next",
                      "__getattribute__"):
            filepath = key[0]
            if "backtrader" in filepath or fname == "hasattr":
                print(f"  {fname:20s} ({os.path.basename(key[0]):30s}:{key[1]}) "
                      f"calls={nc:>10,}  tottime={tt:.4f}s  cumtime={ct:.4f}s")
