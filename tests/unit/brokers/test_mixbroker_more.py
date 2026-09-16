"""Tests for MixBroker additional scenarios."""

import json
import logging
import os
import sys
from types import SimpleNamespace

import backtrader.brokers.mixbroker as mixbroker_module
from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent, TickEvent
from backtrader.order import Order


class DummyData:
    """Dummy data for testing."""

    def __init__(self, name="BTC/USDT"):
        """Initialize dummy data."""
        self._name = name
        self.name = name
        self.symbol = name


def test_account_risk_windows_replace_requests_write_through(monkeypatch, tmp_path):
    """The Windows ledger fence must request a write-through replacement."""

    source = tmp_path / "ledger.tmp"
    target = tmp_path / "ledger.json"
    source.write_text("{}", encoding="utf-8")
    calls = []

    class FakeMoveFile:
        argtypes = None
        restype = None

        def __call__(self, *args):
            calls.append(args)
            return 1

    move_file = FakeMoveFile()
    fake_ctypes = SimpleNamespace(
        WinDLL=lambda *_args, **_kwargs: SimpleNamespace(MoveFileExW=move_file),
        c_wchar_p=str,
        c_uint=int,
        c_int=int,
        get_last_error=lambda: 0,
    )

    class WindowsOsProxy:
        name = "nt"

        def __getattr__(self, name):
            return getattr(os, name)

    monkeypatch.setattr(mixbroker_module, "os", WindowsOsProxy())
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    mixbroker_module._durable_replace(source, target)

    assert calls == [(str(source), str(target), 0x00000001 | 0x00000008)]


def test_account_risk_startup_and_persist_failures_log_exception_context(
    monkeypatch, tmp_path, bt_caplog
):
    """Fail-closed account-risk gates must retain their underlying I/O cause."""

    ledger = tmp_path / "risk.json"
    broker = MixBroker(
        cash=1000.0,
        account_risk_ledger_path=ledger,
        account_risk_venues=("OKX___SWAP",),
    )
    monkeypatch.setattr(
        mixbroker_module,
        "_durable_replace",
        lambda *_args: (_ for _ in ()).throw(OSError("write-through denied")),
    )

    with bt_caplog.at_level(logging.WARNING):
        broker.start()

    snapshot = broker.get_account_risk_snapshot()
    assert snapshot["trading_blocked"] is True
    assert snapshot["error_code"] == "account_risk_ledger_persist_failed"
    records = [
        record
        for record in bt_caplog.records
        if "account-risk ledger persistence failed" in record.getMessage()
    ]
    assert len(records) == 1
    assert records[0].exc_info is not None
    broker.stop()

    second = MixBroker(
        cash=1000.0,
        account_risk_ledger_path=tmp_path / "second.json",
        account_risk_venues=("OKX___SWAP",),
    )
    monkeypatch.setattr(
        mixbroker_module,
        "_acquire_nonblocking_file_lock",
        lambda _handle: (_ for _ in ()).throw(OSError("lock denied")),
    )
    bt_caplog.clear()
    with bt_caplog.at_level(logging.WARNING):
        second.start()

    assert second.get_account_risk_snapshot()["trading_blocked"] is True
    records = [
        record
        for record in bt_caplog.records
        if "account-risk ledger startup failed" in record.getMessage()
    ]
    assert len(records) == 1
    assert records[0].exc_info is not None
    second.stop()


def test_mixbroker_prefers_tick_over_bar_and_no_double_fill():
    """Test MixBroker prefers tick over bar and no double fill."""
    data = DummyData()
    broker = MixBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=data.name)
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)

    broker.process_tick(TickEvent(timestamp=1.0, symbol=data._name, price=100.0, volume=1.0))
    broker.process_bar(
        BarEvent(
            timestamp=2.0,
            symbol=data._name,
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=10.0,
        )
    )

    assert order.status == Order.Completed
    assert len(broker.order_history) == 1
    assert broker.order_history[0]["source"] == "tick"


def test_mixbroker_bar_does_not_act_as_timeout_fallback():
    """Test MixBroker bar does not act as timeout fallback."""
    data = DummyData()
    broker = MixBroker(cash=1000.0)
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Limit)

    broker.process_bar(
        BarEvent(
            timestamp=2.0,
            symbol=data._name,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=5.0,
        )
    )

    assert order.status != Order.Completed
    assert broker.pending_orders == [order]
    assert broker.order_history == []


def test_account_risk_snapshot_defaults_to_fail_closed():
    broker = MixBroker(cash=1000.0)
    broker.start()
    try:
        snapshot = broker.get_account_risk_snapshot()
        assert snapshot["durable"] is False
        assert snapshot["evidence_complete"] is False
        assert snapshot["trading_blocked"] is True
        assert snapshot["error_code"] == "account_risk_ledger_path_required"
    finally:
        broker.stop()


def test_account_risk_ledger_is_atomic_fenced_and_tracks_realized_net(tmp_path):
    ledger = tmp_path / "ignored-paper-risk.json"
    data = DummyData()
    broker = MixBroker(
        cash=1000.0,
        account_risk_ledger_path=ledger,
        account_risk_venues=("OKX___SWAP", "BINANCE___SWAP"),
        account_risk_persist_interval=0,
    )
    broker.setcommission(commission=0.0, name=data.name)
    broker.start()
    try:
        initial = broker.get_account_risk_snapshot()
        assert initial["configured_venues"] == ["binance", "okx"]
        assert initial["baseline_equity"] == initial["current_equity"] == 1000
        assert initial["realized_net"] == 0
        assert initial["generation"] == initial["fencing_epoch"] == 1
        assert initial["as_of_monotonic_ns"] > 0
        assert initial["durable"] is initial["evidence_complete"] is True
        assert initial["trading_blocked"] is False

        broker.buy(owner=None, data=data, size=1, price=100, exectype=Order.Market)
        broker.process_tick(TickEvent(timestamp=1.0, symbol=data.name, price=100, volume=1))
        broker.sell(owner=None, data=data, size=1, price=110, exectype=Order.Market)
        broker.process_tick(TickEvent(timestamp=2.0, symbol=data.name, price=110, volume=1))
        closed = broker.get_account_risk_snapshot()
        assert closed["current_equity"] == 1010
        assert closed["realized_net"] == 10
        closed["generation"] = 999
        assert broker.get_account_risk_snapshot()["generation"] == 1

        persisted = json.loads(ledger.read_text(encoding="utf-8"))
        assert persisted["schema_version"] == 2
        assert persisted["current_equity"] == "1010.0"
        assert persisted["realized_net"] == "10.0"
        assert persisted["session_state"] == "active"
        assert not list(tmp_path.glob(".*.tmp"))
    finally:
        broker.stop()

    sealed = json.loads(ledger.read_text(encoding="utf-8"))
    assert sealed["session_state"] == "closed"
    restarted = MixBroker(
        cash=1000.0,
        account_risk_ledger_path=ledger,
        account_risk_venues=("okx", "binance"),
    )
    restarted.start()
    try:
        snapshot = restarted.get_account_risk_snapshot()
        assert snapshot["generation"] == snapshot["fencing_epoch"] == 2
        assert snapshot["baseline_equity"] == 1000
        assert snapshot["current_equity"] == 1010
        assert snapshot["realized_net"] == 10
        assert restarted.getcash() == 1010
    finally:
        restarted.stop()


def test_account_risk_ledger_refuses_restart_after_open_exposure(tmp_path):
    ledger = tmp_path / "ignored-paper-risk.json"
    data = DummyData()
    broker = MixBroker(
        cash=1000.0,
        account_risk_ledger_path=ledger,
        account_risk_venues=("okx", "binance"),
        account_risk_persist_interval=0,
    )
    broker.start()
    broker.buy(owner=None, data=data, size=1, price=100, exectype=Order.Market)
    broker.process_tick(TickEvent(timestamp=1.0, symbol=data.name, price=100, volume=1))
    broker.stop()

    persisted = json.loads(ledger.read_text(encoding="utf-8"))
    assert persisted["session_state"] == "unsafe_open_exposure"
    restarted = MixBroker(
        cash=1000.0,
        account_risk_ledger_path=ledger,
        account_risk_venues=("okx", "binance"),
    )
    restarted.start()
    try:
        snapshot = restarted.get_account_risk_snapshot()
        assert snapshot["trading_blocked"] is True
        assert snapshot["error_code"] == "account_risk_ledger_previous_session_active"
    finally:
        restarted.stop()


def test_account_risk_ledger_rejects_second_writer_and_crash_active_reuse(tmp_path):
    ledger = tmp_path / "ignored-paper-risk.json"
    first = MixBroker(
        account_risk_ledger_path=ledger,
        account_risk_venues=("okx", "binance"),
    )
    second = MixBroker(
        account_risk_ledger_path=ledger,
        account_risk_venues=("okx", "binance"),
    )
    first.start()
    try:
        second.start()
        locked = second.get_account_risk_snapshot()
        assert locked["durable"] is False
        assert locked["trading_blocked"] is True
        assert locked["error_code"] == "account_risk_ledger_locked"

        # Model a process death: the OS lease disappears, while the last
        # durable record remains active and cannot be silently reset.
        first._release_account_risk_ledger()
        crashed = MixBroker(
            account_risk_ledger_path=ledger,
            account_risk_venues=("okx", "binance"),
        )
        crashed.start()
        snapshot = crashed.get_account_risk_snapshot()
        assert snapshot["durable"] is False
        assert snapshot["error_code"] == "account_risk_ledger_previous_session_active"
        crashed.stop()
    finally:
        second.stop()
        first._release_account_risk_ledger()
