"""Direct-mode selection and first initialization (I62-08, D62-13).

UNIT/FAKE: fake facade + real ``backtrader.live_state`` in ``tmp_path``.
"""

import hashlib

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader import live_state as ls
from backtrader.brokers._btapi_direct_mode import DirectModeError
from backtrader.brokers.btapibroker import BtApiBroker

from ._fakes import (
    ACCOUNT_REF,
    EXCHANGE,
    SYMBOL,
    TODAY,
    crash,
    native_identity,
    order_event,
    position,
)


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------
class _LegacyPathReached(Exception):
    pass


def test_existing_store_path_runs_and_never_calls_direct_start(env, monkeypatch):
    """``direct_write_mode`` False: start() enters the existing path untouched."""
    calls = []
    monkeypatch.setattr(BtApiBroker, "_direct_start", lambda self: calls.append(self))

    def _legacy_marker(self, mode):
        raise _LegacyPathReached(mode)

    monkeypatch.setattr(BtApiBroker, "supports_position_mode", _legacy_marker)
    env.store.direct_write_mode = False
    broker = env.broker()
    with pytest.raises(_LegacyPathReached):
        broker.start()
    assert calls == []
    assert broker._direct_active() is False
    # Existing write/read hooks are not routed to the direct mixin either.
    order = bt.order.BuyOrder(owner=None, data=env.feed, size=1, price=1.0, exectype=bt.Order.Limit)
    broker._direct_tag_order(order, None, "open")
    assert "valid_intent" not in order.info
    assert env.api.facts_calls == [] and env.api.place_calls == []


def test_real_store_without_admission_routes_is_not_direct():
    """``BtApiStore.direct_write_mode`` defaults to False (no write_admission routes)."""
    from backtrader.stores.btapistore import BtApiStore

    store = object.__new__(BtApiStore)
    assert store.direct_write_mode is False
    store._direct_write_mode = True
    assert store.direct_write_mode is True


def test_direct_start_is_only_reached_when_store_selects_direct_mode(env, monkeypatch):
    calls = []
    monkeypatch.setattr(BtApiBroker, "_direct_start", lambda self: calls.append(self))

    env.store.direct_write_mode = False
    off = env.broker()
    assert off._direct_selected() is False

    env.store.direct_write_mode = True
    assert env.broker(market_data_only=True)._direct_selected() is False
    managed = env.broker()
    managed._managed_runtime_session = object()
    assert managed._direct_selected() is False
    service = env.broker()
    service._service_execution_session = object()
    assert service._direct_selected() is False

    on = env.broker()
    assert on._direct_selected() is True
    on.start()
    assert calls == [on]


def test_orders_are_tagged_with_valid_intent_only_in_direct_mode(env):
    env.store.direct_write_mode = False
    broker = env.broker()
    order = bt.order.BuyOrder(owner=None, data=env.feed, size=1, price=1.0, exectype=bt.Order.Limit)
    broker._direct_tag_order(order, None, "open")
    assert "valid_intent" not in order.info
    env.store.direct_write_mode = True
    broker._direct_tag_order(order, bt.Order.DAY, None)
    assert order.info["valid_intent"] == {"kind": "day", "value": None}
    assert order.info["offset_explicit"] is False


def test_strategy_dir_is_required(env):
    broker = env.broker(strategy_dir=None)
    with pytest.raises(DirectModeError) as err:
        broker.start()
    assert err.value.code == "strategy_dir_required"


def test_direct_mode_requires_exactly_one_route(env):
    env.store._sdk_exchanges = {EXCHANGE: {}, "OKX___SWAP": {}}
    with pytest.raises(DirectModeError) as err:
        env.start(first_init=True)
    assert err.value.code == "direct_mode_requires_one_route"


def test_incomplete_startup_facts_refuse_start(env):
    env.api.complete = False
    env.api.blockers = ("orders_partial",)
    with pytest.raises(DirectModeError) as err:
        env.start(first_init=True, direct_startup_facts_retry_delay=0)
    assert err.value.code == "startup_account_facts_incomplete"
    assert "orders_partial" in err.value.detail
    assert len(env.api.facts_calls) == 3  # bounded retries, then fail closed
    assert not (env.strategy_dir / "state" / "identity.json").exists()


def test_startup_reads_complete_facts_including_all_orders_and_trades(env):
    broker = env.start(first_init=True)
    first = env.api.facts_calls[0]
    assert first["all_orders"] is True and first["trades"] is True
    assert first["positions"] is True and first["active_orders"] is True
    assert first["timeout"] == broker.p.direct_facts_timeout


def test_missing_account_reference_refuses_start(env):
    env.api.provider.reference = None
    with pytest.raises(DirectModeError) as err:
        env.start(first_init=True)
    assert err.value.code == "account_reference_unavailable"


# ---------------------------------------------------------------------------
# first initialization (D62-13)
# ---------------------------------------------------------------------------
def test_missing_state_without_first_init_is_refused(env):
    with pytest.raises(DirectModeError) as err:
        env.start()
    assert err.value.code == "first_init_required"
    assert not (env.strategy_dir / "state" / "identity.json").exists()


@pytest.mark.parametrize(
    "venue_state",
    ["long_position", "short_position", "working_order"],
)
def test_first_init_requires_a_flat_account(env, venue_state):
    if venue_state == "long_position":
        env.api.positions = [position("long", 1, 1, 0)]
    elif venue_state == "short_position":
        env.api.positions = [position("long", 0, 0, 0), position("short", 2, 0, 2)]
    else:
        env.api.active_orders = [order_event(native_identity("000000000077"), "accepted")]
    with pytest.raises(DirectModeError) as err:
        env.start(first_init=True)
    assert err.value.code == "first_init_requires_flat_account"
    assert not (env.strategy_dir / "state" / "identity.json").exists()
    assert not (env.strategy_dir / "logs" / "current_position.yaml").exists()


def test_zero_venue_position_rows_count_as_flat(env):
    env.api.positions = [position("long", 0, 0, 0), position("short", 0, 0, 0)]
    broker = env.start(first_init=True)
    assert broker._direct_active() is True


def test_first_init_on_flat_account_creates_identity_snapshot_and_holds_run_lock(env):
    broker = env.start(first_init=True)
    assert broker._direct_active() is True
    assert env.store.start_calls == [broker]

    state = env.state()
    assert state.strategy_uuid == broker._direct_uuid
    expected_hash = hashlib.sha256(f"{EXCHANGE}|{ACCOUNT_REF}".encode()).hexdigest()
    assert broker._direct_account_hash == expected_hash
    assert state.identity.account_binding["account_hash"] == expected_hash

    snapshot = state.snapshot.read()
    assert snapshot["version"] == 2
    assert snapshot["mode"] == "live"
    assert snapshot["strategy_uuid"] == broker._direct_uuid
    assert snapshot["account_hash"] == expected_hash
    assert snapshot["exchange_name"] == EXCHANGE
    assert snapshot["trading_day"] == TODAY
    assert snapshot["positions"] == {}

    # The settlement confirmation went through the host commit port and was closed.
    assert len(env.api.settlement_calls) == 1
    marker = state.pending.get(env.api.settlement_calls[0].marker_id)
    assert marker["operation"] == "settlement_confirm"
    assert marker["status"] == "TERMINAL"
    assert marker["facts"]["resolution_evidence"] == "settlement_readback"
    assert state.pending.active() == []
    assert broker.direct_writes_blocked() == {}

    with pytest.raises(ls.LiveStateLocked):
        env.state().acquire_run_lock()
    broker.stop()
    assert env.store.stop_calls == 1
    env.state().acquire_run_lock().release()


def test_second_start_without_first_init_reuses_the_identity(env):
    env.init_flat()
    uuid = env.state().strategy_uuid
    broker = env.start()
    assert broker._direct_uuid == uuid
    assert broker.get_direct_reconcile_report()["mismatches"] == []


def test_account_binding_mismatch_refuses_restart_and_releases_lock(env):
    env.init_flat()
    env.api.provider.reference = "simnow:999999"
    with pytest.raises(DirectModeError) as err:
        env.start()
    assert err.value.code == "account_binding_mismatch"
    env.state().acquire_run_lock().release()


def test_unusable_snapshot_at_restart_refuses_start_and_releases_lock(env):
    """D62-13: a missing snapshot refuses the start; the run lock must not leak."""
    env.init_flat()
    (env.strategy_dir / "logs" / "current_position.yaml").unlink()
    with pytest.raises(ls.LiveStateNotInitialized):
        env.start()
    env.state().acquire_run_lock().release()  # a retry in this process can start


def test_second_live_run_on_the_same_directory_is_refused(env):
    first = env.start(first_init=True)
    with pytest.raises(ls.LiveStateLocked):
        env.start()
    assert first._direct_active() is True


def test_crashed_run_keeps_markers_and_restart_succeeds(env):
    broker = env.start(first_init=True)
    crash(broker)
    restarted = env.start()
    assert restarted._direct_uuid == broker._direct_uuid


def test_settlement_failure_blocks_all_writes(env):
    from bt_api_base.direct_write_protocol import SettlementStatus

    env.init_flat()
    env.api.settlement_result = SettlementStatus.UNKNOWN
    broker = env.start()
    assert broker.direct_writes_blocked()["*"] == "settlement_unconfirmed"
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "settlement_unconfirmed"
    assert env.api.place_calls == []


def test_symbol_resolution_uses_feed_dataname(env):
    broker = env.start(first_init=True)
    assert broker._direct_symbol(env.feed) == SYMBOL
