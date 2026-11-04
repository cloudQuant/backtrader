"""The configurable example reports actual results without fixed-value gates."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DIR = ROOT / "examples/backtest/001_multi_extend_data"


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE_DIR))
    spec = importlib.util.spec_from_file_location("iter61_example001", EXAMPLE_DIR / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Analysis:
    def __init__(self, values):
        self.values = values

    def get_analysis(self):
        return self.values


def fake_run(monkeypatch, runner, tmp_path, *, bars, trades, sharpe, max_bonds):
    config = tmp_path / "synthetic-settings.yaml"
    config.write_text(
        yaml.safe_dump({"params": {"hold_percent": 3}, "backtest": {"initial_cash": 1000}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "load_config", lambda: yaml.safe_load(config.read_text()))
    monkeypatch.setattr(runner, "data_path", lambda path: tmp_path / "public-fixture.csv")
    monkeypatch.setattr(
        runner.pd,
        "read_csv",
        lambda path: pd.DataFrame({"datetime": ["2024-01-01"], "close": [100.0]}),
    )
    frame = pd.DataFrame({"close": [100.0] * 31})
    monkeypatch.setattr(runner, "clean_data", lambda: {"A": frame, "B": frame, "C": frame})
    monkeypatch.setattr(runner, "ExtendPandasFeed", lambda dataname: dataname)

    analyzers = SimpleNamespace(
        my_sharpe=Analysis({"sharperatio": sharpe}),
        my_returns=Analysis({"rnorm": 0.012}),
        my_drawdown=Analysis({"max": {"drawdown": 3.0}}),
        my_trade_analyzer=Analysis({"total": {"total": trades}}),
    )
    strategy = SimpleNamespace(bar_num=bars, analyzers=analyzers)
    result = [strategy]
    captured = {"feeds": []}

    class Broker:
        def setcash(self, value):
            captured["cash"] = value

        def addcommissioninfo(self, commission, name):
            pass

    class Cerebro:
        def __init__(self, stdstats):
            self.broker = Broker()

        def addstrategy(self, strategy_cls, **params):
            captured["params"] = params

        def adddata(self, feed, name):
            captured["feeds"].append(name)

        def addanalyzer(self, *args, **kwargs):
            pass

        def addobserver(self, *args, **kwargs):
            pass

        def run(self):
            return result

    monkeypatch.setattr(runner.bt, "Cerebro", Cerebro)
    return result, captured, lambda: runner.run(max_bonds=max_bonds)


@pytest.mark.parametrize(
    ("bars", "trades", "sharpe", "max_bonds"),
    [(71, 0, None, 1), (1885, 12, None, 2), (490, 7, 1.25, 3)],
)
def test_configured_run_returns_actual_results(
    monkeypatch, runner, tmp_path, capsys, bars, trades, sharpe, max_bonds
):
    expected, captured, execute = fake_run(
        monkeypatch, runner, tmp_path, bars=bars, trades=trades, sharpe=sharpe, max_bonds=max_bonds
    )

    assert execute() is expected
    assert captured["params"] == {"hold_percent": 3}
    assert captured["cash"] == 1000
    assert captured["feeds"] == ["000000", *["A", "B", "C"][:max_bonds]]
    output = capsys.readouterr().out
    assert "bar_num: %s" % bars in output
    assert "trade_num: %s" % trades in output
    assert "sharpe_ratio: %s" % sharpe in output
    assert "All tests passed!" not in output


def test_backtest_errors_still_propagate(monkeypatch, runner, tmp_path):
    _, _, execute = fake_run(
        monkeypatch, runner, tmp_path, bars=10, trades=0, sharpe=None, max_bonds=1
    )
    cerebro = runner.bt.Cerebro

    class FailingCerebro(cerebro):
        def run(self):
            raise RuntimeError("synthetic backtest failure")

    monkeypatch.setattr(runner.bt, "Cerebro", FailingCerebro)
    with pytest.raises(RuntimeError, match="synthetic backtest failure"):
        execute()
