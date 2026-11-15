"""D67-17: verifiable backup, migration, recovery and rollback of waiting orders.

The version-1 fixture in ``fixtures/waiting_orders_v1.json`` is a frozen
version-1 file (no ``calendar_ref``).  ``_legacy_reader`` is a *simulation* of
the version-1 reader contract (strict schema, ``version == 1``, no calendar
reference); it is evidence about the on-disk format, not the old code itself.
"""

import hashlib
import json
import os

import pytest

from backtrader.live_state import (
    LiveStateCorrupt,
    LiveStateError,
    WaitingOrderStore,
    read_audit,
)
from backtrader.live_state import waiting as waiting_module

from ._helpers import waiting_order

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "waiting_orders_v1.json")
PLACEHOLDER_UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
WAITING_ID = "0b7f3c1e-2d4a-4f6b-8c1d-9e2f3a4b5c6d"
CANCELLED_ID = "1c8e4d2f-3a5b-4c7d-9e1f-0a2b3c4d5e6f"
LEGACY_STORED = frozenset(
    {
        "waiting_id",
        "local_seq",
        "bt_ref",
        "symbol",
        "exchange_name",
        "side",
        "size",
        "exectype",
        "price",
        "pricelimit",
        "offset",
        "position_side",
        "valid_intent",
        "target_session",
        "created_at_utc",
        "updated_at_utc",
        "status",
        "extra",
        "facts",
        "transitions",
    }
)
LEGACY_TARGET_KEYS = frozenset({"trading_day", "continuous_start_utc", "session_end_utc"})
LEGACY_TERMINAL = frozenset({"DISPATCHED", "CANCELLED", "EXPIRED", "REJECTED"})


class LegacyReaderRefusal(ValueError):
    """Finite reasons the simulated version-1 reader refuses a file."""


def legacy_reader(raw_bytes, strategy_uuid):
    """A strict version-1 reader: what the old program can safely read."""
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise LegacyReaderRefusal("parse") from None
    if not isinstance(raw, dict) or set(raw) != {"version", "strategy_uuid", "orders", "history"}:
        raise LegacyReaderRefusal("unexpected_keys")
    if type(raw["version"]) is not int or raw["version"] != 1:
        raise LegacyReaderRefusal("version_unsupported")
    if raw["strategy_uuid"] != strategy_uuid:
        raise LegacyReaderRefusal("strategy_uuid_mismatch")
    if not isinstance(raw["orders"], dict) or not isinstance(raw["history"], list):
        raise LegacyReaderRefusal("invalid_structure")
    for key, order in raw["orders"].items():
        if set(order) != LEGACY_STORED or order["waiting_id"] != key:
            raise LegacyReaderRefusal("invalid_waiting_order")
        if set(order["target_session"]) != LEGACY_TARGET_KEYS:
            raise LegacyReaderRefusal("unexpected_target_session")
        if order["status"] in LEGACY_TERMINAL:
            raise LegacyReaderRefusal("invalid_waiting_status")
    for order in raw["history"]:
        if set(order) != LEGACY_STORED or set(order["target_session"]) != LEGACY_TARGET_KEYS:
            raise LegacyReaderRefusal("invalid_waiting_order")
        if order["status"] not in LEGACY_TERMINAL:
            raise LegacyReaderRefusal("invalid_waiting_status")
    return raw


def install_fixture(state):
    """Copy the frozen version-1 file into the state dir; return its bytes."""
    with open(FIXTURE, "rb") as handle:
        raw = handle.read()
    bound = raw.replace(PLACEHOLDER_UUID.encode("ascii"), state.strategy_uuid.encode("ascii"))
    with open(state.waiting.path, "wb") as handle:
        handle.write(bound)
    return bound


def read_bytes(path):
    with open(path, "rb") as handle:
        return handle.read()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def marker(state):
    raw = state.waiting.migration_status()
    assert raw is not None
    return raw


def audit_events(state):
    return [record["event"] for record in read_audit(state.strategy_dir)]


def fail_on_write(monkeypatch, *, attempt, after=False):
    """Make the N-th direct atomic write in ``waiting`` fail (or fail after)."""
    original = waiting_module.atomic_write_bytes
    calls = {"count": 0}

    def wrapper(path, data):
        calls["count"] += 1
        if calls["count"] == attempt:
            if after:
                original(path, data)
            raise OSError("simulated crash during migration")
        return original(path, data)

    monkeypatch.setattr(waiting_module, "atomic_write_bytes", wrapper)
    return calls


def test_fixture_is_a_readable_version_one_file(state):
    original = install_fixture(state)
    legacy_reader(original, state.strategy_uuid)
    store = state.waiting
    (active,) = store.active()
    assert active["waiting_id"] == WAITING_ID
    assert active["status"] == "WAITING"
    assert active["local_seq"] == 7
    assert "calendar_ref" not in active["target_session"]
    (history,) = store.history()
    assert history["waiting_id"] == CANCELLED_ID


def test_explicit_migration_backs_up_and_preserves_every_record(state):
    original = install_fixture(state)
    result = state.waiting.migrate(operator="op-67", reason="issue 67.07 migration")
    assert result["status"] == "complete" and result["changed"] is True
    record = result["migration"]
    assert record["source_version"] == 1 and record["target_version"] == 2
    assert record["orders_count"] == 1 and record["history_count"] == 1

    backup = read_bytes(os.path.join(state.waiting.backups_dir, record["backup_file"]))
    assert backup == original
    assert sha256(backup) == record["backup_sha256"]
    migrated_bytes = read_bytes(state.waiting.path)
    assert sha256(migrated_bytes) == record["migrated_sha256"]

    source = json.loads(original)
    migrated = json.loads(migrated_bytes)
    assert migrated["version"] == 2
    assert migrated["strategy_uuid"] == source["strategy_uuid"]
    # Order identity, original target, local sequence, status, timestamps and
    # facts are carried over unchanged; no calendar reference is invented.
    assert migrated["orders"] == source["orders"]
    assert migrated["history"] == source["history"]
    assert all("calendar_ref" not in o["target_session"] for o in migrated["orders"].values())
    # Nothing is re-sent or advanced by a migration.
    (active,) = state.waiting.active()
    assert active["status"] == "WAITING" and active["transitions"] == []
    assert state.pending.active() == []

    assert marker(state)["status"] == "complete"
    backup_record = next(
        item
        for item in read_audit(state.strategy_dir)
        if item["event"] == "waiting_migration_backup"
    )
    assert backup_record["backup_file"] == record["backup_file"]
    assert backup_record["backup_sha256"] == record["backup_sha256"]
    assert backup_record["source_version"] == 1
    assert backup_record["target_version"] == 2
    assert "waiting_migration_complete" in audit_events(state)


def test_migrate_is_idempotent_and_never_rewrites_a_current_file(state):
    install_fixture(state)
    first = state.waiting.migrate(operator="op", reason="first")
    before = read_bytes(state.waiting.path)
    second = state.waiting.migrate(operator="op", reason="again")
    assert first["changed"] is True
    assert second["status"] == "already_current" and second["changed"] is False
    assert read_bytes(state.waiting.path) == before


def test_ordinary_write_upgrades_a_legacy_file_only_after_a_backup(state):
    original = install_fixture(state)
    waiting_id = state.waiting.add(waiting_order(local_seq=8))
    record = marker(state)
    assert record["source_version"] == 1 and record["status"] == "complete"
    assert read_bytes(os.path.join(state.waiting.backups_dir, record["backup_file"])) == original
    raw = json.loads(read_bytes(state.waiting.path))
    assert raw["version"] == 2
    assert raw["orders"][WAITING_ID] == json.loads(original)["orders"][WAITING_ID]
    assert raw["orders"][waiting_id]["target_session"]["calendar_ref"]
    assert "waiting_migration_backup" in audit_events(state)


@pytest.mark.parametrize("version", [0, 3, True, "2", None])
def test_unknown_or_newer_versions_are_refused_and_left_untouched(state, version):
    install_fixture(state)
    raw = json.loads(read_bytes(state.waiting.path))
    raw["version"] = version
    with open(state.waiting.path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    before = read_bytes(state.waiting.path)
    for action in (
        lambda: state.waiting.active(),
        lambda: state.waiting.add(waiting_order(local_seq=9)),
        lambda: state.waiting.migrate(operator="op", reason="try"),
    ):
        with pytest.raises(LiveStateCorrupt) as info:
            action()
        assert info.value.code == "state_corrupt"
        assert info.value.reason == "version_unsupported"
        assert read_bytes(state.waiting.path) == before
    assert state.waiting.migration_status() is None


def test_corrupt_backup_is_refused_by_rollback_and_recovery(state):
    install_fixture(state)
    state.waiting.migrate(operator="op", reason="migrate")
    record = marker(state)
    backup_path = os.path.join(state.waiting.backups_dir, record["backup_file"])
    with open(backup_path, "ab") as handle:
        handle.write(b"tampered")
    migrated_bytes = read_bytes(state.waiting.path)
    with pytest.raises(LiveStateCorrupt) as info:
        state.waiting.rollback_migration(operator="op", reason="rollback")
    assert info.value.code == "state_corrupt"
    assert info.value.reason == "migration_backup_digest_mismatch"
    assert read_bytes(state.waiting.path) == migrated_bytes

    raw = json.loads(read_bytes(state.waiting.migration_marker_path))
    raw["status"] = "in_progress"
    with open(state.waiting.migration_marker_path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    with pytest.raises(LiveStateCorrupt) as info:
        state.waiting.recover_migration(operator="op", reason="recover")
    assert info.value.reason == "migration_backup_digest_mismatch"
    assert read_bytes(state.waiting.path) == migrated_bytes


def test_interrupted_before_replace_is_replayed_from_the_verified_backup(state, monkeypatch):
    original = install_fixture(state)
    fail_on_write(monkeypatch, attempt=2)
    with pytest.raises(OSError):
        state.waiting.add(waiting_order(local_seq=8))
    monkeypatch.undo()

    record = marker(state)
    assert record["status"] == "in_progress"
    assert read_bytes(state.waiting.path) == original
    assert (
        sha256(read_bytes(os.path.join(state.waiting.backups_dir, record["backup_file"])))
        == record["backup_sha256"]
    )
    assert "waiting_migration_failed" in audit_events(state)

    recovered = state.waiting.recover_migration(operator="op", reason="resume")
    assert recovered["status"] == "complete" and recovered["recovery"] == "replayed"
    raw = json.loads(read_bytes(state.waiting.path))
    assert raw["version"] == 2
    source = json.loads(original)
    assert raw["orders"] == source["orders"]
    assert raw["history"] == source["history"]
    # The write that crashed was never durable: nothing is fabricated.
    assert list(raw["orders"]) == [WAITING_ID]
    assert state.pending.active() == []
    assert "waiting_migration_recovered" in audit_events(state)


def test_interrupted_after_replace_is_finalized_without_rewriting(state, monkeypatch):
    install_fixture(state)
    fail_on_write(monkeypatch, attempt=2, after=True)
    with pytest.raises(OSError):
        state.waiting.add(waiting_order(local_seq=8))
    monkeypatch.undo()

    record = marker(state)
    assert record["status"] == "in_progress"
    before = read_bytes(state.waiting.path)
    assert json.loads(before)["version"] == 2

    recovered = state.waiting.recover_migration(operator="op", reason="resume")
    assert recovered["status"] == "complete" and recovered["recovery"] == "completed"
    assert read_bytes(state.waiting.path) == before  # only the marker changed
    assert marker(state)["migrated_sha256"] == sha256(before)


def test_missing_state_file_is_restored_from_the_verified_backup(state, monkeypatch):
    original = install_fixture(state)
    fail_on_write(monkeypatch, attempt=2)
    with pytest.raises(OSError):
        state.waiting.add(waiting_order(local_seq=8))
    monkeypatch.undo()
    os.unlink(state.waiting.path)

    recovered = state.waiting.recover_migration(operator="op", reason="restore")
    assert recovered["status"] == "rolled_back" and recovered["recovery"] == "restored"
    assert read_bytes(state.waiting.path) == original
    legacy_reader(read_bytes(state.waiting.path), state.strategy_uuid)


def test_migration_conflict_refuses_and_keeps_the_changed_file(state, monkeypatch):
    install_fixture(state)
    fail_on_write(monkeypatch, attempt=2)
    with pytest.raises(OSError):
        state.waiting.add(waiting_order(local_seq=8))
    monkeypatch.undo()
    # Someone appended a version-1 record after the interruption: the backup no
    # longer describes the file, so recovery must not guess.
    raw = json.loads(read_bytes(state.waiting.path))
    extra = dict(raw["orders"][WAITING_ID])
    extra["waiting_id"] = CANCELLED_ID
    extra["local_seq"] = 12
    raw["orders"][CANCELLED_ID] = extra
    with open(state.waiting.path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    before = read_bytes(state.waiting.path)
    with pytest.raises(LiveStateCorrupt) as info:
        state.waiting.recover_migration(operator="op", reason="recover")
    assert info.value.reason == "migration_conflict"
    assert read_bytes(state.waiting.path) == before


def test_rollback_round_trip_restores_an_old_reader_compatible_file(state):
    original = install_fixture(state)
    state.waiting.migrate(operator="op", reason="migrate")
    with pytest.raises(LegacyReaderRefusal):
        legacy_reader(read_bytes(state.waiting.path), state.strategy_uuid)

    result = state.waiting.rollback_migration(operator="op", reason="old program")
    assert result["status"] == "rolled_back" and result["changed"] is True
    restored = read_bytes(state.waiting.path)
    assert restored == original
    legacy_reader(restored, state.strategy_uuid)
    (active,) = state.waiting.active()
    assert active["status"] == "WAITING"

    again = state.waiting.rollback_migration(operator="op", reason="again")
    assert again["status"] == "rolled_back" and again["changed"] is False
    assert "waiting_migration_rollback" in audit_events(state)


def test_rollback_is_refused_after_post_migration_facts(state):
    install_fixture(state)
    state.waiting.migrate(operator="op", reason="migrate")
    new_id = state.waiting.add(waiting_order(local_seq=20))
    current = read_bytes(state.waiting.path)
    with pytest.raises(LiveStateCorrupt) as info:
        state.waiting.rollback_migration(operator="op", reason="too late")
    assert info.value.code == "state_corrupt"
    assert info.value.reason == "rollback_unsafe"
    # The post-upgrade order is preserved; nothing was overwritten.
    assert read_bytes(state.waiting.path) == current
    assert state.waiting.get(new_id) is not None


def test_rollback_requires_a_completed_migration(state, monkeypatch):
    install_fixture(state)
    fail_on_write(monkeypatch, attempt=2)
    with pytest.raises(OSError):
        state.waiting.add(waiting_order(local_seq=8))
    monkeypatch.undo()
    with pytest.raises(LiveStateCorrupt) as info:
        state.waiting.rollback_migration(operator="op", reason="early")
    assert info.value.reason == "migration_not_complete"


def test_migration_operator_and_reason_are_required(state):
    install_fixture(state)
    for kwargs in ({"operator": "", "reason": "x"}, {"operator": "op", "reason": "  "}):
        with pytest.raises(LiveStateError) as info:
            state.waiting.migrate(**kwargs)
        assert info.value.code in ("operator_required", "reason_required")
    assert state.waiting.migration_status() is None
    with pytest.raises(LiveStateError) as info:
        WaitingOrderStore(state.strategy_dir, state.strategy_uuid).recover_migration(
            operator="op", reason="nothing"
        )
    assert info.value.code == "marker_not_found"


def test_migration_does_not_apply_the_history_bound(state):
    install_fixture(state)
    raw = json.loads(read_bytes(state.waiting.path))
    template = raw["history"][0]
    raw["history"] = []
    for index in range(6):
        item = dict(template)
        item["local_seq"] = 100 + index
        raw["history"].append(item)
    with open(state.waiting.path, "w", encoding="utf-8") as handle:
        json.dump(raw, handle)
    store = WaitingOrderStore(state.strategy_dir, state.strategy_uuid, history_limit=2)
    store.migrate(operator="op", reason="no silent loss")
    assert len(json.loads(read_bytes(state.waiting.path))["history"]) == 6
    # Ordinary writes after the migration still bound the history.
    waiting_id = store.add(waiting_order(local_seq=9))
    assert store.transition(waiting_id, "WAITING", "CANCELLED")
    assert len(json.loads(read_bytes(state.waiting.path))["history"]) == 2


def test_recovery_refuses_to_launder_a_post_crash_write_over_the_migrated_file(
    state, monkeypatch
):
    """A write after the v2 replace must not be adopted as the migrated bytes."""
    install_fixture(state)
    fail_on_write(monkeypatch, attempt=2, after=True)
    with pytest.raises(OSError):
        state.waiting.add(waiting_order(local_seq=8))
    monkeypatch.undo()
    assert marker(state)["status"] == "in_progress"

    # An ordinary durable write lands on the v2 file before recovery runs.
    state.waiting.add(waiting_order(local_seq=9, bt_ref=12))
    before = read_bytes(state.waiting.path)
    # The failed add's order may already be on disk, plus the post-crash one.
    assert len(json.loads(before)["orders"]) >= 2

    with pytest.raises(LiveStateCorrupt) as info:
        state.waiting.recover_migration(operator="op", reason="recover")
    assert info.value.reason == "migration_conflict"
    assert marker(state)["status"] == "in_progress"
    assert read_bytes(state.waiting.path) == before

    # Rollback stays unavailable while the marker is in progress.
    with pytest.raises(LiveStateCorrupt) as info:
        state.waiting.rollback_migration(operator="op", reason="rollback")
    assert info.value.reason == "migration_not_complete"
    assert read_bytes(state.waiting.path) == before
