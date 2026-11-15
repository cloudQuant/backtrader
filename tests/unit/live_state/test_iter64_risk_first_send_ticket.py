"""Synthetic local first-send tickets; no network or account authority."""

import copy
import pickle
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import MethodType

import pytest

from backtrader.live_state import pending as pending_module
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.conftest import state as state
from tests.unit.live_state.test_gateway_pending import inputs as inputs, observe
from tests.unit.live_state.test_iter63_gateway_order_bootstrap import _snapshot, _upgrade, _v4


def _submitted_host(state, binding):
    _v4(state, binding)
    return _upgrade(state, binding).upgrade_for_local_notifications()


def _submitted_snapshot():
    ref, snapshot = _snapshot()
    snapshot["state"]["orders"]["key-a"]["status"] = 1
    return ref, snapshot


def test_host_ticket_contract_is_local_and_bound_and_preserves_single_use(state, inputs, monkeypatch):
    binding, _, make = inputs
    host = _submitted_host(state, binding)
    original_load = host._store._load
    monkeypatch.setattr(host._store, "_load", lambda: pytest.fail("contract must not load state"))
    contract = host.risk_first_send_host_contract()
    assert type(contract) is tuple and len(contract) == 4
    assert contract[0] == "local-first-send-host-v1"
    assert all(type(method) is MethodType and method.__self__ is host for method in contract[1:])
    monkeypatch.setattr(host._store, "_load", original_load)
    ref, snapshot = _submitted_snapshot()
    intent = make()
    ticket = contract[1](intent, local_seq=1, bt_ref=ref, snapshot=snapshot)
    assert ticket is not None and host.load_intent("key-a") == intent
    assert contract[3](intent, ticket) is True
    assert contract[3](intent, ticket) is False


def test_host_contract_create_and_consume_are_same_host_and_single_use(state, inputs):
    binding, _, make = inputs
    host = GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    contract = host.risk_first_send_host_contract()
    intent = make()
    ticket = contract[2](intent)
    assert ticket is not None and host.load_intent("key-a") == intent
    assert contract[2](intent) is None
    assert contract[3](intent, ticket) is True
    assert contract[3](intent, ticket) is False


@pytest.mark.parametrize("name", ["save_submitted_order_intent", "create_risk_reserve_intent",
                                  "consume_risk_reserve_ticket", "_issue_risk_reserve_ticket",
                                  "_save_intent_in_state", "_check_state"])
def test_host_contract_refuses_replaced_method_before_acquisition(state, inputs, monkeypatch, name):
    binding, _, _ = inputs
    host = _submitted_host(state, binding)
    monkeypatch.setattr(host, name, lambda *_a, **_kw: pytest.fail("replacement called"))
    assert host.risk_first_send_host_contract() is None


@pytest.mark.parametrize("name", ["save_submitted_order_intent", "create_risk_reserve_intent",
                                  "consume_risk_reserve_ticket"])
def test_host_contract_refuses_replaced_class_method(state, inputs, monkeypatch, name):
    binding, _, _ = inputs
    host = _submitted_host(state, binding)
    monkeypatch.setattr(GatewayPendingHost, name, lambda *_a, **_kw: pytest.fail("replacement called"))
    assert host.risk_first_send_host_contract() is None


@pytest.mark.parametrize("name", ["_store", "_binding", "_risk_reserve_tickets"])
def test_host_contract_handle_refuses_changed_host_state(state, inputs, monkeypatch, name):
    binding, _, _ = inputs
    host = _submitted_host(state, binding)
    contract = host.risk_first_send_host_contract()
    monkeypatch.setattr(host, name, object())
    with pytest.raises(RuntimeError, match="^RISK_TICKET_HOST_CONTRACT_CHANGED$"):
        contract[2](None)


def test_host_contract_handle_refuses_other_process(state, inputs, monkeypatch):
    import backtrader.live_state.gateway_pending as pending

    binding, _, _ = inputs
    host = _submitted_host(state, binding)
    contract = host.risk_first_send_host_contract()
    actual_pid = pending.os.getpid()
    monkeypatch.setattr(pending.os, "getpid", lambda: actual_pid + 1)
    with pytest.raises(RuntimeError, match="^RISK_TICKET_HOST_CONTRACT_CHANGED$"):
        contract[2](None)


@pytest.mark.parametrize("name", ["save_submitted_order_intent", "create_risk_reserve_intent",
                                  "consume_risk_reserve_ticket"])
def test_host_contract_handle_rechecks_replaced_method(state, inputs, monkeypatch, name):
    binding, _, _ = inputs
    host = _submitted_host(state, binding)
    contract = host.risk_first_send_host_contract()
    index = {"save_submitted_order_intent": 1, "create_risk_reserve_intent": 2,
             "consume_risk_reserve_ticket": 3}[name]
    monkeypatch.setattr(host, name, lambda *_a, **_kw: pytest.fail("replacement called"))
    with pytest.raises(RuntimeError, match="^RISK_TICKET_HOST_CONTRACT_CHANGED$"):
        contract[index](None)
    assert tuple(host.list_intents()) == ()


def test_host_contract_detects_change_after_persistent_save(state, inputs, monkeypatch):
    binding, _, make = inputs
    host = _submitted_host(state, binding)
    contract = host.risk_first_send_host_contract()
    original_store = host._store._store

    def persist_then_change(*args, **kwargs):
        original_store(*args, **kwargs)
        monkeypatch.setattr(host, "consume_risk_reserve_ticket",
                            lambda *_a, **_kw: pytest.fail("replacement called"))

    monkeypatch.setattr(host._store, "_store", persist_then_change)
    ref, snapshot = _submitted_snapshot()
    with pytest.raises(RuntimeError, match="^RISK_TICKET_HOST_CONTRACT_CHANGED$"):
        contract[1](make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    # The post-call refusal cannot undo an already persisted intent.
    assert host.load_intent("key-a") is not None


def test_submitted_ticket_is_single_use_and_bound_to_exact_intent(state, inputs):
    binding, route, make = inputs
    host = _submitted_host(state, binding)
    ref, snapshot = _submitted_snapshot()
    intent = make()
    ticket = host.save_submitted_order_intent(intent, local_seq=1, bt_ref=ref, snapshot=snapshot)
    assert ticket is not None and host.load_intent("key-a") == intent
    for changed in (
        make(price="11"),
        make(ttl=20),
        replace(intent, route=replace(route, instance_id="other")),
        replace(intent, route=replace(route, scope=replace(route.scope, run_id="other-run"))),
    ):
        assert host.consume_risk_reserve_ticket(changed, ticket) is False
    with pytest.raises(TypeError):
        pickle.dumps(ticket)
    with pytest.raises(TypeError):
        copy.deepcopy(ticket)
    assert host.consume_risk_reserve_ticket(intent, ticket) is True
    assert host.consume_risk_reserve_ticket(intent, ticket) is False
    assert host.save_submitted_order_intent(intent, local_seq=1, bt_ref=ref, snapshot=snapshot) is None


def test_ticket_cannot_be_transferred_to_reopened_host_or_fork(state, inputs, monkeypatch):
    binding, _, make = inputs
    host = _submitted_host(state, binding)
    ref, snapshot = _submitted_snapshot()
    intent = make()
    ticket = host.save_submitted_order_intent(intent, local_seq=1, bt_ref=ref, snapshot=snapshot)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert reopened.consume_risk_reserve_ticket(intent, ticket) is False
    assert reopened.save_submitted_order_intent(intent, local_seq=1, bt_ref=ref, snapshot=snapshot) is None
    import backtrader.live_state.gateway_pending as pending

    actual_pid = pending.os.getpid()
    monkeypatch.setattr(pending.os, "getpid", lambda: actual_pid + 1)
    assert host.consume_risk_reserve_ticket(intent, ticket) is False
    monkeypatch.undo()
    assert host.consume_risk_reserve_ticket(intent, ticket) is True


@pytest.mark.parametrize("after_write", [False, True])
def test_failed_persistence_never_issues_ticket(state, inputs, monkeypatch, after_write):
    binding, _, make = inputs
    host = _submitted_host(state, binding)
    ref, snapshot = _submitted_snapshot()
    original = pending_module.atomic_write_json

    def fail(path, value):
        if after_write:
            original(path, value)
        raise OSError("synthetic failure")

    monkeypatch.setattr(pending_module, "atomic_write_json", fail)
    with pytest.raises(OSError):
        host.save_submitted_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    assert not host._risk_reserve_tickets
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    ticket = host.save_submitted_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    assert (ticket is None) is after_write


def test_standalone_creation_and_existing_metadata_upgrade_never_remint(state, inputs):
    binding, _, make = inputs
    host = GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    intent = make()
    ticket = host.create_risk_reserve_intent(intent)
    assert ticket is not None
    assert host.create_risk_reserve_intent(intent) is None
    host.save_intent(intent, local_seq=1, bt_ref=1)
    assert host.create_risk_reserve_intent(intent) is None
    assert host.consume_risk_reserve_ticket(intent, ticket) is True


def test_submitted_metadata_added_to_old_intent_does_not_issue_ticket(state, inputs):
    binding, _, make = inputs
    host = _submitted_host(state, binding)
    host.save_intent(make())
    ref, snapshot = _submitted_snapshot()
    assert host.save_submitted_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot) is None
    assert host.load_context("key-a").local_seq == 1


def test_intervening_gateway_observation_invalidates_ticket(state, inputs):
    binding, _, make = inputs
    host = GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    intent = make()
    ticket = host.create_risk_reserve_intent(intent)
    host.save_record(intent.request_key, observe(intent))
    assert host.consume_risk_reserve_ticket(intent, ticket) is False
    assert host.consume_risk_reserve_ticket(intent, ticket) is False


def test_read_failure_refuses_and_does_not_restore_ticket(state, inputs, monkeypatch):
    binding, _, make = inputs
    host = GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    intent = make()
    ticket = host.create_risk_reserve_intent(intent)
    original = host._store._load
    monkeypatch.setattr(host._store, "_load", lambda: (_ for _ in ()).throw(OSError("synthetic")))
    assert host.consume_risk_reserve_ticket(intent, ticket) is False
    monkeypatch.setattr(host._store, "_load", original)
    assert host.consume_risk_reserve_ticket(intent, ticket) is False


def test_two_hosts_race_to_create_only_one_ticket_and_one_consumer(state, inputs):
    binding, _, make = inputs
    host = GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    other = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    intent = make()
    barrier = threading.Barrier(2)

    def create(current):
        barrier.wait()
        return current, current.create_risk_reserve_intent(intent)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, (host, other)))
    issued = [(owner, ticket) for owner, ticket in results if ticket is not None]
    assert len(issued) == 1
    owner, ticket = issued[0]
    barrier = threading.Barrier(2)

    def consume(_):
        barrier.wait()
        return owner.consume_risk_reserve_ticket(intent, ticket)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(consume, range(2))) == [False, True]
