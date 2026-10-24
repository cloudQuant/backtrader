"""Opt-in live-cohort Store event bridge contracts."""

import threading
import time
from types import SimpleNamespace

import pytest

from backtrader._cerebro.runnext import (
    _LiveBarCohortWake,
    _cap_live_cohort_wait_for_broker,
    _cleanup_live_bar_cohort_wakers,
    _live_cohort_broker_timeout,
)
from backtrader.cerebro import Cerebro
from backtrader.stores.btapistore import BtApiStore


class _EventWakerApi:
    def __init__(self):
        self.callbacks = {}
        self.register_calls = 0
        self.unregister_calls = 0

    def register_event_waker(self, callback):
        self.register_calls += 1
        token = object()
        self.callbacks[token] = callback
        return token

    def unregister_event_waker(self, token):
        self.unregister_calls += 1
        return self.callbacks.pop(token, None) is not None

    def emit(self):
        for callback in tuple(self.callbacks.values()):
            callback()


class _Order:
    def __init__(self, info):
        self.info = info

    def alive(self):
        return True


def test_store_uses_one_sdk_waker_for_multiple_engine_callbacks():
    api = _EventWakerApi()
    store = BtApiStore(provider="btapi", api=api)
    seen = []
    first = store._register_live_bar_event_waker(lambda: seen.append("first"))
    second = store._register_live_bar_event_waker(lambda: seen.append("second"))

    assert api.register_calls == 1
    before = store._live_bar_event_snapshot()
    api.emit()
    assert store._live_bar_event_snapshot() == before + 1
    assert seen == ["first", "second"]

    store._unregister_live_bar_event_waker(first)
    before = store._live_bar_event_snapshot()
    api.emit()
    assert store._live_bar_event_snapshot() == before + 1
    assert seen == ["first", "second", "second"]
    assert api.unregister_calls == 0

    store._unregister_live_bar_event_waker(second)
    assert api.unregister_calls == 1
    before = store._live_bar_event_snapshot()
    api.emit()
    assert store._live_bar_event_snapshot() == before


def test_store_prefers_sdk_waker_when_legacy_setter_also_exists():
    class BothApis(_EventWakerApi):
        def __init__(self):
            super().__init__()
            self.setter_calls = []

        def set_live_bar_event_notifier(self, callback):
            self.setter_calls.append(callback)

    api = BothApis()
    store = BtApiStore(provider="btapi", api=api)
    token = store._register_live_bar_event_waker(lambda: None)

    assert api.register_calls == 1
    assert api.setter_calls == []

    store._unregister_live_bar_event_waker(token)
    assert api.unregister_calls == 1
    assert api.setter_calls == []


def test_failed_legacy_waker_registration_clears_partial_binding():
    class FailingSetter:
        def __init__(self):
            self.callbacks = []

        def set_live_bar_event_notifier(self, callback):
            self.callbacks.append(callback)
            if callback is not None:
                raise RuntimeError("setter bind failed")

    api = FailingSetter()
    store = BtApiStore(provider="btapi", api=api)

    try:
        store._register_live_bar_event_waker(lambda: None)
    except RuntimeError as exc:
        assert str(exc) == "setter bind failed"
    else:
        raise AssertionError("expected notifier registration to fail")

    assert len(api.callbacks) == 2
    assert callable(api.callbacks[0])
    assert api.callbacks[1] is None
    assert store._live_bar_event_wakers == {}
    assert store._live_bar_sdk_waker_setter_api is None


def test_sdk_arrival_wakes_engine_condition_waiter_without_lost_generation():
    api = _EventWakerApi()
    store = BtApiStore(provider="btapi", api=api)
    wake = _LiveBarCohortWake()
    token = store._register_live_bar_event_waker(wake.notify)
    generation = wake.snapshot()
    started = threading.Event()
    result = []

    def wait_for_wake():
        started.set()
        result.append(wake.wait(generation, 2.0))

    waiter = threading.Thread(target=wait_for_wake)
    waiter.start()
    assert started.wait(1.0)
    api.emit()
    waiter.join(1.0)
    store._unregister_live_bar_event_waker(token)

    assert not waiter.is_alive()
    assert result == [True]


def test_cerebro_runstop_wakes_active_cohort_waiter():
    cerebro = Cerebro()
    wake = _LiveBarCohortWake()
    cerebro._live_bar_cohort_waker = wake
    cerebro._run_active = True
    generation = wake.snapshot()
    started = threading.Event()
    result = []

    def wait_for_wake():
        started.set()
        result.append(wake.wait(generation, 2.0))

    waiter = threading.Thread(target=wait_for_wake)
    waiter.start()
    assert started.wait(1.0)
    cerebro.runstop()
    waiter.join(1.0)

    assert not waiter.is_alive()
    assert result == [True]
    assert cerebro._event_stop.is_set()


def test_cerebro_live_cohort_wake_interrupts_without_stopping_or_advancing():
    cerebro = Cerebro()
    wake = _LiveBarCohortWake()
    cerebro._live_bar_cohort = object()
    cerebro._live_bar_cohort_waker = wake
    cerebro._run_active = True
    generation = wake.snapshot()

    assert cerebro.wake_live_bar_cohort() is True
    assert wake.snapshot() == generation + 1
    assert cerebro._event_stop.is_set() is False

    cerebro._live_bar_cohort = None
    assert cerebro.wake_live_bar_cohort() is False
    assert wake.snapshot() == generation + 1

    cerebro._live_bar_cohort = object()
    cerebro._run_active = False
    assert cerebro.wake_live_bar_cohort() is False
    assert wake.snapshot() == generation + 1


def test_waker_cleanup_attempts_all_unbinds_and_preserves_primary_error():
    calls = []
    waker = object()
    owner = SimpleNamespace(_live_bar_cohort_waker=waker)

    class Store:
        def __init__(self, name, fail=False):
            self.name = name
            self.fail = fail

        def _unregister_live_bar_event_waker(self, token):
            calls.append((self.name, token))
            if self.fail:
                raise RuntimeError("unregister failed")

    first = Store("first", fail=True)
    second = Store("second")

    def raise_with_cleanup():
        try:
            raise ValueError("primary run failure")
        finally:
            _cleanup_live_bar_cohort_wakers(
                owner,
                waker,
                ((first, "first-token"), (second, "second-token")),
            )

    with pytest.raises(ValueError, match="primary run failure"):
        raise_with_cleanup()

    assert calls == [
        ("second", "second-token"),
        ("first", "first-token"),
    ]
    assert owner._live_bar_cohort_waker is None


def test_raw_bar_mode_preserves_malformed_and_unknown_source_fields():
    event = {"timestamp": "not-a-time", "close": "not-a-number", "source_extra": 17}
    store = BtApiStore(
        provider="btapi",
        live_bars={"X": [event]},
        historical_bars={"X": [event]},
        preserve_raw_bars=True,
    )

    live = store.poll_live("X")
    history = store.fetch_history("X")

    assert store.preserve_raw_bars is True
    assert live == event and live is not event
    assert history == [event] and history[0] is not event


def test_legacy_bar_mode_remains_normalized_by_default():
    event = {
        "timestamp": "2026-10-24T09:30:00",
        "open": "1.0",
        "high": "2.0",
        "low": "0.5",
        "close": "1.5",
        "volume": "3",
        "source_extra": 17,
    }
    store = BtApiStore(provider="btapi", live_bars={"X": [event]})

    live = store.poll_live("X")

    assert store.preserve_raw_bars is False
    assert live["close"] == 1.5
    assert live["openinterest"] == 0.0
    assert "source_extra" not in live


def test_startup_audit_deadline_is_suppressed_while_orders_are_open():
    now = time.monotonic()
    broker = SimpleNamespace(
        next_without_bar=True,
        p=SimpleNamespace(
            position_sync_policy="startup",
            position_audit_interval=10.0,
        ),
        _live_started=True,
        _positions_snapshot_loaded=True,
        _periodic_reconcile_pending=False,
        _pending_trade_updates=[],
        _last_position_audit=now - 20.0,
        orders={},
        get_orders_open=lambda: [object()],
        _uses_async_commands=lambda: False,
    )

    assert _live_cohort_broker_timeout(broker) is None


def test_execution_wait_uses_the_brokers_selected_deadline_alias():
    now_ns = time.monotonic_ns()
    order = _Order(
        {
            "execution_deadline_monotonic_ns": now_ns + 5_000_000_000,
            "order_deadline_monotonic_ns": now_ns - 1,
        }
    )
    broker = SimpleNamespace(
        next_without_bar=True,
        p=SimpleNamespace(),
        _live_started=False,
        orders={1: order},
        _order_info_get=lambda item, key, default=None: item.info.get(key, default),
        _execution_deadline=lambda item: item.info["execution_deadline_monotonic_ns"],
    )

    timeout = _live_cohort_broker_timeout(broker)

    assert timeout is not None
    assert 4.0 < timeout <= 5.0


def test_due_broker_maintenance_uses_idle_budget_but_keeps_due_cohort_immediate():
    assert _cap_live_cohort_wait_for_broker(5.0, 0.0) == 0.05
    assert _cap_live_cohort_wait_for_broker(0.0, 0.0) == 0.0
    assert _cap_live_cohort_wait_for_broker(5.0, 2.0) == 2.0
