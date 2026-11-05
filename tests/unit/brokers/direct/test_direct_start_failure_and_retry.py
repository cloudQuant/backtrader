"""Failed direct starts and transiently incomplete startup facts.

Regressions from a SimNow smoke run (reported by the coordinator; reproduced
here with fakes only, UNIT/FAKE):

1. ``stop()`` after a failed ``_direct_start`` fell through to the managed
   shutdown path and reported its summary.
2. The complete startup observation can be transiently incomplete right after
   login; startup retries it a bounded number of times and still fails closed.
"""

import time
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader import live_state as ls
from backtrader.brokers import _btapi_direct_mode as direct_mode
from backtrader.brokers._btapi_direct_mode import DirectModeError
from backtrader.brokers.btapibroker import BtApiBroker

from ._fakes import EXCHANGE


@pytest.fixture
def no_managed_shutdown(monkeypatch):
    calls = []

    def _managed(self):
        calls.append(self)
        return {"status": "INCOMPLETE", "reason": "shutdown_state_not_flat"}

    monkeypatch.setattr(BtApiBroker, "_stop_live_resources", _managed)
    return calls


@pytest.fixture
def sleeps(monkeypatch):
    recorded = []
    fake_time = SimpleNamespace(sleep=recorded.append, monotonic=time.monotonic)
    monkeypatch.setattr(direct_mode, "time", fake_time)
    return recorded


# ---------------------------------------------------------------------------
# stop after a failed start
# ---------------------------------------------------------------------------
def test_stop_after_failed_start_uses_direct_path_without_account_writes(
    env, no_managed_shutdown, sleeps
):
    env.api.complete = False
    env.api.blockers = ("positions_timeout",)
    broker = env.broker(first_init=True)
    with pytest.raises(DirectModeError) as err:
        broker.start()
    assert err.value.code == "startup_account_facts_incomplete"

    summary = broker.stop()
    assert no_managed_shutdown == []
    assert summary["status"] == "NOT_STARTED"
    assert summary["reason"] == "direct_start_failed"
    assert env.api.cancel_calls == [] and env.api.place_calls == []
    assert env.store.stop_calls == 1  # the Store started by the attempt is stopped
    assert broker.stop() == summary  # idempotent, still never managed
    assert no_managed_shutdown == [] and env.store.stop_calls == 1


def test_same_broker_can_retry_start_after_stop_of_a_failed_start(env, no_managed_shutdown, sleeps):
    env.api.complete = False
    broker = env.broker(first_init=True)
    with pytest.raises(DirectModeError):
        broker.start()
    assert broker.stop()["status"] == "NOT_STARTED"

    env.api.complete = True
    broker.start()
    assert broker._direct_active() is True
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    assert order.status == bt.Order.Submitted, order.info.get("error_code")  # not broker_stopping
    env.api.auto_cancel_events = True
    assert broker.stop()["status"] == "STOPPED"
    assert len(env.api.cancel_calls) == 1
    assert no_managed_shutdown == []
    env.state().acquire_run_lock().release()


def test_stop_after_start_failed_before_the_store_started(env, no_managed_shutdown):
    broker = env.broker(strategy_dir=None)
    with pytest.raises(DirectModeError):
        broker.start()
    summary = broker.stop()
    assert summary["status"] == "NOT_STARTED"
    assert no_managed_shutdown == []
    assert env.store.start_calls == [] and env.store.stop_calls == 0


def test_stop_after_start_failed_holding_the_lock_releases_it(env, no_managed_shutdown):
    env.init_flat()
    (env.strategy_dir / "logs" / "current_position.yaml").unlink()
    broker = env.broker()
    with pytest.raises(ls.LiveStateNotInitialized):
        broker.start()
    summary = broker.stop()
    assert summary["status"] == "NOT_STARTED" and no_managed_shutdown == []
    env.state().acquire_run_lock().release()


def test_repeated_stop_after_a_normal_direct_stop_never_runs_managed_shutdown(
    env, no_managed_shutdown
):
    broker = env.start(first_init=True)
    summary = broker.stop()
    assert summary["status"] == "STOPPED"
    assert broker.stop() == summary
    assert no_managed_shutdown == []
    assert env.store.stop_calls == 1


def test_non_direct_broker_stop_still_runs_the_managed_shutdown(env, no_managed_shutdown):
    env.store.direct_write_mode = False
    broker = env.broker()
    assert broker.stop()["status"] == "INCOMPLETE"
    assert no_managed_shutdown == [broker]


# ---------------------------------------------------------------------------
# bounded retry of the complete startup observation
# ---------------------------------------------------------------------------
def test_defaults_for_startup_facts():
    broker_params = dict(BtApiBroker.params)
    assert broker_params["direct_facts_timeout"] == 10.0
    assert broker_params["direct_startup_facts_attempts"] == 3
    assert broker_params["direct_startup_facts_retry_delay"] == 2.0


def test_transiently_incomplete_startup_facts_are_retried(env, sleeps):
    env.api.incomplete_reads = 2
    env.api.blockers = ("positions_timeout",)
    broker = env.start(first_init=True)
    assert broker._direct_active() is True
    startup_reads = [call for call in env.api.facts_calls if call.get("all_orders")]
    assert len(startup_reads) == 3
    assert all(call["timeout"] == 10.0 for call in startup_reads)
    assert sleeps == [2.0, 2.0]


def test_startup_fails_closed_after_the_last_incomplete_attempt(env, sleeps):
    env.api.complete = False
    env.api.blockers = ("orders_refused:-2", "trades_refused:-2")
    with pytest.raises(DirectModeError) as err:
        env.start(
            first_init=True, direct_startup_facts_attempts=4, direct_startup_facts_retry_delay=0.5
        )
    assert err.value.code == "startup_account_facts_incomplete"
    assert err.value.detail == "orders_refused:-2,trades_refused:-2"
    assert len(env.api.facts_calls) == 4
    assert sleeps == [0.5, 0.5, 0.5]
    assert not (env.strategy_dir / "state" / "identity.json").exists()


def test_single_attempt_does_not_sleep(env, sleeps):
    env.api.incomplete_reads = 1
    with pytest.raises(DirectModeError):
        env.start(first_init=True, direct_startup_facts_attempts=1)
    assert len(env.api.facts_calls) == 1 and sleeps == []


def test_runtime_facts_reads_use_the_configured_timeout(env):
    broker = env.start(first_init=True, direct_facts_timeout=3.5)
    broker._direct_read_facts(positions=False, active_orders=False)
    assert env.api.facts_calls[-1]["timeout"] == 3.5
    assert env.api.facts_calls[-1]["positions"] is False
    assert EXCHANGE in broker._direct_exchange
