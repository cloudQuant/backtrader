"""Offline CLI checks for missing example configuration files."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = {
    "016": ROOT / "examples/backtest/016_self_similarity/run.py",
    "017": ROOT / "examples/backtest/017_fnn_embedding/run.py",
    "018": ROOT / "examples/backtest/018_sma_crossover/run.py",
}
CONDA = "/Users/yunjinqi/opt/anaconda3/bin/conda"


@pytest.fixture(params=tuple(SCRIPTS))
def runner(request, monkeypatch):
    name = request.param
    script = SCRIPTS[name]
    monkeypatch.syspath_prepend(str(script.parent))
    spec = importlib.util.spec_from_file_location("iter61_example_" + name, script)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return name, module


@pytest.mark.parametrize("name", tuple(SCRIPTS))
@pytest.mark.parametrize("relative", (False, True), ids=("absolute", "relative"))
def test_missing_config_reports_blocked_in_real_cli(name, relative, tmp_path):
    missing = tmp_path / "missing-input.yaml"
    argument = missing.name if relative else str(missing)
    env = {
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(ROOT),
    }
    process = subprocess.run(
        [
            CONDA,
            "run",
            "--no-capture-output",
            "-n",
            "base",
            "python",
            str(SCRIPTS[name]),
            "--config",
            argument,
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert process.returncode == 2, process.stdout + process.stderr
    output = process.stdout + process.stderr
    assert "BLOCKED" in output
    assert argument in output
    assert "--config" in output
    assert "Traceback" not in output
    assert sorted(tmp_path.iterdir()) == []


def test_non_configuration_missing_and_permission_errors_propagate(runner, monkeypatch, tmp_path):
    name, module = runner
    config = tmp_path / "input.yaml"
    loader_name = "_load_config" if name == "018" else "load_yaml_config"
    nested = tmp_path / "another-file.yaml"

    def fail_missing(_):
        raise FileNotFoundError(2, "synthetic missing nested file", str(nested))

    monkeypatch.setattr(module, loader_name, fail_missing)
    with pytest.raises(FileNotFoundError) as caught:
        module.main(["--config", str(config)])
    assert caught.value.filename == str(nested)

    def fail_permission(_):
        raise PermissionError(13, "synthetic permission error", str(config))

    monkeypatch.setattr(module, loader_name, fail_permission)
    with pytest.raises(PermissionError):
        module.main(["--config", str(config)])


def test_invalid_yaml_is_not_reported_as_missing(runner, tmp_path):
    _, module = runner
    config = tmp_path / "input.yaml"
    config.write_text("not: [valid\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        module.main(["--config", str(config)])


def test_later_missing_data_is_not_reported_as_missing_config(
    runner, monkeypatch, tmp_path, capsys
):
    name, module = runner
    config = tmp_path / "input.yaml"
    missing = tmp_path / "synthetic-data.csv"

    def fail(*args, **kwargs):
        raise FileNotFoundError(2, "synthetic missing data", str(missing))

    if name in ("016", "017"):
        config.write_text("mode: backtest\n", encoding="utf-8")
        monkeypatch.setattr(module, "run_single", fail)
    else:
        config.write_text(
            "fast: 2\nslow: 5\ncash: 1000\ndata_file: synthetic.csv\n", encoding="utf-8"
        )
        assert module.main(["--config", str(config)]) == 2
        output = capsys.readouterr().err
        assert "BLOCKED" in output and str(tmp_path / "synthetic.csv") in output
        return
    with pytest.raises(FileNotFoundError) as caught:
        module.main(["--config", str(config)])
    assert caught.value.filename == str(missing)


def test_synthetic_config_still_reaches_success_path(runner, monkeypatch, tmp_path, capsys):
    name, module = runner
    config = tmp_path / "input.yaml"
    calls = []
    if name in ("016", "017"):
        config.write_text("mode: backtest\n", encoding="utf-8")

        def run_single(cfg, **kwargs):
            calls.append((cfg, kwargs))
            return dict(trade_num=0, sum_profit=0, final_value=1000, sharpe_ratio=0, max_drawdown=0)

        monkeypatch.setattr(module, "run_single", run_single)
    else:
        config.write_text(
            "fast: 2\nslow: 5\ncash: 1000\ndata_file: synthetic.csv\n", encoding="utf-8"
        )
        (tmp_path / "synthetic.csv").touch()

        class Broker:
            def setcash(self, value):
                calls.append(("cash", value))

            def getvalue(self):
                return 1000

        class Cerebro:
            broker = Broker()

            def adddata(self, data):
                calls.append(("data", data))

            def addstrategy(self, strategy, **kwargs):
                calls.append(("strategy", kwargs))

            def run(self):
                return [type("Result", (), {"data": [1, 2, 3]})()]

        monkeypatch.setattr(module.bt, "Cerebro", Cerebro)
        monkeypatch.setattr(module.bt.feeds, "BacktraderCSVData", lambda **kwargs: kwargs)
    assert module.main(["--config", str(config)]) == 0
    assert calls
    assert "final" in capsys.readouterr().out.lower()
    expected = ["input.yaml", "synthetic.csv"] if name == "018" else ["input.yaml"]
    assert sorted(p.name for p in tmp_path.iterdir()) == expected


@pytest.mark.parametrize("kind", ("absolute", "config-relative", "root-relative"))
@pytest.mark.parametrize("same_cwd", (False, True), ids=("other-cwd", "config-cwd"))
def test_018_real_cli_accepts_declared_data_path(kind, same_cwd, tmp_path):
    config_dir = tmp_path / "configuration"
    config_dir.mkdir()
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    local_data = config_dir / "fixture.csv"
    shutil.copyfile(ROOT / "tests/datas/2006-day-001.txt", local_data)
    # The root-relative namespace takes precedence even if the config directory
    # contains a same-named, unusable file.
    shadow = config_dir / "tests/datas/2006-day-001.txt"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("not a valid CSV\n", encoding="utf-8")
    value = {
        "absolute": str(local_data),
        "config-relative": "fixture.csv",
        "root-relative": "tests/datas/2006-day-001.txt",
    }[kind]
    config = config_dir / "input.yaml"
    config.write_text(
        yaml.safe_dump(dict(fast=2, slow=5, cash=1000, data_file=value)), encoding="utf-8"
    )
    env = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(ROOT)}
    process = subprocess.run(
        [
            CONDA,
            "run",
            "--no-capture-output",
            "-n",
            "base",
            "python",
            str(SCRIPTS["018"]),
            "--config",
            str(config),
        ],
        cwd=config_dir if same_cwd else other_dir,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert "bars:" in process.stdout and "final portfolio value:" in process.stdout
    assert list(other_dir.iterdir()) == []


@pytest.mark.parametrize("kind", ("absolute", "config-relative", "root-relative"))
def test_018_missing_data_is_blocked_with_explicit_location(kind, tmp_path, monkeypatch, capsys):
    script = SCRIPTS["018"]
    monkeypatch.syspath_prepend(str(script.parent))
    spec = importlib.util.spec_from_file_location("iter61_example_018_missing", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = {
        "absolute": str(tmp_path / "missing.csv"),
        "config-relative": "missing.csv",
        "root-relative": "tests/datas/iter61-nonexistent.csv",
    }[kind]
    config = tmp_path / "input.yaml"
    config.write_text(
        yaml.safe_dump(dict(fast=2, slow=5, cash=1000, data_file=value)), encoding="utf-8"
    )
    if kind != "root-relative":
        monkeypatch.setattr(module, "data_path", lambda value: pytest.fail("unexpected fallback"))
    assert module.main(["--config", str(config)]) == 2
    output = capsys.readouterr().err
    assert "BLOCKED" in output and "data_file" in output
    assert "missing.csv" in output or "iter61-nonexistent.csv" in output


def test_018_other_data_errors_are_not_blocked(tmp_path, monkeypatch):
    script = SCRIPTS["018"]
    monkeypatch.syspath_prepend(str(script.parent))
    spec = importlib.util.spec_from_file_location("iter61_example_018_errors", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = tmp_path / "input.yaml"
    config.write_text(
        yaml.safe_dump(dict(fast=2, slow=5, cash=1000, data_file=str(tmp_path))),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not a regular file"):
        module.main(["--config", str(config)])

    def denied(*args):
        raise PermissionError(13, "synthetic permission error")

    monkeypatch.setattr(module, "_resolve_data_file", denied)
    with pytest.raises(PermissionError):
        module.main(["--config", str(config)])
