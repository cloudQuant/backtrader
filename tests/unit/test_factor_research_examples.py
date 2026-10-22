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
from typing import Any, Dict, List, Tuple

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


def _known_kdj_bars() -> pd.DataFrame:
    rows = [(100.0, 100.0, 100.0, 100.0, 1.0)] * 15
    rows.extend(
        (100.0 + value, 101.0 + value, 99.0 + value, 100.0 + value, 1.0) for value in range(1, 11)
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
        previous = closes[index - period]
        if math.isfinite(previous) and previous != 0.0:
            values[index] = closes[index] / previous - 1.0
    return values


def _run_native_factor(
    frame: pd.DataFrame,
    *,
    factor_name: str,
    factor_class: Any,
    params: Dict[str, int],
    runonce: bool,
) -> List[float]:
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
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    line = strategy.factor_instances[factor_name].outputs[strategy.datas[0]].factor
    return [float(value) for value in line.get(size=len(frame))]


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
        assert math.isnan(observed) == math.isnan(oracle)
        if math.isfinite(oracle):
            assert math.isclose(observed, oracle, rel_tol=1e-12, abs_tol=1e-12)


@pytest.mark.parametrize("runonce", (True, False))
def test_026_native_close_ma_and_roc_match_independent_oracles(runonce: bool):
    frame = _known_close_bars()
    factor_module = _load_module(MULTI_STRATEGY, "iteration45_multi_strategy_source")
    cases = (
        (
            "close_ma",
            factor_module.CloseMAFactor,
            {"period": 20},
            _independent_close_ma_oracle(frame, period=20),
            19,
        ),
        (
            "roc",
            factor_module.ROCFactor,
            {"period": 20},
            _independent_roc_oracle(frame, period=20),
            20,
        ),
    )
    for factor_name, factor_class, params, expected, first_finite in cases:
        actual = _run_native_factor(
            frame,
            factor_name=factor_name,
            factor_class=factor_class,
            params=params,
            runonce=runonce,
        )
        assert len(actual) == len(expected)
        assert math.isnan(expected[first_finite - 1])
        assert math.isfinite(expected[first_finite])
        for observed, oracle in zip(actual, expected):
            assert math.isnan(observed) == math.isnan(oracle)
            if math.isfinite(oracle):
                assert math.isclose(observed, oracle, rel_tol=1e-12, abs_tol=1e-12)


def _independent_kdj_oracle(frame: pd.DataFrame) -> Dict[str, List[float]]:
    """Compute rolling RSV/SMA K/D/J without using production factor helpers."""
    highs = frame["high"].tolist()
    lows = frame["low"].tolist()
    closes = frame["close"].tolist()
    rsv = [math.nan] * len(frame)
    k = [math.nan] * len(frame)
    d = [math.nan] * len(frame)
    j = [math.nan] * len(frame)

    for index in range(len(frame)):
        first_rsv = index - 9 + 1
        if first_rsv >= 0:
            high = max(highs[first_rsv : index + 1])
            low = min(lows[first_rsv : index + 1])
            if math.isfinite(high) and math.isfinite(low) and high > low:
                rsv[index] = 100.0 * (closes[index] - low) / (high - low)

        first_k = index - 3 + 1
        if first_k >= 0 and all(math.isfinite(value) for value in rsv[first_k : index + 1]):
            k[index] = sum(rsv[first_k : index + 1]) / 3.0

        first_d = index - 3 + 1
        if first_d >= 0 and all(math.isfinite(value) for value in k[first_d : index + 1]):
            d[index] = sum(k[first_d : index + 1]) / 3.0

        if math.isfinite(k[index]) and math.isfinite(d[index]):
            j[index] = 3.0 * k[index] - 2.0 * d[index]

    return {"rsv": rsv, "k": k, "d": d, "j": j}


def _run_native_kdj(frame: pd.DataFrame, runonce: bool) -> Dict[str, List[float]]:
    import backtrader as bt
    from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec
    from backtrader.research import align_to_grid

    factor_module = _load_module(MULTI_STRATEGY, "iteration45_multi_strategy_source")
    KDJFactor = factor_module.KDJFactor

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
        indicator=KDJFactor,
        panel_line="factor",
        params={"period": 9, "period_dfast": 3, "period_dslow": 3},
        field_bindings={field: "feed:target:%s" % field for field in KDJFactor.formula_fields},
    )
    cerebro = bt.Cerebro(stdstats=False)
    feed = align_to_grid(
        frame, research, asset, data_version="iteration45-test-kdj-known-answer-bars-v1"
    ).feed
    cerebro.adddata(feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor.name: factor})
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
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
            assert math.isnan(observed) == math.isnan(oracle)
            if math.isfinite(oracle):
                assert math.isclose(observed, oracle, rel_tol=1e-12, abs_tol=1e-12)
