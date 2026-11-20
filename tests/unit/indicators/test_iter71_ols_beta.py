"""Regression checks for the OLS beta indicator's rolling windows."""

import builtins
import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.indicators import ols


class _RawNonfinitePandasData(bt.feeds.PandasData):
    """Expose a raw non-finite line value after normal feed assignment."""

    def _load(self):
        loaded = super()._load()
        override = getattr(self, "_test_raw_override", None)
        if loaded and override is not None:
            index, value = override
            line = self.lines.close
            if line._idx == index:
                line.array[line._idx] = value
        return loaded


def _pandas_feed(frame, raw_override=None):
    if raw_override is None:
        return bt.feeds.PandasData(dataname=frame)

    feed = _RawNonfinitePandasData(dataname=frame)
    feed._test_raw_override = raw_override
    return feed


def _run_beta(y_values, x_values, period, runonce, raw_override=None):
    """Run OLS_BetaN through Cerebro and return its complete line buffer."""
    index = pd.date_range("2025-01-01", periods=len(y_values))
    y_frame = pd.DataFrame({"close": y_values}, index=index)
    x_frame = pd.DataFrame({"close": x_values}, index=index)

    class BetaStrategy(bt.Strategy):
        def __init__(self):
            self.beta = bt.ind.OLS_BetaN(self.datas[0], self.datas[1], period=period)

    cerebro = bt.Cerebro(runonce=runonce)
    y_override = raw_override[1:] if raw_override and raw_override[0] == "y" else None
    x_override = raw_override[1:] if raw_override and raw_override[0] == "x" else None
    cerebro.adddata(_pandas_feed(y_frame, y_override))
    cerebro.adddata(_pandas_feed(x_frame, x_override))
    cerebro.addstrategy(BetaStrategy)
    strategy = cerebro.run()[0]
    return list(strategy.beta.array)


def _run_beta_frames(y_frame, x_frame, period, runonce, x_options=None, third_frame=None):
    """Run OLS_BetaN against explicit calendars through real Cerebro."""

    class BetaStrategy(bt.Strategy):
        def __init__(self):
            self.beta = bt.ind.OLS_BetaN(*self.datas, period=period)

    cerebro = bt.Cerebro(runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=y_frame))
    cerebro.adddata(bt.feeds.PandasData(dataname=x_frame, **(x_options or {})))
    if third_frame is not None:
        cerebro.adddata(bt.feeds.PandasData(dataname=third_frame))
    cerebro.addstrategy(BetaStrategy)
    return cerebro.run()[0]


def _run_beta_with_sma(y_values, x_values, sma_period, beta_period, runonce):
    """Run OLS_BetaN with an upstream SMA on its response input."""
    index = pd.date_range("2025-01-01", periods=len(y_values))
    y_frame = pd.DataFrame({"close": y_values}, index=index)
    x_frame = pd.DataFrame({"close": x_values}, index=index)

    class BetaStrategy(bt.Strategy):
        def __init__(self):
            self.source = bt.ind.SMA(self.datas[0], period=sma_period)
            self.beta = bt.ind.OLS_BetaN(self.source, self.datas[1], period=beta_period)

    cerebro = bt.Cerebro(runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=y_frame))
    cerebro.adddata(bt.feeds.PandasData(dataname=x_frame))
    cerebro.addstrategy(BetaStrategy)
    strategy = cerebro.run()[0]
    return strategy.source._minperiod, strategy.beta._minperiod, list(strategy.beta.array)


def _run_beta_with_unprovable_line_clock(runonce):
    index = pd.date_range("2025-01-01", periods=6)
    frame = pd.DataFrame({"close": range(6)}, index=index)

    class BetaStrategy(bt.Strategy):
        def __init__(self):
            expression = self.data0.close + 1.0
            self.beta = bt.ind.OLS_BetaN(expression, self.data1, period=2)

    cerebro = bt.Cerebro(runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(BetaStrategy)
    return cerebro.run()[0]


def _run_beta_after_delayed_source_start(index, runonce):
    frame = pd.DataFrame({"close": range(len(index))}, index=index)

    class BetaStrategy(bt.Strategy):
        def __init__(self):
            source = bt.ind.SMA(self.datas[0], period=4)
            self.beta = bt.ind.OLS_BetaN(source, self.datas[1], period=2)

    cerebro = bt.Cerebro(runonce=runonce)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(BetaStrategy)
    return cerebro.run()[0]


def _run_beta_with_midstream_reset(
    runonce=False,
    exactbars=0,
    reset_at=5,
    periods=12,
):
    index = pd.date_range("2025-01-01", periods=periods)
    x_values = [float(i + 1) for i in range(len(index))]
    y_values = [2.0 * value + 3.0 for value in x_values]
    x_frame = pd.DataFrame({"close": x_values}, index=index)
    y_frame = pd.DataFrame({"close": y_values}, index=index)

    class ResetStrategy(bt.Strategy):
        def __init__(self):
            self.beta = bt.ind.OLS_BetaN(self.data0, self.data1, period=3)
            self.reset_clock_counts = None
            self.after_reset = []

        def next(self):
            bar = len(self.data0) - 1
            if reset_at is not None and bar == reset_at:
                self.beta.reset()
                self.reset_clock_counts = [
                    state["count"] for state in self.beta._ols_beta_clock_state
                ]
            elif self.reset_clock_counts is not None or reset_at is None:
                self.after_reset.append(self.beta[0])

    cerebro = bt.Cerebro(runonce=runonce, exactbars=exactbars)
    cerebro.adddata(bt.feeds.PandasData(dataname=y_frame))
    cerebro.adddata(bt.feeds.PandasData(dataname=x_frame))
    cerebro.addstrategy(ResetStrategy)
    return cerebro.run()[0]


@pytest.mark.parametrize("runonce", [True, False])
def test_ols_beta_matches_intercept_regression_in_both_cerebro_modes(runonce):
    # OLS is y=data0 on x=data1, with an intercept. The independent
    # covariance/variance calculation gives rolling slopes 2.0, 2.6, and 3.4.
    x_values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    y_values = [10.0, 12.0, 14.0, 16.0, 20.0, 24.0]

    values = _run_beta(y_values, x_values, period=4, runonce=runonce)

    assert len(values) == len(x_values)
    assert all(math.isnan(value) for value in values[:3])
    assert next(i for i, value in enumerate(values) if math.isfinite(value)) == 3
    assert values[3:] == pytest.approx([2.0, 2.6, 3.4])


@pytest.mark.parametrize("runonce", [True, False])
def test_ols_beta_short_history_stays_nan_without_fitting(runonce):
    values = _run_beta([4.0, 7.0], [1.0, 2.0], period=3, runonce=runonce)

    assert len(values) == 2
    assert all(math.isnan(value) for value in values)


@pytest.mark.parametrize("runonce", [True, False])
def test_ols_beta_zero_predictor_variance_returns_nan(runonce):
    values = _run_beta(
        [2.0, 4.0, 6.0, 8.0, 10.0],
        [5.0, 5.0, 5.0, 5.0, 5.0],
        period=3,
        runonce=runonce,
    )

    assert all(math.isnan(value) for value in values)


@pytest.mark.parametrize("runonce", [True, False])
@pytest.mark.parametrize("nan_series", ["y", "x"])
@pytest.mark.parametrize(
    "nonfinite_value",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive_inf", "negative_inf"],
)
def test_ols_beta_nonfinite_window_returns_nan_then_recovers(runonce, nan_series, nonfinite_value):
    x_values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    y_values = [3.0, 5.0, 7.0, 9.0, 11.0, 13.0]
    (y_values if nan_series == "y" else x_values)[2] = nonfinite_value
    raw_override = (2, nonfinite_value) if math.isinf(nonfinite_value) else None
    source_override = nan_series if raw_override is not None else None

    values = _run_beta(
        y_values,
        x_values,
        period=3,
        runonce=runonce,
        raw_override=(source_override, *raw_override) if raw_override is not None else None,
    )

    assert all(math.isnan(value) for value in values[:5])
    assert values[5:] == pytest.approx([2.0])


@pytest.mark.parametrize("runonce", [True, False])
def test_ols_beta_adds_its_period_to_upstream_sma_minperiod(runonce):
    x_values = [float(i) for i in range(1, 11)]
    y_values = [2.0 * value + 5.0 for value in x_values]
    sma_period = 3
    beta_period = 4

    source_minperiod, beta_minperiod, values = _run_beta_with_sma(
        y_values, x_values, sma_period, beta_period, runonce
    )

    expected_minperiod = sma_period + beta_period - 1
    assert source_minperiod == sma_period
    assert beta_minperiod == expected_minperiod
    first_valid = next(i for i, value in enumerate(values) if math.isfinite(value))
    assert first_valid == expected_minperiod - 1
    assert values[first_valid:] == pytest.approx([2.0] * (len(values) - first_valid))


@pytest.mark.parametrize("runonce", [True, False])
@pytest.mark.parametrize(
    "case",
    ["different_start_and_frequency", "different_frequency", "compressed_feed"],
)
def test_ols_beta_rejects_unproven_source_clock_alignment(runonce, case):
    if case == "different_start_and_frequency":
        y_index = pd.date_range("2025-01-01", periods=8, freq="D")
        x_index = pd.date_range("2025-01-04", periods=5, freq="2D")
        x_options = {}
    elif case == "different_frequency":
        y_index = pd.date_range("2025-01-01", periods=8, freq="D")
        x_index = pd.date_range("2025-01-01", periods=5, freq="2D")
        x_options = {}
    else:
        y_index = pd.date_range("2025-01-01", periods=12, freq="D")
        x_index = pd.date_range("2025-01-03", periods=4, freq="3D")
        x_options = {"timeframe": bt.TimeFrame.Days, "compression": 3}

    y_frame = pd.DataFrame({"close": range(len(y_index))}, index=y_index)
    x_frame = pd.DataFrame({"close": range(len(x_index))}, index=x_index)

    with pytest.raises(ValueError, match="OLS_BetaN.*datetime"):
        _run_beta_frames(y_frame, x_frame, period=2, runonce=runonce, x_options=x_options)


@pytest.mark.parametrize("runonce", [True, False])
def test_ols_beta_rejects_a_third_data_input(runonce):
    index = pd.date_range("2025-01-01", periods=5)
    frames = [pd.DataFrame({"close": range(5)}, index=index) for _ in range(3)]

    with pytest.raises(ValueError, match="OLS_BetaN requires exactly two data inputs"):
        _run_beta_frames(frames[0], frames[1], period=2, runonce=runonce, third_frame=frames[2])


@pytest.mark.parametrize("runonce", [True, False])
def test_ols_beta_aligns_distinct_source_indices_by_datetime(runonce):
    x_index = pd.date_range("2025-01-01", periods=8, freq="D")
    y_index = x_index[2:]
    x_values = [float(i) for i in range(8)]
    y_values = [2.0 * value + 4.0 for value in x_values[2:]]
    x_frame = pd.DataFrame({"close": x_values}, index=x_index)
    y_frame = pd.DataFrame({"close": y_values}, index=y_index)

    strategy = _run_beta_frames(y_frame, x_frame, period=3, runonce=runonce)
    values = list(strategy.beta.array)

    assert all(math.isnan(value) for value in values[:2])
    assert values[2:] == pytest.approx([2.0] * (len(y_values) - 2))


@pytest.mark.parametrize("runonce", [True, False])
def test_ols_beta_rejects_line_inputs_without_a_reliable_clock(runonce):
    with pytest.raises(ValueError, match="OLS_BetaN.*datetime"):
        _run_beta_with_unprovable_line_clock(runonce)


@pytest.mark.parametrize("runonce", [True, False])
@pytest.mark.parametrize("clock_issue", ["duplicate", "descending"])
def test_ols_beta_rejects_invalid_history_before_delayed_first_output(runonce, clock_issue):
    index = list(pd.date_range("2025-01-01", periods=8))
    if clock_issue == "duplicate":
        index[1] = index[0]
    else:
        index[1], index[2] = index[2], index[1]

    with pytest.raises(ValueError, match="OLS_BetaN.*(strictly increasing|datetime)"):
        _run_beta_after_delayed_source_start(index, runonce)


def test_ols_beta_reset_preserves_clock_cursor_and_same_instance_reuses_in_cerebro():
    strategy = _run_beta_with_midstream_reset()

    assert strategy.reset_clock_counts == [6, 6]
    assert strategy.after_reset == pytest.approx([2.0] * 6)
    assert [state["count"] for state in strategy.beta._ols_beta_clock_state] == [12, 12]


def test_ols_beta_reset_after_runonce_batch_clears_precomputed_line_without_recalculation():
    strategy = _run_beta_with_midstream_reset(runonce=True)

    assert strategy.reset_clock_counts == [0, 0]
    assert all(math.isnan(value) for value in strategy.after_reset)


@pytest.mark.parametrize("exactbars", [1, -1])
def test_ols_beta_works_with_bounded_buffers_without_reset(exactbars):
    strategy = _run_beta_with_midstream_reset(
        exactbars=exactbars,
        reset_at=None,
        periods=30,
    )

    assert len(strategy.after_reset) == 28
    assert strategy.after_reset == pytest.approx([2.0] * 28)


@pytest.mark.parametrize("exactbars", [1, -1])
def test_ols_beta_reset_reuses_bounded_sources_without_rescanning_lost_history(exactbars):
    strategy = _run_beta_with_midstream_reset(exactbars=exactbars, periods=30)

    assert strategy.reset_clock_counts == [6, 6]
    finite_values = [value for value in strategy.after_reset if math.isfinite(value)]
    assert finite_values == pytest.approx([2.0] * len(finite_values))
    if exactbars == 1:
        assert math.isnan(strategy.after_reset[0])
        assert len(finite_values) == 23
    else:
        assert len(finite_values) == 24
    assert [state["count"] for state in strategy.beta._ols_beta_clock_state] == [30, 30]


def test_ols_beta_source_reset_after_indicator_reset_fails_closed_with_bounded_history():
    strategy = _run_beta_with_midstream_reset(
        exactbars=1,
        reset_at=None,
        periods=30,
    )
    strategy.beta.reset()
    strategy.data0.reset()
    strategy.data1.reset()

    with pytest.raises(ValueError, match="OLS_BetaN source clock reset"):
        strategy.beta.next()


def test_ols_beta_reports_missing_numpy_dependency(monkeypatch):
    original_import = builtins.__import__

    def import_without_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ModuleNotFoundError("No module named 'numpy'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_numpy)

    with pytest.raises(ImportError, match="OLS_BetaN requires NumPy"):
        ols._get_numpy()
