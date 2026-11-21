"""VWAPCloseIndicator must match its n-bar formula in both Cerebro modes."""

from datetime import datetime
import math

import pandas as pd
import pytest

import backtrader as bt


def _frame(closes, volumes):
    index = pd.date_range(datetime(2024, 1, 1), periods=len(closes), freq="min")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
            "openinterest": [0.0] * len(closes),
        },
        index=index,
    )


def _reference_vwap(closes, volumes, period):
    """Compute the close-weighted ratio and documented volume fallback."""
    result = [float("nan")] * len(closes)
    previous = None
    for index in range(period - 1, len(closes)):
        left = index - period + 1
        window_volumes = volumes[left : index + 1]
        if any(math.isnan(float(volume)) for volume in window_volumes):
            current = float(closes[index])
            value = (
                previous
                if previous is not None and not math.isnan(previous)
                else current
            )
        else:
            effective_volumes = [max(float(volume), 1.0) for volume in window_volumes]
            numerator = sum(
                float(closes[offset]) * effective_volume
                for offset, effective_volume in zip(
                    range(left, index + 1), effective_volumes
                )
            )
            denominator = sum(effective_volumes)
            value = numerator / denominator

        result[index] = value
        previous = value
    return result


def _run_cerebro(closes, volumes, *, period, runonce):
    class Probe(bt.Strategy):
        def __init__(self):
            self.indicator = bt.indicators.VWAPCloseIndicator(self.data, n=period)
            self.rows = []

        def _record(self):
            self.rows.append(float(self.indicator[0]))

        def prenext(self):
            self._record()

        def nextstart(self):
            self._record()

        def next(self):
            self._record()

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=_frame(closes, volumes)))
    cerebro.addstrategy(Probe)
    result = cerebro.run()[0]
    return result.indicator._minperiod, result.rows


def _assert_values_match(actual, expected):
    assert len(actual) == len(expected)
    for index, (actual_value, expected_value) in enumerate(zip(actual, expected)):
        if math.isnan(expected_value):
            assert math.isnan(actual_value), (index, actual_value, expected_value)
        else:
            assert actual_value == pytest.approx(expected_value, abs=1e-12), (
                index,
                actual_value,
                expected_value,
            )


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("period", (1, 3))
@pytest.mark.parametrize(
    ("closes", "volumes"),
    (
        (
            (10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0),
            (2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0),
        ),
        (
            (10.0, 20.0, float("nan"), 40.0, 50.0, 60.0, 70.0),
            (2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0),
        ),
        (
            (10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0),
            (2.0, 3.0, float("nan"), 5.0, 6.0, 7.0, 8.0),
        ),
        (
            (10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0),
            (0.0, 0.5, -2.0, 1.0, 0.25, 2.0, 0.0),
        ),
    ),
    ids=(
        "finite",
        "missing-close-recovery",
        "missing-volume-fallback",
        "subunit-volume-clamp",
    ),
)
def test_vwap_close_matches_n_bar_formula_and_minperiod(
    runonce, period, closes, volumes
):
    minperiod, actual = _run_cerebro(
        closes, volumes, period=period, runonce=runonce
    )
    expected = _reference_vwap(closes, volumes, period)

    _assert_values_match(actual, expected)
    assert minperiod == period


def _run_two_feed_first_next(*, runonce):
    base_index = pd.date_range(datetime(2024, 1, 1), periods=25, freq="min")
    base_closes = [10.0 + index for index in range(len(base_index))]
    base = _frame(base_closes, [2.0] * len(base_closes)).set_axis(base_index)
    signal = base.iloc[::6].copy()
    result = {}

    class DualFeedProbe(bt.Strategy):
        def __init__(self):
            self.base = self.datas[0]
            self.signal = self.datas[1]
            self.indicator = bt.indicators.VWAPCloseIndicator(self.signal, n=2)
            result["minperiod"] = self.indicator._minperiod
            result["next_calls"] = []

        def nextstart(self):
            self.next()

        def next(self):
            result["next_calls"].append((len(self.base), len(self.signal)))

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce, preload=True)
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=base,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        )
    )
    cerebro.adddata(
        bt.feeds.PandasData(
            dataname=signal,
            timeframe=bt.TimeFrame.Minutes,
            compression=6,
        )
    )
    cerebro.addstrategy(DualFeedProbe)
    cerebro.run()
    return result


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_vwap_close_multifeed_starts_on_first_complete_window(runonce):
    result = _run_two_feed_first_next(runonce=runonce)

    assert result["minperiod"] == 2
    assert result["next_calls"][0] == (7, 2)
