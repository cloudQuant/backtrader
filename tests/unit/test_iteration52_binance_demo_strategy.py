"""Focused state-machine regressions for the iteration-52 Binance demo strategy."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
STRATEGY_PATH = (
    ROOT
    / "examples"
    / "unified"
    / "052_binance_demo_roundtrip"
    / "binance_demo_roundtrip_strategy.py"
)


def _load_strategy_class():
    spec = importlib.util.spec_from_file_location("i52_binance_demo_strategy", STRATEGY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.BinanceDemoRoundTripStrategy


class _Executed:
    def __init__(self, size=0.0, price=0.0, value=0.0, comm=0.0):
        self.size = size
        self.price = price
        self.value = value
        self.comm = comm


class _Order:
    def __init__(self, ref, status, executed=None):
        self.ref = ref
        self._status = status
        self.executed = executed or _Executed()
        self.info = {}

    def getstatusname(self):
        return self._status

    def alive(self):
        return self._status in ("Submitted", "Accepted", "Partial")


def _strategy():
    cls = _load_strategy_class()
    strategy = object.__new__(cls)
    strategy.p = SimpleNamespace(
        cancel_after_seconds=6.0,
        hard_timeout_seconds=45.0,
        notional_usdt=150.0,
        step_size=0.001,
        tick_size=0.10,
        offset_bps=200.0,
    )
    strategy._phase = "waiting"
    strategy._open_order = None
    strategy._close_order = None
    strategy._cancel_at = None
    strategy._hard_deadline = 10**12
    strategy._cancel_requested = False
    strategy._events = []
    strategy._idle_calls = 0
    strategy._maintenance_calls = 0
    strategy._cancel_error = None
    strategy._maintenance_state = None
    strategy._stop_calls = []
    strategy.env = SimpleNamespace(runstop=lambda: strategy._stop_calls.append(1))
    return strategy


def test_accepted_and_canceled_by_order_ref_drive_the_round_trip():
    strategy = _strategy()
    open_order = _Order(1, "Submitted")
    strategy._open_order = open_order
    strategy.notify_order(_Order(1, "Accepted"))
    assert strategy._phase == "resting"
    assert strategy._cancel_at is not None
    strategy.notify_order(_Order(1, "Canceled"))
    assert strategy._phase == "canceled"
    assert strategy._stop_calls == [1]
    assert strategy.session_facts()["open_order"]["status"] == "Canceled"


def test_foreign_order_ref_does_not_change_state():
    strategy = _strategy()
    strategy._open_order = _Order(1, "Submitted")
    strategy._phase = "submitted"
    strategy.notify_order(_Order(99, "Accepted"))
    assert strategy._phase == "submitted"


def test_partial_fill_then_cancel_flattens_reduce_only():
    strategy = _strategy()
    open_order = _Order(1, "Submitted")
    strategy._open_order = open_order
    strategy.notify_order(_Order(1, "Accepted"))
    strategy.notify_order(_Order(1, "Partial", _Executed(size=0.002)))
    created = []
    strategy.sell = lambda **kwargs: created.append(kwargs) or _Order(2, "Submitted")
    strategy.notify_order(_Order(1, "Canceled", _Executed(size=0.002)))
    assert strategy._phase == "flattening"
    assert created[0]["reduce_only"] is True
    assert created[0]["offset"] == "close"
    assert created[0]["size"] == 0.002
