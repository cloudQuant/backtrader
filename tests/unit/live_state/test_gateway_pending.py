"""Synthetic Gateway persistence; no provider or network calls."""
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding, GatewayCommandRecord
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py._contracts.models import OrderRequest, OrderType, Side
from bt_api_py.gateway_direct_client import GatewayClientRoute, GatewayReleasePlan, build_gateway_order_intent

from backtrader.live_state import LiveStateError, PendingCommandStore, rebind_identity
from backtrader.live_state import pending as pending_module
from backtrader.live_state.gateway_pending import GatewayPendingHost
from ._helpers import place_record


@pytest.fixture
def inputs(state):
    binding = GatewayCommandBinding("journal-a", "account-a", "strategy-a", "principal-a")
    route = GatewayClientRoute("broker.direct_write", "service-a", "instance-a", "scope-a",
        WireScope("paper:demo", account_ref="account-a", strategy_ref="strategy-a", run_id="run-a"),
        WireIdentity(WireRole.STRATEGY_CLIENT, "principal-a", "strategy-a"))
    def intent(key="key-a", ttl=10, price="10"):
        req = OrderRequest(symbol="rb", side=Side.BUY, order_type=OrderType.LIMIT,
            quantity=Decimal("1"), account_id="account-a", client_order_id="client-a",
            price=Decimal(price), idempotency_key=key)
        return build_gateway_order_intent(binding, route, req, ttl_seconds=ttl)
    return binding, route, intent


def observe(intent, *, state="RESERVED", version=1, native=None, strong=(), reservation=None):
    return GatewayCommandRecord(1, intent.binding, intent.request_key,
        reservation or "res-" + intent.request_key, intent.digest, state, version,
        "g1", "g1", True, 9.0 if state == "RESERVED" else None, False,
        None, None, native, strong)


def host(state, binding, **kwargs):
    return GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding, **kwargs)


def data(state):
    with open(state.pending.path, "rb") as f:
        return f.read()


def test_explicit_migration_preserves_old_markers_and_atomic_failure(state, inputs, monkeypatch):
    binding, _, make = inputs
    old = state.pending.commit(place_record(state.strategy_uuid), local_seq=6)
    before = data(state)
    GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert data(state) == before
    original = pending_module.atomic_write_json
    monkeypatch.setattr(pending_module, "atomic_write_json", lambda *a: (_ for _ in ()).throw(OSError("synthetic")))
    with pytest.raises(OSError):
        host(state, binding)
    assert data(state) == before
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    h = host(state, binding)
    assert state.pending.get(old)["local_seq"] == 6
    assert json.loads(data(state))["version"] == 2
    h.save_intent(make())
    assert len(h.list_intents()) == 1
    with pytest.raises(ValueError):
        host(state, replace(binding, journal_id="other"))
    with pytest.raises(Exception):
        host(state, binding, max_entries=9)


def test_two_empty_markers_idempotent_ttl_and_conflicts(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    a, b = make(), make("key-b")
    h.save_intent(a, local_seq=1, bt_ref=2)
    h.save_intent(make(ttl=30))
    assert h.load_intent(a.request_key).ttl_seconds == 10
    h.save_intent(b, local_seq=3)
    ra, rb = observe(a), observe(b)
    h.save_record(a.request_key, ra)
    h.save_record(b.request_key, rb)
    ma = h.commit_pre_dispatch(a.request_key, ra)
    assert ma == GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding).commit_pre_dispatch(a.request_key, replace(ra, remaining_ttl_seconds=5))
    mb = h.commit_pre_dispatch(b.request_key, rb)
    assert ma != mb and state.pending.get(ma)["native_identity"] == {}
    assert state.pending.get(ma)["gateway_ref"] == {"request_key": a.request_key}
    before = data(state)
    with pytest.raises(ValueError):
        h.save_intent(make(price="11"))
    with pytest.raises(ValueError):
        h.save_intent(b, local_seq=1)
    with pytest.raises(ValueError):
        h.commit_pre_dispatch(a.request_key, observe(a, reservation="different"))
    assert data(state) == before


def test_native_binding_is_atomic_and_does_not_change_pending_status(state, inputs, monkeypatch):
    binding, _, make = inputs
    h = host(state, binding)
    a, b = make(), make("key-b")
    for i in (a, b):
        h.save_intent(i)
        h.save_record(i.request_key, observe(i))
        h.commit_pre_dispatch(i.request_key, observe(i))
    native = NativeOrderIdentity("CTP___FUTURE", "42", {"front_id": 1, "trading_day": "20261108"}, 7)
    dispatched = observe(a, state="DISPATCHING", version=2, native=native, strong=("a" * 64,))
    before = data(state)
    original = pending_module.atomic_write_json
    monkeypatch.setattr(pending_module, "atomic_write_json", lambda *a: (_ for _ in ()).throw(OSError("synthetic")))
    with pytest.raises(OSError):
        h.save_record(a.request_key, dispatched)
    assert data(state) == before
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    h.save_record(a.request_key, dispatched)
    marker = state.pending.active()[0]
    assert marker["status"] == "PREPARED" and marker["client_order_id"] == "42"
    assert marker["trading_day"] == "20261108" and marker["session_generation"] == 7
    snapshot = data(state)
    h.save_record(a.request_key, dispatched)
    assert data(state) == snapshot
    with pytest.raises(ValueError):
        h.save_record(b.request_key, observe(b, state="DISPATCHING", version=2, native=native, strong=("b" * 64,)))
    with pytest.raises(ValueError):
        h.save_record(b.request_key, observe(b, state="DISPATCHING", version=2,
            native=replace(native, client_order_id="other"), strong=("a" * 64,)))
    assert data(state) == snapshot


def test_rebind_blocked_by_markerless_intent_and_capacity(state, inputs):
    binding, _, make = inputs
    h = host(state, binding, max_entries=1)
    a = make()
    h.save_intent(a)
    before = data(state)
    with pytest.raises(ValueError):
        h.save_intent(make("key-b"))
    assert data(state) == before
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(state.strategy_dir, mode="new_instance", operator="synthetic", reason="test")
    assert data(state) == before


def test_release_stable_and_wrong_uuid_or_binding_refused(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    a = make()
    h.save_intent(a)
    rec = observe(a)
    h.save_record(a.request_key, rec)
    plan = GatewayReleasePlan(a.request_key, rec.reservation_id, a.digest, "op-a", 1)
    h.save_release(plan)
    assert h.load_release(a.request_key) == plan
    before = data(state)
    with pytest.raises(ValueError):
        h.save_release(replace(plan, operation_id="op-b"))
    with pytest.raises(Exception):
        GatewayPendingHost(state.strategy_dir, "1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b", binding).list_intents()
    assert data(state) == before


def _race_commit(strategy_dir, strategy_uuid, binding, intent, result_queue):
    try:
        h = GatewayPendingHost(strategy_dir, strategy_uuid, binding)
        h.save_intent(intent)
        record = observe(intent)
        h.save_record(intent.request_key, record)
        result_queue.put(("ok", h.commit_pre_dispatch(intent.request_key, record)))
    except Exception as exc:
        result_queue.put(("error", type(exc).__name__))


def test_two_process_hosts_commit_same_marker(state, inputs):
    import multiprocessing

    binding, _, make = inputs
    host(state, binding)
    intent = make()
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    processes = [ctx.Process(target=_race_commit,
        args=(state.strategy_dir, state.strategy_uuid, binding, intent, queue)) for _ in range(2)]
    for process in processes:
        process.start()
    outcomes = [queue.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0
    assert all(status == "ok" for status, _ in outcomes)
    assert outcomes[0][1] == outcomes[1][1]
    assert len(state.pending.active()) == 1


def test_old_run_conflict_and_released_markerless_allows_rebind(state, inputs):
    binding, route, make = inputs
    h = host(state, binding)
    a = make()
    h.save_intent(a)
    newer_route = replace(route, scope=replace(route.scope, run_id="run-b"))
    new_run = replace(a, route=newer_route)
    before = data(state)
    with pytest.raises(ValueError):
        h.save_intent(new_run)
    assert data(state) == before
    reserved = observe(a)
    h.save_record(a.request_key, reserved)
    plan = GatewayReleasePlan(a.request_key, reserved.reservation_id, a.digest, "op-a", 1)
    h.save_release(plan)
    released = replace(reserved, state="RELEASED", version=2, remaining_ttl_seconds=None,
        release_operation_id="op-a", release_expected_version=1)
    h.save_record(a.request_key, released)
    new_identity = rebind_identity(state.strategy_dir, mode="new_instance", operator="synthetic", reason="test")
    assert new_identity.strategy_uuid != state.strategy_uuid


def test_gateway_history_survives_legacy_history_limit(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    store = PendingCommandStore(state.strategy_dir, state.strategy_uuid, history_limit=1)
    ids = []
    for key in ("key-a", "key-b"):
        intent = make(key)
        h.save_intent(intent)
        record = observe(intent)
        h.save_record(key, record)
        marker = h.commit_pre_dispatch(key, record)
        assert store.mark(marker, "TERMINAL")
        ids.append(marker)
    assert [m["marker_id"] for m in store.history()] == ids
    with pytest.raises(ValueError):
        h.commit_pre_dispatch("key-a", observe(make("key-a")))
    assert store.get(ids[0])["status"] == "TERMINAL"


def test_v2_corrupt_marker_or_record_is_refused(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    record = observe(intent)
    h.save_record(intent.request_key, record)
    marker_id = h.commit_pre_dispatch(intent.request_key, record)
    raw = json.loads(data(state))
    raw["active"][marker_id]["symbol"] = "different"
    with open(state.pending.path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    with pytest.raises(Exception):
        h.load_intent(intent.request_key)


def test_migration_does_not_trim_valid_legacy_history(state, inputs):
    import copy
    import uuid

    binding, _, _ = inputs
    marker_id = state.pending.commit(place_record(state.strategy_uuid))
    assert state.pending.mark(marker_id, "TERMINAL")
    raw = json.loads(data(state))
    original = raw["history"][0]
    raw["history"] = []
    for _ in range(502):
        marker = copy.deepcopy(original)
        marker["marker_id"] = str(uuid.uuid4())
        raw["history"].append(marker)
    with open(state.pending.path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    before = list(raw["history"])
    host(state, binding)
    assert json.loads(data(state))["history"] == before


def test_commit_then_raised_error_replay_is_idempotent(state, inputs, monkeypatch):
    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    original = pending_module.atomic_write_json
    def write_then_raise(path, content):
        original(path, content)
        raise OSError("synthetic lost acknowledgement")
    monkeypatch.setattr(pending_module, "atomic_write_json", write_then_raise)
    with pytest.raises(OSError):
        h.save_intent(intent, local_seq=8)
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    committed = data(state)
    h.save_intent(intent)
    assert data(state) == committed
    assert h.load_intent(intent.request_key) == intent


def test_direct_marker_cannot_use_unmarked_gateway_sequence(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    h.save_intent(make(), local_seq=17)
    before = data(state)
    assert state.pending.commit(place_record(state.strategy_uuid), local_seq=17) is None
    assert data(state) == before


def test_empty_gateway_binding_is_not_pristine_for_identity_reinitialization(state, inputs):
    binding, _, _ = inputs
    host(state, binding)
    assert pending_module.is_pristine_pending(json.loads(data(state)), state.pending.path) is False


def test_legacy_pending_fact_conflict_cannot_poison_gateway_native_observation(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    reserved = observe(intent)
    h.save_record(intent.request_key, reserved)
    marker = h.commit_pre_dispatch(intent.request_key, reserved)
    assert state.pending.attach(marker, client_order_id="expected") is True
    before = data(state)
    native = NativeOrderIdentity("CTP___FUTURE", "different", {"front_id": 1}, 7)
    with pytest.raises(ValueError):
        h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
                                                   native=native, strong=("a" * 64,)))
    assert data(state) == before
    assert h.load_record(intent.request_key) == reserved


@pytest.mark.parametrize("new_state", ["SENT", "UNKNOWN", "EXPIRED"])
def test_stale_reserved_cannot_reauthorize_existing_marker(state, inputs, new_state):
    binding, _, make = inputs
    first_host = host(state, binding)
    other_host = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    intent = make()
    first_host.save_intent(intent)
    old_reserved = observe(intent)
    first_host.save_record(intent.request_key, old_reserved)
    marker_id = first_host.commit_pre_dispatch(intent.request_key, old_reserved)
    if new_state == "EXPIRED":
        progressed = observe(intent, state="EXPIRED", version=2)
    else:
        native = NativeOrderIdentity("CTP___FUTURE", "native-a", {"front_id": 1}, 7)
        progressed = observe(intent, state=new_state, version=3, native=native, strong=("a" * 64,))
    other_host.save_record(intent.request_key, progressed)
    snapshot = data(state)
    sends = []
    try:
        first_host.commit_pre_dispatch(intent.request_key, old_reserved)
    except ValueError:
        pass
    else:
        sends.append("synthetic-dispatch")
    assert sends == [] and data(state) == snapshot
    assert state.pending.get(marker_id) is not None


@pytest.mark.parametrize("local_status", ["UNKNOWN", "DISPATCHED", "ACCEPTED", "TERMINAL"])
def test_nonprepared_local_marker_cannot_reauthorize_reserved(state, inputs, local_status):
    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    reserved = observe(intent)
    h.save_record(intent.request_key, reserved)
    marker_id = h.commit_pre_dispatch(intent.request_key, reserved)
    assert state.pending.mark(marker_id, local_status)
    before = data(state)
    with pytest.raises(ValueError):
        h.commit_pre_dispatch(intent.request_key, reserved)
    assert data(state) == before and state.pending.get(marker_id)["status"] == local_status


def test_markerless_native_identity_comparison_is_type_strict(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    identity = NativeOrderIdentity("CTP___FUTURE", "native-a", {"front_id": 1}, 7)
    h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
                                              native=identity, strong=("a" * 64,)))
    before = data(state)
    changed = NativeOrderIdentity("CTP___FUTURE", "native-a", {"front_id": True}, 7)
    with pytest.raises(ValueError):
        h.save_record(intent.request_key, observe(intent, state="SENT", version=3,
                                                  native=changed, strong=("a" * 64,)))
    assert data(state) == before


def test_loaded_gateway_marker_conflicting_native_facts_is_corrupt(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    reserved = observe(intent)
    h.save_record(intent.request_key, reserved)
    marker_id = h.commit_pre_dispatch(intent.request_key, reserved)
    native = NativeOrderIdentity("CTP___FUTURE", "native-a", {"front_id": 1}, 7)
    h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
                                              native=native, strong=("a" * 64,)))
    raw = json.loads(data(state))
    raw["active"][marker_id]["facts"]["front_id"] = True
    with open(state.pending.path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    corrupt = data(state)
    with pytest.raises(Exception):
        h.load_record(intent.request_key)
    assert data(state) == corrupt


def _strong_digests(identity, *, scoped):
    import hashlib
    from bt_api_py.direct_write import project_direct_strong_identity_keys
    return tuple(sorted(hashlib.sha256(key.encode("utf-8")).hexdigest()
                        for key in project_direct_strong_identity_keys(identity, day_scoped_ids=scoped)))


def _shared_session_identity(day, *, extra=True):
    fields = {"front_id": 1, "session_id": 7, "trading_day": day}
    if extra:
        fields.update(exchange_id="SHFE", order_sys_id="synthetic-sys")
    return NativeOrderIdentity("CTP___FUTURE", "000000000001", fields, 3)


def test_context_before_and_after_marker_is_immutable_across_restart(state, inputs):
    from dataclasses import FrozenInstanceError

    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    assert h.load_context(intent.request_key) is None
    h.save_intent(intent, local_seq=9, bt_ref=12)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    context = reopened.load_context(intent.request_key)
    assert (context.marker_id, context.local_seq, context.bt_ref) == (None, 9, 12)
    with pytest.raises(FrozenInstanceError):
        context.local_seq = 1
    record = observe(intent)
    reopened.save_record(intent.request_key, record)
    marker = reopened.commit_pre_dispatch(intent.request_key, record)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert (reopened.load_context(intent.request_key).marker_id,
            reopened.load_context(intent.request_key).local_seq,
            reopened.load_context(intent.request_key).bt_ref) == (marker, 9, 12)


@pytest.mark.parametrize("day,scoped,conflict", [
    ("20261105", True, True),
    ("20261106", True, False),
    ("20261106", False, True),
])
def test_gateway_record_vs_legacy_strong_identity(state, inputs, day, scoped, conflict):
    binding, _, make = inputs
    assert state.pending.commit(place_record(state.strategy_uuid)) is not None
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    h.save_record(intent.request_key, observe(intent))
    identity = _shared_session_identity(day)
    incoming = observe(intent, state="DISPATCHING", version=2, native=identity,
                       strong=_strong_digests(identity, scoped=scoped))
    before = data(state)
    if conflict:
        with pytest.raises(Exception):
            h.save_record(intent.request_key, incoming)
        assert data(state) == before
    else:
        h.save_record(intent.request_key, incoming)
        assert h.load_record(intent.request_key) == incoming


def test_legacy_commit_cannot_overlap_gateway_strong_identity(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    identity = _shared_session_identity("20261105")
    h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
        native=identity, strong=_strong_digests(identity, scoped=True)))
    before = data(state)
    assert state.pending.commit(place_record(state.strategy_uuid)) is None
    assert data(state) == before


def test_loaded_legacy_gateway_strong_conflict_is_corrupt(state, inputs):
    binding, _, make = inputs
    assert state.pending.commit(place_record(state.strategy_uuid)) is not None
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    identity = _shared_session_identity("20261105")
    incoming = observe(intent, state="DISPATCHING", version=2, native=identity,
                       strong=_strong_digests(identity, scoped=True))
    raw = json.loads(data(state))
    raw["gateway"]["intents"][intent.request_key]["record"] = incoming.to_mapping()
    with open(state.pending.path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    before = data(state)
    with pytest.raises(Exception):
        h.load_record(intent.request_key)
    assert data(state) == before


def test_malformed_legacy_identity_and_day_are_not_silently_skipped(state, inputs):
    binding, _, make = inputs
    assert state.pending.commit(place_record(state.strategy_uuid)) is not None
    raw = json.loads(data(state))
    marker = next(iter(raw["active"].values()))
    marker["trading_day"] = "20261106"
    with open(state.pending.path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    identity = _shared_session_identity("20261105")
    before = data(state)
    with pytest.raises(Exception):
        h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
            native=identity, strong=_strong_digests(identity, scoped=True)))
    assert data(state) == before


def test_legacy_without_day_or_strong_identity_is_allowed(state, inputs):
    binding, _, _ = inputs
    marker = place_record(state.strategy_uuid, native_identity={}, trading_day=None)
    assert state.pending.commit(marker) is not None
    h = host(state, binding)
    assert h.list_intents() == ()


def test_malformed_legacy_candidate_fields_are_refused(state, inputs):
    binding, _, make = inputs
    marker = place_record(state.strategy_uuid, native_identity={"front_id": True}, trading_day=None)
    assert state.pending.commit(marker) is not None
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    identity = _shared_session_identity("20261105")
    before = data(state)
    with pytest.raises(Exception):
        h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
            native=identity, strong=_strong_digests(identity, scoped=True)))
    assert data(state) == before


def test_exact_legacy_identity_conflicts_even_when_no_strong_key_is_available(state, inputs):
    binding, _, make = inputs
    assert state.pending.commit(place_record(state.strategy_uuid, native_identity={}, trading_day=None))
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    identity = NativeOrderIdentity("CTP___FUTURE", "000000000001", {}, 3)
    before = data(state)
    with pytest.raises(Exception):
        h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
                                                  native=identity, strong=("a" * 64,)))
    assert data(state) == before


def test_legacy_float_extra_is_preserved_and_does_not_block_gateway(state, inputs):
    binding, _, make = inputs
    legacy = place_record(state.strategy_uuid, native_identity={
        "front_id": 1, "session_id": 7, "trading_day": "20261105", "extra_metric": 0.25})
    marker_id = state.pending.commit(legacy)
    h = host(state, binding)
    assert state.pending.get(marker_id)["native_identity"]["extra_metric"] == 0.25
    intent = make()
    h.save_intent(intent)
    identity = NativeOrderIdentity("CTP___FUTURE", "distinct", {
        "front_id": 9, "session_id": 10, "trading_day": "20261105"}, 3)
    h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
        native=identity, strong=_strong_digests(identity, scoped=True)))
    assert h.load_record(intent.request_key).native_identity == identity


def _facts_native_identity():
    return NativeOrderIdentity("CTP___FUTURE", "different", {
        "front_id": 8, "session_id": 9, "trading_day": "20261105",
        "exchange_id": "SHFE", "order_sys_id": "synthetic-sys"}, 3)


def test_gateway_native_conflicts_with_legacy_facts_identity(state, inputs):
    binding, _, make = inputs
    marker = state.pending.commit(place_record(state.strategy_uuid))
    assert state.pending.attach(marker, exchange_id="SHFE", order_sys_id="synthetic-sys")
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    native = _facts_native_identity()
    before = data(state)
    with pytest.raises(Exception):
        h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
            native=native, strong=_strong_digests(native, scoped=True)))
    assert data(state) == before


def test_legacy_fact_attachment_conflict_and_reload_refused(state, inputs):
    binding, _, make = inputs
    h = host(state, binding)
    intent = make()
    h.save_intent(intent)
    native = _facts_native_identity()
    h.save_record(intent.request_key, observe(intent, state="DISPATCHING", version=2,
        native=native, strong=_strong_digests(native, scoped=True)))
    marker = state.pending.commit(place_record(state.strategy_uuid))
    assert marker is not None
    before = data(state)
    assert not state.pending.attach(marker, exchange_id="SHFE", order_sys_id="synthetic-sys")
    assert data(state) == before
    raw = json.loads(before)
    raw["active"][marker]["facts"].update(exchange_id="SHFE", order_sys_id="synthetic-sys")
    with open(state.pending.path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    corrupt = data(state)
    with pytest.raises(Exception):
        h.load_record(intent.request_key)
    assert data(state) == corrupt
