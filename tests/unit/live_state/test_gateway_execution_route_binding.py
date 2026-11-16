"""Local routing binding tests: temporary files only, no remote authority."""
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from backtrader.live_state.atomic import LiveStateCorrupt
from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.live_state.pending import validate_pending_state
from backtrader.live_state import pending as pending_module
from tests.unit.live_state.test_gateway_pending import inputs, observe
from tests.unit.live_state.test_iter63_gateway_order_bootstrap import _snapshot, _upgrade, _v4, data


def setup_v7(state, inputs):
    binding, _, _ = inputs
    _v4(state, binding)
    host = _upgrade(state, binding).upgrade_for_local_notifications()
    return host.upgrade_for_risk_routing()


def submitted(host, intent, *, configuration_id="config-a"):
    ref, snapshot = _snapshot()
    snapshot["state"]["orders"]["key-a"]["status"] = 1
    ticket = host.save_execution_routing_intent(intent, local_seq=1, bt_ref=ref,
                                                snapshot=snapshot, configuration_id=configuration_id)
    return ticket, ref, snapshot


def prepared(intent, **changes):
    from bt_api_py.execution_routing import ExecutionPreparedRoute
    fields = dict(account="account-a", strategy="strategy-a", request_key=intent.request_key,
                  intent_digest=intent.digest, configuration_id="config-a",
                  execution_domain_ref="paper:demo", request_id="request-a",
                  request_sha256="a" * 64, parent_ref="parent-a")
    fields.update(changes)
    return ExecutionPreparedRoute(**fields)


def test_explicit_upgrade_preserves_legacy_and_schema(state, inputs):
    host = setup_v7(state, inputs)
    before = data(state)
    assert host.load_execution_route("missing") is None
    assert data(state) == before
    old = json.loads(before)
    bad = json.loads(before)
    bad["gateway"]["execution_routes"] = {}
    with pytest.raises(LiveStateCorrupt):
        validate_pending_state(bad, state.pending.path, state.strategy_uuid)
    host.upgrade_for_execution_routing()
    upgraded = json.loads(data(state))
    assert upgraded["version"] == 8
    assert upgraded["gateway"].pop("execution_routes") == {}
    upgraded["version"] = 7
    assert upgraded == old
    host.upgrade_for_execution_routing()


def test_atomic_intent_notice_and_pending_survive_restart(state, inputs, monkeypatch):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    before = data(state)
    original = pending_module.atomic_write_json
    monkeypatch.setattr(pending_module, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("failure")))
    with pytest.raises(OSError):
        submitted(host, intent)
    assert data(state) == before
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    ticket, _, _ = submitted(host, intent)
    assert ticket is not None
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, inputs[0])
    route = reopened.load_execution_route(intent.request_key)
    assert route.kind == "PENDING"
    assert reopened.load_intent(intent.request_key) == intent
    assert reopened.load_order_snapshot(intent.request_key) is not None
    assert reopened.local_order_notifications()[intent.request_key]["status"] == "pending"
    with pytest.raises(FrozenInstanceError):
        route.kind = "GATEWAY"
    assert not host.consume_risk_reserve_ticket(intent, ticket)
    assert reopened.load_execution_route(intent.request_key).kind == "PENDING"


def test_parent_binding_is_durable_immutable_and_exact_type(state, inputs, monkeypatch):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    submitted(host, intent)
    route = prepared(intent)
    before = data(state)
    original = pending_module.atomic_write_json
    monkeypatch.setattr(pending_module, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("failure")))
    with pytest.raises(OSError):
        host.bind_execution_parent_route(intent.request_key, route)
    assert data(state) == before
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    with pytest.raises(ValueError):
        host.bind_execution_parent_route(intent.request_key, object())
    for name in ("account", "strategy", "request_key", "intent_digest", "configuration_id", "execution_domain_ref"):
        with pytest.raises(ValueError):
            host.bind_execution_parent_route(intent.request_key, replace(route, **{name: "mismatch"}))
    assert data(state) == before
    assert host.bind_execution_parent_route(intent.request_key, route) is True
    saved = data(state)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, inputs[0])
    assert reopened.load_execution_route(intent.request_key).parent_ref == "parent-a"
    assert reopened.bind_execution_parent_route(intent.request_key, route) is True
    assert data(state) == saved
    with pytest.raises(ValueError):
        reopened.bind_execution_parent_route(intent.request_key, replace(route, parent_ref="other"))
    with pytest.raises(ValueError):
        reopened.bind_execution_direct_route(intent.request_key, route_kind="RISK")
    assert data(state) == saved


@pytest.mark.parametrize("kind", ["GATEWAY", "RISK"])
def test_direct_selection_cannot_flip(state, inputs, kind):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    ticket, _, _ = submitted(host, intent)
    assert host.bind_execution_direct_route(intent.request_key, route_kind=kind) is True
    assert host.bind_execution_direct_route(intent.request_key, route_kind=kind) is True
    before = data(state)
    with pytest.raises(ValueError):
        host.bind_execution_direct_route(intent.request_key, route_kind="RISK" if kind == "GATEWAY" else "GATEWAY")
    assert data(state) == before
    assert host.consume_risk_reserve_ticket(intent, ticket) is (kind == "RISK")


@pytest.mark.parametrize("phase", ["PENDING", "EXECUTION_PARENT"])
def test_old_gateway_risk_mutators_refuse_unresolved_route(state, inputs, phase):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    _, ref, snapshot = submitted(host, intent)
    if phase == "EXECUTION_PARENT":
        host.bind_execution_parent_route(intent.request_key, prepared(intent))
    before = data(state)
    for action in (
        lambda: host.save_record(intent.request_key, observe(intent)),
        lambda: host.commit_pre_dispatch(intent.request_key, observe(intent)),
        lambda: host.save_delegated_command(intent.request_key, reservation_id="res", digest=intent.digest),
        lambda: host.save_rejected_order_notification(intent.request_key, bt_ref=ref, snapshot=snapshot, code="TEST"),
        lambda: host.save_released_order_notification(intent.request_key, bt_ref=ref, snapshot=snapshot),
        lambda: host.save_intent(intent),
    ):
        with pytest.raises(ValueError):
            action()
        assert data(state) == before


def test_corrupt_v8_routes_rejected(state, inputs):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    submitted(host, inputs[2]())
    pristine = json.loads(data(state))
    for change in (
        lambda r: r.update(kind="EXECUTION_PARENT"),
        lambda r: r.update(account="wrong"),
        lambda r: r.update(request_sha256="x" * 64),
        lambda r: r.update(extra=1),
    ):
        bad = json.loads(json.dumps(pristine))
        change(bad["gateway"]["execution_routes"]["key-a"])
        with pytest.raises(LiveStateCorrupt):
            validate_pending_state(bad, state.pending.path, state.strategy_uuid)


@pytest.mark.parametrize("phase", ["PENDING", "EXECUTION_PARENT"])
def test_unresolved_route_blocks_rebind(state, inputs, phase):
    from backtrader.live_state import LiveStateError, rebind_identity

    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    submitted(host, intent)
    if phase == "EXECUTION_PARENT":
        host.bind_execution_parent_route(intent.request_key, prepared(intent))
    before = data(state)
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(state.strategy_dir, mode="new_instance", operator="test", reason="test")
    assert data(state) == before


def test_repeat_pending_never_reissues_ticket_or_rebinds_legacy(state, inputs):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    ticket, ref, snapshot = submitted(host, intent)
    assert ticket is not None
    assert host.save_execution_routing_intent(intent, local_seq=1, bt_ref=ref,
                                              snapshot=snapshot, configuration_id="config-a") is None
    before = data(state)
    with pytest.raises(ValueError):
        host.save_execution_routing_intent(intent, local_seq=1, bt_ref=ref,
                                           snapshot=snapshot, configuration_id="config-b")
    with pytest.raises(ValueError):
        host.save_execution_routing_intent(inputs[2](ttl=20), local_seq=1, bt_ref=ref,
                                           snapshot=snapshot, configuration_id="config-a")
    assert data(state) == before
    assert host.bind_execution_direct_route(intent.request_key, route_kind="RISK") is True
    assert host.consume_risk_reserve_ticket(intent, ticket) is True
    assert host.consume_risk_reserve_ticket(intent, ticket) is False


@pytest.mark.parametrize("failure", ["before_json", "after_json", "none"])
def test_sqlite_router_barrier_and_json_survive_reopen(state, inputs, tmp_path, failure):
    import sqlite3
    from decimal import Decimal
    from bt_api_base.market_protocol import MarketInstrumentKey
    from bt_api_py._contracts.models import OrderRequest, OrderType, Side
    from bt_api_py.execution_routing import (
        ExecutionOrderRouter, ExecutionRoutingOutcome, install_execution_routing_tables,
        parse_execution_routing,
    )
    from bt_api_py.gateway_direct_client import build_gateway_order_intent

    instrument = MarketInstrumentKey("ctp", "SHFE", "simnow", "future", "rb", "rb")
    config = parse_execution_routing({
        "schema_version": 2, "algorithm_build_id": "build-1", "component": "exec-instance",
        "account_ref": "account-a", "strategy_ref": "strategy-a", "execution_domain_ref": "paper:demo",
        "grant_revision": "grant-v1",
        "delegation": {"delegation_id": "delegation-1", "principal_ref": "principal-a"},
        "instruments": [instrument.to_dict()],
        "rules": [{"id": "rule-1", "match": {"instrument": instrument.to_dict(), "side": "buy",
                   "offset": "open", "order_types": ["limit"], "minimum_quantity": "1", "quantity_unit": "lots"},
                   "schedule_binding": {"quantity_step": "1", "price_step": "1", "retry_limit": 2},
                   "scheme": {"name": "pass-v1", "version": 1},
                   "algorithm": {"class": "PASS", "version": 1, "params": {}},
                   "deadline": {"kind": "absolute", "at": "2099-12-31T08:00:00+08:00"},
                   "time_in_force": "DAY", "trading_day": "20261109"}],
    })
    request = OrderRequest(symbol="rb", side=Side.BUY, order_type=OrderType.LIMIT,
                           quantity=Decimal("1"), account_id="account-a", client_order_id="client-a",
                           price=Decimal("10"), idempotency_key="key-a", quantity_unit="lots",
                           exchange_id="SHFE", offset="open")
    intent = build_gateway_order_intent(inputs[0], inputs[1], request)
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    submitted(host, intent, configuration_id=config.configuration_id)

    class Port:
        def __init__(self):
            self.calls = []
        def submit(self, request):
            self.calls.append(request)
            return {"status": "ACCEPTED", "parent_ref": "parent-1"}

    port = Port()
    path = tmp_path / "route.sqlite"
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("BEGIN IMMEDIATE")
    install_execution_routing_tables(db)
    db.commit()
    router = ExecutionOrderRouter(db=db, config=config, execution_port=port,
                                  risk_selected=False, clock=lambda: 1)

    def barrier(descriptor):
        if failure == "before_json":
            raise RuntimeError("before JSON")
        assert host.bind_execution_parent_route(intent.request_key, descriptor) is True
        if failure == "after_json":
            raise RuntimeError("after JSON")
        return True

    result = router.route(intent, before_submit=barrier)
    assert result.outcome is ExecutionRoutingOutcome.EXECUTION_UNKNOWN
    assert len(port.calls) == (1 if failure == "none" else 0)
    if failure != "none":
        assert result.code == "EXECUTION_PERSISTENCE_BARRIER_FAILED"
    route = host.load_execution_route(intent.request_key)
    assert route.kind == ("PENDING" if failure == "before_json" else "EXECUTION_PARENT")
    db.close()
    reopened_host = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, inputs[0])
    with sqlite3.connect(path, isolation_level=None) as reopened_db:
        reopened_router = ExecutionOrderRouter(db=reopened_db, config=config, execution_port=port,
                                               risk_selected=False, clock=lambda: 1)
        replay = reopened_router.route(intent, before_submit=lambda _: pytest.fail("replayed barrier"))
        assert replay.outcome is ExecutionRoutingOutcome.EXECUTION_UNKNOWN
        assert replay.request_id == result.request_id
    assert len(port.calls) == (1 if failure == "none" else 0)
    assert reopened_host.load_execution_route(intent.request_key) == route
    for kind in ("GATEWAY", "RISK"):
        with pytest.raises(ValueError):
            reopened_host.bind_execution_direct_route(intent.request_key, route_kind=kind)
    with pytest.raises(ValueError):
        reopened_host.save_record(intent.request_key, observe(intent))
    with pytest.raises(ValueError):
        reopened_host.save_delegated_command(intent.request_key, reservation_id="risk-res", digest=intent.digest)


def test_reopen_pending_cannot_choose_direct_or_recreate_decision(state, inputs):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    _, ref, snapshot = submitted(host, intent)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, inputs[0])
    assert reopened.save_execution_routing_intent(intent, local_seq=1, bt_ref=ref,
        snapshot=snapshot, configuration_id="config-a") is None
    for kind in ("GATEWAY", "RISK"):
        with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
            reopened.bind_execution_direct_route(intent.request_key, route_kind=kind)
    assert reopened.load_execution_route(intent.request_key).kind == "PENDING"
    assert host.bind_execution_direct_route(intent.request_key, route_kind="RISK") is True
    assert reopened.bind_execution_direct_route(intent.request_key, route_kind="RISK") is True


def test_direct_decision_is_bound_to_process_and_thread(state, inputs, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from backtrader.live_state import gateway_execution_route

    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    submitted(host, intent)
    original_pid = gateway_execution_route.os.getpid()
    with monkeypatch.context() as m:
        m.setattr(gateway_execution_route.os, "getpid", lambda: original_pid + 1)
        with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
            host.bind_execution_direct_route(intent.request_key, route_kind="GATEWAY")
    with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
        host.bind_execution_direct_route(intent.request_key, route_kind="GATEWAY")
    # A different request and fresh host verify the thread binding independently.
    # Use a new temporary strategy fixture via the original host's second key.
    other = inputs[2]("key-b")
    ref, snapshot = _snapshot()
    order = snapshot["state"]["orders"].pop("key-a")
    snapshot["state"]["orders"]["key-b"] = order
    order["status"] = 1
    order["ref"] = ref + 1
    host.save_execution_routing_intent(other, local_seq=2, bt_ref=ref + 1,
                                      snapshot=snapshot, configuration_id="config-a")
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
            pool.submit(host.bind_execution_direct_route, other.request_key, route_kind="RISK").result()
    with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
        host.bind_execution_direct_route(other.request_key, route_kind="RISK")


def test_parent_binding_write_failure_retires_direct_decision(state, inputs, monkeypatch):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    submitted(host, intent)
    original = pending_module.atomic_write_json
    monkeypatch.setattr(pending_module, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("failure")))
    with pytest.raises(OSError):
        host.bind_execution_parent_route(intent.request_key, prepared(intent))
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    assert host.load_execution_route(intent.request_key).kind == "PENDING"
    with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
        host.bind_execution_direct_route(intent.request_key, route_kind="RISK")


def test_direct_write_failure_consumes_decision(state, inputs, monkeypatch):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    submitted(host, intent)
    original = pending_module.atomic_write_json
    monkeypatch.setattr(pending_module, "atomic_write_json", lambda *a, **k: (_ for _ in ()).throw(OSError("failure")))
    with pytest.raises(OSError):
        host.bind_execution_direct_route(intent.request_key, route_kind="RISK")
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    assert host.load_execution_route(intent.request_key).kind == "PENDING"
    with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
        host.bind_execution_direct_route(intent.request_key, route_kind="RISK")


def test_first_write_uncertain_does_not_issue_decision(state, inputs, monkeypatch):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    original = pending_module.atomic_write_json
    def write_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("uncertain after replacement")
    ref, snapshot = _snapshot()
    snapshot["state"]["orders"]["key-a"]["status"] = 1
    monkeypatch.setattr(pending_module, "atomic_write_json", write_then_fail)
    with pytest.raises(OSError):
        host.save_execution_routing_intent(intent, local_seq=1, bt_ref=ref,
                                          snapshot=snapshot, configuration_id="config-a")
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    assert host.load_execution_route(intent.request_key).kind == "PENDING"
    assert host.save_execution_routing_intent(intent, local_seq=1, bt_ref=ref,
        snapshot=snapshot, configuration_id="config-a") is None
    with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
        host.bind_execution_direct_route(intent.request_key, route_kind="GATEWAY")


@pytest.mark.parametrize("binding_change", ["store", "binding"])
def test_direct_decision_rejects_rebound_host(state, inputs, binding_change):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    submitted(host, intent)
    if binding_change == "store":
        old = host._store
        host._store = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, inputs[0])._store
    else:
        old = host._binding
        host._binding = replace(old)
    try:
        with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
            host.bind_execution_direct_route(intent.request_key, route_kind="GATEWAY")
    finally:
        if binding_change == "store":
            host._store = old
        else:
            host._binding = old
    with pytest.raises(ValueError, match="DECISION_UNAVAILABLE"):
        host.bind_execution_direct_route(intent.request_key, route_kind="GATEWAY")


def test_direct_write_uncertain_reopens_only_same_final(state, inputs, monkeypatch):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    submitted(host, intent)
    original = pending_module.atomic_write_json
    def write_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("uncertain after replacement")
    monkeypatch.setattr(pending_module, "atomic_write_json", write_then_fail)
    with pytest.raises(OSError):
        host.bind_execution_direct_route(intent.request_key, route_kind="GATEWAY")
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, inputs[0])
    assert reopened.bind_execution_direct_route(intent.request_key, route_kind="GATEWAY") is True
    with pytest.raises(ValueError, match="CONFLICT"):
        reopened.bind_execution_direct_route(intent.request_key, route_kind="RISK")


def test_v8_risk_direct_delegated_record_round_trips(state, inputs):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    ticket, _, _ = submitted(host, intent)
    assert host.bind_execution_direct_route(intent.request_key, route_kind="RISK") is True
    assert host.consume_risk_reserve_ticket(intent, ticket) is True
    record = host.save_delegated_command(intent.request_key, reservation_id="risk-reservation",
                                         digest=intent.digest, permit_id="risk-permit",
                                         actor_principal="risk-principal",
                                         gateway_state="RESERVED", gateway_version=1)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, inputs[0])
    assert reopened.load_execution_route(intent.request_key).kind == "RISK"
    assert reopened.load_delegated_command(intent.request_key) == record
    assert record.reservation_id == "risk-reservation"
    assert record.actor_principal == "risk-principal"


def test_v8_gateway_direct_record_round_trips(state, inputs):
    host = setup_v7(state, inputs).upgrade_for_execution_routing()
    intent = inputs[2]()
    submitted(host, intent)
    assert host.bind_execution_direct_route(intent.request_key, route_kind="GATEWAY") is True
    record = observe(intent)
    host.save_record(intent.request_key, record)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, inputs[0])
    assert reopened.load_execution_route(intent.request_key).kind == "GATEWAY"
    assert reopened.load_record(intent.request_key) == record
