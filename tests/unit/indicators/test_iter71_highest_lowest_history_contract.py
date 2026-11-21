import datetime
import importlib.util
import math
import sys
from pathlib import Path
import pytest
import backtrader as bt
import backtrader.indicators.basicops as ops

path = Path("tests/functional/strategies/breakout/test_105_donchian_channel_strategy.py")
spec = importlib.util.spec_from_file_location("donchian_history_extrema", path)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def run(period, once, force_generic):
    old_cutoff = ops._MIN_PERIOD_FOR_MONOTONIC_ONCE
    old_helper = ops._once_monotonic_extreme
    fast = []

    def tracked(*args):
        fast.append(args[-1])
        return old_helper(*args)

    class P(m.DonchianChannelStrategy):
        def __init__(self):
            super().__init__()
            self.rows = []
            self.events = []

        def next(self):
            values = (float(self.data.close[0]), float(self.highest[-1]), float(self.lowest[-1]))
            assert all(
                math.isfinite(float(getattr(self.data, k)[0]))
                for k in ("open", "high", "low", "close")
            )
            values = tuple(x if math.isfinite(x) else None for x in values)
            self.rows.append((len(self.data), *values, self.position.size))
            super().next()

        def notify_order(self, o):
            self.events.append(
                (
                    "order",
                    len(self.data),
                    o.getstatusname(),
                    float(o.executed.size),
                    float(o.executed.price),
                )
            )
            super().notify_order(o)

        def notify_trade(self, t):
            if t.isopen or t.isclosed:
                self.events.append(
                    ("trade", len(self.data), bool(t.isclosed), float(t.size), float(t.pnlcomm))
                )
            super().notify_trade(t)

    try:
        ops._MIN_PERIOD_FOR_MONOTONIC_ONCE = 10**9 if force_generic else old_cutoff
        ops._once_monotonic_extreme = tracked
        c = bt.Cerebro(stdstats=False, runonce=once, preload=True)
        data = bt.feeds.GenericCSVData(
            dataname="tests/datas/orcl-1995-2014.txt",
            dtformat="%Y-%m-%d",
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
            fromdate=datetime.datetime(2010, 1, 1),
            todate=datetime.datetime(2014, 12, 31),
        )
        c.adddata(data)
        c.addstrategy(P, period=period)
        c.broker.setcash(100000)
        c.broker.setcommission(commission=0.001)
        s = c.run()[0]
        return s.rows, s.events, float(c.broker.getvalue()), len(fast)
    finally:
        ops._MIN_PERIOD_FOR_MONOTONIC_ONCE = old_cutoff
        ops._once_monotonic_extreme = old_helper


@pytest.mark.parametrize("period", [37, 129])
def test_actual_donchian_strategy_full_signals_and_events(period):
    next_rows, next_events, next_cash, next_fast = run(period, False, False)
    fast_rows, fast_events, fast_cash, fast_calls = run(period, True, False)
    ref_rows, ref_events, ref_cash, ref_calls = run(period, True, True)
    assert len(next_rows) > 1000 and next_events
    assert fast_calls > 0 and ref_calls == 0 and next_fast == 0
    assert fast_rows == ref_rows == next_rows
    assert fast_events == ref_events == next_events
    assert fast_cash == ref_cash == next_cash
    print(
        "period",
        period,
        "callbacks",
        len(fast_rows),
        "events",
        len(fast_events),
        "cash",
        fast_cash,
        "deque_calls",
        fast_calls,
    )
