"""Regression coverage for remaining Iter-71 contrib indicators:
R71-044 (XmaIchimoku O(1) rolling sum),
R71-047 (UltraXMAIndicator smooth_method/smooth_phase warnings & ADXCrossHullStyleIndicator),
R71-112b (XCCIHistogramVolDirectIndicator missing color, ColorXDerivative minperiod,
VininITrendIndicator segmented runonce continuity).
"""

from __future__ import annotations

import math
import random
import warnings

import pandas as pd
import pytest

import backtrader as bt
from backtrader.indicators.contrib.adx_cross_hull_style_indicator import (
    ADXCrossHullStyleIndicator,
    UltraXMAIndicator,
)
from backtrader.indicators.contrib.color_x_derivative import ColorXDerivative
from backtrader.indicators.contrib.vinin_i_trend_indicator import VininITrendIndicator
from backtrader.indicators.contrib.xcci_histogram_vol_direct_indicator import (
    XCCIHistogramVolDirectIndicator,
)
from backtrader.indicators.contrib.xma_ichimoku import (
    TwoXmaIchimokuOscillator,
    XmaIchimoku,
)


def _ohlcv_frame(closes, *, high_offset=0.6, low_offset=0.6, volume=100.0):
    n = len(closes)
    if isinstance(volume, (int, float)):
        volumes = [float(volume)] * n
    else:
        volumes = list(volume)
    opens = [closes[max(0, i - 1)] for i in range(n)]
    highs = [max(o, c) + high_offset + (i % 3) * 0.1 for i, (o, c) in enumerate(zip(opens, closes))]
    lows = [min(o, c) - low_offset - (i % 4) * 0.1 for i, (o, c) in enumerate(zip(opens, closes))]
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "openinterest": [0.0] * n,
        },
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )


def _flat_ohlcv_frame(values):
    return pd.DataFrame(
        {
            "open": values,
            "high": values,
            "low": values,
            "close": values,
            "volume": [1.0] * len(values),
            "openinterest": [0.0] * len(values),
        },
        index=pd.date_range("2024-01-01", periods=len(values), freq="min"),
    )


def _assert_series_close(actual, expected, *, rel=1e-12, abs_tol=1e-12):
    assert len(actual) == len(expected)
    for idx, (got, want) in enumerate(zip(actual, expected)):
        if math.isnan(want) or math.isinf(want):
            assert math.isnan(got), (idx, got, want)
        else:
            assert got == pytest.approx(want, rel=rel, abs=abs_tol), (idx, got, want)


# ---------------------------------------------------------------------------
# R71-044: XmaIchimoku O(1) rolling SMA sum
# ---------------------------------------------------------------------------


def _run_xma(values, *, period, runonce=False, exactbars=0):
    class Probe(bt.Strategy):
        def __init__(self):
            self.xma = XmaIchimoku(
                self.data,
                up_period=1,
                dn_period=1,
                xma_method="SMA",
                x_length=period,
                price_shift=0.25,
            )
            self.raw_values = []
            self.values = []

        def next(self):
            self.raw_values.append(
                (float(self.data.high[0]) + float(self.data.low[0])) / 2.0
            )
            self.values.append(float(self.xma.lines.value[0]))

    cerebro = bt.Cerebro(
        runonce=runonce,
        preload=not exactbars,
        exactbars=exactbars,
        stdstats=False,
    )
    cerebro.adddata(bt.feeds.PandasData(dataname=_flat_ohlcv_frame(values)))
    cerebro.addstrategy(Probe)
    return cerebro.run()[0]


def _xma_reference_sma(raw_values, period, price_shift=0.25):
    history = []
    out = []
    for raw in raw_values:
        history.append(raw)
        if len(history) < period:
            out.append(raw + price_shift)
        else:
            out.append(sum(history[-period:]) / float(period) + price_shift)
    return out


@pytest.mark.parametrize("period", [128, 256])
@pytest.mark.parametrize(
    "scale", ["normal", "large-offset", "alternating-cancel", "finite-impulse"]
)
def test_xma_long_period_rolling_sum_matches_reference_and_dual_modes(period, scale):
    rng = random.Random(2026)
    n = period + 700
    if scale == "normal":
        values = [100.0 + rng.uniform(-5.0, 5.0) for _ in range(n)]
    elif scale == "large-offset":
        values = [1e12 + rng.random() for _ in range(n)]
    elif scale == "alternating-cancel":
        values = [(1e8 if i % 2 else -1e8) + rng.random() for i in range(n)]
    else:
        values = [100.0 + rng.uniform(-1.0, 1.0) for _ in range(n)]
        values[period + 120] = 1e308
        values[period + 121] = 1e308
        values[period + 400] = 1e16

    s_next = _run_xma(values, period=period, runonce=False)
    s_once = _run_xma(values, period=period, runonce=True)
    expected = _xma_reference_sma(s_next.raw_values, period)

    assert len(s_next.xma._raw_buf) == period
    assert s_next.xma._rolling_period == period
    _assert_series_close(s_next.values, expected, rel=1e-12, abs_tol=1e-12)
    _assert_series_close(s_once.values, expected, rel=1e-12, abs_tol=1e-12)
    _assert_series_close(s_once.values, s_next.values, rel=0.0, abs_tol=0.0)


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
def test_xma_long_period_rolling_sum_recovers_from_nan_and_infinities(runonce):
    period = 160
    values = [100.0 + (i % 37) * 0.25 for i in range(900)]
    # Inject NaN, +inf (via 1e308+1e308 overflow in midpoint), -inf, and +/-inf pair.
    values[200] = float("nan")
    values[420] = 1e308
    values[421] = -1e308
    values[640] = 1e308

    strategy = _run_xma(values, period=period, runonce=runonce)
    expected = _xma_reference_sma(strategy.raw_values, period)

    _assert_series_close(strategy.values, expected, rel=1e-12, abs_tol=1e-12)
    assert any(math.isnan(v) for v in strategy.values)
    assert math.isfinite(strategy.values[-1])


def test_xma_long_period_dynamic_length_and_exactbars():
    values = [100.0 + ((i * 29) % 97) * 0.1 for i in range(600)]

    class DynamicLongProbe(bt.Strategy):
        def __init__(self):
            self.xma = XmaIchimoku(
                self.data,
                up_period=1,
                dn_period=1,
                xma_method="SMA",
                x_length=160,
                price_shift=0.25,
            )
            self.raws = []
            self.vals = []
            self.periods = []
            self.methods = []

        def next(self):
            idx = len(self.vals)
            self.raws.append((float(self.data.high[0]) + float(self.data.low[0])) / 2.0)
            self.vals.append(float(self.xma.lines.value[0]))
            self.periods.append(int(self.xma.p.x_length))
            self.methods.append(str(self.xma.p.xma_method).upper())
            if idx == 180:
                self.xma.p.x_length = 140
            elif idx == 210:
                self.xma.p.x_length = 160
            elif idx == 250:
                self.xma.p.x_length = 64
            elif idx == 290:
                self.xma.p.xma_method = "EMA"
            elif idx == 330:
                self.xma.p.xma_method = "SMA"
                self.xma.p.x_length = 160

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=_flat_ohlcv_frame(values)))
    cerebro.addstrategy(DynamicLongProbe)
    strat = cerebro.run(runonce=False, preload=True)[0]

    # Independent reference for dynamic changes
    history = []
    smooth_prev = None
    expected = []
    for raw, per, method in zip(strat.raws, strat.periods, strat.methods):
        history.append(raw)
        if method in ("SMA", "MODE_SMA_"):
            s = raw if len(history) < per else sum(history[-per:]) / float(per)
        else:
            alpha = max(0.01, min(0.99, (2.0 / (per + 1.0)) * (1.0 + 0.35 * 0.15)))
            s = raw if (smooth_prev is None or not math.isfinite(smooth_prev)) else smooth_prev + alpha * (raw - smooth_prev)
            smooth_prev = s
        expected.append(s + 0.25)

    _assert_series_close(strat.vals, expected, rel=1e-12, abs_tol=1e-12)

    # Verify exactbars=1 parity on XmaIchimoku and TwoXmaIchimokuOscillator
    eb_strat = _run_xma(values, period=160, runonce=False, exactbars=1)
    unb_strat = _run_xma(values, period=160, runonce=False, exactbars=0)
    _assert_series_close(eb_strat.values, unb_strat.values, rel=0.0, abs_tol=0.0)

    class OscProbe(bt.Strategy):
        def __init__(self):
            self.osc = TwoXmaIchimokuOscillator(self.data, x_length1=130, x_length2=160)
            self.rows = []

        def next(self):
            self.rows.append((float(self.osc.line[0]), float(self.osc.color[0])))

    def _run_osc(runonce, exactbars=0):
        c = bt.Cerebro(runonce=runonce, preload=not exactbars, exactbars=exactbars, stdstats=False)
        c.adddata(bt.feeds.PandasData(dataname=_flat_ohlcv_frame(values)))
        c.addstrategy(OscProbe)
        return c.run()[0].rows

    osc_next = _run_osc(False, 0)
    osc_once = _run_osc(True, 0)
    osc_eb = _run_osc(False, 1)
    assert osc_next == osc_once == osc_eb


# ---------------------------------------------------------------------------
# R71-047: UltraXMAIndicator parameter semantics & ADXCrossHullStyleIndicator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("smooth_method", ["jjma", "mode_jjma", "ema", "mode_ema"])
def test_ultraxma_default_and_ema_methods_do_not_warn(smooth_method):
    closes = [100.0 + i * 0.2 + math.sin(i * 0.3) * 3.0 for i in range(120)]
    frame = _ohlcv_frame(closes)

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = UltraXMAIndicator(
                self.data, smooth_method=smooth_method, smooth_length=3, smooth_phase=100
            )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        results = []
        for runonce in (False, True):
            c = bt.Cerebro(stdstats=False)
            c.adddata(bt.feeds.PandasData(dataname=frame))
            c.addstrategy(Probe)
            strat = c.run(runonce=runonce, preload=True)[0]
            results.append(
                (list(strat.ind.bulls.array), list(strat.ind.bears.array))
            )

    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert not user_warnings
    _assert_series_close(results[0][0], results[1][0])
    _assert_series_close(results[0][1], results[1][1])


@pytest.mark.parametrize("smooth_method", ["sma", "smma", "wma", "hma", "invalid_algo"])
def test_ultraxma_unsupported_smooth_method_warns_explicitly(smooth_method):
    closes = [100.0 + i * 0.2 + math.sin(i * 0.3) * 3.0 for i in range(90)]
    frame = _ohlcv_frame(closes)

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = UltraXMAIndicator(
                self.data, smooth_method=smooth_method, smooth_length=4, smooth_phase=100
            )

    with pytest.warns(UserWarning, match="smooth_method"):
        c = bt.Cerebro(stdstats=False)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        c.run(runonce=True, preload=True)


@pytest.mark.parametrize("smooth_phase", [0, 50, -100])
def test_ultraxma_non_default_smooth_phase_warns_explicitly(smooth_phase):
    closes = [100.0 + i * 0.2 + math.sin(i * 0.3) * 3.0 for i in range(90)]
    frame = _ohlcv_frame(closes)

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = UltraXMAIndicator(
                self.data, smooth_method="ema", smooth_length=4, smooth_phase=smooth_phase
            )

    with pytest.warns(UserWarning, match="smooth_phase"):
        c = bt.Cerebro(stdstats=False)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        c.run(runonce=True, preload=True)


def test_adx_cross_hull_style_indicator_parity_and_nan():
    closes = [100.0 + math.sin(i * 0.21) * 5.0 + i * 0.05 for i in range(150)]
    frame = _ohlcv_frame(closes)

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ADXCrossHullStyleIndicator(self.data, adx_period=14)

    runs = []
    for runonce in (False, True):
        c = bt.Cerebro(stdstats=False)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        strat = c.run(runonce=runonce, preload=True)[0]
        runs.append((list(strat.ind.up.array), list(strat.ind.down.array)))

    _assert_series_close(runs[0][0], runs[1][0])
    _assert_series_close(runs[0][1], runs[1][1])
    assert any(v > 0.0 for v in runs[0][0] if math.isfinite(v))
    assert any(v > 0.0 for v in runs[0][1] if math.isfinite(v))


# ---------------------------------------------------------------------------
# R71-112b: XCCIHistogramVolDirectIndicator missing OHLC/volume color NaN
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("runonce", [False, True], ids=["runnext", "runonce"])
@pytest.mark.parametrize("missing_field", ["high", "low", "close", "volume"])
def test_xcci_vol_direct_missing_inputs_emit_nan_color_and_no_fake_flip(
    runonce, missing_field
):
    closes = [100.0 + i * 0.5 + math.sin(i * 0.4) * 2.0 for i in range(45)]
    frame = _ohlcv_frame(closes, volume=10.0)
    gap_idx = 20
    frame.loc[frame.index[gap_idx], missing_field] = float("nan")

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = XCCIHistogramVolDirectIndicator(
                self.data, cci_period=4, ma_length=3
            )
            self.rows = []

        def next(self):
            prev_c = float(self.ind.color_state[-1])
            curr_c = float(self.ind.color_state[0])
            sell_flip = prev_c == 0.0 and curr_c == 1.0
            buy_flip = prev_c == 1.0 and curr_c == 0.0
            self.rows.append(
                (
                    len(self.data),
                    float(self.ind.value[0]),
                    curr_c,
                    sell_flip,
                    buy_flip,
                )
            )

    c = bt.Cerebro(stdstats=False)
    c.adddata(bt.feeds.PandasData(dataname=frame))
    c.addstrategy(Probe)
    strat = c.run(runonce=runonce, preload=True)[0]

    gap_bar_len = gap_idx + 1
    # Every bar with non-finite value must have NaN color_state (never 1.0).
    invalid_rows = [row for row in strat.rows if not math.isfinite(row[1])]
    assert invalid_rows
    assert all(math.isnan(row[2]) for row in invalid_rows)
    # Neither the missing bars nor the first post-gap recovery bar may trigger
    # a spurious 0->1 sell or 1->0 buy flip.
    first_recovery_len = max(row[0] for row in invalid_rows) + 1
    for row in strat.rows:
        if gap_bar_len <= row[0] <= first_recovery_len:
            assert math.isnan(row[2]), row
            assert not row[3] and not row[4], row
    # Subsequent clean bars recover to finite value and finite binary color.
    assert math.isfinite(strat.rows[-1][1])
    assert strat.rows[-1][2] in (0.0, 1.0)


def test_xcci_vol_direct_clean_parity_and_exactbars():
    closes = [100.0 + math.sin(i * 0.25) * 4.0 + i * 0.1 for i in range(60)]
    frame = _ohlcv_frame(closes, volume=[10.0 + (i % 5) for i in range(60)])

    def _run(runonce, exactbars=0):
        class Probe(bt.Strategy):
            def __init__(self):
                self.ind = XCCIHistogramVolDirectIndicator(
                    self.data, cci_period=6, ma_length=4
                )
                self.rows = []

            def next(self):
                self.rows.append(
                    (float(self.ind.value[0]), float(self.ind.color_state[0]))
                )

        c = bt.Cerebro(
            runonce=runonce, preload=not exactbars, exactbars=exactbars, stdstats=False
        )
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        return c.run()[0].rows

    r_next = _run(False, 0)
    r_once = _run(True, 0)
    r_eb = _run(False, 1)
    assert r_next == r_once == r_eb
    assert all(math.isfinite(v) and col in (0.0, 1.0) for v, col in r_next)


# ---------------------------------------------------------------------------
# R71-112b: ColorXDerivative minperiod fix & VininITrendIndicator once parity
# ---------------------------------------------------------------------------


def test_color_x_derivative_minperiod_no_index_error_and_parity():
    closes = [100.0 + i * 0.12 + math.sin(i * 0.19) * 3.0 for i in range(120)]
    frame = _ohlcv_frame(closes)

    class Probe(bt.Strategy):
        def __init__(self):
            self.ind = ColorXDerivative(self.data, i_slowing=34, xlength=15)

    runs = []
    for runonce in (False, True):
        c = bt.Cerebro(stdstats=False)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        strat = c.run(runonce=runonce, preload=True)[0]
        assert strat.ind._minperiod == 49
        runs.append((list(strat.ind.value.array), list(strat.ind.color_idx.array)))

    _assert_series_close(runs[0][0], runs[1][0])
    _assert_series_close(runs[0][1], runs[1][1])
    assert all(math.isnan(v) for v in runs[0][0][:48])
    assert all(math.isfinite(v) for v in runs[0][0][48:])

    # Independent formula check for value line from bar 48 onward
    prices = [
        (float(frame["high"].iloc[i]) + float(frame["low"].iloc[i]) + 2.0 * float(frame["close"].iloc[i]))
        / 4.0
        for i in range(len(frame))
    ]
    for bar in range(48, len(frame)):
        window = [
            100.0 * (prices[bar - k] - prices[bar - (k + 34)]) / 34.0
            for k in range(15)
        ]
        expected_val = sum(window) / 15.0
        assert runs[0][0][bar] == pytest.approx(expected_val, rel=1e-12, abs=1e-12)

    # Short history (< 49 bars) must not raise IndexError
    short_frame = frame.iloc[:40]
    for runonce in (False, True):
        c = bt.Cerebro(stdstats=False)
        c.adddata(bt.feeds.PandasData(dataname=short_frame))
        c.addstrategy(Probe)
        strat = c.run(runonce=runonce, preload=True)[0]
        assert all(math.isnan(v) for v in strat.ind.value.array)


def test_vinin_i_trend_runonce_segmented_and_runnext_parity():
    closes = [100.0 + i * 0.15 + math.sin(i * 0.23) * 3.5 for i in range(220)]
    frame = _ohlcv_frame(closes)

    class SegmentedVininI(VininITrendIndicator):
        def __init__(self):
            self._ranges = []
            super().__init__()

        def once(self, start, end):
            if end - start <= 1:
                self._ranges.append((start, end))
                return super().once(start, end)
            cursor = start
            while cursor < end:
                seg_end = min(cursor + 11, end)
                self._ranges.append((cursor, seg_end))
                super().once(cursor, seg_end)
                cursor = seg_end

    def _run(runonce, cls=VininITrendIndicator):
        class Probe(bt.Strategy):
            def __init__(self):
                self.ind = cls(self.data)

        c = bt.Cerebro(stdstats=False)
        c.adddata(bt.feeds.PandasData(dataname=frame))
        c.addstrategy(Probe)
        strat = c.run(runonce=runonce, preload=True)[0]
        return strat.ind, list(strat.ind.trend.array)

    _, arr_next = _run(False)
    _, arr_once = _run(True)
    seg_ind, arr_seg = _run(True, SegmentedVininI)

    assert len(seg_ind._ranges) > 5
    _assert_series_close(arr_once, arr_next)
    _assert_series_close(arr_seg, arr_next)
    assert all(math.isfinite(v) for v in arr_once[seg_ind._minperiod - 1 :])
