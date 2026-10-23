"""Exercise the quick CLI's engine selection on real seven-column synthetic bars."""

import hashlib
import json

import pandas as pd
import pytest

from tests.unit.test_factor_research_examples import (
    THIRD_RUNNER,
    _example_config,
    _load_module,
    _write_daily_panel,
)


@pytest.mark.parametrize("factor_mode", ("native", "build"))
def test_quick_cli_once_and_runnext_preserve_outputs(tmp_path, monkeypatch, factor_mode):
    root = tmp_path / "a_stocks"
    symbols, dates = _write_daily_panel(root, symbol_count=5, day_count=35)
    manifest_path = root / "_metadata/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    columns = ("trade_time", "open", "high", "low", "close", "volume", "amount")
    for entry in manifest["output"]["symbols"]:
        path = root / entry["file"]
        pd.read_csv(path).loc[:, list(columns)].to_csv(path, index=False)
        raw = path.read_bytes()
        entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    runner = _load_module(THIRD_RUNNER, "alpha003_quick_engine_" + factor_mode)
    monkeypatch.setattr(runner, "_load_config", lambda: _example_config(runner, root))
    original = runner._run_factor
    calls = []

    def observe(config, panel, **kwargs):
        calls.append(kwargs.copy())
        return original(config, panel, **kwargs)

    monkeypatch.setattr(runner, "_run_factor", observe)
    outputs = []
    for engine_args, name in (([], "once"), (["--runnext"], "next")):
        output = tmp_path / name
        assert runner.main(
            ["--output-dir", str(output), "--factor-mode", factor_mode] + engine_args
        ) == 0
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        assert summary["broker"] == {"submit": 0, "cancel": 0}
        assert summary["factor_mode"] == factor_mode
        assert summary["symbols"] == len(symbols)
        assert summary["dates"] == len(dates)
        assert summary["finite"] > 0
        summary.pop("elapsed_seconds")
        outputs.append(((output / "factor_values.csv").read_bytes(), summary))
    assert calls == [
        {"consume_source_frames": True, "runonce": True},
        {"consume_source_frames": True, "runonce": False},
    ]
    assert outputs[0] == outputs[1]
