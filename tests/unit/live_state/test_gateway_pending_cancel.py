"""Synthetic durable Gateway cancellation host; no provider or account access."""

import json
import multiprocessing
from dataclasses import replace

import pytest
from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_base.gateway_cancel_protocol import GatewayCancelRecord
from bt_api_py.gateway_direct_client import GatewayCancelPlan

from backtrader.live_state import LiveStateCorrupt, LiveStateError, rebind_identity
from backtrader.live_state import pending as pending_module
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.test_gateway_pending import data, host, observe
from tests.unit.live_state.test_gateway_pending import inputs as inputs


def prepare(state, inputs, keys=("key-a",)):
    binding, route, make = inputs
    original = host(state, binding)
    for index, key in enumerate(keys):
        intent = make(key)
        original.save_intent(intent, local_seq=index + 1)
        reserved = observe(intent)
        original.save_record(key, reserved)
        original.commit_pre_dispatch(key, reserved)
        native = NativeOrderIdentity(
            "CTP___FUTURE", "ref-" + key, {"front_id": 1, "trading_day": "20261108"}, 7
        )
        original.save_record(
            key,
            observe(
                intent, state="DISPATCHING", version=2, native=native, strong=(str(index + 1) * 64,)
            ),
        )
    return original


def plan(host, route, key="key-a", op="cancel-a"):
    original = host.load_record(key)
    return GatewayCancelPlan(
        original.binding, route, key, original.reservation_id, original.digest, op
    )


def record(plan, status="REQUESTED", *, attempt="attempt-a", owner="g1", generation="g1"):
    return GatewayCancelRecord(
        1,
        plan.binding,
        plan.operation_id,
        attempt,
        plan.request_key,
        plan.reservation_id,
        plan.digest,
        status,
        {"REQUESTED": 1, "DISPATCHING": 2, "SENT": 3, "NOT_SENT": 3, "UNKNOWN": 3}[status],
        owner,
        generation,
        owner == generation,
        None,
    )


def upgrade(state, binding, capacity=10):
    return GatewayPendingHost.upgrade_for_cancellation(
        state.strategy_dir, state.strategy_uuid, binding, max_cancel_entries=capacity
    )


def test_nonempty_v2_migration_is_explicit_validated_and_idempotent(state, inputs, monkeypatch):
    binding, route, _ = inputs
    original = prepare(state, inputs, ("key-a", "key-b"))
    marker = original.load_context("key-b").marker_id
    assert state.pending.mark(marker, "TERMINAL")
    before = data(state)
    old = json.loads(before)
    with pytest.raises(ValueError, match="UPGRADE_REQUIRED"):
        original.save_cancel_plan(plan(original, route))
    assert data(state) == before
    original_write = pending_module.atomic_write_json
    monkeypatch.setattr(
        pending_module, "atomic_write_json", lambda *_: (_ for _ in ()).throw(OSError("synthetic"))
    )
    with pytest.raises(OSError):
        upgrade(state, binding)
    assert data(state) == before
    monkeypatch.setattr(pending_module, "atomic_write_json", original_write)
    current = upgrade(state, binding)
    after = json.loads(data(state))
    assert after["version"] == 3
    assert after["active"] == old["active"] and after["history"] == old["history"]
    for key in ("binding", "max_entries", "intents"):
        assert after["gateway"][key] == old["gateway"][key]
    assert after["gateway"]["cancel_attempts"] == {}
    stable = data(state)
    upgrade(state, binding)
    assert data(state) == stable
    with pytest.raises(ValueError, match="CAPACITY_MISMATCH"):
        upgrade(state, binding, 9)
    current.save_cancel_plan(plan(current, route))
    assert original.load_intent("key-a") == current.load_intent("key-a")


def test_v1_refused_and_corrupt_v2_never_upgraded(state, inputs):
    binding, _, _ = inputs
    before = data(state)
    with pytest.raises(ValueError):
        upgrade(state, binding)
    assert data(state) == before
    prepare(state, inputs)
    bad = json.loads(data(state))
    bad["gateway"]["intents"]["key-a"]["record"]["digest"] = "0" * 64
    with open(state.pending.path, "w", encoding="utf-8") as file:
        json.dump(bad, file)
    before = data(state)
    with pytest.raises(LiveStateCorrupt):
        upgrade(state, binding)
    assert data(state) == before


def test_v1_pending_validation_does_not_import_gateway_sdk():
    import subprocess
    import sys

    script = """
import builtins
old_import = builtins.__import__
def checked(name, *args, **kwargs):
    if name == 'bt_api_py' or name.startswith('bt_api_py.') or name == 'bt_api_base' or name.startswith('bt_api_base.'):
        raise AssertionError('v1 imported optional SDK')
    return old_import(name, *args, **kwargs)
builtins.__import__ = checked
from backtrader.live_state.pending import initial_pending_state, validate_pending_state
uuid = '1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b'
assert validate_pending_state(initial_pending_state(uuid), 'synthetic', uuid)['version'] == 1
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=20, check=False
    )
    assert result.returncode == 0, result.stderr


def test_plan_target_identity_capacity_and_immutable_winner(state, inputs):
    binding, route, _ = inputs
    prepare(state, inputs, ("key-a", "key-b"))
    first = upgrade(state, binding, capacity=1)
    other = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    a, b = plan(first, route), plan(first, route, key="key-b")
    assert first.save_cancel_plan(a) == a
    assert other.save_cancel_plan(b) == a
    assert first.load_cancel_plan(a.operation_id) == a
    for changed in (
        replace(a, digest="0" * 64),
        replace(a, reservation_id="other"),
        replace(a, route=replace(route, scope=replace(route.scope, run_id="run-b"))),
    ):
        with pytest.raises(ValueError):
            first.save_cancel_plan(changed)
    with pytest.raises(ValueError, match="CAPACITY_EXCEEDED"):
        first.save_cancel_plan(replace(b, operation_id="other"))
    assert first.load_cancel_plan(a.operation_id) == a
    assert (
        GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding).load_cancel_plan(
            a.operation_id
        )
        == a
    )


def test_cancel_record_monotonic_stale_winner_and_conflicts(state, inputs):
    binding, route, _ = inputs
    prepare(state, inputs)
    first = upgrade(state, binding)
    second = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    item = first.save_cancel_plan(plan(first, route))
    initial, dispatched, sent = (
        record(item, status) for status in ("REQUESTED", "DISPATCHING", "SENT")
    )
    assert first.save_cancel_record(item.operation_id, initial) == initial
    assert second.save_cancel_record(item.operation_id, dispatched) == dispatched
    assert first.save_cancel_record(item.operation_id, sent) == sent
    assert second.save_cancel_record(item.operation_id, initial) == sent
    observed = replace(sent, owner_generation="g2", generation_current=False)
    assert second.save_cancel_record(item.operation_id, observed) == observed
    with pytest.raises(ValueError):
        first.save_cancel_record(item.operation_id, replace(sent, state="UNKNOWN"))
    with pytest.raises(ValueError):
        first.save_cancel_record(item.operation_id, record(item, attempt="other"))
    assert first.load_cancel_record(item.operation_id) == observed


def _process_plan(root, strategy, binding, candidate, barrier, results):
    try:
        client = GatewayPendingHost(root, strategy, binding)
        barrier.wait(timeout=10)
        results.put(("ok", client.save_cancel_plan(candidate)))
    except BaseException as error:
        results.put(("error", type(error).__name__))


def test_spawned_hosts_race_different_plans_for_same_operation(state, inputs):
    binding, route, _ = inputs
    prepare(state, inputs, ("key-a", "key-b"))
    target = upgrade(state, binding)
    candidates = [plan(target, route, key=key) for key in ("key-a", "key-b")]
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_plan,
            args=(state.strategy_dir, state.strategy_uuid, binding, candidate, barrier, results),
        )
        for candidate in candidates
    ]
    for process in processes:
        process.start()
    try:
        outcomes = [results.get(timeout=20) for _ in processes]
        assert all(status == "ok" for status, _ in outcomes), outcomes
        assert outcomes[0][1] == outcomes[1][1] == target.load_cancel_plan("cancel-a")
        assert outcomes[0][1] in candidates
    finally:
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
                pytest.fail("test process required termination")
            assert process.exitcode == 0
        results.close()


def test_postwrite_exception_retry_recovers_original_plan_and_record(state, inputs, monkeypatch):
    binding, route, _ = inputs
    prepare(state, inputs)
    target = upgrade(state, binding)
    selected = plan(target, route)
    original = pending_module.atomic_write_json

    def write_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("synthetic reply lost after replacement")

    monkeypatch.setattr(pending_module, "atomic_write_json", write_then_fail)
    with pytest.raises(OSError):
        target.save_cancel_plan(selected)
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    assert target.save_cancel_plan(selected) == selected
    value = record(selected)
    monkeypatch.setattr(pending_module, "atomic_write_json", write_then_fail)
    with pytest.raises(OSError):
        target.save_cancel_record(selected.operation_id, value)
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    assert target.save_cancel_record(selected.operation_id, value) == value


def test_cancel_updates_do_not_evict_legacy_history(state, inputs):
    from tests.unit.live_state._helpers import place_record

    binding, route, _ = inputs
    for index in range(2):
        marker = state.pending.commit(place_record(
            state.strategy_uuid, client_order_id=f"legacy-{index}"
        ))
        assert marker and state.pending.mark(marker, "TERMINAL")
    prepare(state, inputs)
    target = upgrade(state, binding)
    target._store.history_limit = 1
    before = json.loads(data(state))["history"]
    selected = target.save_cancel_plan(plan(target, route))
    target.save_cancel_record(selected.operation_id, record(selected))
    assert json.loads(data(state))["history"] == before


@pytest.mark.parametrize("status", [None, "REQUESTED", "DISPATCHING", "UNKNOWN", "SENT"])
def test_unresolved_cancel_blocks_rebind_even_after_original_marker_terminal(state, inputs, status):
    binding, route, _ = inputs
    prepare(state, inputs)
    target = upgrade(state, binding)
    selected = target.save_cancel_plan(plan(target, route))
    if status:
        target.save_cancel_record(selected.operation_id, record(selected, status))
    marker = target.load_context("key-a").marker_id
    assert state.pending.mark(marker, "TERMINAL")
    if status == "SENT":
        new_identity = rebind_identity(
            state.strategy_dir, mode="new_instance", operator="test", reason="test"
        )
        assert new_identity.strategy_uuid != state.strategy_uuid
    else:
        with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
            rebind_identity(state.strategy_dir, mode="new_instance", operator="test", reason="test")


def test_not_sent_does_not_clear_unresolved_original(state, inputs):
    binding, route, _ = inputs
    prepare(state, inputs)
    target = upgrade(state, binding)
    selected = target.save_cancel_plan(plan(target, route))
    target.save_cancel_record(selected.operation_id, record(selected, "NOT_SENT"))
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(state.strategy_dir, mode="new_instance", operator="test", reason="test")


def _process_record(root, strategy, binding, candidate, barrier, results):
    try:
        target = GatewayPendingHost(root, strategy, binding)
        barrier.wait(timeout=10)
        results.put(("ok", target.save_cancel_record(candidate.operation_id, candidate)))
    except BaseException as error:
        results.put(("error", type(error).__name__))


def test_spawned_hosts_race_old_and_new_record_never_regresses(state, inputs):
    binding, route, _ = inputs
    prepare(state, inputs)
    target = upgrade(state, binding)
    item = target.save_cancel_plan(plan(target, route))
    old, new = record(item), record(item, "SENT")
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    processes = [
        ctx.Process(
            target=_process_record,
            args=(state.strategy_dir, state.strategy_uuid, binding, candidate, barrier, results),
        )
        for candidate in (old, new)
    ]
    for process in processes:
        process.start()
    try:
        outcomes = [results.get(timeout=20) for _ in processes]
        assert all(status == "ok" for status, _ in outcomes), outcomes
        assert target.load_cancel_record(item.operation_id) == new
    finally:
        for process in processes:
            process.join(10)
            if process.is_alive():
                process.terminate()
                process.join(5)
                pytest.fail("test process required termination")
            assert process.exitcode == 0
        results.close()


@pytest.mark.parametrize(
    "fault", ["wrong_route", "wrong_target", "wrong_operation", "bad_record", "bad_capacity"]
)
def test_v3_corruption_rejected_on_reload(state, inputs, fault):
    binding, route, _ = inputs
    prepare(state, inputs)
    target = upgrade(state, binding)
    item = target.save_cancel_plan(plan(target, route))
    target.save_cancel_record(item.operation_id, record(item))
    bad = json.loads(data(state))
    attempts = bad["gateway"]["cancel_attempts"]
    row = attempts[item.operation_id]
    if fault == "wrong_route":
        row["plan"]["route"]["scope"]["run_id"] = "other-run"
    elif fault == "wrong_target":
        row["plan"]["reservation_id"] = "other"
    elif fault == "wrong_operation":
        attempts["other"] = attempts.pop(item.operation_id)
    elif fault == "bad_record":
        row["record"]["state"] = "SENT"
    else:
        bad["gateway"]["max_cancel_entries"] = 0
    with open(state.pending.path, "w", encoding="utf-8") as file:
        json.dump(bad, file)
    before = data(state)
    with pytest.raises(LiveStateCorrupt):
        target.load_cancel_plan(item.operation_id)
    assert data(state) == before


@pytest.mark.parametrize("capacity", [0, True, 100001, 1.0])
def test_cancel_capacity_strict(state, inputs, capacity):
    binding, _, _ = inputs
    prepare(state, inputs)
    before = data(state)
    with pytest.raises(ValueError, match="INVALID_GATEWAY_CAPACITY"):
        upgrade(state, binding, capacity)
    assert data(state) == before


def test_sdk_client_uses_durable_host_for_cancel_and_status(state, inputs):
    import time
    from types import SimpleNamespace

    from bt_api_py.gateway_direct_client import GatewayDirectClient
    from bt_api_py.service_runtime_thread import ThreadedServiceClientRuntime

    binding, route, _ = inputs
    prepare(state, inputs)
    target = upgrade(state, binding)
    called = []

    class SyntheticRuntime:
        def __init__(self):
            self.identity, self.run_id = route.identity, route.scope.run_id
            self.bindings = (
                SimpleNamespace(
                    registration_id="reg",
                    service_epoch="epoch",
                    active=True,
                    mount=route.mount,
                    service_id=route.service_id,
                    instance_id=route.instance_id,
                    scope_ref=route.scope_ref,
                    scope=route.scope,
                    operations=frozenset({"direct.cancel", "direct.cancel_status"}),
                    lease_deadline=time.monotonic() + 60,
                    required=True,
                ),
            )
            self.healthy = True
            self.cleanup_failures = self.unregister_uncertainties = 0

        def start(self):
            pass

        def maintain(self):
            pass

        def next_maintenance_delay(self):
            return 1.0

        def call(self, _mount, operation, arguments, **_kwargs):
            called.append((operation, dict(arguments)))
            item = target.load_cancel_plan(arguments["operation_id"])
            assert item is not None
            if operation == "direct.cancel":
                return {
                    "status": "OK",
                    "cancel_queue_state": "QUEUED",
                    "record": record(item).to_mapping(),
                }
            return {"status": "OK", "record": record(item, "DISPATCHING").to_mapping()}

        def close(self):
            self.healthy = False

    runtime = ThreadedServiceClientRuntime(SyntheticRuntime)
    runtime.start(timeout_seconds=5)
    try:
        client = GatewayDirectClient(
            runtime, binding=binding, route=route, host=target, cancel_host=target
        )
        result = client.cancel("key-a", operation_id="op-sdk")
        assert result.outcome == "QUEUED"
        assert target.load_cancel_record("op-sdk").state == "REQUESTED"
        status = client.cancel_status("op-sdk")
        assert status.outcome == "OBSERVED" and status.record.state == "DISPATCHING"
        reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
        assert reopened.load_cancel_plan("op-sdk").request_key == "key-a"
        assert reopened.load_cancel_record("op-sdk").state == "DISPATCHING"
        assert [item[0] for item in called] == ["direct.cancel", "direct.cancel_status"]
    finally:
        runtime.close(timeout_seconds=5)
