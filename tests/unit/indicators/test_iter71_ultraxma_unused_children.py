"""Regression for unused UltraXMA smoothing child indicators (R71-047)."""

from datetime import datetime
import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators.contrib.adx_cross_hull_style_indicator import (
    UltraXMAIndicator,
    resolve_ma_class,
    resolve_price_line,
)


class _PriorChildrenUltraXMA(UltraXMAIndicator):
    """Test fixture preserving the prior constructor and output formulas."""

    def __init__(self):
        price_line = resolve_price_line(self.data, self.p.ipc)
        ma_cls = resolve_ma_class(self.p.w_method)
        smooth_cls = resolve_ma_class(self.p.smooth_method)
        self._periods = [
            int(self.p.start_length + index * self.p.step)
            for index in range(int(self.p.steps_total) + 1)
        ]
        self._ma_lines = [ma_cls(price_line, period=max(1, period)) for period in self._periods]
        self._bull_smooth = smooth_cls(
            self.lines.bulls, period=max(1, int(self.p.smooth_length))
        )
        self._bear_smooth = smooth_cls(
            self.lines.bears, period=max(1, int(self.p.smooth_length))
        )
        self.addminperiod(max(self._periods) + int(self.p.smooth_length) + 5)

    def next(self):
        """Preserve the former per-bar EMA count-smoothing formula."""
        upsch = 0.0
        dnsch = 0.0
        for ma_line in self._ma_lines:
            if float(ma_line[0]) > float(ma_line[-1]):
                upsch += 1.0
            else:
                dnsch += 1.0
        period = max(1, int(self.p.smooth_length))
        alpha = 2.0 / (period + 1.0)
        prev_bulls = float(self.lines.bulls[-1]) if len(self) > 0 else upsch
        prev_bears = float(self.lines.bears[-1]) if len(self) > 0 else dnsch
        if prev_bulls != prev_bulls:
            prev_bulls = upsch
        if prev_bears != prev_bears:
            prev_bears = dnsch
        self.lines.bulls[0] = alpha * upsch + (1.0 - alpha) * prev_bulls if len(self) > 0 else upsch
        self.lines.bears[0] = alpha * dnsch + (1.0 - alpha) * prev_bears if len(self) > 0 else dnsch

    def once(self, start, end):
        """Preserve the former segmented runonce EMA count formula."""
        ma_arrays = [ma_line.array for ma_line in self._ma_lines]
        bulls_line = self.lines.bulls.array
        bears_line = self.lines.bears.array
        for line in (bulls_line, bears_line):
            while len(line) < end:
                line.append(float("nan"))

        period = max(1, int(self.p.smooth_length))
        alpha = 2.0 / (period + 1.0)
        prev_bulls = None
        prev_bears = None
        if start > 0:
            prev_bulls = float(bulls_line[start - 1])
            prev_bears = float(bears_line[start - 1])
            if prev_bulls != prev_bulls:
                prev_bulls = None
            if prev_bears != prev_bears:
                prev_bears = None
        actual_end = min([end] + [len(array) for array in ma_arrays])
        for index in range(start, actual_end):
            upsch = 0.0
            dnsch = 0.0
            for ma_array in ma_arrays:
                if index > 0 and float(ma_array[index]) > float(ma_array[index - 1]):
                    upsch += 1.0
                else:
                    dnsch += 1.0
            bulls = (
                upsch
                if prev_bulls is None
                else alpha * upsch + (1.0 - alpha) * prev_bulls
            )
            bears = (
                dnsch
                if prev_bears is None
                else alpha * dnsch + (1.0 - alpha) * prev_bears
            )
            bulls_line[index] = bulls
            bears_line[index] = bears
            prev_bulls = bulls
            prev_bears = bears


def _run_ultraxma(
    *,
    runonce,
    closes=None,
    indicator_class=UltraXMAIndicator,
    smooth_method="jjma",
    smooth_length=3,
    smooth_phase=100,
):
    if closes is None:
        closes = [100.0 + index for index in range(62)]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=pd.date_range(datetime(2024, 1, 1), periods=len(closes)),
    )
    result = {}

    class CaptureUltraXMA(bt.Strategy):
        def __init__(self):
            self.indicator = indicator_class(
                self.data,
                smooth_method=smooth_method,
                smooth_length=smooth_length,
                smooth_phase=smooth_phase,
            )

        def stop(self):
            result["minperiod"] = self.indicator._minperiod
            result["children"] = (
                hasattr(self.indicator, "_bull_smooth"),
                hasattr(self.indicator, "_bear_smooth"),
            )
            result["params"] = (
                self.indicator.p.smooth_method,
                self.indicator.p.smooth_length,
                self.indicator.p.smooth_phase,
            )
            result["bulls"] = [float(value) for value in self.indicator.bulls.array]
            result["bears"] = [float(value) for value in self.indicator.bears.array]

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(CaptureUltraXMA)
    cerebro.run(runonce=runonce, preload=True)
    return result


def _trend_closes(length):
    """Return a nonmonotonic path that changes the fan's breadth counts."""
    return [
        100.0 + index * 0.17 + math.sin(index * 0.31) * 4.0
        + math.cos(index * 0.13) * 1.5
        for index in range(length)
    ]


def _assert_same_line(actual, expected):
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected):
        if math.isnan(expected_value):
            assert math.isnan(actual_value)
        else:
            assert actual_value == pytest.approx(expected_value, abs=1e-12)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_ultraxma_keeps_parameters_minperiod_and_outputs_without_unused_children(
    runonce,
):
    result = _run_ultraxma(runonce=runonce)

    assert result["children"] == (False, False)
    assert result["params"] == ("jjma", 3, 100)
    assert result["minperiod"] == 61
    assert len(result["bulls"]) == len(result["bears"]) == 62
    assert all(math.isnan(value) for value in result["bulls"][:60])
    assert all(math.isnan(value) for value in result["bears"][:60])
    assert result["bulls"][60:] == pytest.approx([11.0, 11.0])
    assert result["bears"][60:] == pytest.approx([0.0, 0.0])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize(
    ("smooth_method", "smooth_length"),
    (("sma", 2), ("smma", 5), ("unknown", 8)),
)
def test_ultraxma_outputs_match_prior_child_constructor_for_method_and_length(
    runonce, smooth_method, smooth_length
):
    closes = _trend_closes(180)
    options = {
        "runonce": runonce,
        "closes": closes,
        "smooth_method": smooth_method,
        "smooth_length": smooth_length,
        "smooth_phase": 37,
    }
    prior = _run_ultraxma(indicator_class=_PriorChildrenUltraXMA, **options)
    current = _run_ultraxma(indicator_class=UltraXMAIndicator, **options)

    assert prior["children"] == (True, True)
    assert current["children"] == (False, False)
    assert prior["params"] == current["params"] == (
        smooth_method,
        smooth_length,
        37,
    )
    assert prior["minperiod"] == current["minperiod"] == 53 + smooth_length + 5
    _assert_same_line(current["bulls"], prior["bulls"])
    _assert_same_line(current["bears"], prior["bears"])

    first_valid = current["minperiod"] - 1
    assert len(set(current["bulls"][first_valid:])) > 1
    assert len(set(current["bears"][first_valid:])) > 1
