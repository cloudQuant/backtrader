"""Iteration 28 performance probe (D28-06).

Deterministic load sampling for pairing baseline vs candidate runs:
  - single-data direct-load runnext (fast path)
  - multi-data generic runnext
  - multi-timeframe runonce
  - channel iterable
  - cold import (measured externally via -c, here we only time construct+run)
  - Cerebro construction batch

Usage:
    python scripts/iter28_perf_probe.py <out.json> [--pairs N]

Run this on the pre-split code to freeze the baseline distribution, then on
the split code and pair-compare medians. Repeats alternate warmup + samples.
"""
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATAPATH = str(REPO / "tests" / "datas" / "2006-day-001.txt")

import backtrader as bt


class PerfStrategy(bt.Strategy):
    params = (("period", 5),)

    def __init__(self):
        import collections

        self.closes = collections.deque(maxlen=self.p.period)
        self.prev_diff = None
        self.bars = 0

    def next(self):
        close = self.data.close[0]
        self.closes.append(close)
        avg = sum(self.closes) / len(self.closes)
        diff = close - avg
        self.bars += 1
        if self.prev_diff is not None:
            if self.prev_diff <= 0 < diff and not self.position:
                self.buy(size=1)
            elif self.prev_diff >= 0 > diff and self.position:
                self.close()
        self.prev_diff = diff


class PerfIndicatorStrategy(bt.Strategy):
    params = (("period", 5),)

    def __init__(self):
        self.sma = bt.ind.SMA(self.data.close, period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data.close, self.sma)
        self.bars = 0

    def next(self):
        self.bars += 1
        if not self.position and self.crossover > 0:
            self.buy(size=1)
        elif self.position and self.crossover < 0:
            self.close()


def _data():
    return bt.feeds.BacktraderCSVData(dataname=DATAPATH, plot=False)


def load_fastpath():
    cerebro = bt.Cerebro(oldsync=False, runonce=False, stdstats=False)
    cerebro.adddata(_data())
    cerebro.addstrategy(PerfStrategy)
    res = cerebro.run()
    return res[0].bars, cerebro.getbroker().getvalue()


def load_runnext_multi():
    cerebro = bt.Cerebro(oldsync=False, runonce=False)
    cerebro.adddata(_data(), name="d1")
    cerebro.adddata(_data(), name="d2")
    cerebro.addstrategy(PerfIndicatorStrategy)
    res = cerebro.run()
    return res[0].bars, cerebro.getbroker().getvalue()


def load_runonce_multi_tf():
    cerebro = bt.Cerebro(oldsync=False, runonce=True, preload=True)
    cerebro.adddata(_data(), name="day")
    cerebro.resampledata(
        _data(), name="week", timeframe=bt.TimeFrame.Weeks, compression=1
    )
    cerebro.addstrategy(PerfIndicatorStrategy)
    res = cerebro.run()
    return res[0].bars, cerebro.getbroker().getvalue()


def _channel_events():
    from backtrader.channel import Event
    from backtrader.events import BarEvent, TickEvent

    events = []
    for i in range(2000):
        ts = float(i)
        events.append(
            Event(
                data=TickEvent(timestamp=ts, symbol="SYM", price=100.0 + (i % 50), volume=1.0),
                channel_type="tick",
                channel_name="SYM",
            )
        )
        events.append(
            Event(
                data=BarEvent(
                    timestamp=ts,
                    symbol="SYM",
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5,
                    volume=10.0,
                ),
                channel_type="bar",
                channel_name="SYM",
            )
        )
    return events


class ChannelPerfStrategy(bt.Strategy):
    def __init__(self):
        self.ticks = 0
        self.bars = 0

    def notify_tick(self, tick):
        self.ticks += 1

    def notify_bar(self, bar):
        self.bars += 1


def load_channel():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ChannelPerfStrategy)
    events = _channel_events()
    strats = cerebro.run(channel=events)
    return strats[0].ticks + strats[0].bars, len(events)


LOADS = {
    "fastpath_runnext": load_fastpath,
    "runnext_multi": load_runnext_multi,
    "runonce_multi_tf": load_runonce_multi_tf,
    "channel_iterable": load_channel,
}

def main():
    out_path = sys.argv[1]
    pairs = 7
    if "--pairs" in sys.argv:
        pairs = int(sys.argv[sys.argv.index("--pairs") + 1])

    report = {"pairs": pairs, "loads": {}, "construct_batch": [], "results": {}}

    # Warmup once per load, then sample `pairs` times.
    for name, fn in LOADS.items():
        summary = fn()
        report["results"][name] = summary
        samples = []
        for _ in range(pairs):
            t0 = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - t0)
        report["loads"][name] = {
            "samples_s": samples,
            "median_s": statistics.median(samples),
        }

    # Construction batch: build 300 Cerebros (params parsed each time).
    for _ in range(pairs):
        t0 = time.perf_counter()
        for _ in range(300):
            bt.Cerebro(runonce=True, stdstats=False, maxcpus=1)
        report["construct_batch"].append(time.perf_counter() - t0)

    Path(out_path).write_text(json.dumps(report, indent=1))
    print(json.dumps({k: (v if k != "loads" else {n: l["median_s"] for n, l in v.items()}) for k, v in report.items() if k != "construct_batch"}, indent=1))
    print("construct medians:", statistics.median(report["construct_batch"]))


if __name__ == "__main__":
    main()
