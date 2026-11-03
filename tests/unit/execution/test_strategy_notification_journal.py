"""Bounded at-least-once notification journal (iteration 60, re-verification G3).

UNIT/FAKE: temporary SQLite files only. The cost test records numbers; it is
not a performance gate.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time

import pytest

from backtrader.execution.strategy_notification_outbox import (
    NotificationOutboxError,
    NotificationScope,
    StrategyNotificationJournal,
)

SCOPE = NotificationScope("account-a", "direct", "strategy-a", "deployment-a", "generation-1")


def _payload(i: int) -> bytes:
    return b'{"i":%d}' % i


def test_append_pending_ack_order_and_idempotency(tmp_path):
    journal = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE)
    first, created = journal.append("o-1", "order", _payload(1))
    assert created and first.seq == 1 and not first.acked
    journal.append("t-1", "trade", _payload(2))
    journal.append("f-1", "fee_correction", _payload(3))
    # Same id and payload: the existing entry; another payload: refused.
    again, created = journal.append("o-1", "order", _payload(1))
    assert not created and again.seq == 1
    with pytest.raises(NotificationOutboxError, match="EVENT_ID_CONFLICT"):
        journal.append("o-1", "order", _payload(9))
    with pytest.raises(NotificationOutboxError, match="EVENT_ID_CONFLICT"):
        journal.append("o-1", "trade", _payload(1))
    assert [e.event_id for e in journal.pending()] == ["o-1", "t-1", "f-1"]
    # Out-of-order acknowledgement never hides an older pending entry.
    assert journal.acknowledge("t-1") is True
    assert journal.acknowledge("t-1") is False
    assert [e.event_id for e in journal.pending()] == ["o-1", "f-1"]
    with pytest.raises(NotificationOutboxError, match="ACK_UNKNOWN"):
        journal.acknowledge("missing")
    acked, created = journal.append("t-1", "trade", _payload(2))
    assert acked.acked and not created
    journal.close()
    reopened = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE)
    assert [e.event_id for e in reopened.pending()] == ["o-1", "f-1"]
    assert reopened.stats() == {"next_seq": 4, "pending": 2, "retained": 3}
    reopened.close()


@pytest.mark.parametrize("kind, payload", [("other", b"{}"), ("order", b"{ }"), ("order", b"[]")])
def test_invalid_kind_or_noncanonical_payload_is_refused(tmp_path, kind, payload):
    journal = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE)
    with pytest.raises(NotificationOutboxError):
        journal.append("o-1", kind, payload)
    assert journal.pending() == ()
    journal.close()


def test_other_generation_requires_resync_and_other_scope_is_refused(tmp_path):
    path = tmp_path / "j.sqlite"
    StrategyNotificationJournal(path, SCOPE).close()
    before = path.read_bytes()
    with pytest.raises(NotificationOutboxError, match="RESYNC_REQUIRED"):
        StrategyNotificationJournal(
            path, NotificationScope("account-a", "direct", "strategy-a", "deployment-a", "gen-2")
        )
    with pytest.raises(NotificationOutboxError, match="SCOPE_MISMATCH"):
        StrategyNotificationJournal(
            path, NotificationScope("account-a", "direct", "strategy-b", "deployment-a",
                                    "generation-1")
        )
    assert path.read_bytes() == before


def test_retention_bounds_the_file_on_a_long_run(tmp_path):
    journal = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE, retain_acked=50)
    for i in range(3000):
        entry, _ = journal.append(f"o-{i}", "order", _payload(i))
        journal.acknowledge(entry.event_id)
    stats = journal.stats()
    assert stats["pending"] == 0 and stats["next_seq"] == 3001
    assert stats["retained"] <= 50 + 256
    journal.close()
    reopened = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE, retain_acked=50)
    assert reopened.stats()["retained"] == 50  # compacted at open
    # A recent acknowledged id is still recognised as already delivered.
    entry, created = reopened.append("o-2999", "order", _payload(2999))
    assert entry.acked and not created
    reopened.close()


def test_pending_capacity_fails_closed(tmp_path):
    journal = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE, max_pending=3)
    for i in range(3):
        journal.append(f"o-{i}", "order", _payload(i))
    with pytest.raises(NotificationOutboxError, match="PENDING_CAPACITY_EXCEEDED"):
        journal.append("o-3", "order", _payload(3))
    journal.acknowledge("o-0")
    journal.append("o-3", "order", _payload(3))
    assert [e.event_id for e in journal.pending()] == ["o-1", "o-2", "o-3"]
    journal.close()


def test_tampered_row_or_counter_is_detected(tmp_path):
    path = tmp_path / "j.sqlite"
    journal = StrategyNotificationJournal(path, SCOPE)
    journal.append("o-1", "order", _payload(1))
    journal.close()
    with sqlite3.connect(path) as db:
        db.execute("UPDATE journal_notification SET payload=? WHERE seq=1", (_payload(7),))
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        StrategyNotificationJournal(path, SCOPE)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE journal_notification SET payload=? WHERE seq=1", (_payload(1),))
        db.execute("UPDATE journal_meta SET pending=0")
    with pytest.raises(NotificationOutboxError, match="STORE_CORRUPT"):
        StrategyNotificationJournal(path, SCOPE)


def test_foreign_or_old_outbox_database_is_refused(tmp_path):
    from backtrader.execution.strategy_notification_outbox import StrategyNotificationOutbox

    path = tmp_path / "old.sqlite"
    StrategyNotificationOutbox(path, SCOPE).close()
    with pytest.raises(NotificationOutboxError, match="STORE_SCHEMA_INVALID"):
        StrategyNotificationJournal(path, SCOPE)
    empty = tmp_path / "empty.sqlite"
    empty.write_bytes(b"")
    with pytest.raises(NotificationOutboxError, match="STORE_SCHEMA_INVALID"):
        StrategyNotificationJournal(empty, SCOPE)


def test_crash_after_callback_before_ack_redelivers_the_same_id(tmp_path):
    path = tmp_path / "j.sqlite"
    side_effect = tmp_path / "effect.txt"
    code = f"""
import os, sys
from backtrader.execution.strategy_notification_outbox import (
    NotificationScope, StrategyNotificationJournal)
j = StrategyNotificationJournal({str(path)!r}, NotificationScope(*{tuple(SCOPE.__dict__.values())!r}))
j.append("o-1", "order", b'{{"i":1}}')
for entry in j.pending():
    open({str(side_effect)!r}, "a").write(entry.event_id + "\\n")
    os._exit(9)  # the callback ran; the acknowledgement never happened
"""
    env = dict(os.environ, PYTHONPATH=os.getcwd())
    result = subprocess.run([sys.executable, "-c", code], env=env, timeout=60)
    assert result.returncode == 9
    journal = StrategyNotificationJournal(path, SCOPE)
    assert [e.event_id for e in journal.pending()] == ["o-1"]
    assert side_effect.read_text().split() == ["o-1"]
    journal.close()


def test_append_and_ack_cost_is_flat_and_recorded(tmp_path, capsys):
    """Records per-pair cost at two history sizes; not a performance gate."""

    journal = StrategyNotificationJournal(tmp_path / "j.sqlite", SCOPE, retain_acked=256)
    timings = []
    for batch in range(3):
        started = time.perf_counter()
        for i in range(500):
            entry, _ = journal.append(f"o-{batch}-{i}", "order", _payload(i))
            journal.acknowledge(entry.event_id)
        timings.append((time.perf_counter() - started) / 500)
    journal.close()
    with capsys.disabled():
        print(
            "\nnotification journal append+ack per pair (us): "
            + ", ".join(f"{value * 1e6:.1f}" for value in timings)
        )
    # Flat, not growing with history (generous bound against noisy machines).
    assert timings[-1] < max(timings[0] * 5, 0.005)
