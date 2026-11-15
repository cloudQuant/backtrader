"""D63-45 baseline observations only; no orders, account I/O or fake books.

D63-45 requires explicit initial allocation and additional compatibility
work. Equal account getter results do not establish that requirement.
"""

from pathlib import Path
import sys

import backtrader as bt
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    assert Path(bt.__file__).resolve().is_relative_to(ROOT)
    yield
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(ROOT):
                escaped[name] = source
    assert not escaped, f"non-worktree modules: {escaped}"


class Observe(bt.Strategy):
    params = (("label", "strategy"),)

    def __init__(self):
        self.observations = []
        self.observe("init")

    def start(self):
        self.observe("start")

    def next(self):
        self.observe("next")

    def observe(self, phase):
        values = {}
        for key, method in (("cash", self.get_strategy_cash), ("value", self.get_strategy_value),
                            ("position", self.get_strategy_position)):
            try:
                value = method()
                values[key] = ("ok", value.size if key == "position" else value)
            except Exception as exc:
                values[key] = ("error", type(exc).__name__, str(exc))
        self.observations.append((phase, values))


def run_case(cash, strategies):
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    if cash is not None:
        cerebro.broker.setcash(cash)
    bars = pd.DataFrame({"open": [100.0] * 2, "high": [100.0] * 2, "low": [100.0] * 2,
                         "close": [100.0] * 2, "volume": [1.0] * 2},
                        index=pd.date_range("2026-11-12", periods=2, freq="min"))
    cerebro.adddata(bt.feeds.PandasData(dataname=bars, name="synthetic"))
    for label in range(strategies):
        cerebro.addstrategy(Observe, label=str(label))
    result = cerebro.run()
    return cerebro.broker, result


UNAVAILABLE = {
    "cash": ("error", "RuntimeError", "STRATEGY_CASH_UNAVAILABLE"),
    "value": ("error", "RuntimeError", "STRATEGY_VALUE_UNAVAILABLE"),
    "position": ("error", "RuntimeError", "STRATEGY_POSITION_UNAVAILABLE"),
}


def outcomes(cash):
    return {"cash": ("ok", cash), "value": ("ok", cash), "position": ("ok", 0)}


@pytest.mark.parametrize("initial", [None, 10000, 12345], ids=["default", "explicit_default", "explicit_other"])
def test_single_strategy_lifecycle(initial):
    broker, (strategy,) = run_case(initial, 1)
    expected = 10000.0 if initial is None else float(initial)
    assert broker.getcash() == broker.getvalue() == expected
    assert strategy.observations == [
        ("init", UNAVAILABLE), ("start", outcomes(expected)),
        ("next", outcomes(expected)), ("next", outcomes(expected)),
    ]


def test_default_and_explicit_same_amount_have_same_observed_strategy_getters():
    _, (default,) = run_case(None, 1)
    _, (explicit,) = run_case(10000, 1)
    assert default.observations == explicit.observations


def test_two_unallocated_strategies_have_no_strategy_getters_in_any_phase():
    broker, strategies = run_case(12345, 2)
    assert broker.getcash() == broker.getvalue() == 12345
    assert len(strategies) == 2
    for strategy in strategies:
        assert strategy.observations == [
            ("init", UNAVAILABLE), ("start", UNAVAILABLE),
            ("next", UNAVAILABLE), ("next", UNAVAILABLE),
        ]


def test_backbroker_inherits_unavailable_strategy_interfaces():
    for name in ("get_strategy_cash", "get_strategy_value", "get_strategy_position"):
        assert getattr(bt.brokers.BackBroker, name) is getattr(bt.BrokerBase, name)
