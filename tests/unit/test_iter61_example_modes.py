"""Synthetic, offline runner contracts migrated from the retired factor example tests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "backtest"
RUNNERS = {
    "025": EXAMPLES / "025_factor_single" / "run.py",
    "026": EXAMPLES / "026_factor_multi" / "run.py",
    "027": EXAMPLES / "027_alpha003_panel_acceptance" / "run.py",
}
NAMES = {"025": ("close_ma",), "026": ("close_ma", "kdj_j", "roc"), "027": ("alpha003",)}


def load_runner(key):
    path = RUNNERS[key]
    name = "iter61_runner_" + key
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def config_for(runner, directory):
    config = {
        "example_id": runner.EXAMPLE_ID,
        "factor_mode": "native",
        "data": {
            "directory": str(directory),
            "max_symbols": 0,
            "source_timezone": "Asia/Shanghai",
            "snapshot_id": "synthetic-v1",
            "price_basis": "synthetic",
            "calendar_id": "synthetic-weekday-v1",
            "frequency": "1session",
            "data_version": "synthetic-bars-v1",
            "group": "market",
        },
        "evaluation": {
            "periods": [1, 5],
            "label": "next_open_to_open",
            "precomputed_entry": "next_open",
            "quantiles": 5,
            "min_assets": 1,
            "min_quantile_assets": 1,
            "preprocess": "none",
            "max_loss": 1.0,
            "stability_lags": [],
            "segments": {},
            "combinations": {},
            "comparisons": {},
        },
    }
    if runner.EXAMPLE_ID.startswith("025"):
        config["factor"] = {
            "name": "close_ma",
            "params": {"period": 20},
            "panel_line": "factor",
            "direction": 1,
        }
    elif runner.EXAMPLE_ID.startswith("026"):
        config["factors"] = {
            "close_ma": {"params": {"period": 20}, "panel_line": "factor", "direction": 1},
            "kdj_j": {
                "params": {"period": 9, "period_dfast": 3, "period_dslow": 3},
                "panel_line": "factor",
                "direction": 1,
            },
            "roc": {"params": {"period": 20}, "panel_line": "factor", "direction": 1},
        }
    else:
        config.update(factor="alpha003", operator_profile="alpha101-v2")
    return config


def write_panel(root, days=35, count=4):
    """Synthetic daily CSV layout; one asset has a missing bar on day 17."""
    metadata = root / "_metadata"
    metadata.mkdir(parents=True)
    dates = pd.bdate_range("2025-01-02", periods=days).strftime("%Y-%m-%d").tolist()
    symbols = [f"sh{600000 + i:06d}" for i in range(count)]
    pd.DataFrame(
        [
            {
                "trade_date": d,
                "first_trade_time": d + " 09:30:00.000",
                "last_trade_time": d + " 15:00:00.000",
                "symbol_count": count - (i == days // 2),
                "minute_count": 240 * (count - (i == days // 2)),
            }
            for i, d in enumerate(dates)
        ]
    ).to_csv(metadata / "observed_calendar.csv", index=False)
    entries = []
    for n, symbol in enumerate(symbols):
        rows = []
        for i, stamp in enumerate(dates):
            if n == 1 and i == days // 2:
                continue
            op = 10.0 + ((i * (n + 2) + n) % 7) * 0.3 + n * 0.01
            close = op + (i % 3 - 1) * 0.05
            volume = 1000.0 + ((i * (n + 3) + n) % 11) * 10.0
            rows.append(
                {
                    "trade_date": stamp,
                    "trade_time": stamp + " 15:00:00.000",
                    "symbol": symbol,
                    "open": op,
                    "high": max(op, close) + 0.1,
                    "low": min(op, close) - 0.1,
                    "close": close,
                    "volume": volume,
                    "amount": volume * close,
                    "minute_count": 240,
                    "first_trade_time": stamp + " 09:30:00.000",
                    "last_trade_time": stamp + " 15:00:00.000",
                    "missing_or_invalid_count": 0,
                    "invalid_day": False,
                }
            )
        path = root / (symbol + ".csv")
        pd.DataFrame(rows).to_csv(path, index=False)
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
    (metadata / "manifest.json").write_text(
        json.dumps({"status": "complete", "output": {"symbols": entries}})
    )
    return symbols, dates


def assert_same_values(left, right, names):
    assert list(left.columns) == list(right.columns)
    pd.testing.assert_frame_equal(left[["time", "asset"]], right[["time", "asset"]])
    for name in names:
        a = pd.to_numeric(left[name], errors="raise").to_numpy(dtype=float)
        b = pd.to_numeric(right[name], errors="raise").to_numpy(dtype=float)
        assert np.isfinite(a).any(), name
        assert np.array_equal(np.isnan(a), np.isnan(b)), name
        assert np.array_equal(np.isfinite(a), np.isfinite(b)), name
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-12, equal_nan=True)


def block_evaluation(monkeypatch):
    import backtrader.research as research
    from backtrader.errors import DependencyError

    def unavailable(*args, **kwargs):
        raise DependencyError("synthetic runner test: evaluation unavailable")

    monkeypatch.setattr(research, "evaluate_frames", unavailable)


@pytest.mark.parametrize("key", ("025", "026", "027"))
def test_mode_precedence_cli_and_invalid_inputs(key, monkeypatch, tmp_path):
    runner = load_runner(key)
    cfg = config_for(runner, tmp_path)
    monkeypatch.setattr(runner, "_load_config", lambda: copy.deepcopy(cfg))
    assert runner._resolve_factor_mode(None, None) == "native"
    assert runner._resolve_factor_mode(None, "build") == "build"
    assert runner._resolve_factor_mode("native", "build") == "native"
    with pytest.raises(ValueError, match="factor_mode"):
        runner._resolve_factor_mode(None, "invalid")
    assert runner._parser().parse_args(["--output-dir", str(tmp_path / "out")]).factor_mode is None
    with pytest.raises(SystemExit) as error:
        runner._parser().parse_args(["--output-dir", "out", "--factor-mode", "invalid"])
    assert error.value.code == 2
    cfg["factor_mode"] = "invalid"
    assert runner.main(["--output-dir", str(tmp_path / "invalid")]) == 2
    if key != "027":
        assert runner._parser().parse_args(["--output-dir", "out"]).asset_batch_size == 256
        assert (
            runner._parser()
            .parse_args(["--output-dir", "out", "--asset-batch-size", "0"])
            .asset_batch_size
            == 0
        )
        with pytest.raises(SystemExit) as error:
            runner.main(["--output-dir", str(tmp_path / "bad-batch"), "--asset-batch-size", "-1"])
        assert error.value.code == 2
    else:
        cfg["factor_mode"] = "native"
        cfg["factor"] = "not-alpha003"
        assert runner.main(["--output-dir", str(tmp_path / "bad-factor")]) == 2


@pytest.mark.parametrize("key", ("025", "026", "027"))
def test_real_runner_mode_and_execution_matrix(key, monkeypatch, tmp_path):
    runner = load_runner(key)
    monkeypatch.syspath_prepend(str(RUNNERS[key].parent))
    source = tmp_path / "source"
    symbols, dates = write_panel(source)
    cfg = config_for(runner, source)
    # Force a CLI override for native and leave build to the configuration.
    cfg["factor_mode"] = "build"
    monkeypatch.setattr(runner, "_load_config", lambda: copy.deepcopy(cfg))
    if key != "027":
        block_evaluation(monkeypatch)
    else:
        run_factor = runner._run_factor

        def check_coverage(*args, **kwargs):
            strategy, panel, indicator = run_factor(*args, **kwargs)
            for instance in strategy._factor_instances_by_name["alpha003"]:
                diagnostics = instance.lifecycle_diagnostics
                assert diagnostics["coverage_matches"]
                assert diagnostics["coverage_count"] == diagnostics["grid_count"] == len(panel.grid)
            return strategy, panel, indicator

        monkeypatch.setattr(runner, "_run_factor", check_coverage)
    panels = {}
    for mode in ("native", "build"):
        for runnext in (False, True):
            output = tmp_path / f"{mode}-{runnext}"
            args = ["--output-dir", str(output), "--data-dir", str(source)]
            if key != "027":
                args += ["--asset-batch-size", "0"]
            if mode == "native":
                args += ["--factor-mode", "native"]
            if runnext:
                args.append("--runnext")
            assert runner.main(args) == 0, (key, mode, runnext)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            assert summary["status"] == ("COMPLETED" if key == "027" else "PANEL_ONLY")
            assert summary["factor_mode"] == mode
            assert summary["factor_calculation"] == "RAN"
            assert summary["broker"] == {"submit": 0, "cancel": 0}
            assert (summary["symbols"], summary["dates"]) == (len(symbols), len(dates))
            if key == "027":
                assert summary["factor"] == "alpha003"
                assert summary["cells"] == len(symbols) * len(dates)
                assert summary["operator_profile"] == "alpha101-v2"
            else:
                assert tuple(summary["factor_classes"]) == tuple(sorted(NAMES[key]))
            values = pd.read_csv(output / "factor_values.csv")
            assert len(values) == len(symbols) * len(dates)
            assert tuple(c for c in values.columns if c in NAMES[key]) == NAMES[key]
            assert set(values["asset"]) == set(symbols)
            assert not values.duplicated(["time", "asset"]).any()
            missing = values[
                (values["asset"] == symbols[1])
                & (
                    pd.to_datetime(values["time"], utc=True).dt.strftime("%Y-%m-%d")
                    == dates[len(dates) // 2]
                )
            ]
            assert len(missing) == 1
            assert missing[list(NAMES[key])].isna().all(axis=None)
            panels[(mode, runnext)] = values
    baseline = panels[("native", False)]
    for values in panels.values():
        assert_same_values(baseline, values, NAMES[key])


@pytest.mark.parametrize("key", ("025", "026"))
def test_offline_panel_does_not_recompute_and_cli_conflict(key, monkeypatch, tmp_path):
    runner = load_runner(key)
    monkeypatch.syspath_prepend(str(RUNNERS[key].parent))
    source = tmp_path / "source"
    write_panel(source)
    cfg = config_for(runner, source)
    monkeypatch.setattr(runner, "_load_config", lambda: copy.deepcopy(cfg))
    block_evaluation(monkeypatch)
    initial = tmp_path / "initial"
    assert (
        runner.main(["--output-dir", str(initial), "--save-panel", "--asset-batch-size", "0"]) == 0
    )
    expected = pd.read_csv(initial / "factor_values.csv")
    cfg["factor_mode"] = "invalid"

    def forbidden(*args, **kwargs):
        pytest.fail("offline panel recalculated factors")

    monkeypatch.setattr(runner, "_run_native_collection", forbidden)
    monkeypatch.setattr(runner, "_run_batched_collection", forbidden)
    offline = tmp_path / "offline"
    assert runner.main(["--output-dir", str(offline), "--panel", str(initial / "panel")]) == 0
    summary = json.loads((offline / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "PANEL_ONLY"
    assert summary["factor_mode"] == "NOT_APPLICABLE"
    assert summary["factor_calculation"] == "NOT_RUN"
    assert summary["factor_classes"] == {}
    assert_same_values(expected, pd.read_csv(offline / "factor_values.csv"), NAMES[key])
    with pytest.raises(SystemExit) as error:
        runner.main(
            [
                "--output-dir",
                str(tmp_path / "conflict"),
                "--panel",
                str(initial / "panel"),
                "--factor-mode",
                "native",
            ]
        )
    assert error.value.code == 2


@pytest.mark.parametrize("key", ("025", "026"))
@pytest.mark.parametrize("mode", ("native", "build"))
@pytest.mark.parametrize("runnext", (False, True))
def test_batches_preserve_reordered_assets_and_full_panel(
    key, mode, runnext, monkeypatch, tmp_path
):
    runner = load_runner(key)
    monkeypatch.syspath_prepend(str(RUNNERS[key].parent))
    source = tmp_path / "source"
    symbols, _ = write_panel(source, count=4)
    manifest_file = source / "_metadata" / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["output"]["symbols"].reverse()
    manifest_file.write_text(json.dumps(manifest))
    cfg = config_for(runner, source)
    cfg["factor_mode"] = mode
    inputs = runner.load_daily_panel(cfg["data"])
    assert inputs["assets"] == tuple(reversed(symbols))

    def fresh():
        return {**inputs, "feeds": {name: frame.copy() for name, frame in inputs["feeds"].items()}}

    strategy, whole, broker = runner._run_native_collection(cfg, fresh(), runnext)
    batched, batch_broker = runner._run_batched_collection(cfg, fresh(), runnext, batch_size=3)
    assert runner._actual_factor_mode(strategy, mode) == mode
    for name in NAMES[key]:
        for instance in strategy._factor_instances_by_name[name]:
            diagnostics = instance.lifecycle_diagnostics
            assert diagnostics["coverage_matches"]
            assert diagnostics["coverage_count"] == diagnostics["grid_count"] == len(whole.grid)
    assert (broker.submit_count, broker.cancel_count) == (0, 0)
    assert batch_broker == {"submit": 0, "cancel": 0}
    assert whole.target_order == batched.target_order == inputs["assets"]
    assert whole.factor_order == batched.factor_order == NAMES[key]
    for attr in ("grid", "factors", "prices_open", "prices_close", "universe"):
        pd.testing.assert_frame_equal(
            getattr(whole, attr), getattr(batched, attr), rtol=1e-12, atol=1e-12
        )
    assert whole.groups == batched.groups
    assert whole.directions == batched.directions
