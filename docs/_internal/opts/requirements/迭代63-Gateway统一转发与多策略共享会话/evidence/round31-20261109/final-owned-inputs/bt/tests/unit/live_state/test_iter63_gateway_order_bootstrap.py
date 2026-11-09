"""Synthetic pre-event BT snapshots; no provider, account, or network access."""
import copy
import json
import subprocess
import sys

import pytest

import backtrader as bt
from backtrader.brokers._btapi_gateway_projection import capture_framework_state
from backtrader.live_state import LiveStateCorrupt, LiveStateError, rebind_identity
from backtrader.live_state import pending as pending_module
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.test_gateway_framework_checkpoint import _framework
from tests.unit.live_state.test_gateway_pending import data, host, inputs as inputs, observe
from tests.unit.live_state.test_gateway_pending_cancel import plan, record, upgrade
from tests.unit.live_state.test_gateway_execution_checkpoint import ready as ready
from tests.unit.live_state.test_iter63_gateway_notification_state import ingest, commit


def _v4(state, binding):
    host(state, binding)
    upgrade(state, binding)
    return GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref="gexec:" + "a" * 64
    )


def _snapshot(key="key-a"):
    data_feed, owner, broker = _framework()
    order = bt.BuyOrder(owner=owner, data=data_feed, size=1, price=10.0,
                        exectype=bt.Order.Limit, simulated=False)
    order.addcomminfo(broker.getcommissioninfo(data_feed))
    snapshot = capture_framework_state(orders={key: order}, positions={}, trades={},
        data_by_ref={"rb": data_feed}, owner=owner, broker=broker)
    return order.ref, snapshot


def _upgrade(state, binding, **kwargs):
    return GatewayPendingHost.upgrade_for_order_state(
        state.strategy_dir, state.strategy_uuid, binding, **kwargs)


def test_upgrade_atomic_snapshot_idempotency_conflicts_and_reopen(state, inputs):
    binding, _, make = inputs
    old = _v4(state, binding)
    old.save_intent(make("legacy"), local_seq=99, bt_ref=99)
    before = json.loads(data(state))
    ref, snapshot = _snapshot()
    with pytest.raises(ValueError, match="UPGRADE_REQUIRED"):
        old.save_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    current = _upgrade(state, binding)
    after = json.loads(data(state))
    assert after["version"] == 5
    assert {k: v for k, v in after["gateway"].items()
            if k not in {"order_snapshots", "max_order_snapshot_bytes"}} == before["gateway"]
    assert after["active"] == before["active"] and after["history"] == before["history"]
    assert current.load_order_snapshot("legacy") is None
    current.save_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    saved = data(state)
    current.save_order_intent(make(ttl=30), local_seq=1, bt_ref=ref, snapshot=copy.deepcopy(snapshot))
    current.save_intent(make())
    assert data(state) == saved
    changed = copy.deepcopy(snapshot)
    changed["state"]["orders"]["key-a"]["plen"] = 1
    for seq, order_ref, snap in ((1, ref, changed), (2, ref, snapshot), (1, ref + 1, snapshot)):
        with pytest.raises(ValueError):
            current.save_order_intent(make(), local_seq=seq, bt_ref=order_ref, snapshot=snap)
        assert data(state) == saved
    with pytest.raises(ValueError):
        current.save_order_intent(make("different"), local_seq=2, bt_ref=ref, snapshot=snapshot)
    local = current.load_order_snapshot("key-a")
    local["snapshot"]["state"]["orders"].clear()
    current.iter_order_snapshots()["key-a"]["snapshot"]["state"].clear()
    assert current.load_order_snapshot("key-a")["snapshot"] == snapshot
    script = '''import json, sys
from backtrader.live_state.gateway_pending import GatewayPendingHost
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
h = GatewayPendingHost(sys.argv[1], sys.argv[2], GatewayCommandBinding("journal-a", "account-a", "strategy-a", "principal-a"))
print(json.dumps(h.iter_order_snapshots(), sort_keys=True))
'''
    output = subprocess.check_output([sys.executable, "-c", script, str(state.strategy_dir),
                                      state.strategy_uuid], text=True)
    assert json.loads(output) == current.iter_order_snapshots()
    _upgrade(state, binding)
    assert data(state) == saved
    with pytest.raises(ValueError, match="CAPACITY_MISMATCH"):
        _upgrade(state, binding, max_order_snapshot_bytes=1)
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(state.strategy_dir, mode="new_instance", operator="test", reason="test")


@pytest.mark.parametrize("window", ["before", "after"])
def test_atomic_write_failure_and_retry(state, inputs, monkeypatch, window):
    binding, _, make = inputs
    _v4(state, binding)
    current = _upgrade(state, binding)
    ref, snapshot = _snapshot()
    before = data(state)
    original = pending_module.atomic_write_json
    def fail(path, value):
        if window == "after":
            original(path, value)
        raise OSError("synthetic failure")
    monkeypatch.setattr(pending_module, "atomic_write_json", fail)
    with pytest.raises(OSError):
        current.save_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    if window == "before":
        assert data(state) == before
        assert current.load_intent("key-a") is None
    else:
        assert current.load_intent("key-a") is not None
        assert current.load_order_snapshot("key-a")["snapshot"] == snapshot
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    current.save_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snapshot)
    assert current.load_order_snapshot("key-a")["snapshot"] == snapshot


def test_capacity_corruption_and_strict_inputs(state, inputs):
    binding, _, make = inputs
    _v4(state, binding)
    ref, snap = _snapshot()
    current = _upgrade(state, binding, max_order_snapshot_bytes=1)
    before = data(state)
    with pytest.raises(ValueError):
        current.save_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snap)
    assert data(state) == before
    for value in (True, 0, -1):
        with pytest.raises(ValueError):
            current.save_order_intent(make(), local_seq=value, bt_ref=ref, snapshot=snap)
    broken = json.loads(before)
    broken["gateway"]["order_snapshots"]["orphan"] = {
        "schema_version": 1, "local_seq": 1, "bt_ref": ref, "snapshot": snap}
    with open(state.pending.path, "w", encoding="utf-8") as file:
        json.dump(broken, file)
    with pytest.raises(LiveStateCorrupt):
        current.iter_order_snapshots()


def test_upgrade_preserves_receipts_notifications_and_marker(state, ready, inputs):
    old, binding, consumer = ready
    _, route, _ = inputs
    checkpoint = commit(old, ingest(old, binding, consumer))
    old_state = json.loads(data(state))
    assert old_state["active"] and old_state["gateway"]["execution"]["receipts"]
    assert old.load_execution_notification_batch()["status"] == "pending"
    current = _upgrade(state, binding)
    new_state = json.loads(data(state))
    assert new_state["active"] == old_state["active"]
    assert new_state["history"] == old_state["history"]
    assert {k: v for k, v in new_state["gateway"].items()
            if k not in {"order_snapshots", "max_order_snapshot_bytes"}} == old_state["gateway"]
    assert current.load_execution_checkpoint() == checkpoint
    assert current.load_execution_notification_batch() == old.load_execution_notification_batch()
    assert len(current.read_execution_events()) == 1
    cancel = plan(current, route)
    current.save_cancel_plan(cancel)
    current.save_cancel_record(cancel.operation_id, record(cancel))
    assert current.load_cancel_record(cancel.operation_id) == record(cancel)
    with pytest.raises(ValueError, match="NOTIFICATION"):
        current.commit_execution_projection(8, {"schema_version": 1, "state": {}},
            expected_revision=checkpoint.revision, expected_applied_sequence=3)
    marker = current.load_context("key-a").marker_id
    assert state.pending.mark(marker, "TERMINAL")
    with pytest.raises(LiveStateError, match="rebind_blocked_active_state"):
        rebind_identity(state.strategy_dir, mode="new_instance", operator="test", reason="test")


@pytest.mark.parametrize("kind", ["missing_map", "mismatched_seq", "mismatched_ref", "bad_json_graph"])
def test_existing_snapshot_corruption_fails_closed(state, inputs, kind):
    binding, _, make = inputs
    _v4(state, binding)
    current = _upgrade(state, binding)
    ref, snap = _snapshot()
    current.save_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snap)
    broken = json.loads(data(state))
    if kind == "missing_map":
        del broken["gateway"]["order_snapshots"]
    elif kind == "mismatched_seq":
        broken["gateway"]["order_snapshots"]["key-a"]["local_seq"] = 2
    elif kind == "mismatched_ref":
        broken["gateway"]["order_snapshots"]["key-a"]["snapshot"]["state"]["orders"]["key-a"]["ref"] += 1
    else:
        broken["gateway"]["order_snapshots"]["key-a"]["snapshot"]["state"]["positions"] = {"x": {}}
    with open(state.pending.path, "w", encoding="utf-8") as file:
        json.dump(broken, file)
    with pytest.raises(LiveStateCorrupt):
        current.load_order_snapshot("key-a")


def test_aggregate_capacity_and_old_intent_does_not_invent_snapshot(state, inputs):
    binding, _, make = inputs
    _v4(state, binding)
    ref, snap = _snapshot()
    size = len(json.dumps(snap, ensure_ascii=False, sort_keys=True, allow_nan=False,
                          separators=(",", ":")).encode())
    current = _upgrade(state, binding, max_order_snapshot_bytes=size + 1)
    current.save_order_intent(make(), local_seq=1, bt_ref=ref, snapshot=snap)
    ref_b, snap_b = _snapshot("key-b")
    before = data(state)
    with pytest.raises(ValueError):
        current.save_order_intent(make("key-b"), local_seq=2, bt_ref=ref_b, snapshot=snap_b)
    assert data(state) == before and current.load_intent("key-b") is None


def test_existing_observation_cannot_backfill_but_snapshot_retry_survives_observation(state, inputs):
    binding, _, make = inputs
    _v4(state, binding)
    current = _upgrade(state, binding)
    ref_a, snap_a = _snapshot()
    a = make()
    current.save_order_intent(a, local_seq=1, bt_ref=ref_a, snapshot=snap_a)
    current.save_record("key-a", observe(a))
    before = data(state)
    current.save_order_intent(a, local_seq=1, bt_ref=ref_a, snapshot=snap_a)
    assert data(state) == before
    ref_b, snap_b = _snapshot("key-b")
    b = make("key-b")
    current.save_intent(b, local_seq=2, bt_ref=ref_b)
    current.save_record("key-b", observe(b))
    before = data(state)
    with pytest.raises(ValueError, match="TOO_LATE"):
        current.save_order_intent(b, local_seq=2, bt_ref=ref_b, snapshot=snap_b)
    assert data(state) == before and current.load_order_snapshot("key-b") is None


def test_snapshot_ref_collision_is_refused_on_write_and_reopen(state, inputs):
    binding, _, make = inputs
    _v4(state, binding)
    current = _upgrade(state, binding)
    ref_a, snap_a = _snapshot()
    ref_b, snap_b = _snapshot("key-b")
    assert ref_a != ref_b
    current.save_order_intent(make(), local_seq=1, bt_ref=ref_a, snapshot=snap_a)
    before = data(state)
    current.save_order_intent(make(), local_seq=1, bt_ref=ref_a, snapshot=copy.deepcopy(snap_a))
    assert data(state) == before
    duplicate = copy.deepcopy(snap_b)
    duplicate["state"]["orders"]["key-b"]["ref"] = ref_a
    with pytest.raises(ValueError, match="SNAPSHOT_REF_CONFLICT"):
        current.save_order_intent(make("key-b"), local_seq=2, bt_ref=ref_a, snapshot=duplicate)
    assert data(state) == before and current.load_intent("key-b") is None
    current.save_order_intent(make("key-b"), local_seq=2, bt_ref=ref_b, snapshot=snap_b)
    assert len(current.iter_order_snapshots()) == 2
    forged = json.loads(data(state))
    forged["gateway"]["intents"]["key-b"]["bt_ref"] = ref_a
    forged["gateway"]["order_snapshots"]["key-b"]["bt_ref"] = ref_a
    forged["gateway"]["order_snapshots"]["key-b"]["snapshot"]["state"]["orders"]["key-b"]["ref"] = ref_a
    with open(state.pending.path, "w", encoding="utf-8") as file:
        json.dump(forged, file)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    with pytest.raises(LiveStateCorrupt):
        reopened.iter_order_snapshots()
