"""WMA batch ranges preserve other output and match streaming calculation."""

import math

import backtrader as bt
import pandas as pd
import pytest


def _run(values, *, period=4, runonce=True):
    frame = pd.DataFrame(
        {"open": values, "high": values, "low": values, "close": values,
         "volume": [1.0] * len(values), "openinterest": [0.0] * len(values)},
        index=pd.date_range("2024-01-01", periods=len(values)),
    )

    class Strategy(bt.Strategy):
        def __init__(self):
            self.wma = bt.indicators.WMA(self.data.close, period=period)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Strategy)
    return cerebro.run(runonce=runonce, preload=True)[0].wma


def _expected(values, period):
    result = []
    coef = 2.0 / (period * (period + 1.0))
    for index in range(len(values)):
        if index < period - 1:
            result.append(float("nan"))
        else:
            window = values[index - period + 1:index + 1]
            result.append(coef * math.fsum((j + 1.0) * item for j, item in enumerate(window)))
    return result


def _assert_values(actual, expected):
    assert len(actual) == len(expected)
    for found, wanted in zip(actual, expected):
        if math.isnan(wanted):
            assert math.isnan(found)
        else:
            assert found == pytest.approx(wanted, rel=1e-12, abs=1e-12)


def test_once_only_writes_requested_interior_segment():
    values = [100.0 + i * 0.25 for i in range(16)]
    indicator = _run(values)
    output = indicator.lines.wma.array
    for index in range(len(output)):
        output[index] = -9999.0

    indicator.once(8, 12)

    assert list(output[:8]) == [-9999.0] * 8
    _assert_values(list(output[8:12]), _expected(values, 4)[8:12])
    assert list(output[12:]) == [-9999.0] * (len(output) - 12)


def test_once_warmup_and_empty_ranges_do_not_touch_other_slots():
    indicator = _run([float(i) for i in range(12)])
    output = indicator.lines.wma.array
    for index in range(len(output)):
        output[index] = -9999.0

    indicator.once(1, 3)
    assert output[0] == -9999.0
    assert math.isnan(output[1]) and math.isnan(output[2])
    assert list(output[3:]) == [-9999.0] * (len(output) - 3)

    snapshot = list(output)
    indicator.once(8, 8)
    assert all((math.isnan(a) and math.isnan(b)) or a == b for a, b in zip(output, snapshot))
    indicator.once(30, 30)
    assert len(output) == len(snapshot)


def test_once_input_shortage_marks_only_requested_unavailable_slots():
    values = [float(i) for i in range(12)]
    indicator = _run(values)
    output = indicator.lines.wma.array
    while len(output) < 18:
        output.append(-9999.0)
    for index in range(len(output)):
        output[index] = -9999.0

    indicator.once(10, 15)

    assert list(output[:10]) == [-9999.0] * 10
    _assert_values(list(output[10:12]), _expected(values, 4)[10:12])
    assert all(math.isnan(value) for value in output[12:15])
    assert list(output[15:]) == [-9999.0] * (len(output) - 15)


@pytest.mark.parametrize("period", [1, 4, 8])
@pytest.mark.parametrize("missing", [False, True], ids=["finite", "nan"])
def test_contiguous_segments_match_full_once_next_and_independent_formula(missing, period):
    values = [100.0 + i * 0.1 + i % 3 for i in range(40)]
    if missing:
        values[17] = float("nan")
    expected = _expected(values, period)
    streamed = _run(values, period=period, runonce=False)
    batched = _run(values, period=period, runonce=True)
    segmented = _run(values, period=period, runonce=True)
    output = segmented.lines.wma.array
    for index in range(len(values)):
        output[index] = -9999.0
    for start, end in ((0, 1), (1, 3), (3, 9), (9, 18), (18, 25), (25, 40)):
        segmented.once(start, end)

    assert streamed._minperiod == batched._minperiod == segmented._minperiod == period
    _assert_values(list(streamed.lines.wma.array[:len(values)]), expected)
    _assert_values(list(batched.lines.wma.array[:len(values)]), expected)
    _assert_values(list(output[:len(values)]), expected)


@pytest.mark.parametrize("runonce", [False, True], ids=["next", "once"])
def test_zpf_wma_children_match_independent_reference_with_missing_input(runonce):
    prices = [100.0 + i * 0.2 + i % 3 for i in range(40)]
    volumes = [2.0 + i % 4 for i in range(40)]
    prices[17] = float("nan")
    frame = pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices,
         "volume": volumes, "openinterest": [0.0] * len(prices)},
        index=pd.date_range("2024-01-01", periods=len(prices)),
    )

    class Strategy(bt.Strategy):
        def __init__(self):
            self.zpf = bt.indicators.ZPFIndicator(self.data, xlength=4, xma_method="wma")

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(Strategy)
    indicator = cerebro.run(runonce=runonce, preload=True)[0].zpf
    short = _expected(prices, 4)
    long = _expected(prices, 8)
    volume = _expected(volumes, 4)
    expected = [v * (s - ell) / 2.0 for v, s, ell in zip(volume, short, long)]

    assert indicator._minperiod == 17
    _assert_values(list(indicator.zpf.array[:len(prices)]), expected)
    _assert_values(list(indicator.line2.array[:len(prices)]), expected)
    _assert_values(list(indicator.line1.array[:len(prices)]), [-v for v in expected])
