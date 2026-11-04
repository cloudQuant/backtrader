"""Independent synthetic formula and missing-bar witnesses for Iteration 61."""

import importlib.util
import math
from pathlib import Path
import sys

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import FactorSpec, ResearchSpec, align_to_grid
from backtrader.strategies.factor_strategy import FactorStrategy

_EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "examples/backtest/026_factor_multi/multi_factor_strategy.py"
)
_spec = importlib.util.spec_from_file_location("iter61_multi_factor", _EXAMPLE)
_factors = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _factors
_spec.loader.exec_module(_factors)
_single_path = _EXAMPLE.parent.parent / "025_factor_single/close_ma_factor_strategy.py"
_single_spec = importlib.util.spec_from_file_location("iter61_single_factor", _single_path)
_single = importlib.util.module_from_spec(_single_spec)
sys.modules[_single_spec.name] = _single
_single_spec.loader.exec_module(_single)


def _average(values, end, period):
    start = end - period + 1
    if start < 0:
        return math.nan
    window = values[start : end + 1]
    if not all(math.isfinite(value) for value in window):
        return math.nan
    return sum(window) / period


def _oracle(frame, formula):
    close = frame["close"].tolist()
    size = len(frame)
    output = [math.nan] * size
    if formula == "close_ma":
        for i in range(size):
            avg = _average(close, i, 5)
            if math.isfinite(avg) and avg != 0 and math.isfinite(close[i]):
                output[i] = close[i] / avg
    elif formula == "roc":
        for i in range(5, size):
            if math.isfinite(close[i]) and math.isfinite(close[i - 5]) and close[i - 5] != 0:
                output[i] = (close[i] - close[i - 5]) / close[i - 5]
    else:
        highs, lows = frame["high"].tolist(), frame["low"].tolist()
        rsv, k = [math.nan] * size, [math.nan] * size
        for i in range(size):
            if i >= 4:
                hi_window, lo_window = highs[i - 4 : i + 1], lows[i - 4 : i + 1]
                if all(math.isfinite(v) for v in hi_window + lo_window) and math.isfinite(close[i]):
                    high, low = max(hi_window), min(lo_window)
                    if high > low:
                        rsv[i] = 100.0 * (close[i] - low) / (high - low)
            k[i] = _average(rsv, i, 2)
            d = _average(k, i, 4)
            if math.isfinite(k[i]) and math.isfinite(d):
                output[i] = 3.0 * k[i] - 2.0 * d
    return output


def _check_formula(formula, mode, runonce, *, single=False):
    factor_class, params, lookback = {
        "close_ma": (_factors.CloseMAFactor, {"period": 5}, 4),
        "roc": (_factors.ROCFactor, {"period": 5}, 5),
        "kdj": (_factors.KDJFactor, {"period": 5, "period_dfast": 2, "period_dslow": 4}, 8),
    }[formula]
    if single:
        factor_class = _single.CloseMAFactor
    times = pd.date_range("2020-01-01 16:00", periods=42, freq="B", tz="UTC", name="close_time")
    closes = [0.0] * 5 + [10.0] * 11 + [10.0 + (i % 7) for i in range(26)]
    # A flat price range yields undefined RSV, followed by a varying range.
    high = [0.0] * 5 + [v + 2.0 for v in closes[5:]]
    low = [0.0] * 5 + [v - 2.0 for v in closes[5:]]
    base = pd.DataFrame(
        {
            "open": closes,
            "high": high,
            "low": low,
            "close": closes,
            "volume": [1000.0] * len(times),
        },
        index=times,
    )
    assets = ("asset-A", "asset-B")
    frames = {assets[0]: base.copy(), assets[1]: base.drop(index=times[21])}
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=assets,
        source_timezone="UTC",
        snapshot_id="iter61-synthetic-formula-oracle",
        price_basis="synthetic",
        calendar_id="synthetic-weekday",
        frequency="1session",
        feed_time_kind="close_time",
        groups={assets[0]: "group-A", assets[1]: "group-B"},
    )
    factor = FactorSpec(
        name=formula,
        indicator=factor_class,
        mode=mode,
        panel_line="factor",
        params=params,
        field_bindings={field: "feed:target:" + field for field in factor_class.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    for asset in assets:
        cerebro.adddata(align_to_grid(frames[asset], research, asset).feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={formula: factor})
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    assert all(
        instance.factor_mode == mode for instance in strategy._factor_instances_by_name[formula]
    )
    panel = strategy.get_panel()
    assert tuple(panel.target_order) == assets
    assert tuple(panel.factors.columns) == (formula,)
    assert tuple(panel.factors.index.get_level_values("asset")) == assets * len(times)
    assert tuple(panel.factors.index.get_level_values("time")) == tuple(
        t for t in times for _ in assets
    )
    for asset in assets:
        frame = frames[asset].reindex(times)
        expected = _oracle(frame, formula)
        # The panel invalidates the missing bar and the following lookback_h points.
        for i in range(len(times)):
            start = max(0, i - lookback)
            if any(
                not math.isfinite(float(v))
                for field in factor_class.formula_fields
                for v in frame[field].iloc[start : i + 1]
            ):
                expected[i] = math.nan
        actual = panel.factors.xs(asset, level="asset")[formula].tolist()
        assert len(actual) == len(expected)
        assert any(math.isfinite(v) for v in expected)
        for i, (observed, wanted) in enumerate(zip(actual, expected)):
            assert not math.isinf(observed), (asset, i)
            assert math.isnan(observed) == math.isnan(wanted), (asset, i, observed, wanted)
            if math.isfinite(wanted):
                assert observed == pytest.approx(wanted, rel=1e-12, abs=1e-12), (asset, i)
        if asset == assets[1]:
            assert all(math.isnan(actual[i]) for i in range(21, 22 + lookback))
            assert math.isfinite(actual[22 + lookback])
        if formula == "roc" and asset == assets[0]:
            assert math.isnan(actual[5])  # zero denominator
            assert actual[10] == 0.0  # genuine zero return
        if formula == "close_ma" and asset == assets[0]:
            assert math.isnan(actual[4])  # zero mean


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
def test_close_ma_independent_oracle(mode, runonce):
    _check_formula("close_ma", mode, runonce)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
def test_single_close_ma_independent_oracle(mode, runonce):
    _check_formula("close_ma", mode, runonce, single=True)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
def test_roc_independent_oracle(mode, runonce):
    _check_formula("roc", mode, runonce)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("mode", ("native", "build"))
def test_kdj_independent_oracle(mode, runonce):
    _check_formula("kdj", mode, runonce)
