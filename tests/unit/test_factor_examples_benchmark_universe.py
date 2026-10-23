"""Small contract tests for the optional full-universe benchmark mode."""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _load_script(name, relative):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_inputs(root, runner, verifier, monkeypatch):
    metadata = root / "_metadata"
    metadata.mkdir(parents=True)
    rows = []
    for symbol, filename in (("zeta", "zeta.csv"), ("alpha", "alpha.csv")):
        content = ("trade_time,open,high,low,close,volume,amount\n"
                   "2025-01-02 15:00:00,1,2,1,2,3,4\n").encode("utf-8")
        (root / filename).write_bytes(content)
        rows.append({"symbol": symbol, "file": filename,
                     "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
    dates = ["2025-01-02", "2025-01-03"]
    calendar_path = metadata / "observed_calendar.csv"
    with calendar_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("trade_date", "last_trade_time"))
        writer.writeheader()
        for date in dates:
            writer.writerow({"trade_date": date, "last_trade_time": date + " 15:00:00"})
    manifest = {
        "status": "complete",
        "output": {"symbols": rows, "symbol_count": 2, "csv_file_count": 2,
                   "observed_dates": 2, "date_range": {"first": dates[0], "last": dates[-1]}},
    }
    manifest_path = metadata / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    calendar_sha = hashlib.sha256(calendar_path.read_bytes()).hexdigest()
    monkeypatch.setattr(runner, "ALL_SYMBOLS", 2)
    monkeypatch.setattr(runner, "DATES", 2)
    monkeypatch.setattr(runner, "ALL_MANIFEST_SHA256", manifest_sha)
    monkeypatch.setattr(runner, "ALL_CALENDAR_SHA256", calendar_sha)
    monkeypatch.setattr(verifier, "EXPECTED_ALL_SYMBOL_COUNT", 2)
    monkeypatch.setattr(verifier, "EXPECTED_ALL_DATE_COUNT", 2)
    monkeypatch.setattr(verifier, "EXPECTED_ALL_MANIFEST_SHA256", manifest_sha)
    monkeypatch.setattr(verifier, "EXPECTED_ALL_CALENDAR_SHA256", calendar_sha)
    return rows


def test_universe_cli_preserves_fixed500_default_and_has_full_opt_in():
    runner = _load_script("factor_benchmark_universe_runner", "scripts/benchmark_factor_examples.py")
    verifier = _load_script("factor_benchmark_universe_verifier", "scripts/verify_factor_examples_benchmark.py")
    runner_default = runner._parser().parse_args([
        "--fincore-root", "fincore", "--data-root", "data", "--example", "025", "--output", "out"
    ])
    verifier_default = verifier._parser().parse_args(["--run", "025=out"])
    assert runner_default.universe == "fixed500"
    assert verifier_default.universe == "fixed500"
    assert runner._parser().parse_args([
        "--fincore-root", "fincore", "--data-root", "data", "--example", "025", "--output", "out",
        "--universe", "all",
    ]).universe == "all"
    assert verifier._parser().parse_args(["--run", "025=out", "--universe", "all"]).universe == "all"


def test_full_universe_loads_manifest_order_and_validates_each_csv(tmp_path, monkeypatch):
    runner = _load_script("factor_benchmark_universe_runner_data", "scripts/benchmark_factor_examples.py")
    verifier = _load_script("factor_benchmark_universe_verifier_data", "scripts/verify_factor_examples_benchmark.py")
    _write_inputs(tmp_path, runner, verifier, monkeypatch)

    runner_identity, runner_pins = runner._data_state(tmp_path, None, "all")
    verified = verifier._load_all_inputs(tmp_path)
    assert runner_identity["universe"] == verified["universe"] == "all"
    assert runner_identity["symbols"] == verified["source_symbol_count"] == 2
    assert runner_identity["dates"] == len(verified["dates"]) == 2
    assert runner_identity["grid_cells"] == verified["grid_cells"] == 4
    assert verified["symbols"] == ["zeta", "alpha"]
    assert set(runner_pins) == {
        "_metadata/manifest.json", "_metadata/observed_calendar.csv", "zeta.csv", "alpha.csv"
    }

    (tmp_path / "alpha.csv").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="CSV pin mismatch"):
        runner._data_state(tmp_path, None, "all")
    with pytest.raises(verifier.VerificationError, match="full-manifest pin"):
        verifier._load_all_inputs(tmp_path)


def test_dynamic_evaluation_counts_match_selected_grid_size():
    verifier = _load_script("factor_benchmark_universe_counts", "scripts/verify_factor_examples_benchmark.py")
    fixed = {"symbols": [None] * 500, "dates": [None] * 243}
    full = {"symbols": [None] * 5471, "dates": [None] * 243}
    assert verifier._grid_cell_count(fixed) == 121500
    assert verifier._grid_cell_count(full) == 1329453
    assert verifier._expected_evaluation_counts("025", fixed) == {
        "targets": 500, "study_dates": 243, "panel_cells": 121500,
        "factors": 1, "signal_rows": 121500, "label_rows": 364500,
    }
    assert verifier._expected_evaluation_counts("026", full) == {
        "targets": 5471, "study_dates": 243, "panel_cells": 1329453,
        "factors": 3, "signal_rows": 3988359, "label_rows": 3988359,
    }
    runner = _load_script("factor_benchmark_universe_command", "scripts/benchmark_factor_examples.py")
    command = runner._example_cli_arguments("027", "full", Path("out"), Path("data"), 5471)
    assert command[command.index("--max-symbols") + 1] == "5471"
