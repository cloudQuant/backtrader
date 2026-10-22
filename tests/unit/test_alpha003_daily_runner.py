"""Small end-to-end contract for the real daily Alpha003 runner."""

import hashlib
import importlib.util
import json
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

    reasons = pd.read_csv(output_dir / "availability_reasons.csv")
    assert len(reasons) == len(dates) * len(symbols)
    assert {"ready", "valid", "reason"}.issubset(reasons.columns)
    assert "NO_CURRENT_BAR" in set(reasons["reason"])
    assert "NONFINITE_INPUT" in set(reasons["reason"])

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


def test_rejects_incomplete_aggregate_manifest(tmp_path):
    data_dir = tmp_path / "a_stocks"
    _write_daily_fixture(data_dir, day_count=2, symbol_count=2)
    manifest_path = data_dir / "_metadata" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "running"
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="status must be 'complete'"):
        _RUNNER._read_manifest(data_dir)
