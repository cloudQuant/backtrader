"""MT5 close stochastic updates once per input bar, including replay revisions."""

import datetime as dt
import math

import backtrader as bt
import pytest


class _Feed(bt.feed.DataBase):
    params = (("samples", ()),)

    def __init__(self):
        super().__init__()
        self.index = 0

    def _load(self):
        if self.index == len(self.p.samples):
            return False
        timestamp, value = self.p.samples[self.index]
        self.datetime[0] = bt.date2num(timestamp)
        self.open[0] = self.high[0] = self.low[0] = self.close[0] = value
        self.volume[0], self.openinterest[0] = 1.0, 0.0
        self.index += 1
        return True


def _prices(count):
    return [100.0 + i * .13 + math.sin(i * .27) * 3.0 + (i % 7) * .1 for i in range(count)]


def _reference(values, kperiod=5, slowing=3, dperiod=3):
    minperiod = kperiod + max(slowing, dperiod) + 2
    main, signal = [math.nan] * len(values), [math.nan] * len(values)
    slow_prev = signal_prev = None
    for index in range(minperiod - 1, len(values)):
        window = [values[index - j] for j in range(kperiod)]
        high, low = max(window), min(window)
        raw = 0.0 if high == low else 100.0 * (values[index] - low) / (high - low)
        slow = raw if slow_prev is None else slow_prev + 2.0 / (slowing + 1) * (raw - slow_prev)
        sig = slow if signal_prev is None else signal_prev + 2.0 / (dperiod + 1) * (slow - signal_prev)
        main[index], signal[index] = slow, sig
        slow_prev, signal_prev = slow, sig
    return main, signal


def _daily(values, *, step_days=1):
    return [(dt.datetime(2020, 1, 1, 9) + dt.timedelta(days=i * step_days), value)
            for i, value in enumerate(values)]


def _run(values, runonce, *, multifeed=False, replay=False, missing_revision=False):
    class Probe(bt.Strategy):
        def __init__(self):
            source = self.datas[1] if multifeed else self.data
            self.ind = bt.indicators.Mt5StochasticCloseClose(source)
            self.seen = []

        def prenext(self):
            self.next()

        def next(self):
            self.seen.append((len(self.ind.data), float(self.ind.data.close[0]),
                              float(self.ind.main[0]), float(self.ind.signal[0])))

        def stop(self):
            self.output = (list(self.ind.main.array), list(self.ind.signal.array))

    engine = bt.Cerebro(runonce=runonce, preload=not replay, stdstats=False)
    if multifeed:
        engine.adddata(_Feed(samples=_daily(_prices(len(values) * 3))))
    if replay:
        samples = [(dt.datetime(2020, 1, 1, 9) + dt.timedelta(days=i, hours=j),
                    math.nan if missing_revision and i == 20 and j == 1
                    else value + (0.6, -0.4, 0.0)[j])
                   for i, value in enumerate(values) for j in range(3)]
        feed = _Feed(samples=samples, timeframe=bt.TimeFrame.Minutes, compression=60)
        engine.replaydata(feed, timeframe=bt.TimeFrame.Days)
    else:
        engine.adddata(_Feed(samples=_daily(values, step_days=3 if multifeed else 1)))
    engine.addstrategy(Probe)
    return engine.run(runonce=runonce, preload=not replay)[0]


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("count", [9, 10, 80])
def test_daily_formula_and_short_history(runonce, count):
    values = _prices(count)
    result = _run(values, runonce)
    assert result.ind._minperiod == 10
    for actual, expected in zip(result.output, _reference(values)):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_missing_close_keeps_existing_non_reseeding_behavior(runonce):
    values = _prices(70)
    values[25] = math.nan
    result = _run(values, runonce)
    for actual, expected in zip(result.output, _reference(values)):
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)
        assert all(math.isnan(value) for value in actual[25:])


def test_replay_revisions_recompute_from_previous_completed_bar():
    values = _prices(40)
    result = _run(values, False, replay=True)
    assert len(result.seen) == len(values) * 3
    for bar, current, main, signal in result.seen:
        expected = _reference(values[:bar - 1] + [current])
        assert main == pytest.approx(expected[0][-1], rel=1e-12, abs=1e-12, nan_ok=True)
        assert signal == pytest.approx(expected[1][-1], rel=1e-12, abs=1e-12, nan_ok=True)


def test_replay_missing_revision_can_be_replaced_on_same_bar():
    values = _prices(40)
    result = _run(values, False, replay=True, missing_revision=True)
    revisions = [row for row in result.seen if row[0] == 21]
    assert len(revisions) == 3
    assert math.isnan(revisions[1][1])
    assert math.isnan(revisions[1][2]) and math.isnan(revisions[1][3])
    expected = _reference(values[:21])
    assert revisions[2][2] == pytest.approx(expected[0][-1])
    assert revisions[2][3] == pytest.approx(expected[1][-1])


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_secondary_feed_uses_its_own_bar_clock(runonce):
    values = _prices(40)
    result = _run(values, runonce, multifeed=True)
    for actual, expected in zip(result.output, _reference(values)):
        assert len(actual) == len(values)
        assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12, nan_ok=True)
