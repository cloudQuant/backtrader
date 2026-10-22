"""Small end-to-end contract for the real daily Alpha003 runner."""

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_PATH = _ROOT / "examples" / "backtest" / "027_alpha003_panel_acceptance" / "run_daily.py"
_SPEC = importlib.util.spec_from_file_location("alpha003_daily_runner_test_module", _RUNNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNNER)


def _write_daily_fixture(data_dir: Path, *, day_count=22, symbol_count=12):
    metadata_dir = data_dir / "_metadata"
    metadata_dir.mkdir(parents=True)
    dates = pd.bdate_range("2025-01-02", periods=day_count).strftime("%Y-%m-%d").tolist()
    symbols = ["sh%06d" % index for index in range(symbol_count)]
    calendar_rows = []
    for day, date in enumerate(dates):
        missing_symbol = symbols[1] if day == 15 else None
        rows_today = symbol_count - int(missing_symbol is not None)
        calendar_rows.append(
            {
                "trade_date": date,
                "minute_count": rows_today * 240,
                "symbol_count": rows_today,
                "min_minutes_per_symbol": 240,
                "max_minutes_per_symbol": 240,
                "first_trade_time": date + " 09:30:00.000",
                "last_trade_time": date + " 15:00:00.000",
            }
        )
    pd.DataFrame(calendar_rows).to_csv(metadata_dir / "observed_calendar.csv", index=False)

    manifest_symbols = []
    for symbol_index, symbol in enumerate(symbols):
        rows = []
        for day, date in enumerate(dates):
            if symbol_index == 1 and day == 15:
                continue
            ohlc_invalid = symbol_index == 0 and day == 6
            volume_invalid = symbol_index == 3 and day == 10
            amount_invalid = symbol_index == 2 and day == 8
            invalid = ohlc_invalid or volume_invalid or amount_invalid
            opening = 10.0 + ((day * 7 + symbol_index * 3 + day * symbol_index * 2) % 19)
            opening += (symbol_index % 5) * 0.05
            volume = 1000.0 + ((day * 11 + symbol_index * 5 + day * symbol_index) % 23) * 10
            row = {
                "trade_date": date,
                "trade_time": date + " 15:00:00.000",
                "symbol": symbol,
                "open": opening,
                "high": opening + 2.0,
                "low": opening - 1.0,
                "close": opening + 0.5,
                "volume": volume,
                "amount": opening * volume,
                "minute_count": 240,
                "first_trade_time": date + " 09:30:00.000",
                "last_trade_time": date + " 15:00:00.000",
                "missing_or_invalid_count": 2 if invalid else 0,
                "invalid_day": invalid,
            }
            if ohlc_invalid:
                for field in ("open", "high", "low", "close"):
                    row[field] = np.nan
            if volume_invalid:
                row["volume"] = np.nan
            if amount_invalid:
                row["amount"] = np.nan
            rows.append(row)
        path = data_dir / (symbol + ".csv")
        pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
        invalid_count = sum(bool(row["invalid_day"]) for row in rows)
        manifest_symbols.append(
            {
                "symbol": symbol,
                "file": path.name,
                "rows": len(rows),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "first_trade_date": dates[0],
                "last_trade_date": dates[-1],
                "invalid_daily_rows": invalid_count,
            }
        )
    manifest = {
        "format": "test-daily-csv-v1",
        "status": "complete",
        "output": {"symbols": manifest_symbols},
    }
    (metadata_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return dates, symbols


def test_daily_runner_keeps_full_universe_and_warmup_across_two_subprocess_chunks(tmp_path):
    data_dir = tmp_path / "a_stocks"
    output_dir = tmp_path / "alpha003"
    dates, symbols = _write_daily_fixture(data_dir)

    result = _RUNNER.main(
        [
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(output_dir),
            "--chunk-days",
            "11",
        ]
    )

    assert result == 0
    summary = json.loads((output_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "COMPLETED"
    assert summary["evidence_level"] == "SOURCE_OBSERVED_DAILY_ALPHA003_PRODUCTION_FACTORSTRATEGY"
    assert summary["symbol_count"] == len(symbols)
    assert summary["grid_count"] == len(dates)
    assert summary["panel_cell_count"] == len(dates) * len(symbols)
    assert summary["broker_submit_count"] == summary["broker_cancel_count"] == 0
    assert summary["oracle"]["finite_mask_matches"] is True
    assert summary["oracle"]["max_abs_error"] <= _RUNNER.ORACLE_ATOL
    assert summary["chunks"][0]["warmup_grid_rows"] == 0
    assert summary["chunks"][1]["warmup_grid_rows"] == _RUNNER.LOOKBACK
    assert summary["chunks"][1]["study_first_date"] == dates[11]
    assert summary["chunks"][1]["grid_first_date"] == dates[2]
    assert summary["actual_chunk_runs_this_invocation"] == 2
    assert summary["reused_successful_chunks"] == 0

    factor_path = output_dir / "factor_values.parquet"
    factors = pd.read_parquet(factor_path)
    assert len(factors) == len(dates) * len(symbols)
    assert factors["trade_date"].nunique() == len(dates)
    assert set(factors["asset"]) == set(symbols)
    by_day = factors.groupby("trade_date", sort=True)["alpha003"]
    for date in dates[: _RUNNER.LOOKBACK]:
        assert not np.isfinite(by_day.get_group(date).to_numpy(dtype=float)).any()
    assert np.isfinite(by_day.get_group(dates[_RUNNER.LOOKBACK]).to_numpy(dtype=float)).any()
    assert factors["alpha003"].dropna().between(-1.0, 1.0).all()
    amount_only_cell = factors.loc[
        (factors["trade_date"] == dates[9]) & (factors["asset"] == symbols[2]), "alpha003"
    ]
    assert len(amount_only_cell) == 1 and np.isfinite(amount_only_cell.iloc[0])
    volume_gap_cell = factors.loc[
        (factors["trade_date"] == dates[19]) & (factors["asset"] == symbols[3]), "alpha003"
    ]
    volume_recovered_cell = factors.loc[
        (factors["trade_date"] == dates[20]) & (factors["asset"] == symbols[3]), "alpha003"
    ]
    assert len(volume_gap_cell) == len(volume_recovered_cell) == 1
    assert not np.isfinite(volume_gap_cell.iloc[0])
    assert np.isfinite(volume_recovered_cell.iloc[0])

    # The collection path returns factor values only: no availability table,
    # no per-cell ready/valid/reason columns, and no reason distribution.
    assert set(summary["output_files"]) == {"factor_values.parquet", "factor_values.csv"}
    assert set(summary["output_sha256"]) == set(summary["output_files"])
    for name, digest in summary["output_sha256"].items():
        assert hashlib.sha256((output_dir / name).read_bytes()).hexdigest() == digest
    assert "availability_reason_distribution" not in summary
    assert not (output_dir / "availability_reasons.csv").exists()
    assert {"ready", "valid", "reason"}.isdisjoint(factors.columns)
    assert summary["chunk_count"] == 2
    assert summary["panel_cell_count"] == len(dates) * len(symbols)
    assert summary["finite_factor_count"] == int(np.isfinite(factors["alpha003"]).sum())

    from backtrader.research import align as research_align

    assert summary["input_alignment_source_path"] == str(Path(research_align.__file__).resolve())
    assert Path(summary["input_alignment_source_path"]).is_file()
    assert Path(summary["factor_source_path"]).is_file()
    assert Path(summary["factor_source_path"]).name == "alpha003.py"
    assert Path(summary["factor_strategy_source_path"]).is_file()

    # A completed exact-identity run is reusable without launching its chunks again.
    assert (
        _RUNNER.main(
            ["--data-dir", str(data_dir), "--output-dir", str(output_dir), "--chunk-days", "11"]
        )
        == 0
    )
    summary_path = output_dir / "run_summary.json"
    tampered_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tampered_summary["finite_factor_count"] += 1
    summary_path.write_text(json.dumps(tampered_summary) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="completed run summary hash mismatch"):
        _RUNNER.main(
            ["--data-dir", str(data_dir), "--output-dir", str(output_dir), "--chunk-days", "11"]
        )
    assert (
        json.loads((output_dir / "run_state.json").read_text(encoding="utf-8"))["status"]
        == "COMPLETED"
    )


def test_daily_native_build_modes_match_oracle_exports_and_resume_identity(tmp_path, monkeypatch):
    data_dir = tmp_path / "mode_a_stocks"
    dates, symbols = _write_daily_fixture(data_dir)
    outputs = {}

    for factor_mode, class_name in (
        ("native", "Alpha003Native"),
        ("build", "Alpha003Build"),
    ):
        output_dir = tmp_path / ("alpha003_" + factor_mode)
        assert (
            _RUNNER.main(
                [
                    "--data-dir",
                    str(data_dir),
                    "--output-dir",
                    str(output_dir),
                    "--chunk-days",
                    "11",
                    "--factor-mode",
                    factor_mode,
                ]
            )
            == 0
        )
        summary_path = output_dir / "run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["factor_mode"] == factor_mode
        assert summary["factor_class"].endswith("." + class_name)
        assert summary["oracle"]["finite_mask_matches"] is True
        assert summary["oracle"]["max_abs_error"] <= _RUNNER.ORACLE_ATOL
        assert summary["broker_submit_count"] == summary["broker_cancel_count"] == 0
        assert summary["chunk_count"] == 2
        assert summary["actual_chunk_runs_this_invocation"] == 2
        assert summary["reused_successful_chunks"] == 0
        assert summary["chunks"][1]["warmup_grid_rows"] == _RUNNER.LOOKBACK

        worker_configs = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((output_dir / "_chunks").glob("chunk_*/worker.json"))
        ]
        assert len(worker_configs) == 2
        assert all(config["factor_mode"] == factor_mode for config in worker_configs)
        assert all(config["factor_class"].endswith("." + class_name) for config in worker_configs)

        factors = pd.read_csv(output_dir / "factor_values.csv")
        assert len(factors) == len(dates) * len(symbols)
        assert tuple(factors.columns) == (
            "time",
            "trade_date",
            "asset",
            "alpha003",
            "oracle_alpha003",
            "abs_error",
        )
        assert np.isfinite(factors["alpha003"].to_numpy(dtype=float)).any()
        np.testing.assert_array_equal(
            np.isfinite(factors["alpha003"].to_numpy(dtype=float)),
            np.isfinite(factors["oracle_alpha003"].to_numpy(dtype=float)),
        )
        assert factors["trade_date"].nunique() == len(dates)
        assert set(factors["asset"]) == set(symbols)
        outputs[factor_mode] = factors

        resumed = _RUNNER._run_parent(data_dir, output_dir, 11, factor_mode)
        assert resumed["actual_chunk_runs_this_invocation"] == 0
        assert resumed["reused_successful_chunks"] == 2
    pd.testing.assert_frame_equal(outputs["native"], outputs["build"], check_dtype=False)
    native_output = tmp_path / "alpha003_native"

    def snapshot_owned_files(output_dir):
        paths = [output_dir / "run_state.json", output_dir / "run_summary.json"]
        paths.extend(path for path in (output_dir / "_chunks").rglob("*") if path.is_file())
        return {
            path.relative_to(output_dir).as_posix(): path.read_bytes()
            for path in sorted(paths)
        }

    def unexpected_worker(*args, **kwargs):
        raise AssertionError("an identity conflict must not launch a worker subprocess")

    monkeypatch.setattr(_RUNNER.subprocess, "Popen", unexpected_worker)
    completed_before = snapshot_owned_files(native_output)
    with pytest.raises(_RUNNER.RunIdentityConflictError):
        _RUNNER.main(
            [
                "--data-dir",
                str(data_dir),
                "--output-dir",
                str(native_output),
                "--chunk-days",
                "11",
                "--factor-mode",
                "build",
            ]
        )
    assert snapshot_owned_files(native_output) == completed_before

    interrupted_output = tmp_path / "alpha003_native_interrupted"
    shutil.copytree(native_output, interrupted_output)
    state_path = interrupted_output / "run_state.json"
    interrupted_state = json.loads(state_path.read_text(encoding="utf-8"))
    interrupted_state["status"] = "RUNNING"
    state_path.write_text(json.dumps(interrupted_state) + "\n", encoding="utf-8")
    interrupted_before = snapshot_owned_files(interrupted_output)

    with pytest.raises(_RUNNER.RunIdentityConflictError):
        _RUNNER.main(
            [
                "--data-dir",
                str(data_dir),
                "--output-dir",
                str(interrupted_output),
                "--chunk-days",
                "11",
                "--factor-mode",
                "build",
            ]
        )
    assert snapshot_owned_files(interrupted_output) == interrupted_before


def test_rejects_incomplete_aggregate_manifest(tmp_path):
    data_dir = tmp_path / "a_stocks"
    _write_daily_fixture(data_dir, day_count=2, symbol_count=2)
    manifest_path = data_dir / "_metadata" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "running"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="status must be 'complete'"):
        _RUNNER._read_manifest(data_dir)
