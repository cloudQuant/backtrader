"""Bounded runnext coverage for the legacy cohort-off feed path."""

import datetime as dt

import backtrader as bt


class _DelayedFiniteFeed(bt.feeds.DataBase):
    """Yield an initial live-style no-data result, then a finite bar sequence."""

    params = (("bars", ()), ("initial_none_loads", 0))

    def __init__(self):
        super().__init__()
        self._bars = tuple(self.p.bars)
        self._index = 0
        self._none_left = self.p.initial_none_loads
        self.none_returns = 0
        self.check_calls = 0
        self.rewind_calls = 0

    def start(self):
        super().start()
        self._index = 0
        self._none_left = self.p.initial_none_loads

    def _load(self):
        if self._none_left:
            self._none_left -= 1
            self.none_returns += 1
            return None
        if self._index >= len(self._bars):
            return False

        timestamp, close = self._bars[self._index]
        self.lines.datetime[0] = bt.date2num(timestamp)
        self.lines.open[0] = close
        self.lines.high[0] = close
        self.lines.low[0] = close
        self.lines.close[0] = close
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        self._index += 1
        return True

    def _check(self, forcedata=None):
        self.check_calls += 1
        return super()._check(forcedata=forcedata)

    def rewind(self, size=1):
        self.rewind_calls += 1
        return super().rewind(size)


class _RecordAlignedBars(bt.Strategy):
    def __init__(self):
        self.observed = []

    def next(self):
        self.observed.append(tuple(data.datetime.datetime(0) for data in self.datas))


def test_cohort_off_all_none_then_arrival_multidata_rewind_and_short_member_eof():
    start = dt.datetime(2026, 10, 24, 9, 0)
    short_member = _DelayedFiniteFeed(
        bars=(
            (start, 10.0),
            (start + dt.timedelta(minutes=1), 11.0),
        ),
        initial_none_loads=1,
    )
    long_member = _DelayedFiniteFeed(
        bars=(
            (start, 20.0),
            (start + dt.timedelta(minutes=2), 22.0),
        ),
        initial_none_loads=1,
    )
    cerebro = bt.Cerebro(runonce=False, preload=False)
    cerebro.adddata(short_member, name="short")
    cerebro.adddata(long_member, name="long")
    cerebro.addstrategy(_RecordAlignedBars)

    strategy = cerebro.run()[0]

    assert cerebro.live_bar_cohort is None
    assert getattr(short_member, "_live_bar_cohort", None) is None
    assert getattr(long_member, "_live_bar_cohort", None) is None
    assert [short_member.none_returns, long_member.none_returns] == [1, 1]
    assert short_member.check_calls > 0
    assert long_member.check_calls > 0
    assert long_member.rewind_calls > 0
    assert strategy.observed == [
        (start, start),
        (start + dt.timedelta(minutes=1), start),
        (start + dt.timedelta(minutes=1), start + dt.timedelta(minutes=2)),
    ]
    assert len(short_member) == 2
    assert len(long_member) == 2
