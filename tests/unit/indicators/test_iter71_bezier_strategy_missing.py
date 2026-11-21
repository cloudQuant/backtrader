"""Public synthetic Cerebro checks for the Bezier strategy's missing signals."""
import contextlib
import importlib.util
import io
import math
from pathlib import Path
import sys

import backtrader as bt
import pandas as pd
import pytest

path = Path(__file__).resolve().parents[3] / "tests/functional/strategies/volatility_systems/test_0028_0899_bezier_stdev.py"
spec = importlib.util.spec_from_file_location("bezier_regression_strategy", path)
strategy_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = strategy_module
spec.loader.exec_module(strategy_module)


class Probe(strategy_module.ExpBezierStDevStrategy):
    def __init__(self):
        super().__init__()
        self.rows, self.entries, self.exits = [], [], []
        self._closing = self._forced = False

    def buy(self, *args, **kwargs):
        if not self._closing and not self._forced:
            self.entries.append((len(self.signal_data), "buy"))
        return super().buy(*args, **kwargs)

    def sell(self, *args, **kwargs):
        if not self._closing and not self._forced:
            self.entries.append((len(self.signal_data), "sell"))
        return super().sell(*args, **kwargs)

    def close(self, *args, **kwargs):
        self.exits.append((len(self.signal_data), self.position.size))
        self._closing = True
        try:
            return super().close(*args, **kwargs)
        finally:
            self._closing = False

    def next(self):
        bar = len(self.signal_data)
        if bar >= 10:
            self.rows.append((bar, *(float(self.indicator.bezier[-i]) for i in range(3)),
                              float(self.indicator.bulls[0]), float(self.indicator.bears[0]),
                              self.position.size))
        if getattr(self, "force_order", None) and bar == self.force_bar:
            self._forced = True
            try:
                getattr(self, self.force_order)(size=1)
            finally:
                self._forced = False
        super().next()


def _frame(values):
    return pd.DataFrame({"open": values, "high": values, "low": values, "close": values,
                         "volume": [10.] * len(values), "openinterest": [0.] * len(values)},
                        index=pd.date_range("2024-01-01", periods=len(values), freq="D"))


def _run(values, runonce, *, modes=1, close_modes=1, force=None, risk=False, dk=2.0):
    base = [100.] * len(values)
    if risk:
        base[16] = 90.
    engine = bt.Cerebro(stdstats=False, runonce=runonce)
    engine.adddata(bt.feeds.PandasData(dataname=_frame(base)))
    engine.adddata(bt.feeds.PandasData(dataname=_frame(values)))
    engine.addstrategy(Probe, bperiod=2, std_period=2, ipc=0,
                       buy_open_mode=modes, sell_open_mode=modes,
                       buy_close_mode=close_modes, sell_close_mode=close_modes, dk=dk,
                       stop_loss_points=10 if risk else 0, take_profit_points=0, point=1.)
    Probe.force_order = force
    Probe.force_bar = 14 if risk else 19
    with contextlib.redirect_stdout(io.StringIO()):
        return engine.run(preload=True)[0]


def _values(direction="down"):
    tail = ([104., 103., 102., 101., 102., 103., 104., 105., 104., 103., 102., 103., 104.]
            if direction == "down" else
            [100., 102., 104., 106., 105., 104., 103., 102., 103., 104., 105., 106., 107.])
    return [100.] * 13 + [101., 102., 103., math.nan] + tail


@pytest.mark.parametrize("runonce", [False, True])
def test_direct_missing_current_or_history_never_opens_and_recovers(runonce):
    result = _run(_values(), runonce)
    rows = {row[0]: row for row in result.rows}
    assert math.isnan(rows[17][1]) and math.isfinite(rows[17][2])
    assert math.isfinite(rows[20][1]) and math.isnan(rows[20][2])
    assert math.isfinite(rows[21][1]) and math.isfinite(rows[21][2]) and math.isnan(rows[21][3])
    assert all(bar not in (17, 18, 19, 20, 21) for bar, _ in result.entries)
    assert (23, "buy") in result.entries


@pytest.mark.parametrize("runonce", [False, True])
def test_point_missing_does_not_become_nonzero_signal(runonce):
    result = _run(_values(), runonce, modes=0)
    rows = {row[0]: row for row in result.rows}
    assert math.isnan(rows[17][4]) and math.isnan(rows[17][5])
    assert not any(bar == 17 for bar, _ in result.entries)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("direction,force", [("down", "buy"), ("up", "sell")])
def test_direct_valid_two_point_exit_not_blocked_by_missing_third(runonce, direction, force):
    result = _run(_values(direction), runonce, force=force)
    row = {row[0]: row for row in result.rows}[21]
    assert math.isfinite(row[1]) and math.isfinite(row[2]) and math.isnan(row[3])
    assert (row[6] > 0) == (force == "buy")
    assert any(bar == 21 for bar, _ in result.exits)


@pytest.mark.parametrize("runonce", [False, True])
def test_risk_exit_remains_active_during_missing_indicator(runonce):
    result = _run(_values(), runonce, force="buy", risk=True)
    row = {row[0]: row for row in result.rows}[17]
    assert math.isnan(row[1]) and row[6] > 0
    assert any(bar == 17 and size > 0 for bar, size in result.exits)


@pytest.mark.parametrize("runonce", [False, True])
@pytest.mark.parametrize("direction,force", [("down", "buy"), ("up", "sell")])
def test_point_missing_does_not_close_and_finite_exit_recovers(runonce, direction, force):
    result = _run(_values(direction), runonce, modes=1, close_modes=0, force=force, dk=0.1)
    rows = {row[0]: row for row in result.rows}
    assert math.isnan(rows[20][4]) and math.isnan(rows[20][5])
    assert not any(bar == 20 for bar, _ in result.exits)
    assert any(bar >= 21 for bar, _ in result.exits)

