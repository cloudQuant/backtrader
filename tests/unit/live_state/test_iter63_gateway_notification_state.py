"""R27 notification checkpoint behavior using a real R24 pending host."""

import copy
import json

import pytest
from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionStreamProgress

from backtrader.live_state import LiveStateCorrupt, LiveStateError
from backtrader.live_state import pending as pending_module
from backtrader.live_state.gateway_execution_state import has_unresolved_gateway_execution
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event, page, ready
from tests.unit.live_state.test_gateway_pending import inputs

SNAP = {"schema_version": 1, "state": {"orders": [{"value": 2.5}], "fees": [1, None]}}
NOTICE = [
    {"notification_id": "a" * 64, "kind": "trade", "object_key": "order/α", "payload": {"size": 1}}
]


def ingest(current, binding, consumer):
    return current.ingest_execution_page(
        page(
            binding,
            consumer,
            [make_event(current, 3), make_event(current, 8, fact="f" * 64, trade="c" * 64)],
        ),
        expected_revision=0,
        after_sequence=0,
    )


def commit(current, checkpoint, projection=SNAP, notifications=NOTICE, through=3):
    return current.commit_execution_notification_batch(
        through,
        projection,
        notifications,
        expected_revision=checkpoint.revision,
        expected_applied_sequence=checkpoint.applied_sequence,
    )


def confirm(current, checkpoint, **kwargs):
    batch = current.load_execution_notification_batch()
    args = dict(
        expected_revision=checkpoint.revision,
        expected_applied_sequence=checkpoint.applied_sequence,
        expected_projection_digest=checkpoint.projection_digest,
    )
    args.update(kwargs)
    return current.confirm_execution_notification_batch(batch["batch_id"], **args)


def test_atomic_batch_confirmation_and_ack(state, ready):
    current, binding, consumer = ready
    initial = ingest(current, binding, consumer)
    pending = commit(current, initial)
    batch = current.load_execution_notification_batch()
    assert batch["status"] == "pending" and batch["through_sequence"] == 3
    assert (
        len(batch["batch_id"]) == 64
        and pending.projection["state"]["orders"] == SNAP["state"]["orders"]
    )
    batch["notifications"][0]["payload"]["size"] = 50
    assert current.load_execution_notification_batch()["notifications"] == NOTICE
    assert has_unresolved_gateway_execution(
        json.loads(open(state.pending.path, encoding="utf-8").read())
    )
    for projection in (SNAP, pending.projection):
        with pytest.raises(ValueError, match="NOTIFICATION"):
            current.commit_execution_projection(
                8, projection, expected_revision=pending.revision, expected_applied_sequence=3
            )
    progress = GatewayExecutionStreamProgress(binding, consumer, "e" * 64, 8, 3)
    with pytest.raises(ValueError, match="NOTIFICATION_PENDING"):
        current.record_execution_ack(progress)
    assert (
        current.record_execution_ack(
            GatewayExecutionStreamProgress(binding, consumer, "e" * 64, 8, 0)
        )
        == pending
    )
    before = copy.deepcopy(pending.projection)
    done = confirm(current, pending)
    assert (
        done.applied_sequence == pending.applied_sequence and done.revision == pending.revision + 1
    )
    before["state"]["_gateway_notifications"]["status"] = "confirmed"
    assert json.dumps(done.projection, sort_keys=True) == json.dumps(before, sort_keys=True)
    assert confirm(current, pending) == done
    assert confirm(current, done) == done
    acknowledged = current.record_execution_ack(progress)
    assert acknowledged.acknowledged_sequence == 3
    second = commit(current, acknowledged, through=8)
    assert second.projection["state"]["_gateway_notifications"]["batch_id"] != batch["batch_id"]


def test_failures_before_and_after_replace_reopen(state, ready, monkeypatch):
    current, binding, consumer = ready
    initial = ingest(current, binding, consumer)
    original = pending_module.atomic_write_json
    before = open(state.pending.path, "rb").read()

    def fail_before(*args):
        raise OSError("before replace")

    def fail_after(*args):
        original(*args)
        raise OSError("after replace")

    monkeypatch.setattr(pending_module, "atomic_write_json", fail_before)
    with pytest.raises(OSError):
        commit(current, initial)
    assert open(state.pending.path, "rb").read() == before
    monkeypatch.setattr(pending_module, "atomic_write_json", fail_after)
    with pytest.raises(OSError):
        commit(current, initial)
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    pending = commit(reopened, initial)
    assert (
        pending.applied_sequence == 3
        and reopened.load_execution_notification_batch()["status"] == "pending"
    )
    monkeypatch.setattr(pending_module, "atomic_write_json", fail_after)
    with pytest.raises(OSError):
        confirm(reopened, pending)
    monkeypatch.setattr(pending_module, "atomic_write_json", original)
    assert (
        confirm(reopened, pending).projection["state"]["_gateway_notifications"]["status"]
        == "confirmed"
    )


def test_confirmation_cas_and_digest_conflicts(state, ready):
    current, binding, consumer = ready
    pending = commit(current, ingest(current, binding, consumer))
    other = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    batch = current.load_execution_notification_batch()
    with pytest.raises(ValueError, match="REVISION"):
        confirm(other, pending, expected_revision=pending.revision - 1)
    with pytest.raises(ValueError, match="DIGEST"):
        confirm(other, pending, expected_projection_digest="0" * 64)
    with pytest.raises(ValueError, match="CONFLICT"):
        confirm(other, pending, expected_applied_sequence=0)
    with pytest.raises(ValueError):
        other.confirm_execution_notification_batch(
            "f" * 64,
            expected_revision=pending.revision,
            expected_applied_sequence=3,
            expected_projection_digest=pending.projection_digest,
        )
    # Ingesting a future event changes the revision while leaving the projection untouched.
    current.ingest_execution_page(
        page(binding, consumer, [make_event(current, 10, fact="d" * 64, trade="e" * 64)]),
        expected_revision=pending.revision,
        after_sequence=8,
    )
    with pytest.raises(ValueError, match="REVISION"):
        confirm(other, pending)
    fresh = current.load_execution_checkpoint()
    done = confirm(other, fresh)
    assert confirm(current, pending) == done
    with pytest.raises(ValueError, match="REVISION"):
        confirm(current, done, expected_revision=done.revision + 1)
    with pytest.raises(ValueError, match="DIGEST"):
        confirm(current, done, expected_projection_digest="0" * 64)
    with pytest.raises(ValueError):
        commit(current, done, through=3)


@pytest.mark.parametrize(
    "notices",
    [
        [],
        [{}],
        [
            {
                "notification_id": "a" * 64,
                "kind": "trade",
                "object_key": "x",
                "payload": {"api_key": "secret"},
            }
        ],
        [{"notification_id": "a" * 64, "kind": "trade", "object_key": "x\n", "payload": {}}],
        [{"notification_id": "a" * 64, "kind": "trade", "object_key": "α" * 513, "payload": {}}],
        [{"notification_id": "a" * 64, "kind": "trade", "object_key": "\ud800", "payload": {}}],
        [
            {
                "notification_id": "a" * 64,
                "kind": "trade",
                "object_key": "x",
                "payload": {"n": float("nan")},
            }
        ],
        NOTICE * 2,
        NOTICE * 4097,
    ],
)
def test_invalid_notification_inputs_are_atomic(state, ready, notices):
    current, binding, consumer = ready
    initial = ingest(current, binding, consumer)
    before = open(state.pending.path, "rb").read()
    with pytest.raises((ValueError, LiveStateError, UnicodeError)):
        commit(current, initial, notifications=notices)
    assert open(state.pending.path, "rb").read() == before


@pytest.mark.parametrize(
    "change",
    ["id", "through", "status", "version", "payload", "consumer", "epoch", "binding", "ack"],
)
def test_tampered_batch_rejected_at_load(state, ready, change):
    current, binding, consumer = ready
    commit(current, ingest(current, binding, consumer))
    with open(state.pending.path, encoding="utf-8") as source:
        raw = json.load(source)
    execution = raw["gateway"]["execution"]
    batch = execution["projection"]["state"]["_gateway_notifications"]
    if change == "id":
        batch["batch_id"] = "1" * 64
    elif change == "through":
        batch["through_sequence"] = 8
    elif change == "status":
        batch["status"] = "unknown"
    elif change == "version":
        batch["version"] = True
    elif change == "payload":
        batch["notifications"][0]["payload"]["size"] = 9
    elif change == "consumer":
        execution["consumer_ref"] = "gexec:" + "1" * 64
    elif change == "epoch":
        execution["epoch"] = "1" * 64
    elif change == "binding":
        raw["gateway"]["binding"]["strategy_scope"] = "different"
    else:
        execution["acknowledged_sequence"] = 3
    with open(state.pending.path, "w", encoding="utf-8") as target:
        json.dump(raw, target)
    with pytest.raises((ValueError, LiveStateCorrupt)):
        current.load_execution_notification_batch()


def test_legacy_projection_and_reserved_key(ready):
    current, binding, consumer = ready
    initial = ingest(current, binding, consumer)
    assert current.load_execution_notification_batch() is None
    fake = {"schema_version": 1, "state": {"_gateway_notifications": {}}}
    with pytest.raises(ValueError, match="RESERVED"):
        current.commit_execution_projection(
            3, fake, expected_revision=initial.revision, expected_applied_sequence=0
        )
    with pytest.raises(ValueError, match="RESERVED"):
        commit(current, initial, projection=fake)
    checkpoint = current.commit_execution_projection(
        3, SNAP, expected_revision=initial.revision, expected_applied_sequence=0
    )
    assert current.load_execution_notification_batch() is None and checkpoint.projection == SNAP


def test_legacy_v4_reserved_key_conflict_is_rejected_without_migration(state, ready):
    current, binding, consumer = ready
    initial = ingest(current, binding, consumer)
    current.commit_execution_projection(
        3, SNAP, expected_revision=initial.revision, expected_applied_sequence=0
    )
    # This was an opaque, valid v4 state before the name became reserved.
    with open(state.pending.path, encoding="utf-8") as source:
        old_v4 = json.load(source)
    old_v4["gateway"]["execution"]["projection"]["state"]["_gateway_notifications"] = {
        "legacy_application_data": ["keep", 1]
    }
    with open(state.pending.path, "w", encoding="utf-8") as target:
        json.dump(old_v4, target, ensure_ascii=False)
    with open(state.pending.path, "rb") as source:
        before = source.read()
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    for load in (reopened.load_execution_checkpoint, reopened.load_execution_notification_batch):
        with pytest.raises((LiveStateCorrupt, ValueError)):
            load()
        with open(state.pending.path, "rb") as source:
            assert source.read() == before


def test_batch_capacity_and_strict_types(state, ready):
    current, binding, consumer = ready
    initial = ingest(current, binding, consumer)
    before = open(state.pending.path, "rb").read()
    distinct = [
        {"notification_id": format(i, "064x"), "kind": "order", "object_key": "x", "payload": {}}
        for i in range(4097)
    ]
    invalid = [
        tuple(NOTICE),
        distinct,
        [{**NOTICE[0], "kind": 1}],
        [{**NOTICE[0], "payload": []}],
        [{**NOTICE[0], "notification_id": "A" * 64}],
        [{**NOTICE[0], "notification_id": "a" * 64 + "\n"}],
    ]
    for notices in invalid:
        with pytest.raises(ValueError):
            commit(current, initial, notifications=notices)
        assert open(state.pending.path, "rb").read() == before
    with current._store._lock():
        raw = current._store._load()
        raw["gateway"]["execution"]["max_projection_bytes"] = 1024
        current._store._store(raw, trim_history=False)
    before = open(state.pending.path, "rb").read()
    with pytest.raises(ValueError, match="CAPACITY"):
        commit(current, initial, notifications=[{**NOTICE[0], "payload": {"data": "x" * 1024}}])
    assert open(state.pending.path, "rb").read() == before


@pytest.mark.parametrize("extra", [0, 1, 2])
def test_confirmation_capacity_is_reserved_before_commit(state, ready, extra):
    current, binding, consumer = ready
    initial = ingest(current, binding, consumer)
    candidate = copy.deepcopy(SNAP)
    candidate["state"]["_gateway_notifications"] = {
        "version": 1,
        "batch_id": "0" * 64,
        "through_sequence": 3,
        "notifications": NOTICE,
        "status": "pending",
    }
    pending_bytes = len(
        json.dumps(
            candidate, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    )
    with current._store._lock():
        raw = current._store._load()
        raw["gateway"]["execution"]["max_projection_bytes"] = pending_bytes + extra
        current._store._store(raw, trim_history=False)
    with open(state.pending.path, "rb") as source:
        before = source.read()
    if extra < 2:
        with pytest.raises((ValueError, LiveStateCorrupt), match="CAPACITY"):
            commit(current, initial)
        with open(state.pending.path, "rb") as source:
            assert source.read() == before
    else:
        pending = commit(current, initial)
        confirmed = confirm(current, pending)
        encoded = json.dumps(
            confirmed.projection,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        assert len(encoded) == pending_bytes + extra


def test_existing_unconfirmable_pending_is_rejected_without_rewrite(state, ready):
    current, binding, consumer = ready
    pending = commit(current, ingest(current, binding, consumer))
    encoded = json.dumps(
        pending.projection,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    with open(state.pending.path, encoding="utf-8") as source:
        old = json.load(source)
    old["gateway"]["execution"]["max_projection_bytes"] = len(encoded) + 1
    with open(state.pending.path, "w", encoding="utf-8") as target:
        json.dump(old, target, ensure_ascii=False)
    with open(state.pending.path, "rb") as source:
        before = source.read()
    with pytest.raises((ValueError, LiveStateCorrupt)):
        current.load_execution_checkpoint()
    with open(state.pending.path, "rb") as source:
        assert source.read() == before


def test_unresolved_guard_includes_pending_status(state, ready):
    current, binding, consumer = ready
    pending = commit(current, ingest(current, binding, consumer))
    with open(state.pending.path, encoding="utf-8") as source:
        raw = json.load(source)
    # Exercise this predicate independently of the watermark-gap checks.
    raw["gateway"]["execution"]["stored_sequence"] = 3
    raw["gateway"]["execution"]["acknowledged_sequence"] = 3
    assert has_unresolved_gateway_execution(raw)
    raw["gateway"]["execution"]["projection"]["state"]["_gateway_notifications"][
        "status"
    ] = "confirmed"
    assert not has_unresolved_gateway_execution(raw)
    assert pending.projection_digest is not None
