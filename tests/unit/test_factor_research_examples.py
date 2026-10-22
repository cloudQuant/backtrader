"""Independent formula and real-panel checks for the factor examples.

These tests exercise source components only. Copy/install entrypoints and the
full research evaluations remain separate acceptance work.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
SINGLE_RUNNER = ROOT / "examples" / "backtest" / "025_factor_single" / "run.py"
SINGLE_STRATEGY = (
    ROOT / "examples" / "backtest" / "025_factor_single" / "close_ma_factor_strategy.py"
)
MULTI_RUNNER = ROOT / "examples" / "backtest" / "026_factor_multi" / "run.py"
MULTI_STRATEGY = ROOT / "examples" / "backtest" / "026_factor_multi" / "multi_factor_strategy.py"
THIRD_RUNNER = ROOT / "examples" / "backtest" / "027_alpha003_panel_acceptance" / "run.py"


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load example source %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _write_daily_panel(
    root: Path, *, symbol_count: int = 3, day_count: int = 30
) -> Tuple[List[str], List[str]]:
    """Write a tiny panel in the real a_stocks manifest/calendar/CSV layout."""
    metadata = root / "_metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range("2025-01-02", periods=day_count).strftime("%Y-%m-%d").tolist()
    symbols = ["sh%06d" % (600000 + index) for index in range(symbol_count)]
    missing_day = day_count // 2
    calendar_rows = []
    for day_index, stamp in enumerate(dates):
        rows_today = symbol_count - int(symbol_count > 1 and day_index == missing_day)
        calendar_rows.append(
            {
                "trade_date": stamp,
                "first_trade_time": stamp + " 09:30:00.000",
                "last_trade_time": stamp + " 15:00:00.000",
                "symbol_count": rows_today,
                "minute_count": rows_today * 240,
            }
        )
    pd.DataFrame(calendar_rows).to_csv(metadata / "observed_calendar.csv", index=False)

    entries = []
    for symbol_index, symbol in enumerate(symbols):
        rows = []
        for day_index, stamp in enumerate(dates):
            if symbol_index == 1 and day_index == missing_day:
                continue
            open_value = (
                10.0
                + ((day_index * (symbol_index + 2) + symbol_index) % 7) * 0.3
                + symbol_index * 0.01
            )
            close_value = open_value + (day_index % 3 - 1) * 0.05
            rows.append(
                {
                    "trade_date": stamp,
                    "trade_time": stamp + " 15:00:00.000",
                    "symbol": symbol,
                    "open": open_value,
                    "high": max(open_value, close_value) + 0.1,
                    "low": min(open_value, close_value) - 0.1,
                    "close": close_value,
                    "volume": 1000.0
                    + ((day_index * (symbol_index + 3) + symbol_index) % 11) * 10.0,
                    "amount": (
                        1000.0 + ((day_index * (symbol_index + 3) + symbol_index) % 11) * 10.0
                    )
                    * close_value,
                    "minute_count": 240,
                    "first_trade_time": stamp + " 09:30:00.000",
                    "last_trade_time": stamp + " 15:00:00.000",
                    "missing_or_invalid_count": 0,
                    "invalid_day": False,
                }
            )
        path = root / (symbol + ".csv")
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
        entries.append(
            {
                "symbol": symbol,
                "file": path.name,
                "rows": len(rows),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "first_trade_date": dates[0],
                "last_trade_date": dates[-1],
                "invalid_daily_rows": 0,
            }
        )
    manifest = {"status": "complete", "output": {"symbols": entries}}
    (metadata / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return symbols, dates


def test_single_and_multi_examples_load_the_same_real_panel(tmp_path: Path):
    root = tmp_path / "a_stocks"
    symbols, _ = _write_daily_panel(root, symbol_count=4, day_count=30)
    panels = []
    for runner_path, module_name in (
        (SINGLE_RUNNER, "iteration45_single_real_panel"),
        (MULTI_RUNNER, "iteration45_multi_real_panel"),
    ):
        runner = _load_module(runner_path, module_name)
        data_config = dict(runner._load_config()["data"])
        data_config["directory"] = str(root)
        data_config["max_symbols"] = 3
        panel = runner.load_daily_panel(data_config)
        assert len(panel["grid"]) == 30
        assert panel["assets"] == tuple(symbols[:3])
        assert panel["research_start_position"] == 0
        assert panel["research_end_position"] == 29
        assert str(panel["grid"].index.tz) == "UTC"
        assert len(panel["feeds"][symbols[1]]) == 29
        panels.append(panel)
    for asset in panels[0]["assets"]:
        pd.testing.assert_frame_equal(panels[0]["feeds"][asset], panels[1]["feeds"][asset])


@pytest.mark.parametrize(
    ("runner_path", "module_name", "factor_names"),
    (
        (SINGLE_RUNNER, "iteration45_single_report_label", ("close_ma",)),
        (
            MULTI_RUNNER,
            "iteration45_multi_report_label",
            ("close_ma", "kdj_j", "roc"),
        ),
    ),
)
@pytest.mark.parametrize("label", ("next_open_to_open", "close_to_close"))
def test_factor_example_reports_follow_the_evaluation_label(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner_path: Path,
    module_name: str,
    factor_names: Tuple[str, ...],
    label: str,
):
    from backtrader.errors import DependencyError
    import backtrader.research as research

    runner = _load_module(runner_path, module_name)
    config = runner._load_config()
    assert config["evaluation"]["label"] == "next_open_to_open"
    config["evaluation"]["label"] = label
    monkeypatch.setattr(runner, "_load_config", lambda: config)

    dates = pd.date_range("2025-01-02", periods=3, freq="B", tz="UTC", name="time")
    assets = ("ASSET_A", "ASSET_B")
    index = pd.MultiIndex.from_product([dates, assets], names=("time", "asset"))
    factors = pd.DataFrame(
        {name: range(len(index)) for name in factor_names},
        index=index,
    )
    panel = SimpleNamespace(
        factors=factors,
        target_order=assets,
        grid=pd.DataFrame(index=dates),
    )
    broker = SimpleNamespace(submit_count=0, cancel_count=0)
    monkeypatch.setattr(runner, "load_daily_panel", lambda data_config: {})
    monkeypatch.setattr(
        runner,
        "_run_native_collection",
        lambda run_config, data, runnext: (None, panel, broker),
    )
    monkeypatch.setattr(runner, "_evaluation_spec", lambda run_config, result_panel, periods: None)
    report_calls = []

    def capture_report(_panel, factor_name, target, **kwargs):
        report_calls.append((factor_name, kwargs["label"]))
        return Path(target)

    def unavailable(*args, **kwargs):
        raise DependencyError("synthetic unavailable evaluation")

    monkeypatch.setattr(research, "write_factor_report", capture_report)
    monkeypatch.setattr(research, "evaluate_frames", unavailable)

    result = runner.main(["--output-dir", str(tmp_path / (module_name + "-" + label)), "--report"])

    assert result == 0
    assert report_calls == [(name, label) for name in factor_names]


@pytest.mark.parametrize(
    ("runner_path", "module_name", "factor_names"),
    (
        (SINGLE_RUNNER, "iteration45_single_broker_guard_source", ("close_ma",)),
        (
            MULTI_RUNNER,
            "iteration45_multi_broker_guard_source",
            ("close_ma", "kdj_j", "roc"),
        ),
    ),
)
@pytest.mark.parametrize("runnext", (False, True))
def test_native_example_collection_observes_zero_broker_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner_path: Path,
    module_name: str,
    factor_names: Tuple[str, ...],
    runnext: bool,
):
    root = tmp_path / "a_stocks"
    _write_daily_panel(root, symbol_count=3, day_count=30)
    runner = _load_module(runner_path, module_name)
    monkeypatch.syspath_prepend(str(runner_path.parent))
    config = runner._load_config()
    config["data"] = dict(config["data"])
    config["data"]["directory"] = str(root)
    config["data"]["max_symbols"] = 3
    panel = runner.load_daily_panel(config["data"])

    strategy, dataset, broker = runner._run_native_collection(config, panel, runnext)

    assert tuple(strategy.factor_instances) == factor_names
    assert len(dataset.grid) == 30
    assert len(dataset.factors) == 30 * len(panel["assets"])
    assert broker.submit_count == 0
    assert broker.cancel_count == 0


def test_026_multi_example_preserves_legacy_factor_order():
    runner = _load_module(MULTI_RUNNER, "iteration45_multi_factor_order_contract")

    assert tuple(runner._load_config()["factors"]) == ("close_ma", "kdj_j", "roc")


def test_alpha003_real_runner_exports_factor_values(tmp_path: Path):
    root = tmp_path / "a_stocks"
    symbols, dates = _write_daily_panel(root, symbol_count=3, day_count=30)
    runner = _load_module(THIRD_RUNNER, "iteration46_alpha003_real_source")
    output = tmp_path / "output"
    assert (
        runner.main(
            [
                "--data-dir",
                str(root),
                "--max-symbols",
                "3",
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    values = pd.read_csv(output / "factor_values.csv")
    assert set(values.columns) == {"time", "asset", "alpha003"}
    assert len(values) == len(dates) * len(symbols)
    for _, group in values.groupby("asset", sort=False):
        assert group["alpha003"].iloc[:9].isna().all()
        assert group["alpha003"].iloc[9:].notna().any()
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "COMPLETED"
    assert summary["symbols"] == len(symbols)
    assert summary["dates"] == len(dates)
    assert "Alpha003Native" in summary["indicator"]


def _weekday_session_times(count: int) -> Tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    day = date(2025, 3, 3)
    opens = []
    closes = []
    while len(closes) < count:
        if day.weekday() < 5:
            opens.append(datetime.combine(day, time(9, 30), tzinfo=timezone.utc))
            closes.append(datetime.combine(day, time(16, 0), tzinfo=timezone.utc))
        day += timedelta(days=1)
    return pd.DatetimeIndex(opens), pd.DatetimeIndex(closes, name="close_time")


def _known_kdj_bars(count: int = 25) -> pd.DataFrame:
    if count < 16:
        raise ValueError("KDJ fixture requires at least 16 bars")
    rows = [(100.0, 100.0, 100.0, 100.0, 1.0)] * 15
    rows.extend(
        (100.0 + value, 101.0 + value, 99.0 + value, 100.0 + value, 1.0)
        for value in range(1, count - 14)
    )
    _, close_times = _weekday_session_times(len(rows))
    return pd.DataFrame(
        rows,
        index=close_times,
        columns=("open", "high", "low", "close", "volume"),
        dtype="float64",
    )


def _known_close_bars(count: int = 37) -> pd.DataFrame:
    rows = []
    for index in range(count):
        open_value = 80.0 + 0.7 * index
        close_value = open_value + (index % 5 - 2.0) * 0.13
        rows.append(
            (
                open_value,
                max(open_value, close_value) + 0.8,
                min(open_value, close_value) - 0.6,
                close_value,
                1000.0 + index,
            )
        )
    _, close_times = _weekday_session_times(count)
    return pd.DataFrame(
        rows,
        index=close_times,
        columns=("open", "high", "low", "close", "volume"),
        dtype="float64",
    )


def _independent_close_ma_oracle(frame: pd.DataFrame, period: int) -> List[float]:
    closes = frame["close"].tolist()
    values = [math.nan] * len(closes)
    for index in range(period - 1, len(closes)):
        window = closes[index - period + 1 : index + 1]
        average = sum(window) / period
        if math.isfinite(average) and average != 0.0:
            values[index] = closes[index] / average
    return values


def _independent_roc_oracle(frame: pd.DataFrame, period: int) -> List[float]:
    closes = frame["close"].tolist()
    values = [math.nan] * len(closes)
    for index in range(period, len(closes)):
        current = closes[index]
        previous = closes[index - period]
        if math.isfinite(current) and math.isfinite(previous) and previous != 0.0:
            candidate = (current - previous) / previous
            if math.isfinite(candidate):
                values[index] = candidate
    return values


def _run_factor_strategy(
    frame: pd.DataFrame,
    *,
    factor_name: str,
    factor_class: Any,
    params: Dict[str, int],
    runonce: bool,
    strict: bool = True,
):
    import backtrader as bt
    from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec
    from backtrader.research import align_to_grid

    open_times, close_times = _weekday_session_times(len(frame))
    grid = pd.DataFrame({"open_time": open_times}, index=close_times)
    asset = "FACTOR00"
    research = ResearchSpec(
        grid=grid,
        start=close_times[0],
        end=close_times[-1],
        targets=(asset,),
        source_timezone="UTC",
        snapshot_id="iteration45-test-factor-known-answer-v1",
        price_basis="synthetic unadjusted known-answer fixture units",
        calendar_id="synthetic-weekday-v1",
        frequency="1session",
        feed_time_kind="close_time",
        groups={asset: "synthetic-factor-test"},
    )
    factor = FactorSpec(
        name=factor_name,
        indicator=factor_class,
        panel_line="factor",
        params=params,
        field_bindings={field: "feed:target:%s" % field for field in factor_class.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    feed = align_to_grid(
        frame, research, asset, data_version="iteration45-test-factor-known-answer-bars-v1"
    ).feed
    cerebro.adddata(feed, name=asset)
    if strict:
        cerebro.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    else:

        class NonStrictFactorStrategy(bt.Strategy):
            def __init__(self):
                instance = factor_class._bind_for_research(
                    *self.datas,
                    output_datas=self.datas,
                    asset_names=(asset,),
                    factor_name=factor_name,
                    field_bindings=factor.field_bindings,
                    research=research,
                    available_datas=self.datas,
                    strict=False,
                    **params,
                )
                self.factor_instances = {factor_name: instance}

        cerebro.addstrategy(NonStrictFactorStrategy)
    strategy = cerebro.run(runonce=runonce, preload=True)[0]

    return strategy, asset


def _run_panel_factor_strategy(
    frames: Dict[str, pd.DataFrame],
    *,
    grid: pd.DatetimeIndex,
    factor_name: str,
    factor_class: Any,
    params: Dict[str, int],
    runonce: bool,
    asset_order: Tuple[str, ...],
    groups: Optional[Dict[str, str]] = None,
):
    import backtrader as bt
    from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec
    from backtrader.research import align_to_grid

    grid = pd.DatetimeIndex(grid, name="close_time")
    research_grid = pd.DataFrame(
        {"open_time": grid - pd.Timedelta(hours=6)},
        index=grid,
    )
    research = ResearchSpec(
        grid=research_grid,
        start=grid[0],
        end=grid[-1],
        targets=asset_order,
        source_timezone="UTC",
        snapshot_id="iteration47-panel-factor-math-v1",
        price_basis="synthetic unadjusted oracle fixtures",
        calendar_id="synthetic-weekday-v1",
        frequency="1session",
        feed_time_kind="close_time",
        groups=groups or dict.fromkeys(asset_order, "market"),
    )
    factor = FactorSpec(
        name=factor_name,
        indicator=factor_class,
        panel_line="factor",
        params=params,
        field_bindings={field: "feed:target:%s" % field for field in factor_class.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    for asset in asset_order:
        feed = align_to_grid(frames[asset], research, asset).feed
        cerebro.adddata(feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor_name: factor})
    return cerebro.run(runonce=runonce, preload=True)[0]


def _panel_factor_by_asset(strategy: Any, factor_name: str) -> Dict[str, List[float]]:
    panel = strategy.get_panel()
    return {
        asset: [
            float(value) for value in panel.factors.xs(asset, level="asset")[factor_name].to_list()
        ]
        for asset in panel.target_order
    }


def _run_native_factor(
    frame: pd.DataFrame,
    *,
    factor_name: str,
    factor_class: Any,
    params: Dict[str, int],
    runonce: bool,
) -> List[float]:
    strategy, asset = _run_factor_strategy(
        frame,
        factor_name=factor_name,
        factor_class=factor_class,
        params=params,
        runonce=runonce,
    )
    line = strategy.factor_instances[factor_name].outputs[strategy.datas[0]].factor
    return [float(value) for value in line.get(size=len(frame))]


def _factor_values(strategy: Any, factor_name: str, size: int) -> List[float]:
    factor = strategy.factor_instances[factor_name]
    line = factor.outputs[strategy.datas[0]].factor
    return [float(value) for value in line.get(size=size)]


def _assert_exact_pair_and_oracle(
    native: List[float], built: List[float], expected: List[float], *, first_finite: int
) -> None:
    assert len(native) == len(built) == len(expected)
    assert any(math.isfinite(value) for value in native)
    assert any(math.isfinite(value) for value in built)
    assert next(index for index, value in enumerate(native) if math.isfinite(value)) == first_finite
    assert next(index for index, value in enumerate(built) if math.isfinite(value)) == first_finite
    for index, (native_value, build_value, oracle_value) in enumerate(zip(native, built, expected)):
        assert not math.isinf(native_value), index
        assert not math.isinf(build_value), index
        assert not math.isinf(oracle_value), index
        assert math.isnan(native_value) == math.isnan(build_value), index
        if math.isfinite(native_value):
            assert build_value == native_value, index
            assert math.isclose(native_value, oracle_value, rel_tol=1e-12, abs_tol=1e-12), index
        else:
            assert math.isnan(oracle_value), index


def _assert_exact_line_pair(native: List[float], built: List[float]) -> None:
    """Compare complete child lines without hiding mask or infinity changes."""
    assert len(native) == len(built)
    for index, (native_value, build_value) in enumerate(zip(native, built)):
        assert not math.isinf(native_value), index
        assert not math.isinf(build_value), index
        assert math.isnan(native_value) == math.isnan(build_value), index
        if math.isfinite(native_value):
            assert build_value == native_value, index


@pytest.mark.parametrize("runonce", (True, False))
def test_025_native_close_ma_matches_independent_full_window_oracle(runonce: bool):
    frame = _known_close_bars()
    factor_module = _load_module(SINGLE_STRATEGY, "iteration45_single_strategy_source")
    expected = _independent_close_ma_oracle(frame, period=20)
    actual = _run_native_factor(
        frame,
        factor_name="close_ma",
        factor_class=factor_module.CloseMAFactor,
        params={"period": 20},
        runonce=runonce,
    )

    assert len(actual) == len(expected)
    assert math.isnan(expected[18])
    assert math.isfinite(expected[19])
    for observed, oracle in zip(actual, expected):
        assert not math.isinf(observed)
        assert not math.isinf(oracle)
        assert math.isnan(observed) == math.isnan(oracle)
        if math.isfinite(oracle):
            assert math.isclose(observed, oracle, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
@pytest.mark.parametrize("period", (20, 5), ids=("default", "short-window"))
def test_025_close_ma_build_matches_native_and_independent_oracle(runonce: bool, period: int):
    from backtrader.indicators import SMA

    frame = _known_close_bars(count=45)
    # A zero first value creates a genuine zero ROC denominator, while a
    # separate NaN exercises SMA invalidation at different rolling windows.
    frame.loc[frame.index[0], "close"] = 0.0
    frame.loc[frame.index[12], "close"] = math.nan
    factor_module = _load_module(SINGLE_STRATEGY, "iteration47_single_build_math")
    params = {"period": period}
    native_strategy, _ = _run_factor_strategy(
        frame,
        factor_name="close_ma",
        factor_class=factor_module.CloseMAFactor,
        params=params,
        runonce=runonce,
    )
    build_strategy, _ = _run_factor_strategy(
        frame,
        factor_name="close_ma",
        factor_class=factor_module.CloseMAFactorBuild,
        params=params,
        runonce=runonce,
    )
    native = _factor_values(native_strategy, "close_ma", len(frame))
    built = _factor_values(build_strategy, "close_ma", len(frame))
    expected = _independent_close_ma_oracle(frame, period)
    first_finite = next(index for index, value in enumerate(expected) if math.isfinite(value))

    assert build_strategy.factor_instances["close_ma"]._minperiod == period
    _assert_exact_pair_and_oracle(native, built, expected, first_finite=first_finite)
    native_factor = native_strategy.factor_instances["close_ma"]
    build_factor = build_strategy.factor_instances["close_ma"]
    native_data = native_strategy.datas[0]
    build_sma = [node for node in build_factor._nodes.values() if isinstance(node, SMA)]
    assert len(build_sma) == 1
    _assert_exact_line_pair(
        [
            float(value)
            for value in native_factor._averages[native_data].lines.sma.get(size=len(frame))
        ],
        [float(value) for value in build_sma[0].lines.sma.get(size=len(frame))],
    )


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
def test_025_close_ma_zero_average_window_is_missing_then_recovers(runonce: bool):
    frame = _known_close_bars(count=14)
    frame.loc[:, "close"] = (
        0.0,
        0.0,
        0.0,
        9.0,
        12.0,
        13.0,
        11.0,
        15.0,
        14.0,
        16.0,
        17.0,
        18.0,
        19.0,
        20.0,
    )
    factor_module = _load_module(SINGLE_STRATEGY, "iteration47_single_zero_average")
    expected = _independent_close_ma_oracle(frame, period=3)
    values = {}
    for name, factor_class in (
        ("native", factor_module.CloseMAFactor),
        ("build", factor_module.CloseMAFactorBuild),
    ):
        strategy, _ = _run_factor_strategy(
            frame,
            factor_name="close_ma",
            factor_class=factor_class,
            params={"period": 3},
            runonce=runonce,
        )
        values[name] = _factor_values(strategy, "close_ma", len(frame))

    assert math.isnan(expected[2])  # the complete three-bar SMA window is exactly zero
    assert math.isnan(values["native"][2]) and math.isnan(values["build"][2])
    assert math.isfinite(expected[3]) and math.isfinite(values["native"][3])
    _assert_exact_pair_and_oracle(
        values["native"],
        values["build"],
        expected,
        first_finite=next(i for i, value in enumerate(expected) if math.isfinite(value)),
    )


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
@pytest.mark.parametrize(
    "factor_name", ("close_ma", "roc", "kdj_j"), ids=("close-ma", "roc", "kdj")
)
def test_factor_build_multitarget_handles_missing_bars_reordering_and_group_isolation(
    runonce: bool, factor_name: str
):
    from backtrader.research.factor_strategy import _FactorGroupInstances

    if factor_name == "kdj_j":
        base = _known_kdj_bars(count=42)
        formula_fields = ("open", "high", "low", "close")
        params = {"period": 5, "period_dfast": 2, "period_dslow": 4}
        expected_for = lambda frame: _independent_kdj_oracle(
            frame, period=5, period_dfast=2, period_dslow=4
        )["j"]
        factor_module = _load_module(MULTI_STRATEGY, "iteration47_multitarget_kdj")
        native_class, build_class = factor_module.KDJFactor, factor_module.KDJFactorBuild
    else:
        base = _known_close_bars(count=42)
        formula_fields = ("open", "high", "low", "close")
        if factor_name == "close_ma":
            params = {"period": 5}
            expected_for = lambda frame: _independent_close_ma_oracle(frame, 5)
            factor_module = _load_module(SINGLE_STRATEGY, "iteration47_single_multitarget")
            native_class, build_class = (
                factor_module.CloseMAFactor,
                factor_module.CloseMAFactorBuild,
            )
        else:
            params = {"period": 5}
            expected_for = lambda frame: _independent_roc_oracle(frame, 5)
            factor_module = _load_module(MULTI_STRATEGY, "iteration47_multitarget_roc")
            native_class, build_class = factor_module.ROCFactor, factor_module.ROCFactorBuild
    grid = pd.DatetimeIndex(base.index, name="close_time")
    assets = ("asset-A", "asset-B", "asset-C")
    frames = {asset: base.copy(deep=True) for asset in assets}
    for field in formula_fields:
        frames["asset-B"].loc[:, field] *= 1.2
    frames["asset-B"] = frames["asset-B"].drop(index=grid[14])
    for field in formula_fields:
        frames["asset-C"].loc[:, field] *= 0.75

    native = _run_panel_factor_strategy(
        frames,
        grid=grid,
        factor_name=factor_name,
        factor_class=native_class,
        params=params,
        runonce=runonce,
        asset_order=assets,
    )
    built = _run_panel_factor_strategy(
        frames,
        grid=grid,
        factor_name=factor_name,
        factor_class=build_class,
        params=params,
        runonce=runonce,
        asset_order=assets,
    )
    reordered = _run_panel_factor_strategy(
        frames,
        grid=grid,
        factor_name=factor_name,
        factor_class=build_class,
        params=params,
        runonce=runonce,
        asset_order=tuple(reversed(assets)),
    )
    grouped = _run_panel_factor_strategy(
        frames,
        grid=grid,
        factor_name=factor_name,
        factor_class=build_class,
        params=params,
        runonce=runonce,
        asset_order=assets,
        groups={asset: "group-%s" % asset for asset in assets},
    )
    native_values = _panel_factor_by_asset(native, factor_name)
    build_values = _panel_factor_by_asset(built, factor_name)
    reordered_values = _panel_factor_by_asset(reordered, factor_name)
    grouped_values = _panel_factor_by_asset(grouped, factor_name)

    assert tuple(native.get_panel().target_order) == assets
    assert tuple(reordered.get_panel().target_order) == tuple(reversed(assets))
    lookback_h = native_class.lookback_h(**params)
    for asset in assets:
        aligned_frame = frames[asset].reindex(grid)
        expected = expected_for(aligned_frame)
        # The panel contract nulls the point containing a missing input and
        # the next H points, even when a pointwise formula's own operands are
        # already finite again.
        fields = tuple(native_class.formula_fields)
        for index in range(len(aligned_frame)):
            first = max(0, index - lookback_h)
            window = aligned_frame.iloc[first : index + 1]
            if not all(math.isfinite(float(value)) for field in fields for value in window[field]):
                expected[index] = math.nan
        first_finite = next(i for i, value in enumerate(expected) if math.isfinite(value))
        _assert_exact_pair_and_oracle(
            native_values[asset],
            build_values[asset],
            expected,
            first_finite=first_finite,
        )
        assert len(build_values[asset]) == len(reordered_values[asset]) == len(grid)
        for left, right, split in zip(
            build_values[asset], reordered_values[asset], grouped_values[asset]
        ):
            assert not math.isinf(left)
            assert not math.isinf(right)
            assert not math.isinf(split)
            assert math.isnan(left) == math.isnan(right) == math.isnan(split)
            if math.isfinite(left):
                assert left == right == split
    missing_index = grid.get_loc(grid[14])
    assert math.isnan(native_values["asset-B"][missing_index])
    assert math.isnan(build_values["asset-B"][missing_index])
    recovery_index = missing_index + lookback_h + 1
    assert math.isfinite(build_values["asset-B"][recovery_index])

    aggregate = grouped.factor_instances[factor_name]
    assert isinstance(aggregate, _FactorGroupInstances)
    instances = tuple(aggregate.group_instances.values())
    node_id_sets = [{id(node) for node in factor._nodes.values()} for factor in instances]
    assert all(node_ids for node_ids in node_id_sets)
    for index, factor in enumerate(instances):
        nodes = tuple(factor._nodes.values())
        assert len({id(node) for node in nodes}) == len(nodes)
        for node in nodes:
            assert node._owner is factor
            registrations = [
                child
                for children in factor._lineiterators.values()
                for child in children
                if child is node
            ]
            assert len(registrations) == 1
        for other in node_id_sets[index + 1 :]:
            assert node_id_sets[index].isdisjoint(other)


@pytest.mark.parametrize("runonce", (True, False))
def test_026_native_close_ma_and_roc_match_independent_oracles(runonce: bool):
    frame = _known_close_bars()
    factor_module = _load_module(MULTI_STRATEGY, "iteration45_multi_strategy_source")
    cases = (
        (
            "close_ma",
            factor_module.CloseMAFactor,
            factor_module.CloseMAFactorBuild,
            {"period": 20},
            _independent_close_ma_oracle(frame, period=20),
            19,
        ),
        (
            "roc",
            factor_module.ROCFactor,
            factor_module.ROCFactorBuild,
            {"period": 20},
            _independent_roc_oracle(frame, period=20),
            20,
        ),
    )
    for factor_name, factor_class, build_class, params, expected, first_finite in cases:
        actual = _run_native_factor(
            frame,
            factor_name=factor_name,
            factor_class=factor_class,
            params=params,
            runonce=runonce,
        )
        built = _run_native_factor(
            frame,
            factor_name=factor_name,
            factor_class=build_class,
            params=params,
            runonce=runonce,
        )
        assert math.isnan(expected[first_finite - 1])
        assert math.isfinite(expected[first_finite])
        _assert_exact_pair_and_oracle(actual, built, expected, first_finite=first_finite)


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
@pytest.mark.parametrize("period", (20, 5), ids=("default", "short-window"))
def test_026_roc_build_matches_native_and_independent_oracle(runonce: bool, period: int):
    from backtrader.indicators import ROC

    frame = _known_close_bars(count=45)
    frame.loc[frame.index[0], "close"] = 0.0
    frame.loc[frame.index[12], "close"] = math.nan
    factor_module = _load_module(MULTI_STRATEGY, "iteration47_multi_roc_math")
    params = {"period": period}
    native_strategy, _ = _run_factor_strategy(
        frame,
        factor_name="roc",
        factor_class=factor_module.ROCFactor,
        params=params,
        runonce=runonce,
    )
    build_strategy, _ = _run_factor_strategy(
        frame,
        factor_name="roc",
        factor_class=factor_module.ROCFactorBuild,
        params=params,
        runonce=runonce,
    )
    native = _factor_values(native_strategy, "roc", len(frame))
    built = _factor_values(build_strategy, "roc", len(frame))
    expected = _independent_roc_oracle(frame, period)
    first_finite = next(index for index, value in enumerate(expected) if math.isfinite(value))

    assert math.isnan(native[period])  # native ROC's 0-denominator zero is masked by the factor
    assert math.isnan(built[period])
    assert build_strategy.factor_instances["roc"]._minperiod == period + 1
    _assert_exact_pair_and_oracle(native, built, expected, first_finite=first_finite)
    native_factor = native_strategy.factor_instances["roc"]
    build_factor = build_strategy.factor_instances["roc"]
    native_data = native_strategy.datas[0]
    build_roc = [node for node in build_factor._nodes.values() if isinstance(node, ROC)]
    assert len(build_roc) == 1
    _assert_exact_line_pair(
        [float(value) for value in native_factor._roc[native_data].lines.roc.get(size=len(frame))],
        [float(value) for value in build_roc[0].lines.roc.get(size=len(frame))],
    )


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
@pytest.mark.parametrize("factor_name", ("close_ma", "roc"), ids=("flat-close-ma", "flat-roc"))
def test_026_flat_close_ma_and_roc_match_native_oracle_and_raw_child_lines(
    runonce: bool, factor_name: str
):
    from backtrader.indicators import ROC, SMA

    frame = _known_close_bars(count=18)
    frame.loc[:, "close"] = (
        10.0,
        10.0,
        10.0,
        10.0,
        12.0,
        12.0,
        12.0,
        15.0,
        14.0,
        16.0,
        17.0,
        18.0,
        19.0,
        20.0,
        21.0,
        22.0,
        23.0,
        24.0,
    )
    factor_module = _load_module(MULTI_STRATEGY, "iteration47_multi_flat_%s" % factor_name)
    if factor_name == "close_ma":
        params = {"period": 3}
        native_class, build_class = factor_module.CloseMAFactor, factor_module.CloseMAFactorBuild
        expected = _independent_close_ma_oracle(frame, period=3)
        child_type = SMA
    else:
        params = {"period": 2}
        native_class, build_class = factor_module.ROCFactor, factor_module.ROCFactorBuild
        expected = _independent_roc_oracle(frame, period=2)
        child_type = ROC

    native_strategy, _ = _run_factor_strategy(
        frame,
        factor_name=factor_name,
        factor_class=native_class,
        params=params,
        runonce=runonce,
    )
    build_strategy, _ = _run_factor_strategy(
        frame,
        factor_name=factor_name,
        factor_class=build_class,
        params=params,
        runonce=runonce,
    )
    native = _factor_values(native_strategy, factor_name, len(frame))
    built = _factor_values(build_strategy, factor_name, len(frame))
    first_finite = next(index for index, value in enumerate(expected) if math.isfinite(value))
    _assert_exact_pair_and_oracle(native, built, expected, first_finite=first_finite)

    if factor_name == "close_ma":
        assert native[2] == built[2] == 1.0
        assert native[3] == built[3] == 1.0
        assert native[4] == built[4] == 12.0 / (10.0 + 10.0 + 12.0) * 3.0
    else:
        assert native[2] == built[2] == 0.0
        assert native[3] == built[3] == 0.0
        assert native[4] == built[4] == 0.2

    native_factor = native_strategy.factor_instances[factor_name]
    build_factor = build_strategy.factor_instances[factor_name]
    native_data = native_strategy.datas[0]
    build_children = [node for node in build_factor._nodes.values() if isinstance(node, child_type)]
    assert len(build_children) == 1
    if factor_name == "close_ma":
        native_child = native_factor._averages[native_data].lines.sma
        build_child = build_children[0].lines.sma
    else:
        native_child = native_factor._roc[native_data].lines.roc
        build_child = build_children[0].lines.roc
    _assert_exact_line_pair(
        [float(value) for value in native_child.get(size=len(frame))],
        [float(value) for value in build_child.get(size=len(frame))],
    )


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
@pytest.mark.parametrize("strict", (True, False), ids=("strict", "non-strict"))
@pytest.mark.parametrize(
    "scenario",
    ("difference-overflow", "division-overflow", "zero-denominator", "nan-input", "normal"),
)
def test_026_roc_native_build_gate_matches_in_both_strict_modes(runonce, strict, scenario):
    from backtrader.errors import FactorComputationError

    frame = _known_close_bars(count=12)
    if scenario == "difference-overflow":
        frame.loc[frame.index[:2], "close"] = (-1.7e308, 1.7e308)
    elif scenario == "division-overflow":
        frame.loc[frame.index[:2], "close"] = (1.0e-309, 1.0)
    elif scenario == "zero-denominator":
        frame.loc[frame.index[:2], "close"] = (0.0, 10.0)
    elif scenario == "nan-input":
        frame.loc[frame.index[3], "close"] = math.nan
    factor_module = _load_module(MULTI_STRATEGY, "iteration47_multi_roc_overflow")
    errors = []
    values = []
    for factor_class in (factor_module.ROCFactor, factor_module.ROCFactorBuild):
        try:
            strategy, _ = _run_factor_strategy(
                frame,
                factor_name="roc",
                factor_class=factor_class,
                params={"period": 1},
                runonce=runonce,
                strict=strict,
            )
        except FactorComputationError as error:
            errors.append(error)
        else:
            errors.append(None)
            values.append(_factor_values(strategy, "roc", len(frame)))

    arithmetic_overflow = scenario in ("difference-overflow", "division-overflow")
    if strict and arithmetic_overflow:
        assert all(error is not None for error in errors)
        assert all(error.factor == "roc" for error in errors)
        assert errors[0].phase == errors[1].phase
        assert all(error.__cause__ is not None for error in errors)
        return

    assert errors == [None, None]
    native, built = values
    _assert_exact_line_pair(native, built)
    assert any(math.isfinite(value) for value in native)
    if not arithmetic_overflow:
        expected = _independent_roc_oracle(frame, period=1)
        _assert_exact_pair_and_oracle(
            native,
            built,
            expected,
            first_finite=next(i for i, value in enumerate(expected) if math.isfinite(value)),
        )


def _independent_kdj_oracle(
    frame: pd.DataFrame, *, period: int = 9, period_dfast: int = 3, period_dslow: int = 3
) -> Dict[str, List[float]]:
    """Compute rolling RSV/SMA K/D/J without using production factor helpers."""
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    closes = frame["close"].tolist()
    highest_values = [math.nan] * len(frame)
    lowest_values = [math.nan] * len(frame)
    rsv = [math.nan] * len(frame)
    k = [math.nan] * len(frame)
    d = [math.nan] * len(frame)
    j = [math.nan] * len(frame)

    for index in range(len(frame)):
        first_rsv = index - period + 1
        if first_rsv >= 0:
            high = max(highs[first_rsv : index + 1])
            low = min(lows[first_rsv : index + 1])
            highest_values[index] = high
            lowest_values[index] = low
            if (
                math.isfinite(high)
                and math.isfinite(low)
                and math.isfinite(closes[index])
                and high > low
            ):
                rsv[index] = 100.0 * (closes[index] - low) / (high - low)

        first_k = index - period_dfast + 1
        if first_k >= 0 and all(math.isfinite(value) for value in rsv[first_k : index + 1]):
            k[index] = sum(rsv[first_k : index + 1]) / period_dfast

        first_d = index - period_dslow + 1
        if first_d >= 0 and all(math.isfinite(value) for value in k[first_d : index + 1]):
            d[index] = sum(k[first_d : index + 1]) / period_dslow

        if math.isfinite(k[index]) and math.isfinite(d[index]):
            j[index] = 3.0 * k[index] - 2.0 * d[index]

    return {
        "highest": highest_values,
        "lowest": lowest_values,
        "rsv": rsv,
        "k": k,
        "d": d,
        "j": j,
    }


def _run_kdj_strategy(
    frame: pd.DataFrame,
    runonce: bool,
    factor_class: Any,
    params: Dict[str, int],
):
    import backtrader as bt
    from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec
    from backtrader.research import align_to_grid

    open_times, close_times = _weekday_session_times(len(frame))
    grid = pd.DataFrame(
        {"open_time": open_times},
        index=close_times,
    )
    asset = "KDJ00"
    research = ResearchSpec(
        grid=grid,
        start=close_times[0],
        end=close_times[-1],
        targets=(asset,),
        source_timezone="UTC",
        snapshot_id="iteration45-test-kdj-known-answer-v1",
        price_basis="synthetic unadjusted USD-like fixture units",
        calendar_id="synthetic-weekday-v1",
        frequency="1session",
        feed_time_kind="close_time",
        groups={asset: "synthetic-kdj-test"},
    )
    factor = FactorSpec(
        name="kdj_j",
        indicator=factor_class,
        panel_line="factor",
        params=params,
        field_bindings={field: "feed:target:%s" % field for field in factor_class.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    feed = align_to_grid(
        frame, research, asset, data_version="iteration45-test-kdj-known-answer-bars-v1"
    ).feed
    cerebro.adddata(feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    strategy = cerebro.run(runonce=runonce, preload=True)[0]

    return strategy, asset


def _run_native_kdj(frame: pd.DataFrame, runonce: bool) -> Dict[str, List[float]]:
    factor_module = _load_module(MULTI_STRATEGY, "iteration45_multi_strategy_source")
    strategy, _ = _run_kdj_strategy(
        frame,
        runonce,
        factor_module.KDJFactor,
        {"period": 9, "period_dfast": 3, "period_dslow": 3},
    )
    indicator = strategy.factor_instances["kdj_j"]
    data = strategy.datas[0]
    return {
        "rsv": [float(value) for value in indicator._rsv[data].rsv.get(size=len(frame))],
        "k": [float(value) for value in indicator._k[data].get(size=len(frame))],
        "d": [float(value) for value in indicator._d[data].get(size=len(frame))],
        "j": [float(value) for value in indicator.outputs[data].factor.get(size=len(frame))],
    }


@pytest.mark.parametrize("runonce", (True, False))
def test_native_kdj_lines_match_independent_full_window_oracle(runonce: bool):
    frame = _known_kdj_bars()
    expected = _independent_kdj_oracle(frame)
    actual = _run_native_kdj(frame, runonce=runonce)

    assert math.isnan(expected["rsv"][14])
    assert math.isfinite(expected["rsv"][15])
    assert math.isnan(expected["k"][16])
    assert math.isfinite(expected["k"][17])
    assert math.isnan(expected["d"][18])
    assert math.isfinite(expected["d"][19])
    assert math.isfinite(expected["j"][19])
    for line_name in ("rsv", "k", "d", "j"):
        assert len(actual[line_name]) == len(expected[line_name])
        for observed, oracle in zip(actual[line_name], expected[line_name]):
            assert not math.isinf(observed)
            assert not math.isinf(oracle)
            assert math.isnan(observed) == math.isnan(oracle)
            if math.isfinite(oracle):
                assert math.isclose(observed, oracle, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
@pytest.mark.parametrize(
    "params",
    (
        {"period": 9, "period_dfast": 3, "period_dslow": 3},
        {"period": 5, "period_dfast": 2, "period_dslow": 4},
    ),
    ids=("default", "period-variant"),
)
def test_026_kdj_build_matches_native_oracle_and_all_intermediate_lines(runonce, params):
    from backtrader.indicators import Highest, Lowest, SMA

    frame = _known_kdj_bars(count=40)
    # The base fixture has a long flat range (zero denominator). These NaNs
    # occupy different locations in the high, low and current-close windows.
    frame.loc[frame.index[20], "high"] = math.nan
    frame.loc[frame.index[24], "low"] = math.nan
    frame.loc[frame.index[28], "close"] = math.nan
    factor_module = _load_module(MULTI_STRATEGY, "iteration47_multi_kdj_math")
    native_strategy, _ = _run_kdj_strategy(frame, runonce, factor_module.KDJFactor, params)
    build_strategy, _ = _run_kdj_strategy(frame, runonce, factor_module.KDJFactorBuild, params)
    native_factor = native_strategy.factor_instances["kdj_j"]
    build_factor = build_strategy.factor_instances["kdj_j"]
    native_data = native_strategy.datas[0]

    native_lines = {
        "highest": [
            float(value)
            for value in native_factor._rsv[native_data]._highest.lines.highest.get(size=len(frame))
        ],
        "lowest": [
            float(value)
            for value in native_factor._rsv[native_data]._lowest.lines.lowest.get(size=len(frame))
        ],
        "rsv": [
            float(value) for value in native_factor._rsv[native_data].lines.rsv.get(size=len(frame))
        ],
        "k": [
            float(value) for value in native_factor._k[native_data].lines.sma.get(size=len(frame))
        ],
        "d": [
            float(value) for value in native_factor._d[native_data].lines.sma.get(size=len(frame))
        ],
        "j": _factor_values(native_strategy, "kdj_j", len(frame)),
    }
    build_nodes = tuple(build_factor._nodes.values())
    build_highest = [node for node in build_nodes if isinstance(node, Highest)]
    build_lowest = [node for node in build_nodes if isinstance(node, Lowest)]
    build_sma = [node for node in build_nodes if isinstance(node, SMA)]
    build_rsv = [node for node in build_nodes if node.p.function is factor_module._kdj_rsv]
    build_j = [node for node in build_nodes if node.p.function is factor_module._kdj_j]
    assert (
        len(build_highest),
        len(build_lowest),
        len(build_sma),
        len(build_rsv),
        len(build_j),
    ) == (
        1,
        1,
        2,
        1,
        1,
    )
    build_lines = {
        "highest": [float(value) for value in build_highest[0].lines.highest.get(size=len(frame))],
        "lowest": [float(value) for value in build_lowest[0].lines.lowest.get(size=len(frame))],
        "rsv": [float(value) for value in build_rsv[0].lines.value.get(size=len(frame))],
        "k": [float(value) for value in build_sma[0].lines.sma.get(size=len(frame))],
        "d": [float(value) for value in build_sma[1].lines.sma.get(size=len(frame))],
        "j": [float(value) for value in build_j[0].lines.value.get(size=len(frame))],
    }
    build_output = _factor_values(build_strategy, "kdj_j", len(frame))
    expected = _independent_kdj_oracle(
        frame,
        period=params["period"],
        period_dfast=params["period_dfast"],
        period_dslow=params["period_dslow"],
    )
    assert build_factor._minperiod == sum(params.values()) - 2
    for line_name in ("highest", "lowest", "rsv", "k", "d", "j"):
        first_finite = next(
            index for index, value in enumerate(expected[line_name]) if math.isfinite(value)
        )
        _assert_exact_pair_and_oracle(
            native_lines[line_name],
            build_lines[line_name],
            expected[line_name],
            first_finite=first_finite,
        )
    for output, node_value in zip(build_output, build_lines["j"]):
        assert not math.isinf(output)
        assert not math.isinf(node_value)
        assert math.isnan(output) == math.isnan(node_value)
        if math.isfinite(output):
            assert output == node_value


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
def test_025_close_ma_sma_sum_overflow_matches_strict_native_build_behavior(runonce):
    from backtrader.errors import FactorComputationError

    frame = _known_close_bars(count=12)
    frame.loc[frame.index[:2], "close"] = 1.7e308
    factor_module = _load_module(SINGLE_STRATEGY, "iteration47_single_close_ma_overflow")
    outcomes = []
    for factor_class in (factor_module.CloseMAFactor, factor_module.CloseMAFactorBuild):
        try:
            strategy, _ = _run_factor_strategy(
                frame,
                factor_name="close_ma",
                factor_class=factor_class,
                params={"period": 2},
                runonce=runonce,
            )
        except FactorComputationError as error:
            outcomes.append(error)
        else:
            outcomes.append(_factor_values(strategy, "close_ma", len(frame)))

    native, built = outcomes
    if isinstance(native, FactorComputationError) or isinstance(built, FactorComputationError):
        assert isinstance(native, FactorComputationError)
        assert isinstance(built, FactorComputationError)
        assert (native.factor, native.phase) == (built.factor, built.phase)
        assert native.factor == "close_ma"
    else:
        assert len(native) == len(built) == len(frame)
        for native_value, build_value in zip(native, built):
            assert not math.isinf(native_value)
            assert not math.isinf(build_value)
            assert math.isnan(native_value) == math.isnan(build_value)
            if math.isfinite(native_value):
                assert native_value == build_value
        assert math.isnan(native[1])  # SMA's fsum window overflows on finite inputs.
        assert math.isfinite(native[2])


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
def test_025_close_ma_result_overflow_preserves_native_strict_failure(runonce):
    from backtrader.errors import FactorComputationError

    frame = _known_close_bars(count=8)
    frame.loc[:, "close"] = (-1.7e308, 2e-309, 1.7e308, 80.0, 81.0, 82.0, 83.0, 84.0)
    factor_module = _load_module(SINGLE_STRATEGY, "iteration47_single_close_ratio_overflow")
    errors = []
    for factor_class in (factor_module.CloseMAFactor, factor_module.CloseMAFactorBuild):
        with pytest.raises(FactorComputationError) as raised:
            _run_factor_strategy(
                frame,
                factor_name="close_ma",
                factor_class=factor_class,
                params={"period": 3},
                runonce=runonce,
            )
        errors.append(raised.value)

    assert all(error.factor == "close_ma" for error in errors)
    assert errors[0].phase == errors[1].phase


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
def test_026_kdj_rsv_result_overflow_preserves_native_strict_failure(runonce):
    from backtrader.errors import FactorComputationError

    frame = _known_kdj_bars(count=20)
    frame.loc[frame.index[0], ["high", "low", "close"]] = (1e307, 0.0, 1e307)
    factor_module = _load_module(MULTI_STRATEGY, "iteration47_multi_kdj_rsv_overflow")
    params = {"period": 1, "period_dfast": 1, "period_dslow": 1}
    errors = []
    for factor_class in (factor_module.KDJFactor, factor_module.KDJFactorBuild):
        with pytest.raises(FactorComputationError) as raised:
            _run_kdj_strategy(frame, runonce, factor_class, params)
        errors.append(raised.value)

    assert all(error.factor == "kdj_j" for error in errors)
    assert errors[0].phase == errors[1].phase


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
def test_026_kdj_flat_extreme_rsv_guard_keeps_native_build_finite_values(runonce):
    frame = _known_kdj_bars(count=16)
    frame.loc[frame.index[0], ["high", "low", "close"]] = (1e307, 1e307, 1.7e308)
    for index in range(1, len(frame)):
        frame.loc[frame.index[index], ["high", "low", "close"]] = (
            101.0 + index,
            99.0 + index,
            100.0 + index,
        )
    factor_module = _load_module(MULTI_STRATEGY, "iteration47_multi_kdj_flat_guard")
    params = {"period": 1, "period_dfast": 1, "period_dslow": 1}
    native_strategy, _ = _run_kdj_strategy(frame, runonce, factor_module.KDJFactor, params)
    build_strategy, _ = _run_kdj_strategy(frame, runonce, factor_module.KDJFactorBuild, params)
    native = _factor_values(native_strategy, "kdj_j", len(frame))
    built = _factor_values(build_strategy, "kdj_j", len(frame))

    assert len(native) == len(built) == len(frame)
    assert math.isnan(native[0]) == math.isnan(built[0])
    assert math.isnan(native[0])
    assert math.isfinite(native[1]) and native[1] == built[1]
    for native_value, build_value in zip(native, built):
        assert not math.isinf(native_value)
        assert not math.isinf(build_value)
        assert math.isnan(native_value) == math.isnan(build_value)
        if math.isfinite(native_value):
            assert native_value == build_value


@pytest.mark.parametrize("runonce", (True, False), ids=("runonce", "runnext"))
@pytest.mark.parametrize(
    ("strategy_path", "module_name", "factor_name", "native_name", "build_name", "params"),
    (
        (
            SINGLE_STRATEGY,
            "iteration47_single_causality",
            "close_ma",
            "CloseMAFactor",
            "CloseMAFactorBuild",
            {"period": 5},
        ),
        (
            MULTI_STRATEGY,
            "iteration47_multi_close_ma_causality",
            "close_ma",
            "CloseMAFactor",
            "CloseMAFactorBuild",
            {"period": 5},
        ),
        (
            MULTI_STRATEGY,
            "iteration47_roc_causality",
            "roc",
            "ROCFactor",
            "ROCFactorBuild",
            {"period": 5},
        ),
        (
            MULTI_STRATEGY,
            "iteration47_kdj_causality",
            "kdj_j",
            "KDJFactor",
            "KDJFactorBuild",
            {"period": 5, "period_dfast": 2, "period_dslow": 4},
        ),
    ),
    ids=("close-ma-025", "close-ma-026", "roc", "kdj"),
)
def test_time_series_build_formulas_do_not_look_ahead(
    runonce, strategy_path, module_name, factor_name, native_name, build_name, params
):
    frame = _known_close_bars(count=42)
    cut = 28
    perturbed = frame.copy(deep=True)
    future = perturbed.index[cut:]
    perturbed.loc[future, "close"] += 100.0
    perturbed.loc[future, "high"] += 250.0
    perturbed.loc[future, "low"] -= 125.0
    factor_module = _load_module(strategy_path, module_name)
    results = {}
    for mode, class_name in (("native", native_name), ("build", build_name)):
        factor_class = getattr(factor_module, class_name)
        original_strategy, _ = _run_factor_strategy(
            frame,
            factor_name=factor_name,
            factor_class=factor_class,
            params=params,
            runonce=runonce,
        )
        changed_strategy, _ = _run_factor_strategy(
            perturbed,
            factor_name=factor_name,
            factor_class=factor_class,
            params=params,
            runonce=runonce,
        )
        original = _factor_values(original_strategy, factor_name, len(frame))
        changed = _factor_values(changed_strategy, factor_name, len(frame))
        results[mode] = original
        assert any(math.isfinite(value) for value in original[:cut])
        for left, right in zip(original[:cut], changed[:cut]):
            assert not math.isinf(left)
            assert not math.isinf(right)
            assert math.isnan(left) == math.isnan(right)
            if math.isfinite(left):
                assert left == right

    for native_value, build_value in zip(results["native"], results["build"]):
        assert not math.isinf(native_value)
        assert not math.isinf(build_value)
        assert math.isnan(native_value) == math.isnan(build_value)
        if math.isfinite(native_value):
            assert native_value == build_value
