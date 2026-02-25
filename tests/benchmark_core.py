"""Benchmark script for core line system performance.

Measures execution time of a representative backtest to track
performance improvements from attribute access optimizations.
"""
import datetime
import random
import time
import sys
import os

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
    """Strategy with multiple indicators to stress attribute access."""

    def __init__(self):
        self.sma5 = bt.indicators.SMA(self.data.close, period=5)
        self.sma20 = bt.indicators.SMA(self.data.close, period=20)
        self.ema10 = bt.indicators.EMA(self.data.close, period=10)
        self.atr = bt.indicators.ATR(self.data, period=14)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.bb = bt.indicators.BollingerBands(self.data.close, period=20)
        self.macd = bt.indicators.MACD(self.data.close)
        self.cross = bt.indicators.CrossOver(self.sma5, self.sma20)
        self.bar_count = 0

    def next(self):
        self.bar_count += 1
        # Simulate typical strategy attribute access patterns
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


def run_benchmark(num_bars=2000, runonce=True, label=""):
    cerebro = bt.Cerebro()
    cerebro.adddata(BenchFeed(num_bars=num_bars))
    cerebro.addstrategy(BenchStrategy)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer)

    t0 = time.perf_counter()
    results = cerebro.run(runonce=runonce)
    elapsed = time.perf_counter() - t0

    strat = results[0]
    trades = strat.analyzers.tradeanalyzer.get_analysis()
    total_trades = trades.get("total", {}).get("total", 0) if hasattr(trades, "get") else 0

    print(f"[{label}] {num_bars} bars, runonce={runonce}: "
          f"{elapsed:.3f}s, {strat.bar_count} bars processed, {total_trades} trades")
    return elapsed


if __name__ == "__main__":
    print("=" * 60)
    print("Backtrader Core Performance Benchmark")
    print("=" * 60)

    # Warm up
    run_benchmark(num_bars=100, label="warmup")

    # Main benchmarks
    times = []
    for i in range(3):
        t = run_benchmark(num_bars=2000, runonce=True, label=f"runonce-{i+1}")
        times.append(t)

    avg_runonce = sum(times) / len(times)
    print(f"\nAverage runonce (2000 bars): {avg_runonce:.3f}s")

    times2 = []
    for i in range(3):
        t = run_benchmark(num_bars=2000, runonce=False, label=f"step-{i+1}")
        times2.append(t)

    avg_step = sum(times2) / len(times2)
    print(f"Average step-by-step (2000 bars): {avg_step:.3f}s")
    print(f"\n{'='*60}")
    print(f"SUMMARY: runonce={avg_runonce:.3f}s  step={avg_step:.3f}s")
    print(f"{'='*60}")
