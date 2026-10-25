"""Strict read-only Store proof for an original order absent after restart."""

from __future__ import annotations

import collections
from types import SimpleNamespace

import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStoreError
from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper


_ACCOUNT = "registered-sim-account-1"
_INSTRUMENT = "IF2712"
_EXCHANGE = "CFFEX"
_ORDER_REF = "7001"
_ORDER_SYS_ID = "SYS7001"
_BACKTRADER_ORDER_REF = 51


class _FakeTraderClient:
    def __init__(self):
        self.account_fingerprint = _ACCOUNT
        self.connection_generation = 2
        self.trading_day = "20261025"
        self.front_id = 8
        self.session_id = 9
        self.read_only_ready = True
        self.is_ready = True
        self.is_trading_ready = True
        self.gate_state = {"managed": False, "armed": False}
        self.gate_reads = 0

    def get_query_session_scope(self):
        return SimpleNamespace(
            account_fingerprint=self.account_fingerprint,
            connection_generation=self.connection_generation,
            trading_day=self.trading_day,
            read_only_ready=self.read_only_ready,
        )

    def get_session_state(self):
        return {
            "account_fingerprint": self.account_fingerprint,
            "connection_generation": self.connection_generation,
            "trading_day": self.trading_day,
            "front_id": self.front_id,
            "session_id": self.session_id,
            "trading_ready": self.is_ready,
        }

    def get_execution_gate_state(self):
        self.gate_reads += 1
        return dict(self.gate_state)

    def submit_order_insert(self, *_args, **_kwargs):
        raise AssertionError("absence check must not call native insert")

    def submit_order_action(self, *_args, **_kwargs):
        raise AssertionError("absence check must not call native cancel")


class _FakeSdkClient:
    """Fake SDK leaves composed under the production RegisteredSimWrapper."""

    def __init__(self, **_kwargs):
        self._connected = True
        self.trader_client = _FakeTraderClient()
        self._pending_orders = {}
        self._pending_orders_by_sys_id = {}
        self._order_updates = collections.deque()
        self.notifier_calls = 0

    def _notify_live_bar_event(self):
        self.notifier_calls += 1


def _system():
    store = RegisteredSimStore(allow_writes=True, api_cls=_FakeSdkClient, autostart=False)
    api = store._api_cls()
    assert isinstance(api, RegisteredSimWrapper)
    store._api = api
    store._connected = True
    api._connected = True
    broker = BtApiBroker(
        store=store,
        cash=1000.0,
        validation_enabled=False,
        cash_check_enabled=False,
    )
    store._broker = broker
    return store, api, broker


def _current_session(api):
    client = api.trader_client
    return {
        "account_fingerprint": client.account_fingerprint,
        "connection_generation": client.connection_generation,
        "trading_day": client.trading_day,
        "front_id": client.front_id,
        "session_id": client.session_id,
    }


def _original_identity():
    # The original order was created under an earlier connection/session.
    return {
        "operation": "insert",
        "backtrader_order_ref": _BACKTRADER_ORDER_REF,
        "order_ref": _ORDER_REF,
        "order_sys_id": _ORDER_SYS_ID,
        "instrument_id": _INSTRUMENT,
        "exchange_id": _EXCHANGE,
        "account_fingerprint": _ACCOUNT,
        "connection_generation": 1,
        "trading_day": "20261025",
        "front_id": 4,
        "session_id": 7,
    }


def _call(store, api, *, expected_session=None, original_identity=None):
    return store.registered_sim_assert_original_order_absent(
        original_identity=_original_identity() if original_identity is None else original_identity,
        expected_session=_current_session(api) if expected_session is None else expected_session,
    )


def _state_snapshot(store, api, broker):
    return {
        "store_gate": dict(store._registered_sim_gate),
        "wrapper_capability": api._registered_sim_capability,
        "wrapper_armed_key": api._registered_sim_armed_key,
        "wrapper_frozen": api._registered_sim_frozen,
        "unknown_dispatch": api._registered_sim_unknown_dispatch,
        "order_state": dict(api._order_state),
        "dispatching": set(api._dispatching_order_ids),
        "pending_orders": dict(api._pending_orders),
        "pending_orders_by_sys_id": dict(api._pending_orders_by_sys_id),
        "order_updates": list(api._order_updates),
        "broker_orders": dict(broker.orders),
        "broker_client_refs": dict(broker._orders_by_client_ref),
        "broker_external_ids": dict(broker._orders_by_external_id),
        "broker_pending_trades": list(broker._pending_trade_updates),
        "store_open_orders": list(store._open_orders_cache),
        "broker_open_orders": list(broker._remote_open_orders_snapshot),
        "notifier_calls": api.notifier_calls,
    }


def _insert_unrelated_order_state(store, api, broker):
    other_order = SimpleNamespace(
        ref=999,
        info={"external_order_ref": "8000", "order_sys_id": "SYS8000"},
    )
    api._order_state["8000"] = "active"
    api._pending_orders["8000"] = {"order_ref": "8000"}
    api._pending_orders_by_sys_id["SYS8000"] = {"order_sys_id": "SYS8000"}
    api._order_updates.append({"kind": "order", "order_ref": "8000", "bt_order_ref": 999})
    broker.orders[999] = other_order
    broker._orders_by_client_ref[("ctp:account", "8000")] = other_order
    broker._orders_by_external_id["SYS8000"] = other_order
    broker._pending_trade_updates.append({"kind": "trade", "order_ref": "8000"})
    store._open_orders_cache.append({"OrderRef": "8000"})
    broker._remote_open_orders_snapshot.append({"order_ref": "8000"})


def test_store_absence_is_read_only_and_allows_a_new_current_session():
    store, api, broker = _system()
    _insert_unrelated_order_state(store, api, broker)
    before = _state_snapshot(store, api, broker)
    gate_reads = api.trader_client.gate_reads

    result = _call(store, api)

    assert result == "ALREADY_ABSENT"
    assert api.trader_client.gate_reads == gate_reads + 1
    assert _state_snapshot(store, api, broker) == before
    assert api.notifier_calls == 0
    assert store._registered_sim_gate["armed"] is False
    assert api._registered_sim_capability is None


def test_store_absence_rejects_the_original_session_as_current_session():
    store, api, broker = _system()
    stale_expected = {
        **_current_session(api),
        "connection_generation": 1,
        "front_id": 4,
        "session_id": 7,
    }
    before = _state_snapshot(store, api, broker)

    with pytest.raises(BtApiStoreError, match="CURRENT_SESSION_IDENTITY_MISMATCH"):
        _call(store, api, expected_session=stale_expected)

    assert _state_snapshot(store, api, broker) == before


def test_store_absence_rechecks_session_after_expected_identity_is_captured():
    store, api, broker = _system()
    expected = _current_session(api)
    api.trader_client.connection_generation = 3
    before = _state_snapshot(store, api, broker)

    with pytest.raises(BtApiStoreError, match="CURRENT_SESSION_IDENTITY_MISMATCH"):
        _call(store, api, expected_session=expected)

    assert _state_snapshot(store, api, broker) == before


def test_store_absence_rejects_original_identity_from_another_account():
    store, api, broker = _system()
    original = {**_original_identity(), "account_fingerprint": "other-account"}
    before = _state_snapshot(store, api, broker)

    with pytest.raises(BtApiStoreError, match="ORIGINAL_IDENTITY_INVALID"):
        _call(store, api, original_identity=original)

    assert _state_snapshot(store, api, broker) == before


@pytest.mark.parametrize(
    ("blocker", "reason"),
    [
        ("store_armed", "STORE_GATE_NOT_DISARMED"),
        ("store_frozen", "STORE_GATE_NOT_DISARMED"),
        ("sdk_armed", "SDK_GATE_NOT_OBSERVED_DISARMED"),
        ("wrapper_capability", "WRAPPER_NOT_DISARMED"),
        ("unknown_latch", "UNKNOWN_LATCH_PRESENT"),
        ("unrelated_unknown_id", "UNKNOWN_ORDER_IDS_PRESENT"),
        ("dispatching_id", "DISPATCHING_ORDER_IDS_PRESENT_OR_UNOBSERVED"),
        ("target_order_state", "LOCAL_ORDER_REFERENCE_PRESENT"),
        ("target_pending_order", "LOCAL_PENDING_ORDER_PRESENT"),
        ("target_pending_sys_id", "LOCAL_PENDING_ORDER_PRESENT"),
        ("target_callback", "LOCAL_ORDER_CALLBACK_PENDING"),
        ("broker_order", "BROKER_ORDER_REFERENCE_PRESENT"),
        ("broker_client_ref", "BROKER_CLIENT_REFERENCE_PRESENT"),
        ("broker_external_id", "BROKER_EXTERNAL_REFERENCE_PRESENT"),
        ("store_open_order", "LOCAL_OPEN_ORDER_SNAPSHOT_PRESENT_OR_AMBIGUOUS"),
        ("broker_open_order", "LOCAL_OPEN_ORDER_SNAPSHOT_PRESENT_OR_AMBIGUOUS"),
        ("pending_trade", "BROKER_TRADE_CALLBACK_PENDING"),
    ],
)
def test_store_absence_fails_closed_without_mutating_local_state(blocker, reason):
    store, api, broker = _system()
    if blocker == "store_armed":
        store._registered_sim_gate["armed"] = True
    elif blocker == "store_frozen":
        store._registered_sim_gate["frozen"] = True
    elif blocker == "sdk_armed":
        api.trader_client.gate_state["armed"] = True
    elif blocker == "wrapper_capability":
        api._registered_sim_capability = object()
    elif blocker == "unknown_latch":
        api._registered_sim_unknown_dispatch = object()
    elif blocker == "unrelated_unknown_id":
        api._order_state["9000"] = "unknown"
    elif blocker == "dispatching_id":
        api._dispatching_order_ids.add("9000")
    elif blocker == "target_order_state":
        api._order_state[_ORDER_REF] = "terminal"
    elif blocker == "target_pending_order":
        api._pending_orders[_ORDER_REF] = {"order_ref": _ORDER_REF}
    elif blocker == "target_pending_sys_id":
        api._pending_orders_by_sys_id[_ORDER_SYS_ID] = {"order_sys_id": _ORDER_SYS_ID}
    elif blocker == "target_callback":
        api._order_updates.append({"kind": "order", "order_ref": _ORDER_REF})
    elif blocker == "broker_order":
        broker.orders[_BACKTRADER_ORDER_REF] = SimpleNamespace(ref=_BACKTRADER_ORDER_REF, info={})
    elif blocker == "broker_client_ref":
        broker._orders_by_client_ref[("old-session", _ORDER_REF)] = SimpleNamespace(
            ref=999, info={"external_order_ref": _ORDER_REF}
        )
    elif blocker == "broker_external_id":
        broker._orders_by_external_id[_ORDER_SYS_ID] = SimpleNamespace(ref=999, info={})
    elif blocker == "store_open_order":
        store._open_orders_cache.append({"OrderRef": _ORDER_REF})
    elif blocker == "broker_open_order":
        broker._remote_open_orders_snapshot.append({"OrderRef": _ORDER_REF})
    elif blocker == "pending_trade":
        broker._pending_trade_updates.append({"kind": "trade", "order_ref": _ORDER_REF})
    else:  # pragma: no cover - every case is listed above
        raise AssertionError(blocker)

    before = _state_snapshot(store, api, broker)

    with pytest.raises(BtApiStoreError, match=reason):
        _call(store, api)

    assert _state_snapshot(store, api, broker) == before
    assert api.notifier_calls == 0


def test_store_absence_rejects_opaque_queued_callback():
    store, api, broker = _system()
    api._order_updates.append(object())
    before = _state_snapshot(store, api, broker)

    with pytest.raises(BtApiStoreError, match="LOCAL_ORDER_CALLBACK_PENDING"):
        _call(store, api)

    assert _state_snapshot(store, api, broker) == before


def test_store_absence_does_not_create_unknown_retirement_receipt():
    store, api, broker = _system()
    retired = []
    api.retire_registered_sim_unknown = lambda *args, **kwargs: retired.append((args, kwargs))
    before = _state_snapshot(store, api, broker)

    assert _call(store, api) == "ALREADY_ABSENT"

    assert retired == []
    assert _state_snapshot(store, api, broker) == before
