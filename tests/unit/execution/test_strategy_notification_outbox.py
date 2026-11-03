"""Offline tests for the unconnected BT notification projection outbox."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import backtrader.execution.strategy_notification_outbox as outbox_module
from backtrader.execution.strategy_notification_outbox import (
    NotificationOutboxError,
    NotificationScope,
    NotificationSnapshot,
    ProjectionCheckpoint,
    StrategyNotificationOutbox,
)


SCOPE = NotificationScope("account-a", "route-a", "strategy-a", "run-a", "epoch-a")


def event(event_id="event-1", kind="order", payload=b'{"status":"submitted"}'):
    return NotificationSnapshot(
        event_id,
        kind,
        "feed-a",
        "order-a",
        "trade-a" if kind == "trade" else None,
        "bt-projection",
        1,
        payload,
    )


def commit(store, source_id="source-1", revision=0, checkpoint=b'{"position":"1"}', events=None):
    return store.commit(
        source_id=source_id,
        expected_revision=revision,
        checkpoint=ProjectionCheckpoint("checkpoint", 1, checkpoint),
        notifications=(event(),) if events is None else events,
    )


def test_checkpoint_notifications_and_ack_are_durable_and_idempotent(tmp_path):
    path = tmp_path / "outbox.sqlite"
    first, second = event(), event("event-2", "trade", b'{"size":"1"}')
    store = StrategyNotificationOutbox(path, SCOPE)
    assert commit(store, events=(first, second)).revision == 1
    assert commit(store, events=(first, second)).revision == 1
    with pytest.raises(NotificationOutboxError, match="SOURCE_ID_CONFLICT"):
        commit(store, checkpoint=b'{"position":"2"}', events=(first, second))
    with pytest.raises(NotificationOutboxError, match="ACK_OUT_OF_ORDER"):
        store.acknowledge("event-2")
    assert store.pending() == first
    store.acknowledge("event-1")
    store.acknowledge("event-1")
    store.close()

    reopened = StrategyNotificationOutbox(path, SCOPE)
    assert reopened.checkpoint().checkpoint == ProjectionCheckpoint(
        "checkpoint", 1, b'{"position":"1"}'
    )
    assert reopened.pending() == second
    seen = []
    assert reopened.deliver_next(seen.append)
    assert seen == [second]
    assert reopened.pending() is None
    reopened.close()


def test_duplicate_event_and_revision_conflicts_roll_back_checkpoint_and_rows(tmp_path):
    path = tmp_path / "outbox.sqlite"
    store = StrategyNotificationOutbox(path, SCOPE)
    commit(store)
    with pytest.raises(NotificationOutboxError, match="REVISION_CONFLICT"):
        commit(store, source_id="source-2", revision=0, events=(event("new"),))
    with pytest.raises(NotificationOutboxError, match="EVENT_ID_CONFLICT"):
        commit(store, source_id="source-2", revision=1, events=(event("new"), event()))
    assert store.checkpoint().revision == 1
    assert store.pending() == event()
    store.close()
    reopened = StrategyNotificationOutbox(path, SCOPE)
    assert reopened.checkpoint().revision == 1
    assert commit(reopened, source_id="source-2", revision=1, events=(event("new"),)).revision == 2
    reopened.close()


@pytest.mark.parametrize(
    "field", ["account_ref", "route_ref", "strategy_ref", "run_id", "source_epoch"]
)
def test_existing_database_rejects_other_declared_scope_without_modification(tmp_path, field):
    path = tmp_path / "outbox.sqlite"
    store = StrategyNotificationOutbox(path, SCOPE)
    commit(store)
    store.close()
    before = path.read_bytes()
    values = {
        "account_ref": "account-a",
        "route_ref": "route-a",
        "strategy_ref": "strategy-a",
        "run_id": "run-a",
        "source_epoch": "epoch-a",
    }
    values[field] = "different"
    with pytest.raises(NotificationOutboxError, match="SCOPE_MISMATCH"):
        StrategyNotificationOutbox(path, NotificationScope(**values))
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "invalid",
    [b'{"a":1,"a":2}', b'{"a": NaN}', b'{"b":1,"a":2}', b"[]", b"\xff"],
)
def test_noncanonical_and_invalid_payloads_are_rejected(invalid):
    with pytest.raises(NotificationOutboxError, match="SNAPSHOT_INVALID"):
        event(payload=invalid)


def test_bounded_schema_and_order_trade_references_are_required():
    value = {}
    for _ in range(18):
        value = {"x": value}
    with pytest.raises(NotificationOutboxError, match="SNAPSHOT_INVALID"):
        event(payload=json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(NotificationOutboxError, match="SNAPSHOT_INVALID"):
        event(payload=b'{"text":"' + b"x" * 65536 + b'"}')
    with pytest.raises(NotificationOutboxError, match="SNAPSHOT_INVALID"):
        event(payload=b'{"x":"\\ud800"}')
    with pytest.raises(NotificationOutboxError, match="SCHEMA_UNSUPPORTED"):
        ProjectionCheckpoint("schema", 2, b"{}")
    with pytest.raises(NotificationOutboxError, match="IDENTITY_INVALID"):
        NotificationSnapshot("e", "trade", "feed", "order", None, "schema", 1, b"{}")
    with pytest.raises(NotificationOutboxError, match="TRADE_BINDING_INVALID"):
        NotificationSnapshot("e", "order", "feed", "order", "trade", "schema", 1, b"{}")


def test_reflection_altered_snapshot_is_not_committed(tmp_path):
    store = StrategyNotificationOutbox(tmp_path / "outbox.sqlite", SCOPE)
    item = event()
    object.__setattr__(item, "payload", b"not a canonical object")
    with pytest.raises(NotificationOutboxError, match="SNAPSHOT_INVALID"):
        commit(store, events=(item,))
    assert store.checkpoint().revision == 0
    store.close()


def test_runtime_tampering_and_ack_gap_are_not_consumed(tmp_path):
    path = tmp_path / "outbox.sqlite"
    store = StrategyNotificationOutbox(path, SCOPE)
    commit(store, events=(event(), event("event-2")))
    store.acknowledge("event-1")
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM projection_ack")
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        store.pending()
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        store.checkpoint()
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        store.acknowledge("event-2")
    store.close()


def test_source_identity_drift_is_detected_even_without_callbacks(tmp_path):
    path = tmp_path / "outbox.sqlite"
    store = StrategyNotificationOutbox(path, SCOPE)
    commit(store, events=())
    store.close()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projection_batch SET source_id='other-source'")
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        StrategyNotificationOutbox(path, SCOPE)


def test_capacity_failure_neither_advances_checkpoint_nor_drops_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox_module, "_MAX_PENDING_EVENTS", 1)
    store = StrategyNotificationOutbox(tmp_path / "outbox.sqlite", SCOPE)
    commit(store)
    with pytest.raises(NotificationOutboxError, match="PENDING_CAPACITY_EXCEEDED"):
        commit(store, source_id="source-2", revision=1, events=(event("event-2"),))
    assert store.checkpoint().revision == 1
    assert store.pending().event_id == "event-1"
    store.acknowledge("event-1")
    assert commit(store, source_id="source-2", revision=1, events=(event("event-2"),)).revision == 2
    store.close()


def test_concurrent_writers_with_same_revision_cannot_both_commit(tmp_path):
    path = tmp_path / "outbox.sqlite"
    stores = [StrategyNotificationOutbox(path, SCOPE), StrategyNotificationOutbox(path, SCOPE)]

    def write(index):
        try:
            return commit(
                stores[index], source_id=f"source-{index}", events=(event(f"event-{index}"),)
            )
        except NotificationOutboxError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, range(2)))
    assert sum(result == "REVISION_CONFLICT" for result in results) == 1
    assert sum(getattr(result, "revision", None) == 1 for result in results) == 1
    for store in stores:
        store.close()
    reopened = StrategyNotificationOutbox(path, SCOPE)
    assert reopened.checkpoint().revision == 1
    assert reopened.pending() is not None
    reopened.close()


def test_locked_store_reports_finite_failure_and_can_retry(tmp_path):
    path = tmp_path / "outbox.sqlite"
    store = StrategyNotificationOutbox(path, SCOPE)
    store._db.execute("PRAGMA busy_timeout=10")
    lock = sqlite3.connect(path, isolation_level=None)
    try:
        lock.execute("BEGIN IMMEDIATE")
        with pytest.raises(NotificationOutboxError, match="STORE_UNAVAILABLE"):
            commit(store)
        assert store.checkpoint().revision == 0
    finally:
        lock.execute("ROLLBACK")
        lock.close()
    assert commit(store).revision == 1
    assert store.pending() == event()
    store.close()


def test_callback_failure_leaves_pending_and_cannot_ack_out_of_order(tmp_path):
    store = StrategyNotificationOutbox(tmp_path / "outbox.sqlite", SCOPE)
    commit(store, events=(event(), event("event-2")))

    def fail(_event):
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        store.deliver_next(fail)
    assert store.pending().event_id == "event-1"
    with pytest.raises(NotificationOutboxError, match="ACK_OUT_OF_ORDER"):
        store.acknowledge("event-2")
    store.close()


def test_process_exit_after_side_effect_before_ack_redelivers_same_id(tmp_path):
    path = tmp_path / "outbox.sqlite"
    marker = tmp_path / "effect.txt"
    store = StrategyNotificationOutbox(path, SCOPE)
    commit(store)
    store.close()
    code = """
import os, sys
from backtrader.execution.strategy_notification_outbox import NotificationScope, StrategyNotificationOutbox
s = StrategyNotificationOutbox(sys.argv[1], NotificationScope("account-a", "route-a", "strategy-a", "run-a", "epoch-a"))
def callback(e):
    with open(sys.argv[2], "a", encoding="utf-8") as f:
        f.write(e.event_id + "\\n")
        f.flush()
        os.fsync(f.fileno())
    os._exit(17)
s.deliver_next(callback)
"""
    child = subprocess.run([sys.executable, "-c", code, str(path), str(marker)], check=False)
    assert child.returncode == 17
    reopened = StrategyNotificationOutbox(path, SCOPE)
    assert reopened.pending().event_id == "event-1"
    assert reopened.deliver_next(
        lambda e: marker.write_text(marker.read_text() + e.event_id + "\n")
    )
    assert marker.read_text() == "event-1\nevent-1\n"
    reopened.close()
    assert StrategyNotificationOutbox(path, SCOPE).pending() is None


def test_corruption_and_unknown_schema_are_rejected_without_overwrite(tmp_path):
    path = tmp_path / "outbox.sqlite"
    store = StrategyNotificationOutbox(path, SCOPE)
    commit(store)
    store.close()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE projection_notification SET payload=?", (b'{"status":"changed"}',))
    before = path.read_bytes()
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        StrategyNotificationOutbox(path, SCOPE)
    assert path.read_bytes() == before

    other = tmp_path / "other.sqlite"
    with sqlite3.connect(other) as db:
        db.execute("CREATE TABLE unrelated (x INTEGER)")
    before = other.read_bytes()
    with pytest.raises(NotificationOutboxError, match="STORE_SCHEMA_INVALID"):
        StrategyNotificationOutbox(other, SCOPE)
    assert other.read_bytes() == before


@pytest.mark.parametrize("kind", ["zero_bytes", "empty_sqlite", "truncated"])
def test_preexisting_empty_or_truncated_file_is_never_initialised(tmp_path, kind):
    path = tmp_path / "previous.sqlite"
    if kind == "zero_bytes":
        path.write_bytes(b"")
    elif kind == "empty_sqlite":
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE discarded (x INTEGER)")
            db.execute("DROP TABLE discarded")
        assert path.stat().st_size > 0
    else:
        store = StrategyNotificationOutbox(path, SCOPE)
        commit(store)
        store.close()
        path.write_bytes(path.read_bytes()[:64])
    before = path.read_bytes()
    with pytest.raises(NotificationOutboxError):
        StrategyNotificationOutbox(path, SCOPE)
    assert path.read_bytes() == before


def test_existing_valid_database_with_live_wal_remains_readable(tmp_path):
    path = tmp_path / "wal.sqlite"
    first = StrategyNotificationOutbox(path, SCOPE)
    commit(first)
    first.close()
    keeper = sqlite3.connect(path, isolation_level=None)
    try:
        assert keeper.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower() == "wal"
        reopened = StrategyNotificationOutbox(path, SCOPE)
        assert reopened.checkpoint().revision == 1
        reopened.acknowledge("event-1")
        reopened.close()
        final = StrategyNotificationOutbox(path, SCOPE)
        assert final.pending() is None
        final.close()
    finally:
        keeper.close()


def test_runtime_schema_mutation_is_rejected_before_ack(tmp_path):
    path = tmp_path / "outbox.sqlite"
    store = StrategyNotificationOutbox(path, SCOPE)
    commit(store)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TRIGGER erase_ack AFTER UPDATE OF ack_seq ON projection_meta "
            "BEGIN DELETE FROM projection_ack; END"
        )
    with pytest.raises(NotificationOutboxError, match="STORE_SCHEMA_INVALID"):
        store.acknowledge("event-1")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT ack_seq FROM projection_meta").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM projection_ack").fetchone() == (0,)
    store.close()


def test_path_replaced_between_readonly_and_writable_open_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "outbox.sqlite"
    replacement = tmp_path / "replacement.sqlite"
    original = tmp_path / "original.sqlite"
    for candidate in (path, replacement):
        store = StrategyNotificationOutbox(candidate, SCOPE)
        store.close()
    before_original, before_replacement = path.read_bytes(), replacement.read_bytes()
    real_connect = sqlite3.connect

    def switch_file(database, *args, **kwargs):
        if str(database).endswith("?mode=rw"):
            os.replace(path, original)
            os.replace(replacement, path)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", switch_file)
    with pytest.raises(NotificationOutboxError, match="STORE_PATH_CHANGED"):
        StrategyNotificationOutbox(path, SCOPE)
    assert original.read_bytes() == before_original
    assert path.read_bytes() == before_replacement


def test_new_path_replacement_during_initialization_is_rolled_back(tmp_path, monkeypatch):
    path = tmp_path / "new.sqlite"
    replacement = tmp_path / "unrelated"
    original = tmp_path / "new-moved.sqlite"
    replacement.write_bytes(b"unrelated data")
    check = StrategyNotificationOutbox._check_identity
    calls = 0

    def replace_before_commit(candidate, identity):
        nonlocal calls
        calls += 1
        if calls == 4:
            os.replace(path, original)
            os.replace(replacement, path)
        check(candidate, identity)

    monkeypatch.setattr(
        StrategyNotificationOutbox, "_check_identity", staticmethod(replace_before_commit)
    )
    with pytest.raises(NotificationOutboxError, match="STORE_PATH_CHANGED"):
        StrategyNotificationOutbox(path, SCOPE)
    assert path.read_bytes() == b"unrelated data"
    assert original.exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable on this platform")
def test_existing_fifo_is_rejected_without_blocking(tmp_path):
    path = tmp_path / "not-an-outbox"
    os.mkfifo(path)
    code = """
import sys
from backtrader.execution.strategy_notification_outbox import (
    NotificationOutboxError, NotificationScope, StrategyNotificationOutbox,
)
try:
    StrategyNotificationOutbox(sys.argv[1], NotificationScope("account-a", "route-a", "strategy-a", "run-a", "epoch-a"))
except NotificationOutboxError as exc:
    print(exc.code)
else:
    raise SystemExit(1)
"""
    child = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "STORE_PATH_INVALID"
    assert path.exists()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symbolic links unavailable")
@pytest.mark.parametrize("dangling", [False, True])
def test_symlink_never_initializes_or_changes_its_target(tmp_path, dangling):
    target = tmp_path / "target.sqlite"
    if not dangling:
        store = StrategyNotificationOutbox(target, SCOPE)
        commit(store)
        store.close()
        before = target.read_bytes()
    link = tmp_path / "link.sqlite"
    link.symlink_to(target)
    with pytest.raises(NotificationOutboxError):
        StrategyNotificationOutbox(link, SCOPE)
    if dangling:
        assert not target.exists()
    else:
        assert target.read_bytes() == before
    assert link.is_symlink()


@pytest.mark.parametrize("_trial", range(5))
def test_concurrent_process_create_does_not_reset_or_overwrite(tmp_path, _trial):
    path = tmp_path / "outbox.sqlite"
    gate = tmp_path / "go"
    code = """
import pathlib, sys, time
from backtrader.execution.strategy_notification_outbox import (
    NotificationOutboxError, NotificationScope, NotificationSnapshot,
    ProjectionCheckpoint, StrategyNotificationOutbox,
)
path, gate, ready, source = sys.argv[1:]
pathlib.Path(ready).touch()
deadline = time.monotonic() + 10
while not pathlib.Path(gate).exists():
    if time.monotonic() > deadline:
        raise SystemExit(90)
    time.sleep(0.005)
try:
    store = StrategyNotificationOutbox(path, NotificationScope("account-a", "route-a", "strategy-a", "run-a", "epoch-a"))
    store.commit(source_id=source, expected_revision=0,
        checkpoint=ProjectionCheckpoint("checkpoint", 1, b"{}"),
        notifications=(NotificationSnapshot(source, "order", "feed", "order", None, "schema", 1, b"{}"),))
    store.close()
    print("COMMITTED")
except NotificationOutboxError as exc:
    print(exc.code)
"""
    children = []
    try:
        for index in range(2):
            ready = tmp_path / f"ready-{index}"
            children.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        code,
                        str(path),
                        str(gate),
                        str(ready),
                        f"event-{index}",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )
        deadline = time.monotonic() + 10
        while not all((tmp_path / f"ready-{i}").exists() for i in range(2)):
            if time.monotonic() > deadline:
                raise AssertionError("child setup timed out")
            time.sleep(0.005)
        gate.touch()
        results = []
        for child in children:
            stdout, stderr = child.communicate(timeout=15)
            assert child.returncode == 0, stderr
            results.append(stdout.strip())
        assert results.count("COMMITTED") == 1
        assert set(results) <= {
            "COMMITTED",
            "REVISION_CONFLICT",
            "STORE_SCHEMA_INVALID",
            "STORE_INVALID",
        }
        store = StrategyNotificationOutbox(path, SCOPE)
        assert store.checkpoint().revision == 1
        assert store.pending().event_id in {"event-0", "event-1"}
        store.close()
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()
