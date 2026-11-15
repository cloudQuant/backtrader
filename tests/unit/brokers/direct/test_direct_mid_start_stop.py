"""A latched stop request during a direct start (iteration 66, §5.2 B4).

Iteration 62 latches a SIGTERM (or stop-file) request and turns it into
``cerebro.runstop()``; ``runstop()`` only sets the run's stop event, so before
this change every startup step ran to completion first.  The direct start now
checks the request at each side-effect boundary:

1. before the Store starts (nothing connects),
2. after the read-only startup observation (nothing written),
3. before the settlement step (nothing written),
4. inside the settlement commit (the SDK sends nothing),
5. after the settlement step (a committed or unclear write is UNKNOWN).

A start provably free of account writes is cleaned up as ``NOT_STARTED``; one
after a committed (or unclear) settlement write keeps its durable marker and
the run lock and reports ``UNKNOWN`` — never a clean ``NOT_STARTED``.

Evidence: UNIT/FAKE — fake facade + real ``backtrader.live_state`` in
``tmp_path``.
"""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

from backtrader import live_state as ls
from backtrader.brokers._btapi_direct_mode import DirectStartStopped
from backtrader.brokers.btapibroker import BtApiBroker
from bt_api_base.direct_write_protocol import SettlementStatus

from ._fakes import SYMBOL


class FakeCerebro:
    """The only owner state the direct start consults: the run's stop event."""

    def __init__(self) -> None:
        self._event_stop = threading.Event()


@pytest.fixture
def no_managed_shutdown(monkeypatch):
    calls = []

    def _managed(self):
        calls.append(self)
        return {"status": "INCOMPLETE", "reason": "shutdown_state_not_flat"}

    monkeypatch.setattr(BtApiBroker, "_stop_live_resources", _managed)
    return calls


def _attach(env, broker, monkeypatch):
    """Give the Broker a fake Cerebro and make ownership explicit."""
    cerebro = FakeCerebro()
    broker.cerebro = cerebro
    monkeypatch.setattr(env, "cerebro", cerebro, raising=False)
    return cerebro


def _lock_is_free(env) -> bool:
    try:
        state = env.state()
    except ls.LiveStateNotInitialized:
        return True
    try:
        with state.acquire_run_lock():
            return True
    except ls.LiveStateLocked:
        return False


# ---------------------------------------------------------------------------
# boundaries that prove no account write
# ---------------------------------------------------------------------------
def test_a_request_before_the_store_starts_aborts_before_any_side_effect(
    env, monkeypatch, no_managed_shutdown
):
    broker = env.broker(first_init=True)
    cerebro = _attach(env, broker, monkeypatch)
    cerebro._event_stop.set()

    with pytest.raises(DirectStartStopped) as err:
        broker.start()

    assert err.value.code == "stop_requested"
    assert err.value.detail == "before_side_effects"
    assert env.store.start_calls == []
    summary = broker.stop()
    assert summary["status"] == "NOT_STARTED"
    assert summary["reason"] == "stop_requested_during_start"
    assert summary["startup_boundary"] == "before_side_effects"
    assert env.api.settlement_calls == [] and env.api.place_calls == []
    assert not (env.strategy_dir / "state" / "identity.json").exists()
    assert no_managed_shutdown == []
    assert broker._direct_active() is False


def test_a_request_after_the_read_only_queries_aborts_before_the_settlement(
    env, monkeypatch, no_managed_shutdown
):
    broker = env.broker(first_init=True)
    cerebro = _attach(env, broker, monkeypatch)
    original = env.api.direct_account_facts

    def facts_read(*args, **kwargs):
        result = original(*args, **kwargs)
        cerebro._event_stop.set()  # the request arrives while the read completes
        return result

    env.api.direct_account_facts = facts_read

    with pytest.raises(DirectStartStopped) as err:
        broker.start()

    assert err.value.detail == "read_only_queries"
    assert env.api.settlement_calls == []
    assert env.api.place_calls == [] and env.api.cancel_calls == []
    assert not (env.strategy_dir / "state" / "identity.json").exists()
    summary = broker.stop()
    assert summary["status"] == "NOT_STARTED"
    assert summary["startup_boundary"] == "read_only_queries"
    assert no_managed_shutdown == []


def test_a_request_before_the_settlement_commit_writes_nothing(
    env, monkeypatch, no_managed_shutdown
):
    broker = env.broker(first_init=True)
    cerebro = _attach(env, broker, monkeypatch)
    original = type(broker)._direct_read_permissions
    broker._direct_read_permissions = lambda: (
        cerebro._event_stop.set(),
        original(broker),
    )[1]

    with pytest.raises(DirectStartStopped) as err:
        broker.start()

    assert err.value.detail == "before_settlement_commit"
    assert env.api.settlement_calls == [] and env.api.place_calls == []
    state = env.state()
    assert state.pending.active() == []  # nothing was committed
    summary = broker.stop()
    assert summary["status"] == "NOT_STARTED"
    assert summary["startup_boundary"] == "before_settlement_commit"
    assert _lock_is_free(env)  # the run lock of a write-free abort is released
    assert no_managed_shutdown == []


def test_a_request_at_the_commit_refuses_the_write(env, monkeypatch, no_managed_shutdown):
    broker = env.broker(first_init=True)
    cerebro = _attach(env, broker, monkeypatch)
    original = env.api.ensure_settlement_confirmed

    def settle(*args, **kwargs):
        cerebro._event_stop.set()  # arrives between the check and the commit
        return original(*args, **kwargs)

    env.api.ensure_settlement_confirmed = settle

    with pytest.raises(DirectStartStopped) as err:
        broker.start()

    assert err.value.detail == "after_settlement_step"
    assert env.api.settlement_calls[-1].marker_id is None  # the commit was refused
    assert env.state().pending.active() == []
    summary = broker.stop()
    assert summary["status"] == "NOT_STARTED"
    assert _lock_is_free(env)
    assert no_managed_shutdown == []


# ---------------------------------------------------------------------------
# boundaries after a committed write: UNKNOWN, marker and lock kept
# ---------------------------------------------------------------------------
def test_a_request_after_a_committed_confirmation_keeps_the_marker_and_the_lock(
    env, monkeypatch, no_managed_shutdown
):
    env.api.settlement_result = SettlementStatus.CONFIRMED
    broker = env.broker(first_init=True)
    cerebro = _attach(env, broker, monkeypatch)
    original = env.api.ensure_settlement_confirmed

    def settle(*args, **kwargs):
        result = original(*args, **kwargs)  # becomes the original
        cerebro._event_stop.set()  # the request arrives after the write
        return result

    env.api.ensure_settlement_confirmed = settle

    with pytest.raises(DirectStartStopped) as err:
        broker.start()

    assert err.value.detail == "after_settlement_step"
    marker = env.api.settlement_calls[-1].marker_id
    assert marker is not None
    state = env.state()
    assert state.pending.get(marker)["status"] == "TERMINAL"

    summary = broker.stop()
    assert summary["status"] == "UNKNOWN"  # never a clean NOT_STARTED
    assert summary["reason"] == "stop_requested_during_start"
    assert summary["startup_write"] == "committed"
    assert summary["startup_boundary"] == "after_settlement_step"
    assert summary["startup_marker"] == marker
    assert summary["run_lock_held"] is True
    assert state.pending.get(marker) is not None  # the durable marker survives
    assert _lock_is_free(env) is False  # the run lock stays with the write
    assert no_managed_shutdown == []


def test_a_request_with_an_unclear_settlement_outcome_is_unknown_not_a_clean_stop(
    env, monkeypatch, no_managed_shutdown
):
    env.api.settlement_result = SettlementStatus.UNKNOWN
    broker = env.broker(first_init=True)
    cerebro = _attach(env, broker, monkeypatch)
    original = env.api.ensure_settlement_confirmed

    def settle(*args, **kwargs):
        result = original(*args, **kwargs)
        cerebro._event_stop.set()
        return result

    env.api.ensure_settlement_confirmed = settle

    with pytest.raises(DirectStartStopped) as err:
        broker.start()
    assert err.value.detail == "after_settlement_step"

    marker = env.api.settlement_calls[-1].marker_id
    assert marker is not None
    state = env.state()
    assert state.pending.get(marker)["status"] == "UNKNOWN"

    summary = broker.stop()
    assert summary["status"] == "UNKNOWN"
    assert summary["startup_write"] == "unknown"
    assert summary["run_lock_held"] is True
    assert _lock_is_free(env) is False
    assert no_managed_shutdown == []


def test_a_stop_after_the_kept_lock_cannot_start_another_run(env, monkeypatch, no_managed_shutdown):
    env.api.settlement_result = SettlementStatus.CONFIRMED
    broker = env.broker(first_init=True)
    cerebro = _attach(env, broker, monkeypatch)
    original = env.api.ensure_settlement_confirmed

    def settle(*args, **kwargs):
        result = original(*args, **kwargs)
        cerebro._event_stop.set()
        return result

    env.api.ensure_settlement_confirmed = settle
    with pytest.raises(DirectStartStopped):
        broker.start()
    assert broker.stop()["status"] == "UNKNOWN"

    retry = env.broker()  # same strategy directory, same process
    retry.cerebro = FakeCerebro()
    with pytest.raises(ls.LiveStateLocked):
        retry.start()


# ---------------------------------------------------------------------------
# regressions: without a request nothing changes
# ---------------------------------------------------------------------------
def test_a_start_without_a_request_is_unaffected(env, monkeypatch):
    broker = env.broker(first_init=True)
    _attach(env, broker, monkeypatch)
    broker.start()
    assert broker._direct_active() is True
    assert broker._direct_start_stop is None
    assert env.api.settlement_calls
    summary = broker.stop()
    assert summary["status"] == "STOPPED"
    env.state().acquire_run_lock().release()


def test_a_broker_without_an_owner_never_sees_a_request(env, no_managed_shutdown):
    broker = env.broker(first_init=True)
    assert broker._direct_stop_requested() is False
    broker.start()
    assert broker._direct_active() is True
    assert broker.stop()["status"] == "STOPPED"
    env.state().acquire_run_lock().release()


def test_the_running_stop_path_still_cancels_own_orders(env, monkeypatch):
    import backtrader as bt

    broker = env.start(first_init=True)
    cerebro = _attach(env, broker, monkeypatch)
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    call = env.api.place_calls[-1]
    from ._fakes import order_event

    env.api.push(order_event(call.identity, "accepted", sys_id="7101", qty=1))
    broker.next()
    assert order.alive()
    env.api.auto_cancel_events = True
    cerebro._event_stop.set()  # as runstop() would set it
    summary = broker.stop()
    assert summary["status"] == "STOPPED"
    assert len(env.api.cancel_calls) == 1
    assert env.api.cancel_calls[0].symbol == SYMBOL
