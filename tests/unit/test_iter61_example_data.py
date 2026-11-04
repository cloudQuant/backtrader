"""Offline checks for the example data entrypoints."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "backtest"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cli(script, cwd, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_alignment_paths_allow_override_when_default_missing(tmp_path, monkeypatch, capsys):
    common = load(EXAMPLES / "002_hft_alignment_demo/common.py", "alignment_common")
    monkeypatch.setattr(common, "DEFAULT_DATA_DIR", tmp_path / "missing-default")
    parser = common.add_common_arguments(__import__("argparse").ArgumentParser())
    args = parser.parse_args(["--data-dir", str(tmp_path)])
    paths = common.resolve_paths(args)
    assert paths["market_data"] == tmp_path / "ETHUSDT_20240101.npz"
    assert common.missing_data(paths, ("market_data",))
    assert "BLOCKED" in capsys.readouterr().out


def test_alignment_missing_optional_dependency(monkeypatch, capsys):
    common = load(EXAMPLES / "002_hft_alignment_demo/common.py", "alignment_dependency")

    def fail(name):
        raise ModuleNotFoundError("missing transitive dependency")

    monkeypatch.setattr(common.importlib, "import_module", fail)
    assert common.hftbacktest_blocked() == 2
    assert "missing transitive dependency" in capsys.readouterr().out


def test_notebook_offline_default_and_explicit_download(tmp_path, monkeypatch, capsys):
    module = load(EXAMPLES / "003_hft_notebook_examples/prepare_data.py", "prepare_data")
    calls = []

    def prepare(data_root, source_root, project_root, date, skip_download):
        calls.append((source_root, skip_download))
        if skip_download:
            raise FileNotFoundError("local fixture missing")
        return {}

    monkeypatch.setattr(module, "_prepare_glft_dataset", prepare)
    monkeypatch.setattr(
        sys, "argv", ["prepare_data.py", "--prepare-glft", "--binance-project-root", str(tmp_path)]
    )
    assert module.main() == 2
    assert calls[-1] == (tmp_path / "data", True)
    assert "BLOCKED" in capsys.readouterr().out
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare_data.py",
            "--prepare-glft",
            "--download",
            "--binance-project-root",
            str(tmp_path),
        ],
    )
    assert module.main() == 0
    assert calls[-1] == (tmp_path / "data", False)


def test_notebook_explicit_root_does_not_fall_back(tmp_path):
    common = load(EXAMPLES / "003_hft_notebook_examples/common.py", "notebook_common")
    result = common.default_paths("glft_market_making", tmp_path)
    assert result["root"] == tmp_path / "ethusdt_20240101"
    assert common.missing_data(result)


def test_notebook_missing_local_source_never_downloads(tmp_path, monkeypatch):
    module = load(EXAMPLES / "003_hft_notebook_examples/prepare_data.py", "prepare_local")
    monkeypatch.setattr(
        module, "_run_local_downloader", lambda *a: pytest.fail("downloader called")
    )
    monkeypatch.setattr(
        module, "_direct_download_futures_daily", lambda *a: pytest.fail("network called")
    )
    monkeypatch.setattr(
        module, "_direct_download_spot_daily", lambda *a: pytest.fail("network called")
    )
    with pytest.raises(FileNotFoundError):
        module._ensure_local_futures_daily(
            tmp_path, tmp_path, "ETHUSDT", "trades", "2024-01-01", True
        )
    with pytest.raises(FileNotFoundError):
        module._resolve_local_spot_source(tmp_path, "BTCUSDT", "2024-01-01", True)


def test_optimizer_loads_external_zip(tmp_path):
    module = load(
        EXAMPLES / "020_bollinger_binance_optimizer/optimize_bollinger_strategy.py", "optimizer"
    )
    with zipfile.ZipFile(tmp_path / "fixture.zip", "w") as archive:
        archive.writestr(
            "fixture.csv", "open_time,open,high,low,close,volume\n1704067200000,1,2,1,2,5\n"
        )
    frame = module.load_binance_data(str(tmp_path))
    assert len(frame) == 1
    assert frame.iloc[0]["close"] == 2


def test_premium_external_input_does_not_resolve_default(tmp_path, monkeypatch):
    module = load(EXAMPLES / "021_premium_rate_crossover/run.py", "premium_example")
    csv = tmp_path / "data.csv"
    csv.write_text("x\n1\n")
    monkeypatch.setattr(module, "data_path", lambda *args: pytest.fail("resolved default fixture"))
    monkeypatch.setattr(module, "run_strategy", lambda **kwargs: (None, None, None))
    monkeypatch.setattr(module, "plot_results", lambda *args, **kwargs: None)
    assert module.main(["--data-file", str(csv), "--output-dir", str(tmp_path), "--no-show"]) == 0


def test_offline_cli_blocked_from_other_cwd(tmp_path):
    scripts = [
        (
            EXAMPLES / "002_hft_alignment_demo/run_backtrader.py",
            ["--data-dir", tmp_path / "missing"],
        ),
        (
            EXAMPLES / "003_hft_notebook_examples/run_backtrader.py",
            ["--data-root", tmp_path / "missing"],
        ),
        (
            EXAMPLES / "020_bollinger_binance_optimizer/optimize_bollinger_strategy.py",
            ["--data-dir", tmp_path / "missing"],
        ),
        (EXAMPLES / "021_premium_rate_crossover/run.py", ["--data-file", tmp_path / "missing.csv"]),
        (EXAMPLES / "022_cryptohftdata_sma/run.py", []),
    ]
    for script, args in scripts:
        result = cli(script, tmp_path, *args)
        assert result.returncode == 2, (script, result.stdout, result.stderr)
        assert "blocked" in result.stdout.lower(), (script, result.stdout, result.stderr)
