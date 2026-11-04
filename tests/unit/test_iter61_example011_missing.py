"""Missing local fixtures should report a controlled block for both HFT examples."""

import importlib.util
from pathlib import Path
import sys

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/backtest/011_hft_backtest"


@pytest.mark.parametrize(
    ("filename", "fixture", "generator"),
    [
        ("tick_backtest.py", "tests/datas/tick_data/tick_BTC_USDT.csv", "--type tick"),
        (
            "orderbook_backtest.py",
            "tests/datas/tick_data/orderbook_BTC_USDT.jsonl",
            "--type orderbook",
        ),
    ],
)
def test_missing_fixture_is_blocked(filename, fixture, generator, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("iter61_011_missing", EXAMPLE / filename)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    requested = []

    def missing(path):
        requested.append(path)
        raise FileNotFoundError(path)

    monkeypatch.setattr(module, "data_path", missing)
    with pytest.raises(SystemExit) as caught:
        module.main()

    assert caught.value.code == 2
    assert requested == [fixture]
    output = capsys.readouterr().out
    assert "BLOCKED" in output
    assert fixture in output
    assert "python tools/generate_test_data.py " + generator in output


@pytest.mark.parametrize("filename", ["tick_backtest.py", "orderbook_backtest.py"])
def test_other_input_errors_are_not_reported_as_missing(filename, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("iter61_011_other", EXAMPLE / filename)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    def denied(path):
        raise PermissionError(path)

    monkeypatch.setattr(module, "data_path", denied)
    with pytest.raises(PermissionError):
        module.main()
    assert "BLOCKED" not in capsys.readouterr().out
