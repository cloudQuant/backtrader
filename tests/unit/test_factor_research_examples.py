"""Independent formula and fixture checks for the Iteration 45 examples.

These tests exercise source components only. Copy/install entrypoints and the
full research evaluations remain separate acceptance work.
"""

from __future__ import annotations

import importlib.util
import csv
import hashlib
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


def _generator_config() -> Dict[str, Any]:
    return {
        "generator_version": "synthetic-ohlcv-sha256-v1",
        "seed": 4510,
        "start_date": date(2025, 1, 6),
        "asset_prefix": "SYN",
        "asset_count": 20,
        "warmup_bars": 20,
        "research_bars": 260,
        "tail_bars": 21,
        "source_timezone": "UTC",
        "open_time_utc": "09:30:00",
        "close_time_utc": "16:00:00",
    }


def test_single_and_multi_examples_generate_identical_ohlcv_and_grid():
    single = _load_module(SINGLE_RUNNER, "iteration45_single_run_source")
    multi = _load_module(MULTI_RUNNER, "iteration45_multi_run_source")
    single_config = single._load_config()
    multi_config = multi._load_config()
    single_data = single_config["data"]
    multi_data = multi_config["data"]
    for data_config in (single_data, multi_data):
        assert data_config["asset_count"] == 20
        assert data_config["warmup_bars"] >= 20
        assert data_config["research_bars"] == 260
        assert data_config["tail_bars"] >= 21
    assert single_config["evaluation"]["periods"] == [1, 5, 20]
    assert multi_config["evaluation"]["periods"] == [1, 5, 20]
    assert single_config["evaluation"]["segments"]["development"]["research_bar_end"] + 1 == 160
    assert single_config["evaluation"]["segments"]["validation"]["research_bar_end"] + 1 == 260
    assert multi_config["evaluation"]["segments"] == single_config["evaluation"]["segments"]
    for name, expected_bars in (("development", 160), ("validation", 100)):
        segment = single_config["evaluation"]["segments"][name]
        segment_bars = segment["research_bar_end"] - segment["research_bar_start"] + 1
        assert segment_bars == expected_bars
        assert tuple(min(horizon + 1, segment_bars) for horizon in (1, 5, 20)) == (
            2,
            6,
            21,
        )

    left = single.build_synthetic_panel(single_data)
    right = multi.build_synthetic_panel(multi_data)

    assert left["ohlcv_sha256"] == right["ohlcv_sha256"]
    assert left["assets"] == right["assets"]
    assert left["bar_count"] == 301
    assert len(left["grid"]) == 301
    assert left["research_start_position"] == 20
    assert left["research_end_position"] == 279
    assert str(left["grid"].index.tz) == "UTC"
    assert (left["grid"]["open_time"].array < left["grid"].index).all()
    pd.testing.assert_frame_equal(left["grid"], right["grid"])
    for asset in left["assets"]:
        pd.testing.assert_frame_equal(left["feeds"][asset], right["feeds"][asset])
        frame = left["feeds"][asset]
        assert frame.iloc[:15]["high"].eq(frame.iloc[:15]["low"]).all()
        assert frame.iloc[:15]["close"].eq(frame.iloc[:15]["open"]).all()
        assert frame.iloc[:15]["volume"].gt(0.0).all()
    for field in ("open", "close"):
        pd.testing.assert_frame_equal(left["prices"][field], right["prices"][field])


@pytest.mark.parametrize(
    ("runner_path", "module_name", "factor_names"),
    (
        (SINGLE_RUNNER, "iteration45_single_broker_guard_source", ("close_ma",)),
        (
            MULTI_RUNNER,
            "iteration45_multi_broker_guard_source",
            ("close_ma", "roc", "kdj_j"),
        ),
    ),
)
@pytest.mark.parametrize("runnext", (False, True))
def test_native_example_collection_observes_zero_broker_writes(
    monkeypatch: pytest.MonkeyPatch,
    runner_path: Path,
    module_name: str,
    factor_names: Tuple[str, ...],
    runnext: bool,
):
    runner = _load_module(runner_path, module_name)
    monkeypatch.syspath_prepend(str(runner_path.parent))
    config = runner._load_config()
    panel = runner.build_synthetic_panel(config["data"])

    strategy, dataset, broker = runner._run_native_collection(config, panel, runnext)

    assert tuple(strategy.factor_instances) == factor_names
    assert len(dataset.grid) == panel["bar_count"]
    assert len(dataset.raw_factors) == config["data"]["research_bars"] * len(panel["assets"])
    assert broker.submit_count == 0
    assert broker.cancel_count == 0


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


def _minimal_required_result(runner: Any, multi: bool = False) -> SimpleNamespace:
    """Build two fully covered bars with the runner's required table contract."""
    opens, closes = _weekday_session_times(4)
    research_times = tuple(closes[:2])
    open_positions = {stamp: index for index, stamp in enumerate(opens)}
    close_positions = {stamp: index for index, stamp in enumerate(closes)}
    group = "synthetic-demo"
    if multi:
        base_signals = ("close_ma", "roc", "kdj_j")
        expected_signals = {
            **dict.fromkeys(base_signals, ("raw", "oriented", "transformed")),
            "equal_weight": ("composite",),
        }
        expected_signals.update(
            {"equal_weight::without::%s" % name: ("composite",) for name in base_signals}
        )
        comparison_id = "all_variants"
    else:
        base_signals = ()
        expected_signals = {"close_ma": ("raw", "oriented", "transformed")}
        comparison_id = None

    ablation_signals = (
        {"equal_weight::without::%s" % name for name in base_signals} if multi else set()
    )
    axes = [
        (
            signal,
            variant,
            "common:" + comparison_id if signal in ablation_signals else "own:" + signal,
        )
        for signal, variants in expected_signals.items()
        for variant in variants
    ]
    signals = []
    ic = []
    ic_summary = []
    quantile_returns = []
    spreads = []
    stability = []
    coverage = []
    for axis_index, (signal, variant, pool_id) in enumerate(axes, start=1):
        for time_index, stamp in enumerate(research_times, start=1):
            signals.append(
                {
                    "time": stamp,
                    "asset": "SYN00",
                    "signal": signal,
                    "variant": variant,
                    "pool_id": pool_id,
                    "group": group,
                    "value": float(axis_index + time_index),
                }
            )
            quantile_returns.append(
                {
                    "record_type": "period",
                    "time": stamp,
                    "segment_id": "full",
                    "signal": signal,
                    "variant": variant,
                    "pool_id": pool_id,
                    "group": group,
                    "horizon": 1,
                    "quantile": 1,
                    "mean": 0.01 * time_index,
                    "status": "OK",
                    "reason": None,
                    "n_assets": 1,
                }
            )
            for metric in ("pearson", "spearman"):
                ic.append(
                    {
                        "time": stamp,
                        "segment_id": "full",
                        "signal": signal,
                        "variant": variant,
                        "pool_id": pool_id,
                        "group": group,
                        "horizon": 1,
                        "metric": metric,
                        "value": 0.1 * time_index,
                        "status": "OK",
                        "reason": None,
                        "n_assets": 1,
                    }
                )
            spreads.append(
                {
                    "record_type": "period",
                    "time": stamp,
                    "segment_id": "full",
                    "signal": signal,
                    "variant": variant,
                    "pool_id": pool_id,
                    "group": group,
                    "horizon": 1,
                    "lower_quantile": 1,
                    "upper_quantile": 1,
                    "value": 0.01 * time_index,
                    "status": "OK",
                    "reason": None,
                    "n_assets": 1,
                }
            )
        for metric in ("pearson", "spearman"):
            ic_summary.append(
                {
                    "record_type": "summary",
                    "time": pd.NaT,
                    "period": "all",
                    "segment_id": "full",
                    "signal": signal,
                    "variant": variant,
                    "pool_id": pool_id,
                    "group": group,
                    "horizon": 1,
                    "metric": metric,
                    "mean": 0.15,
                    "sample_std": 0.05,
                    "information_ratio": 3.0,
                    "positive_fraction": 1.0,
                    "n_periods_total": 2,
                    "n_periods_valid": 2,
                    "status": "OK",
                    "reason": None,
                }
            )
        for metric, quantile in (("rank_autocorrelation", None), ("quantile_turnover", 1)):
            stability.append(
                {
                    "time": research_times[-1],
                    "segment_id": "full",
                    "segment_role": "research",
                    "signal": signal,
                    "variant": variant,
                    "pool_id": pool_id,
                    "group": group,
                    "metric": metric,
                    "lag": 1,
                    "quantile": quantile,
                    "value": 0.25,
                    "status": "OK",
                    "reason": None,
                    "n_assets": 1,
                }
            )
        coverage.append(
            {
                "record_type": "summary",
                "time": pd.NaT,
                "segment_id": "full",
                "segment_role": "research",
                "signal": signal,
                "variant": variant,
                "pool_id": pool_id,
                "group": group,
                "horizon": 1,
                "candidate_count": 2,
                "pool_member_count": 2,
                "finite_value_count": 2,
                "label_count": 2,
                "paired_count": 2,
                "formation_loss_count": 0,
                "analysis_loss_count": 0,
                "segment_boundary_count": 0,
                "loss_rate": 0.0,
                "status": "OK",
                "reason": None,
                "period_count": 2,
            }
        )

    labels = []
    for stamp in research_times:
        close_index = close_positions[stamp]
        entry_index = close_index + 1
        exit_index = entry_index + 1
        labels.append(
            {
                "time": stamp,
                "asset": "SYN00",
                "horizon": 1,
                "value": 0.01,
                "entry_time": opens[entry_index],
                "exit_time": opens[exit_index],
                "entry_bar": open_positions[opens[entry_index]],
                "exit_bar": open_positions[opens[exit_index]],
            }
        )

    tables: Dict[str, pd.DataFrame] = {
        "signals": pd.DataFrame(signals),
        "labels": pd.DataFrame(labels),
        "ic": pd.DataFrame(ic),
        "ic_summary": pd.DataFrame(ic_summary),
        "quantile_returns": pd.DataFrame(quantile_returns),
        "spreads": pd.DataFrame(spreads),
        "stability": pd.DataFrame(stability),
        "coverage": pd.DataFrame(coverage),
    }
    if multi:
        common_pool = "common:" + comparison_id
        for name in (
            "signals",
            "ic",
            "ic_summary",
            "quantile_returns",
            "spreads",
            "stability",
            "coverage",
        ):
            common_rows = (
                tables[name].loc[tables[name]["pool_id"].astype(str).str.startswith("own:")].copy()
            )
            common_rows["pool_id"] = common_pool
            tables[name] = pd.concat((tables[name], common_rows), ignore_index=True)
        correlations = []
        for left_index, left in enumerate(base_signals):
            for right in base_signals[left_index + 1 :]:
                for metric in ("pearson", "spearman"):
                    correlations.append(
                        {
                            "record_type": "summary",
                            "time": pd.NaT,
                            "segment_id": "full",
                            "segment_role": "research",
                            "signal_left": left,
                            "signal_right": right,
                            "variant_left": "transformed",
                            "variant_right": "transformed",
                            "pool_id": "common:" + comparison_id,
                            "group": group,
                            "metric": metric,
                            "value": 0.2,
                            "status": "OK",
                            "reason": None,
                            "n_assets": 1,
                            "n_periods": 2,
                        }
                    )
        comparisons = []
        comparison_variants = {
            name: "transformed" if name in base_signals else "composite"
            for name in expected_signals
        }
        comparison_names = tuple(expected_signals)
        for left_index, left in enumerate(comparison_names):
            for right in comparison_names[left_index + 1 :]:
                for metric in ("pearson", "spearman"):
                    for stamp in research_times:
                        comparisons.append(
                            {
                                "record_type": "period",
                                "period": stamp,
                                "comparison_id": comparison_id,
                                "left_signal": left,
                                "right_signal": right,
                                "variant_left": comparison_variants[left],
                                "variant_right": comparison_variants[right],
                                "horizon": 1,
                                "pool_id": "common:" + comparison_id,
                                "group": group,
                                "segment_id": "full",
                                "segment_role": "research",
                                "metric": metric,
                                "delta": 0.01,
                                "status": "OK",
                                "reason": None,
                            }
                        )
                    comparisons.append(
                        {
                            "record_type": "summary",
                            "period": "all",
                            "comparison_id": comparison_id,
                            "left_signal": left,
                            "right_signal": right,
                            "variant_left": comparison_variants[left],
                            "variant_right": comparison_variants[right],
                            "horizon": 1,
                            "pool_id": "common:" + comparison_id,
                            "group": group,
                            "segment_id": "full",
                            "segment_role": "research",
                            "metric": metric,
                            "mean_delta": 0.01,
                            "sample_std_delta": 0.001,
                            "positive_delta_fraction": 1.0,
                            "paired_period_count": 2,
                            "n_periods_total": 2,
                            "status": "OK",
                            "reason": None,
                        }
                    )
        tables["correlation"] = pd.DataFrame(correlations)
        tables["comparisons"] = pd.DataFrame(comparisons)

    # The diagnostics attribute is deliberately absent: this is the declared
    # optional table, while every mandatory result table above is populated.
    return SimpleNamespace(status="PARTIAL", **tables)


@pytest.mark.parametrize(
    ("runner_path", "module_name", "multi"),
    (
        (SINGLE_RUNNER, "iteration45_single_cli_status", False),
        (MULTI_RUNNER, "iteration45_multi_cli_status", True),
    ),
)
def test_partial_status_requires_all_mandatory_rows_but_not_optional_diagnostics(
    tmp_path: Path, runner_path: Path, module_name: str, multi: bool
):
    runner = _load_module(runner_path, module_name)
    result = _minimal_required_result(runner, multi=multi)
    if multi:
        ablation_signals = {
            "equal_weight::without::%s" % name for name in ("close_ma", "roc", "kdj_j")
        }
        for table_name in (
            "signals",
            "ic",
            "ic_summary",
            "quantile_returns",
            "spreads",
            "coverage",
            "stability",
        ):
            rows = getattr(result, table_name)
            ablation_rows = rows.loc[rows["signal"].isin(ablation_signals)]
            assert not ablation_rows.empty
            assert set(ablation_rows["pool_id"]) == {"common:all_variants"}
        common_comparisons = result.comparisons.loc[
            result.comparisons["pool_id"].eq("common:all_variants")
            & result.comparisons["record_type"].eq("summary")
        ]
        assert len(common_comparisons) == 42
        for signal in ablation_signals:
            assert (
                common_comparisons["left_signal"].eq(signal)
                | common_comparisons["right_signal"].eq(signal)
            ).sum() == 12
    times = tuple(result.labels["time"].drop_duplicates())
    assets = ("SYN00",)
    expected_signals = (
        {
            **dict.fromkeys(("close_ma", "roc", "kdj_j"), ("raw", "oriented", "transformed")),
            "equal_weight": ("composite",),
            **{
                "equal_weight::without::%s" % name: ("composite",)
                for name in ("close_ma", "roc", "kdj_j")
            },
        }
        if multi
        else {"close_ma": ("raw", "oriented", "transformed")}
    )
    validation_kwargs = {
        "group": "synthetic-demo",
        "segment_bars": {"full": 2},
        "asset_count": 1,
        "research_times": times,
        "target_assets": assets,
        "grid_close_times": tuple(_weekday_session_times(4)[1]),
        "grid_open_times": tuple(_weekday_session_times(4)[0]),
        "quantiles": 1,
        "stability_lags": (1,),
        "segment_times": {"full": times},
        "max_loss": 0.35,
    }
    if multi:
        validation_kwargs.update(
            {
                "comparison_id": "all_variants",
                "base_signals": ("close_ma", "roc", "kdj_j"),
                "signal_pools": {
                    "equal_weight::without::close_ma": ("common:all_variants",),
                    "equal_weight::without::roc": ("common:all_variants",),
                    "equal_weight::without::kdj_j": ("common:all_variants",),
                },
            }
        )
    mandatory = runner._validate_result(result, expected_signals, (1,), **validation_kwargs)
    assert mandatory["passed"] is True
    assert runner._evaluation_exit_code("PARTIAL", mandatory) == 0
    required_diagnostic = runner._validate_result(
        result,
        expected_signals,
        (1,),
        required_optional_tables=("diagnostics",),
        **validation_kwargs,
    )
    assert required_diagnostic["passed"] is False
    assert "diagnostics" in required_diagnostic["missing_tables"]
    assert runner._evaluation_exit_code("PARTIAL", required_diagnostic) == 1

    result.ic = result.ic.iloc[:-1]
    missing_required = runner._validate_result(result, expected_signals, (1,), **validation_kwargs)
    assert missing_required["passed"] is False
    assert runner._evaluation_exit_code("PARTIAL", missing_required) == 1
    result.ic = pd.DataFrame()
    empty_required = runner._validate_result(result, expected_signals, (1,), **validation_kwargs)
    assert empty_required["passed"] is False
    assert runner._evaluation_exit_code("PARTIAL", empty_required) == 1
    assert runner._evaluation_exit_code("UNEVALUABLE", mandatory) == 1

    evaluation_dir = tmp_path / module_name / "evaluation"
    evaluation_dir.mkdir(parents=True)
    required_tables = tuple(runner._EXPORT_REQUIRED_COLUMNS)
    table_schemas = {}
    table_files = {}
    file_records = {}
    for name in required_tables:
        columns = list(runner._EXPORT_REQUIRED_COLUMNS[name])
        schema_columns = [
            {
                "name": column,
                "type": runner._EXPORT_LOGICAL_TYPES.get(column, "string"),
            }
            for column in columns
        ]
        table_schemas[name] = {"columns": schema_columns}
        table_files[name] = {"csv": name + ".csv", "json": name + ".json"}
        # The diagnostics table is intentionally empty but retains its declared schema.
        records = [] if name == "diagnostics" else [dict.fromkeys(columns)]
        csv_path = evaluation_dir / (name + ".csv")
        with csv_path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.writer(target)
            writer.writerow(columns)
            for record in records:
                writer.writerow([record[column] for column in columns])
        json_path = evaluation_dir / (name + ".json")
        json_path.write_text(json.dumps(records, separators=(",", ":")), encoding="utf-8")
        for table_path, media_type in ((csv_path, "text/csv"), (json_path, "application/json")):
            payload = table_path.read_bytes()
            file_records[table_path.name] = {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "rows": len(records),
                "media_type": media_type,
            }
    manifest = {
        "schema": "fincore-factor-research-result-v1",
        "result_schema_version": 1,
        "export_schema_version": 1,
        "complete": True,
        "evaluation_id": "small-fixture",
        "status": "PARTIAL",
        "result_table_schemas": table_schemas,
        "tables": table_files,
        "files": file_records,
    }
    manifest_path = evaluation_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    exported = runner._validate_export_output(
        evaluation_dir,
        charts_requested=False,
        expected_status="PARTIAL",
        expected_evaluation_id="small-fixture",
    )
    assert exported["passed"] is True
    assert exported["table_file_count"] == 22
    assert exported["table_row_count"] == 10
    assert exported["optional_tables"] == ["diagnostics"]
    assert runner._evaluation_exit_code("PARTIAL", exported) == 0
    required_export = runner._validate_export_output(
        evaluation_dir,
        charts_requested=False,
        expected_status="PARTIAL",
        optional_tables=(),
    )
    assert required_export["passed"] is True
    assert required_export["optional_tables"] == []

    (evaluation_dir / "ic.csv").write_text("required\n", encoding="utf-8")
    broken_csv = runner._validate_export_output(
        evaluation_dir,
        charts_requested=False,
        expected_status="PARTIAL",
        expected_evaluation_id="small-fixture",
    )
    assert broken_csv["passed"] is False
    assert broken_csv["reason"] == "evaluation_table_file_manifest_mismatch"
    # A matching manifest hash still cannot make a malformed header acceptable.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = (evaluation_dir / "ic.csv").read_bytes()
    manifest["files"]["ic.csv"]["sha256"] = hashlib.sha256(payload).hexdigest()
    manifest["files"]["ic.csv"]["bytes"] = len(payload)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    wrong_header = runner._validate_export_output(
        evaluation_dir,
        charts_requested=False,
        expected_status="PARTIAL",
        expected_evaluation_id="small-fixture",
    )
    assert wrong_header["passed"] is False
    assert wrong_header["reason"] == "evaluation_csv_schema_mismatch"
    manifest["evaluation_id"] = "different-evaluation"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    wrong_identity = runner._validate_export_output(
        evaluation_dir,
        charts_requested=False,
        expected_status="PARTIAL",
        expected_evaluation_id="small-fixture",
    )
    assert wrong_identity["passed"] is False
    assert wrong_identity["reason"] == "evaluation_manifest_status_or_id_missing"
    assert runner._failure_result(ImportError("missing fincore")) == ("BLOCKED_DEPENDENCY", 2)
    missing_input = RuntimeError("input prerequisite failed")
    missing_input.code = "MISSING_INPUT"
    assert runner._failure_result(missing_input) == ("INVALID_INPUT", 2)
    assert runner._failure_result(OSError("output unavailable")) == ("OUTPUT_ERROR", 3)
    assert runner._failure_result(KeyboardInterrupt()) == ("INTERRUPTED", 3)
    assert runner._failure_result(RuntimeError("required result missing")) == ("FAILED", 1)

    (evaluation_dir / "signals.csv").unlink()
    missing_export = runner._validate_export_output(
        evaluation_dir, charts_requested=False, expected_status="PARTIAL"
    )
    assert missing_export["passed"] is False
    assert runner._evaluation_exit_code("PARTIAL", missing_export) == 1


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
    from backtrader.research.inputs import prealign_bars

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
    feed = prealign_bars(
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
    from backtrader.research.inputs import prealign_bars

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
    feed = prealign_bars(
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
