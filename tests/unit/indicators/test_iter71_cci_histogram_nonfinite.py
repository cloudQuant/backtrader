"""CCI histogram validity and recovery on public, synthetic data."""

import math
from types import SimpleNamespace

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.cci_histogram_indicator import CCIHistogramIndicator
from tests.functional.strategies.mean_reversion.test_0268_0925_cci_histogram import (
    ExpCCIHistogramStrategy,
)


def _frame(count=180, *, missing=None, flat=False, every="min"):
    values = [100.0 if flat else 100.0 + 0.2 * i + 3 * math.sin(0.4 * i) for i in range(count)]
    if missing is not None:
        values[missing] = math.nan
    return pd.DataFrame(
        {
            "open": values,
            "high": [v + 1.0 for v in values],
            "low": [v - 1.0 for v in values],
            "close": values,
            "volume": [100.0] * count,
        },
        index=pd.date_range("2024-01-01", periods=count, freq=every),
    )


def _run(frame, *, runonce, primary=None):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = CCIHistogramIndicator(self.datas[-1], cci_period=14)

    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    if primary is not None:
        cerebro.adddata(bt.feeds.PandasData(dataname=primary))
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0].indicator


def _assert_classification(indicator):
    assert indicator._minperiod == 42  # Preserve current publication timing.
    cci, color, base = (list(line.array) for line in indicator.lines)
    assert len(cci) == len(color) == len(base)
    assert all(math.isnan(v) for v in color[:41])
    assert all(math.isnan(v) for v in base[:41])
    for raw, state, zero in zip(cci[41:], color[41:], base[41:]):
        assert zero == 0.0
        if not math.isfinite(raw):
            assert math.isnan(state)
        else:
            assert state == (0.0 if raw > 100 else 2.0 if raw < -100 else 1.0)
    return cci, color


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_missing_cci_is_not_neutral_and_recovers(runonce):
    indicator = _run(_frame(missing=55), runonce=runonce)
    cci, color = _assert_classification(indicator)
    # The current CCI implementation's nested period-14 windows recover here.
    assert all(math.isnan(v) for v in cci[55:82])
    assert all(math.isnan(v) for v in color[55:82])
    assert cci[82] > 100.0
    assert color[82] == 0.0
    assert math.isfinite(cci[83])


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_flat_data_produces_undefined_cci_without_fabricated_color(runonce):
    cci, color = _assert_classification(_run(_frame(flat=True), runonce=runonce))
    assert all(math.isnan(v) for v in cci[41:])
    assert all(math.isnan(v) for v in color[41:])


@pytest.mark.parametrize("raw", [math.nan, math.inf, -math.inf])
def test_nonfinite_cci_classification_including_signed_infinity(raw):
    # Directly exercise the classification hook because normal LineBuffer
    # writes convert infinities to NaN before this indicator can observe them.
    lines = SimpleNamespace(cci=[raw], color_state=[-1.0], hist_base=[-1.0])
    owner = SimpleNamespace(lines=lines, p=SimpleNamespace(high_level=100, low_level=-100))
    CCIHistogramIndicator.next(owner)
    assert math.isnan(lines.color_state[0])
    assert lines.hist_base[0] == 0.0


@pytest.mark.parametrize("raw,expected", [(-101.0, 2.0), (-100.0, 1.0), (100.0, 1.0), (101.0, 0.0)])
def test_finite_threshold_boundaries_are_unchanged(raw, expected):
    lines = SimpleNamespace(cci=[raw], color_state=[-1.0], hist_base=[-1.0])
    owner = SimpleNamespace(lines=lines, p=SimpleNamespace(high_level=100, low_level=-100))
    CCIHistogramIndicator.next(owner)
    assert lines.color_state[0] == expected
    assert lines.hist_base[0] == 0.0


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_secondary_feed_retains_validity_and_classification(runonce):
    signal = _frame(180, missing=55, every="3min")
    indicator = _run(signal, runonce=runonce, primary=_frame(540))
    cci, color = _assert_classification(indicator)
    assert all(math.isnan(v) for v in cci[55:82])
    assert all(math.isnan(v) for v in color[55:82])
    assert cci[82] > 100.0 and color[82] == 0.0


def test_replay_each_revision_projects_current_cci_validity():
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = CCIHistogramIndicator(self.data, cci_period=14)
            self.rows = []

        def next(self):
            self.rows.append((len(self.data), float(self.indicator.cci[0]),
                              float(self.indicator.color_state[0])))

    frame = _frame(550)
    frame.iloc[:240, frame.columns.get_indexer(["open", "high", "low", "close"])] = 100.0
    cerebro = bt.Cerebro(runonce=False, preload=False, stdstats=False)
    cerebro.replaydata(bt.feeds.PandasData(dataname=frame),
                       timeframe=bt.TimeFrame.Minutes, compression=5)
    cerebro.addstrategy(Probe)
    rows = cerebro.run()[0].rows
    assert any(a[0] == b[0] for a, b in zip(rows, rows[1:]))
    assert any(not math.isfinite(cci) for _, cci, _ in rows)
    assert any(math.isfinite(cci) for _, cci, _ in rows)
    for _, cci, color in rows:
        if math.isfinite(cci):
            assert color == (0.0 if cci > 100 else 2.0 if cci < -100 else 1.0)
        else:
            assert math.isnan(color)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_existing_strategy_does_not_signal_on_first_recovered_cci(runonce):
    class Trace(ExpCCIHistogramStrategy):
        def __init__(self):
            super().__init__()
            self.recovery_rows = []

        def next(self):
            before = self.signal_count
            super().next()
            if len(self.signal_data) in (82, 83, 84):
                self.recovery_rows.append((len(self.signal_data),
                                           float(self.indicator.color_state[-1]),
                                           float(self.indicator.color_state[0]),
                                           self.signal_count - before))

    frame = _frame(missing=55)
    cerebro = bt.Cerebro(runonce=runonce, preload=True, stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Trace, stop_loss_points=0, take_profit_points=0)
    rows = cerebro.run()[0].recovery_rows
    recovered = next(row for row in rows if row[0] == 83)
    assert math.isnan(recovered[1])
    assert recovered[2] == 0.0
    assert recovered[3] == 0
    following = next(row for row in rows if row[0] == 84)
    assert following[1:3] == (0.0, 0.0)
    assert following[3] == 0
