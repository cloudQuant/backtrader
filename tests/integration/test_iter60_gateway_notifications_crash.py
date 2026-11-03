"""Iteration 60 R2-C: Gateway-mode notifications across real process crashes.

A spawned Backtrader child consumes strategy A's Gateway execution stream
(Gateway producer -> account journal -> co-located ``GatewayReadService`` ->
SDK ``ServiceExecutionEventConsumer`` -> ``BtApiBroker``) and is killed with
``os._exit`` at one crash window. This process then restarts on the same
files and must reach exactly one ledger effect (strategy A sells its 2 once),
the SDK cursor at the stream head with no pending ACK, and no Gateway event
delivered *live* twice; journaled but unacknowledged notifications come back
as replays with their original ``notification_id`` (at least once, as in
direct mode). INTEGRATION_SIM: local SQLite files and test-owned processes.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("bt_api_py.service_execution_event_consumer")
pytest.importorskip("bt_api_gateway.execution_event_publisher")

_HERE = Path(__file__).resolve().parent


def _support():
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    import iter60_gateway_execution_support as support

    return support


def _log(path, entries):
    with open(path, "a", encoding="utf-8") as stream:
        for kind, status, event_id, replayed in entries:
            stream.write(f"{kind}|{status}|{event_id}|{int(bool(replayed))}\n")
        stream.flush()
        os.fsync(stream.fileno())


class _LoggedList(list):
    """Write each delivery durably before the callback returns (the side effect)."""

    def __init__(self, path, stage):
        super().__init__()
        self.path = path
        self.stage = stage

    def append(self, entry):
        _log(self.path, [entry])
        super().append(entry)
        if self.stage == "in_callback" and entry[:2] == ("order", "Completed"):
            os._exit(72)


def _child(directory, stage):
    t = _support()
    directory = Path(directory)
    received = _LoggedList(directory / "child.log", stage)
    s = t.stack(
        directory,
        "gateway",
        received=received,
        acknowledge="manual" if stage == "after_callback_before_ack" else "after_apply",
    )
    binding = s.broker._gateway_execution_bindings[id(s.a)]
    recovery = s.broker._strategy_notification_recovery[id(s.a)]
    t.place(s)
    t.cycle(s)
    if stage == "after_read":
        real_read = binding.consumer.read

        def read_then_die():
            page = real_read()
            assert len(page.events) == 5
            os._exit(71)  # read from the SDK, nothing appended to the journal

        binding.consumer.read = read_then_die
    if stage == "after_append":
        real_append = recovery.journal.append

        def append_then_die(event_id, kind, payload):
            entry, created = real_append(event_id, kind, payload)
            if created and b'"status_name":"Partial"' in payload:
                os._exit(73)  # journaled; no callback, no fact record, no SDK commit
            return entry, created

        recovery.journal.append = append_then_die
    if stage == "before_commit":

        def commit_then_die(page):
            os._exit(75)  # applied and recorded, the SDK cursor not committed

        binding.consumer.commit = commit_then_die
    s.broker.poll_gateway_execution_events()
    t.cycle(s)
    if stage == "after_callback_before_ack":
        os._exit(76)  # every callback returned; the SDK cursor is committed, not ACKed
    os._exit(74)


def _run(directory, stage):
    context = multiprocessing.get_context("spawn")
    child = context.Process(target=_child, args=(str(directory), stage))
    child.start()
    child.join(timeout=120)
    try:
        return child.exitcode
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)


def _read_log(path):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        kind, status, event_id, replayed = line.split("|")
        rows.append((kind, status, event_id, replayed == "1"))
    return rows


@pytest.mark.parametrize(
    ("stage", "exit_code"),
    [
        ("after_read", 71),
        ("after_append", 73),
        ("in_callback", 72),
        ("before_commit", 75),
        ("after_callback_before_ack", 76),
        ("after_ack", 74),
    ],
)
def test_gateway_notifications_have_exactly_one_effect_across_a_crash(tmp_path, stage, exit_code):
    t = _support()
    t.publish(tmp_path / "gateway.sqlite3", t.observations())
    assert _run(tmp_path, stage) == exit_code
    child = _read_log(tmp_path / "child.log")
    s = t.stack(tmp_path, "gateway")
    try:
        s.broker.poll_gateway_execution_events()
        t.cycle(s)
        after = list(s.received)

        # Nothing failed closed on the way (a journal conflict would disable trading).
        assert s.broker._trading_enabled is not False
        assert s.broker.strategy_notification_recovery_state(s.a) == "ACTIVE"
        assert s.broker.gateway_execution_events_state(s.a)["state"] == "ACTIVE"
        assert all(event_id for _k, _s, event_id, _r in child + after)
        # Exactly one ledger effect, whatever the window.
        assert t.position(s) == Decimal("0"), (stage, child, after)
        assert s.ledger.intent_state("intent-sa-1") == "FILLED"
        # The SDK cursor reached the stream head and nothing waits for an ACK.
        checkpoint = s.broker._gateway_execution_bindings[id(s.a)].consumer.checkpoint()
        assert checkpoint.cursor == 5 and not checkpoint.pending_ack

        # No Gateway effect is delivered live twice across the two processes.
        live_child = {event_id for _k, _s, event_id, replayed in child if not replayed}
        for kind, status, event_id, replayed in after:
            if not replayed:
                assert event_id not in live_child, (stage, kind, status)
        # Replays are journaled-but-unacknowledged notifications of the child.
        child_ids = {event_id for _k, _s, event_id, _r in child}
        for kind, status, event_id, replayed in after:
            if replayed and event_id not in {e for _k, _s, e, r in after if not r}:
                assert kind in ("order", "trade")
        # Every order state reached the Strategy at least once.
        statuses = {status for kind, status, *_ in child + after if kind == "order"}
        assert {"Accepted", "Partial", "Completed"} <= statuses, (stage, child, after)

        if stage == "after_read":
            assert s.rebuilt == 1 and s.replayed == 0
            assert [st for k, st, *_ in after if k == "order"][-1] == "Completed"
        elif stage == "after_append":
            # Partial was journaled by the child and replayed; its re-application
            # by the SDK re-read is recognised and not delivered again.
            assert s.replayed >= 1 and after[0][:2] == ("order", "Partial") and after[0][3]
            assert after[0][2] not in child_ids
            assert sum(1 for k, st, *_ in after if (k, st) == ("order", "Partial")) == 1, after
        elif stage == "in_callback":
            assert after[0][:2] == ("order", "Completed") and after[0][3]
            assert after[0][2] in child_ids  # replayed with the id it was delivered with
        elif stage == "before_commit":
            # All facts were recorded: the re-read page has no second effect; the
            # undelivered notifications come back as replays.
            assert all(replayed for *_x, replayed in after)
            assert ("order", "Completed") in t.shapes(after)
        elif stage in ("after_callback_before_ack", "after_ack"):
            assert after == [] and s.replayed == 0

        # A third start delivers nothing and has nothing left to apply.
        s.broker.close_gateway_execution_events()
        s.broker.close_strategy_notification_recovery()
        s.ledger.close()
        third = t.stack(tmp_path, "gateway")
        third.broker.poll_gateway_execution_events()
        t.cycle(third)
        assert third.received == [] and third.replayed == 0 and third.rebuilt == 0
        assert t.position(third) == Decimal("0")
        third.broker.close_gateway_execution_events()
        third.broker.close_strategy_notification_recovery()
        third.ledger.close()
    finally:
        if s.broker._gateway_execution_bindings is not None:
            s.broker.close_gateway_execution_events()
        if s.broker._strategy_notification_recovery is not None:
            s.broker.close_strategy_notification_recovery()


def test_recorded_facts_of_a_live_order_are_not_reapplied_after_a_crash(tmp_path):
    """Crash after the effects and fact records, before the SDK commit, order still open."""

    t = _support()
    t.publish(tmp_path / "gateway.sqlite3", t.observations()[:3])  # open, fill 1, partial
    assert _run(tmp_path, "before_commit") == 75
    s = t.stack(tmp_path, "gateway")
    try:
        assert s.rebuilt == 1
        rebuilt = next(iter(s.broker.orders.values()))
        assert rebuilt.executed.size == -1.0
        assert s.broker.poll_gateway_execution_events() == 0  # the re-read page is skipped
        t.cycle(s)
        assert rebuilt.executed.size == -1.0 and t.position(s) == Decimal("1")
        assert all(replayed for *_x, replayed in s.received)
        state = s.broker.gateway_execution_events_state(s.a)
        assert state["skipped"] == 3 and state["applied"] == 0
        checkpoint = s.broker._gateway_execution_bindings[id(s.a)].consumer.checkpoint()
        assert checkpoint.cursor == 3 and not checkpoint.pending_ack
        # The rest of the order still projects onto the rebuilt order.
        t.publish(tmp_path / "gateway.sqlite3", t.observations()[3:])
        assert s.broker.poll_gateway_execution_events() == 2
        t.cycle(s)
        assert t.position(s) == Decimal("0")
        assert s.ledger.intent_state("intent-sa-1") == "FILLED"
    finally:
        s.broker.close_gateway_execution_events()
        s.broker.close_strategy_notification_recovery()
        s.ledger.close()
