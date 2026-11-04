"""Offline regression tests for the Bollinger optimizer's process outcome."""

import importlib.util
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "examples/backtest/020_bollinger_binance_optimizer/optimize_bollinger_strategy.py"
)


@pytest.fixture
def optimizer():
    spec = importlib.util.spec_from_file_location("iter61_optimizer_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def synthetic_frame(unit="ms"):
    values = np.array(
        ["2024-01-01 12:34:56.123456789", "2024-01-01 12:34:57.987654321"],
        dtype="datetime64[ns]",
    ).astype("datetime64[%s]" % unit)
    index = pd.DatetimeIndex(values)
    return pd.DataFrame(
        {name: [1.0, 2.0] for name in ("open", "high", "low", "close", "volume")}, index=index
    )


def result_for(params):
    return {
        "params": params,
        "return_pct": 1.0,
        "sharpe_ratio": 1.0,
        "max_drawdown": 0.0,
        "total_trades": 1,
        "win_rate": 100.0,
        "final_value": 10100.0,
    }


class FakePool:
    def __init__(self, processes, *, all_fail=False):
        self.closed = False
        self.all_fail = all_fail

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def imap_unordered(self, worker, params):
        if self.all_fail:
            return iter([None for _ in params])
        return iter([worker(params[0])])


def execute_cli(module, monkeypatch, args):
    # Execute the script's real CLI block while substituting only its I/O and
    # backtest functions. The synthetic ZIP is only checked for existence.
    source = SCRIPT.read_text(encoding="utf-8")
    marker = "\nif __name__ == '__main__':"
    assert source.count(marker) == 1
    cli = marker + source.split(marker, 1)[1]
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *map(str, args)])
    module.__name__ = "__main__"
    exec(compile(cli, str(SCRIPT), "exec"), module.__dict__)


@pytest.mark.parametrize("multiprocessing", [False, True])
def test_cli_all_parameter_combinations_fail_exit_one(
    tmp_path, monkeypatch, optimizer, capsys, multiprocessing
):
    (tmp_path / "fixture.zip").touch()
    monkeypatch.setattr(optimizer, "load_binance_data", lambda *args: synthetic_frame())
    monkeypatch.setattr(optimizer, "cpu_count", lambda: 4)
    pools = []
    if multiprocessing:

        def create_pool(processes):
            pool = FakePool(processes, all_fail=True)
            pools.append(pool)
            return pool

        monkeypatch.setattr(optimizer, "Pool", create_pool)
    else:

        def fail(*args):
            raise RuntimeError("synthetic backtest failure")

        monkeypatch.setattr(optimizer, "run_single_backtest", fail)
    args = ["--data-dir", tmp_path, "--output-dir", tmp_path / "out"]
    if not multiprocessing:
        args.append("--no-multiprocessing")
    with pytest.raises(SystemExit) as exc:
        execute_cli(optimizer, monkeypatch, args)
    assert exc.value.code == 1
    output = capsys.readouterr().out
    assert "No valid backtest results!" in output
    assert not (tmp_path / "out" / "optimization_results.csv").exists()
    assert all(pool.closed for pool in pools)
    assert len(pools) == int(multiprocessing)


def test_cli_missing_input_remains_blocked_exit_two(tmp_path, monkeypatch, optimizer, capsys):
    with pytest.raises(SystemExit) as exc:
        execute_cli(optimizer, monkeypatch, ["--data-dir", tmp_path / "missing"])
    assert exc.value.code == 2
    assert "BLOCKED" in capsys.readouterr().out


@pytest.mark.parametrize("multiprocessing", [False, True])
def test_cli_all_fail_actual_process_exit(tmp_path, multiprocessing):
    (tmp_path / "fixture.zip").touch()
    launcher = tmp_path / "synthetic_cli.py"
    launcher.write_text(
        """import importlib.util
from pathlib import Path
import sys
import pandas as pd
script = Path(sys.argv[1])
directory = Path(sys.argv[2])
use_pool = sys.argv[3] == "pool"
spec = importlib.util.spec_from_file_location("optimizer_child", script)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.load_binance_data = lambda *args: pd.DataFrame(
    {name: [1.0] for name in ("open", "high", "low", "close", "volume")},
    index=pd.to_datetime(["2024-01-01"]),
)
module.cpu_count = lambda: 4
def fail(*args):
    raise RuntimeError("synthetic backtest failure")
module.run_single_backtest = fail
class FakePool:
    def __init__(self, processes): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def imap_unordered(self, worker, params): return iter([None for _ in params])
module.Pool = FakePool
sys.argv = [str(script), "--data-dir", str(directory), "--output-dir", str(directory / "out")]
if not use_pool:
    sys.argv.append("--no-multiprocessing")
module.__name__ = "__main__"
source = script.read_text(encoding="utf-8")
marker = "\\nif __name__ == '__main__':"
exec(compile(marker + source.split(marker, 1)[1], str(script), "exec"), module.__dict__)
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            "/Users/yunjinqi/opt/anaconda3/bin/conda",
            "run",
            "--no-capture-output",
            "-n",
            "base",
            "python",
            str(launcher),
            str(SCRIPT),
            str(tmp_path),
            "pool" if multiprocessing else "single",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "No valid backtest results!" in result.stdout
    assert not (tmp_path / "out" / "optimization_results.csv").exists()


@pytest.mark.parametrize("multiprocessing", [False, True])
def test_cli_with_valid_result_completes(tmp_path, monkeypatch, optimizer, multiprocessing):
    (tmp_path / "fixture.zip").touch()
    monkeypatch.setattr(optimizer, "load_binance_data", lambda *args: synthetic_frame())
    monkeypatch.setattr(optimizer, "cpu_count", lambda: 4)
    pools = []
    seen = []

    def backtest(frame, params):
        if seen:
            raise RuntimeError("only one synthetic success")
        seen.append(True)
        return result_for(params)

    def create_pool(processes):
        pool = FakePool(processes)
        pools.append(pool)
        return pool

    monkeypatch.setattr(optimizer, "run_single_backtest", backtest)
    monkeypatch.setattr(optimizer, "Pool", create_pool)
    args = ["--data-dir", tmp_path, "--output-dir", tmp_path / "out"]
    if not multiprocessing:
        args.append("--no-multiprocessing")
    with redirect_stdout(io.StringIO()):
        execute_cli(optimizer, monkeypatch, args)
    assert (tmp_path / "out" / "optimization_results.csv").is_file()
    assert len(pools) == int(multiprocessing)
    assert all(pool.closed for pool in pools)


def test_legacy_worker_dictionary_defaults_to_milliseconds(monkeypatch, optimizer):
    data = synthetic_frame("ms")
    captured = []
    monkeypatch.setattr(
        optimizer, "run_single_backtest", lambda frame, params: captured.append(frame.index) or {}
    )
    payload = {name: data[name].tolist() for name in ("open", "high", "low", "close", "volume")}
    payload["dates"] = (
        data.index.to_numpy(dtype="datetime64[ns]").astype("int64") // 1000000
    ).tolist()
    assert optimizer.run_backtest_with_dict({}, payload) == {}
    np.testing.assert_array_equal(
        captured[0].to_numpy(dtype="datetime64[ns]"), data.index.to_numpy(dtype="datetime64[ns]")
    )


@pytest.mark.parametrize("unit", ["ns", "us", "ms"])
@pytest.mark.parametrize("multiprocessing", [False, True])
def test_process_modes_preserve_timestamps(tmp_path, monkeypatch, optimizer, unit, multiprocessing):
    data = synthetic_frame(unit)
    if np.datetime_data(data.index.to_numpy().dtype)[0] != unit:
        pytest.skip("this pandas version normalizes the input index to a different unit")
    captured = []
    pools = []
    monkeypatch.setattr(optimizer, "load_binance_data", lambda *args: data)
    monkeypatch.setattr(optimizer, "cpu_count", lambda: 4)

    def backtest(frame, params):
        if captured and not multiprocessing:
            raise RuntimeError("only one synthetic success")
        captured.append(frame.index)
        return result_for(params)

    def create_pool(processes):
        pool = FakePool(processes)
        pools.append(pool)
        return pool

    monkeypatch.setattr(optimizer, "run_single_backtest", backtest)
    monkeypatch.setattr(optimizer, "Pool", create_pool)
    with redirect_stdout(io.StringIO()):
        results = optimizer.run_optimization(
            str(tmp_path), use_multiprocessing=multiprocessing, output_dir=str(tmp_path / "out")
        )
    assert len(results) == 1
    assert len(captured) == 1
    np.testing.assert_array_equal(
        captured[0].to_numpy(dtype="datetime64[ns]"), data.index.to_numpy(dtype="datetime64[ns]")
    )
    assert (tmp_path / "out" / "optimization_results.csv").is_file()
    assert all(pool.closed for pool in pools)
    assert len(pools) == int(multiprocessing)
