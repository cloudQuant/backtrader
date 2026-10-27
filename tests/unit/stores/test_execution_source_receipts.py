"""Durable, non-executing source anchors for saved cohort history."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backtrader.research.live_cohort import (
    LiveCalendarMemberSession,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortJournalHighWater,
    LiveCohortJournalMemberHighWater,
)
from backtrader.stores import execution_journal_archive as archive_module
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
    ExecutionSourceMemberReceipt,
    ExecutionSourceReceipt,
    ExecutionSourceRestartMarker,
    _source_receipt_sha256,
    _source_receipt_values,
)


_ACCOUNT = "source-account"
_STRATEGY = "source-strategy"
_RUN = "source-run"
_SOURCE_KIND = "ALPHA003_GRID"
_MEMBER = "IF2720"
_SOURCE_REF = "ctp-live"
_BASE = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def _drop_v17_workflow_tables(connection: sqlite3.Connection) -> None:
    """Remove only the v17 addition before presenting a historical schema."""

    connection.execute("DROP TABLE execution_fee_pair_workflow_decision_reservations")
    connection.execute("DROP TABLE execution_fee_pair_workflow_durable_reservations")
    connection.execute("DROP TABLE execution_fee_pair_workflow_events")
    connection.execute("DROP TABLE execution_fee_pair_workflows")


def _time(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _calendar(epoch: int, *, count: int = 12) -> LiveCohortCalendar:
    trading_day = "20261026"
    session = LiveCalendarMemberSession(trading_day, "morning")
    slots = tuple(
        LiveCalendarSlot(
            slot_id="slot-{}".format(index),
            bucket_start=_BASE + timedelta(minutes=index),
            close_time=_BASE + timedelta(minutes=index + 1),
            trading_day=trading_day,
            session_segment="morning",
            member_sessions={_MEMBER: session},
        )
        for index in range(count)
    )
    return LiveCohortCalendar(
        calendar_id="source-calendar",
        version="v{}".format(epoch),
        epoch_id=epoch,
        frequency="1m",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="synthetic-ctp-clock",
        session_semantics="explicit-session-slots",
        slots=slots,
    )


def _receipt(
    calendar: LiveCohortCalendar,
    *,
    cohort_id: str,
    slot_index: int,
    tape_file_id: str,
    tape_record_index: int,
    source_role: str,
    connection_generation: str,
    feed_sequence: int,
    predecessor=None,
    restart_marker=None,
    readiness=None,
    origin_partition=None,
) -> ExecutionSourceReceipt:
    slot = calendar.slots[slot_index]
    close_time = _time(slot.close_time)
    member = ExecutionSourceMemberReceipt(
        member_id=_MEMBER,
        source_ref=_SOURCE_REF,
        source_role=source_role,
        connection_generation=connection_generation,
        feed_sequence=feed_sequence,
        bar_id="bar-{}-{}".format(calendar.epoch_id, slot.slot_id),
        bucket_start=_time(slot.bucket_start),
        close_time=close_time,
        available_at=_time(slot.close_time + timedelta(seconds=1)),
        trading_day=slot.trading_day,
        session_segment=slot.member_sessions[_MEMBER].session_segment,
        timezone_id=calendar.timezone_id,
        clock_domain_id=calendar.clock_domain_id,
        complete=True,
        quality="GOOD",
        present=True,
        origin_partition=origin_partition,
    )
    return ExecutionSourceReceipt(
        source_kind=_SOURCE_KIND,
        cohort_id=cohort_id,
        calendar_id=calendar.calendar_id,
        calendar_version=calendar.version,
        calendar_fingerprint=calendar.fingerprint,
        epoch_id=calendar.epoch_id,
        slot_index=slot_index,
        slot_id=slot.slot_id,
        close_time=close_time,
        batch_id="{}:{}:{}:{}:{}".format(
            cohort_id, calendar.calendar_id, calendar.epoch_id, calendar.version, slot_index
        ),
        readiness=readiness
        or ("LIVE_READY" if source_role == "live" else "WARMUP"),
        tape_file_id=tape_file_id,
        tape_record_id="{}-{}".format(tape_file_id, tape_record_index),
        tape_record_index=tape_record_index,
        members=(member,),
        predecessor=predecessor,
        restart_marker=restart_marker,
    )


def _record_source(journal, receipt: ExecutionSourceReceipt, *, eligible=False):
    key = ExecutionDecisionKey(
        account_scope=_ACCOUNT,
        strategy_scope=_STRATEGY,
        logical_run_id=_RUN,
        cohort_id=receipt.cohort_id,
        close_time=receipt.close_time,
        decision_kind=_SOURCE_KIND,
    )
    return journal.record_grid_decision(
        key,
        {"signal": "synthetic-source"},
        epoch_id=str(receipt.epoch_id),
        batch_id=receipt.batch_id,
        eligible=eligible,
        complete=True,
        live_ready=receipt.readiness == "LIVE_READY",
        inputs_complete=all(member.quality == "GOOD" for member in receipt.members),
        intent_keys=(
            (ExecutionIntentKey("SUBMIT", "IF2720", "BUY", "OPEN", 0),)
            if eligible
            else ()
        ),
        source_receipt=receipt,
    )


def _durable_usage(connection):
    return tuple(
        tuple(row)
        for row in connection.execute(
            "SELECT capacity_class,record_count,payload_bytes "
            "FROM execution_durable_capacity_usage ORDER BY capacity_class"
        )
    )


def _core_highwater(source_highwater) -> LiveCohortJournalHighWater:
    receipt = source_highwater.receipt
    members = {
        member.member_id: LiveCohortJournalMemberHighWater(
            member_id=member.member_id,
            source_ref=member.source_ref,
            source_role=member.source_role,
            connection_generation=member.connection_generation,
            feed_sequence=member.feed_sequence,
            bar_id=member.bar_id,
            close_time=_datetime(member.close_time),
            trading_day=member.trading_day,
            session_segment=member.session_segment,
        )
        for member in receipt.members
    }
    return LiveCohortJournalHighWater(
        cohort_id=receipt.cohort_id,
        calendar_id=receipt.calendar_id,
        calendar_version=receipt.calendar_version,
        calendar_fingerprint=receipt.calendar_fingerprint,
        epoch_id=receipt.epoch_id,
        slot_index=receipt.slot_index,
        slot_id=receipt.slot_id,
        close_time=_datetime(receipt.close_time),
        batch_id=receipt.batch_id,
        members=members,
    )


def _highwater(journal):
    return journal.source_highwater(_ACCOUNT, _STRATEGY, _RUN, _SOURCE_KIND)


def test_source_receipts_survive_reopen_and_exact_replay_without_advancing_grid(tmp_path):
    path = tmp_path / "source-receipts.sqlite3"
    calendar = _calendar(1)
    journal = ExecutionDecisionJournal(path)
    first = _receipt(
        calendar,
        cohort_id="cohort-1",
        slot_index=0,
        tape_file_id="tape-1",
        tape_record_index=1,
        source_role="live",
        connection_generation="generation-1",
        feed_sequence=1,
    )
    _record_source(journal, first)
    first_usage = _durable_usage(journal._connection)
    first_usage_by_class = {row[0]: (row[1], row[2]) for row in first_usage}
    assert first_usage_by_class["BASE"][0] == 2
    assert first_usage_by_class["SETTLEMENT"] == (0, 0)
    second = _receipt(
        calendar,
        cohort_id="cohort-1",
        slot_index=1,
        tape_file_id="tape-1",
        tape_record_index=2,
        source_role="live",
        connection_generation="generation-1",
        feed_sequence=2,
        predecessor=_highwater(journal).reference,
    )
    _record_source(journal, second)
    before = _highwater(journal)
    assert before is not None
    assert before.receipt == second
    assert journal._connection.execute(
        "SELECT COUNT(*) FROM execution_source_highwaters"
    ).fetchone()[0] == 1
    assert journal._connection.execute(
        "SELECT COUNT(*) FROM execution_decisions"
    ).fetchone()[0] == 2
    second_usage = _durable_usage(journal._connection)
    second_usage_by_class = {row[0]: (row[1], row[2]) for row in second_usage}
    assert second_usage_by_class["BASE"][0] == 3
    assert second_usage_by_class["BASE"][1] > first_usage_by_class["BASE"][1]
    assert second_usage_by_class["SETTLEMENT"] == (0, 0)
    assert journal.grid_cursor(_ACCOUNT, _STRATEGY, "cohort-1") is None
    assert journal._connection.execute(
        "SELECT COUNT(*) FROM execution_grid_highwaters"
    ).fetchone()[0] == 0
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    try:
        replay = _record_source(reopened, second)
        assert replay.is_new_grid is False
        assert replay.cursor is None
        assert replay.source_anchor is not None
        assert _highwater(reopened) == before
        assert reopened._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == 1
        assert reopened._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0] == 2
    finally:
        reopened.close()


def test_legacy_source_receipt_hash_and_bytes_survive_reopen(tmp_path):
    path = tmp_path / "legacy-source-receipt.sqlite3"
    receipt = _receipt(
        _calendar(1),
        cohort_id="cohort-1",
        slot_index=0,
        tape_file_id="tape-1",
        tape_record_index=1,
        source_role="live",
        connection_generation="generation-1",
        feed_sequence=1,
    )
    member_values = _source_receipt_values(receipt)["members"][0]
    assert "origin_partition" not in member_values
    expected_legacy_hash = "2c4c49968802265f1dd58bf9ae20939c33f885d3ad3c310eb6a257886e2cd9a1"
    assert _source_receipt_sha256(receipt) == expected_legacy_hash

    journal = ExecutionDecisionJournal(path)
    _record_source(journal, receipt)
    before = _highwater(journal)
    assert before is not None and before.receipt_sha256 == expected_legacy_hash
    journal.close()

    reopened = ExecutionDecisionJournal(path)
    try:
        after = _highwater(reopened)
        assert after == before
        assert after.receipt_sha256 == expected_legacy_hash
        assert _source_receipt_values(after.receipt)["members"][0] == member_values
    finally:
        reopened.close()


def test_source_origin_partition_accepts_epoch_scoped_generation_reuse_and_rejects_rollback(
    tmp_path,
):
    journal = ExecutionDecisionJournal(tmp_path / "origin-partition-order.sqlite3")

    def partition(cohort_id, epoch_id, source_role):
        return {
            "schema": "backtrader.execution_source_origin_partition.v1",
            "cohort_id": cohort_id,
            "epoch_id": epoch_id,
            "member_id": _MEMBER,
            "source_ref": _SOURCE_REF,
            "source_role": source_role,
            "connection_generation": "generation-reused-after-restart",
        }

    try:
        epoch1_partition = partition("cohort-1", 1, "live")
        first = _receipt(
            _calendar(1),
            cohort_id="cohort-1",
            slot_index=0,
            tape_file_id="tape-1",
            tape_record_index=1,
            source_role="live",
            connection_generation="generation-reused-after-restart",
            feed_sequence=1,
            origin_partition=epoch1_partition,
        )
        _record_source(journal, first)
        prior = _highwater(journal)
        assert prior is not None

        epoch2_calendar = _calendar(2)
        epoch2_first = _receipt(
            epoch2_calendar,
            cohort_id="cohort-2",
            slot_index=0,
            tape_file_id="tape-2",
            tape_record_index=1,
            source_role="history",
            connection_generation="generation-reused-after-restart",
            feed_sequence=1,
            predecessor=prior.reference,
            restart_marker=ExecutionSourceRestartMarker(prior_highwater=prior.reference),
            origin_partition=epoch1_partition,
        )
        _record_source(journal, epoch2_first)
        epoch2_prior = _highwater(journal)
        assert epoch2_prior is not None

        epoch2_history_origin = partition("cohort-2", 2, "history")
        epoch2_second = _receipt(
            epoch2_calendar,
            cohort_id="cohort-2",
            slot_index=1,
            tape_file_id="tape-2",
            tape_record_index=2,
            source_role="history",
            connection_generation="generation-reused-after-restart",
            feed_sequence=1,
            predecessor=epoch2_prior.reference,
            origin_partition=epoch2_history_origin,
        )
        _record_source(journal, epoch2_second)
        epoch2_prior = _highwater(journal)
        assert epoch2_prior is not None

        rolled_back = _receipt(
            epoch2_calendar,
            cohort_id="cohort-2",
            slot_index=2,
            tape_file_id="tape-2",
            tape_record_index=3,
            source_role="history",
            connection_generation="generation-reused-after-restart",
            feed_sequence=2,
            predecessor=epoch2_prior.reference,
            origin_partition=epoch1_partition,
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="SOURCE_RECEIPT_LINEAGE_ORDER_INVALID"
        ):
            _record_source(journal, rolled_back)
        assert _highwater(journal) == epoch2_prior
    finally:
        journal.close()


def test_grid_source_anchor_is_atomic_and_source_only_cannot_upgrade(tmp_path):
    path = tmp_path / "grid-anchor.sqlite3"
    journal = ExecutionDecisionJournal(path)
    try:
        calendar = _calendar(1)
        warmup = _receipt(
            calendar,
            cohort_id="cohort-1",
            slot_index=0,
            tape_file_id="tape-1",
            tape_record_index=1,
            source_role="live",
            connection_generation="generation-1",
            feed_sequence=1,
            readiness="WARMUP",
        )
        _record_source(journal, warmup)
        with pytest.raises(
            ExecutionDecisionJournalError, match="SOURCE_ONLY_ANCHOR_HAS_INTENTS"
        ):
            _record_source(journal, warmup, eligible=True)

        live_ready_no_open = _receipt(
            calendar,
            cohort_id="cohort-1",
            slot_index=1,
            tape_file_id="tape-1",
            tape_record_index=2,
            source_role="live",
            connection_generation="generation-1",
            feed_sequence=2,
            predecessor=_highwater(journal).reference,
            readiness="LIVE_READY",
        )
        _record_source(journal, live_ready_no_open, eligible=False)
        with pytest.raises(
            ExecutionDecisionJournalError, match="SOURCE_RECEIPT_ALREADY_ANCHORED"
        ):
            _record_source(journal, live_ready_no_open, eligible=True)

        live = _receipt(
            calendar,
            cohort_id="cohort-1",
            slot_index=2,
            tape_file_id="tape-1",
            tape_record_index=3,
            source_role="live",
            connection_generation="generation-1",
            feed_sequence=3,
            predecessor=_highwater(journal).reference,
        )
        accepted = _record_source(journal, live, eligible=True)
        assert accepted.eligible is True
        assert accepted.is_new_grid is True
        assert accepted.decision is not None
        assert accepted.source_anchor == accepted.decision
        assert accepted.cursor is not None
        head = _highwater(journal)
        assert head is not None and head.anchor_kind == "GRID"
        assert head.decision_id == accepted.decision.decision_id
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == 1
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decision_slots"
        ).fetchone()[0] == 1

        replay = _record_source(journal, live, eligible=True)
        assert replay.is_new_grid is False
        assert replay.decision == accepted.decision
        assert _highwater(journal) == head
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0] == 3

        journal.close()
        reopened = ExecutionDecisionJournal(path)
        try:
            replay = _record_source(reopened, live, eligible=True)
            assert replay.is_new_grid is False
            assert replay.decision == accepted.decision
            assert _highwater(reopened) == head
            assert reopened._connection.execute(
                "SELECT COUNT(*) FROM execution_decisions"
            ).fetchone()[0] == 3
        finally:
            reopened.close()
    finally:
        journal.close()


@pytest.mark.parametrize(
    "change,expected_code",
    (
        ("role_downgrade", "SOURCE_RECEIPT_ROLE_ORDER_INVALID"),
        ("generation_drift", "SOURCE_RECEIPT_MEMBER_SEQUENCE_INVALID"),
        ("sequence_rewind", "SOURCE_RECEIPT_MEMBER_SEQUENCE_INVALID"),
        ("missing_predecessor", "SOURCE_HIGHWATER_PREDECESSOR_MISMATCH"),
        ("decision_kind_drift", "SOURCE_RECEIPT_DECISION_MISMATCH"),
    ),
)
def test_source_append_rejects_role_sequence_and_predecessor_drift(
    tmp_path, change, expected_code
):
    journal = ExecutionDecisionJournal(tmp_path / (change + ".sqlite3"))
    try:
        calendar = _calendar(1)
        first = _receipt(
            calendar,
            cohort_id="cohort-1",
            slot_index=0,
            tape_file_id="tape-1",
            tape_record_index=1,
            source_role="live",
            connection_generation="generation-1",
            feed_sequence=4,
        )
        _record_source(journal, first)
        previous = _highwater(journal).reference
        options = {
            "cohort_id": "cohort-1",
            "slot_index": 1,
            "tape_file_id": "tape-1",
            "tape_record_index": 2,
            "source_role": "live",
            "connection_generation": "generation-1",
            "feed_sequence": 5,
            "predecessor": previous,
        }
        if change == "role_downgrade":
            options.update(source_role="history", readiness="WARMUP")
        elif change == "generation_drift":
            options.update(connection_generation="generation-2")
        elif change == "sequence_rewind":
            options.update(feed_sequence=4)
        elif change == "missing_predecessor":
            options.update(predecessor=None)
        candidate = _receipt(calendar, **options)
        if change == "decision_kind_drift":
            candidate = replace(candidate, source_kind="OTHER_SOURCE_KIND")
        with pytest.raises(ExecutionDecisionJournalError, match=expected_code):
            _record_source(journal, candidate)
        assert _highwater(journal).receipt == first
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0] == 1
    finally:
        journal.close()


def test_core_restart_gap_marker_supports_history_prefix_live_tail_and_epoch_three(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "three-epochs.sqlite3")
    try:
        first_calendar = _calendar(1)
        first_head = None
        for index in range(3):
            receipt = _receipt(
                first_calendar,
                cohort_id="cohort-1",
                slot_index=index,
                tape_file_id="tape-1",
                tape_record_index=index + 1,
                source_role="live",
                connection_generation="generation-1",
                feed_sequence=index + 1,
            )
            if first_head is not None:
                receipt = replace(receipt, predecessor=first_head.reference)
            _record_source(journal, receipt)
            first_head = _highwater(journal)
        assert first_head is not None

        second_full_calendar = _calendar(2)
        second_calendar = LiveCohortCalendar.with_restart_gap(
            second_full_calendar,
            startup_time_utc=_BASE + timedelta(minutes=5),
            journal_highwater=_core_highwater(first_head),
            first_live_slot_id="slot-5",
        )
        gap2 = second_calendar.restart_gap
        assert gap2 is not None
        second_previous = first_head.reference
        second_head = None
        for index, role in ((0, "history"), (1, "history"), (2, "history"), (3, "live"), (4, "live")):
            marker = (
                ExecutionSourceRestartMarker(
                    prior_highwater=second_previous,
                    gap_fingerprint=gap2.fingerprint,
                )
                if index == 0
                else None
            )
            receipt = _receipt(
                second_calendar,
                cohort_id="cohort-2",
                slot_index=index,
                tape_file_id="tape-2",
                tape_record_index=index + 1,
                source_role=role,
                connection_generation="generation-1" if role == "history" else "generation-2",
                feed_sequence=index + 1 if role == "history" else index - 2,
                predecessor=second_previous,
                restart_marker=marker,
            )
            if index == 0:
                assert _datetime(receipt.close_time) < _datetime(second_previous.close_time)
            _record_source(journal, receipt)
            second_head = _highwater(journal)
            second_previous = second_head.reference
        assert second_head is not None
        assert second_head.receipt.epoch_id == 2
        assert second_head.receipt.members[0].source_role == "live"

        third_full_calendar = _calendar(3)
        third_calendar = LiveCohortCalendar.with_restart_gap(
            third_full_calendar,
            startup_time_utc=_BASE + timedelta(minutes=9),
            journal_highwater=_core_highwater(second_head),
            first_live_slot_id="slot-9",
        )
        gap3 = third_calendar.restart_gap
        assert gap3 is not None
        third_marker = ExecutionSourceRestartMarker(
            prior_highwater=second_head.reference,
            gap_fingerprint=gap3.fingerprint,
        )
        third_first = _receipt(
            third_calendar,
            cohort_id="cohort-3",
            slot_index=0,
            tape_file_id="tape-3",
            tape_record_index=1,
            source_role="history",
            connection_generation="generation-2",
            feed_sequence=1,
            predecessor=second_head.reference,
            restart_marker=third_marker,
        )
        assert _datetime(third_first.close_time) < _datetime(second_head.receipt.close_time)
        _record_source(journal, third_first)
        final_head = _highwater(journal)
        assert final_head is not None
        assert final_head.receipt.epoch_id == 3
        assert final_head.receipt.slot_index == 0
        assert final_head.receipt.close_time == third_first.close_time
        assert final_head.receipt.restart_marker == third_marker
    finally:
        journal.close()


def test_restart_requires_exact_prior_highwater_marker(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "restart-marker.sqlite3")
    try:
        calendar = _calendar(1)
        first = _receipt(
            calendar,
            cohort_id="cohort-1",
            slot_index=0,
            tape_file_id="tape-1",
            tape_record_index=1,
            source_role="live",
            connection_generation="generation-1",
            feed_sequence=1,
        )
        _record_source(journal, first)
        old_head = _highwater(journal)
        assert old_head is not None
        new_calendar = LiveCohortCalendar.with_restart_gap(
            _calendar(2),
            startup_time_utc=_BASE + timedelta(minutes=5),
            journal_highwater=_core_highwater(old_head),
            first_live_slot_id="slot-5",
        )
        good_marker = ExecutionSourceRestartMarker(
            prior_highwater=old_head.reference,
            gap_fingerprint=new_calendar.restart_gap.fingerprint,
        )
        bad_ref = replace(old_head.reference, receipt_sha256="0" * 64)
        candidate = _receipt(
            new_calendar,
            cohort_id="cohort-2",
            slot_index=0,
            tape_file_id="tape-2",
            tape_record_index=1,
            source_role="history",
            connection_generation="generation-1",
            feed_sequence=1,
            predecessor=old_head.reference,
            restart_marker=ExecutionSourceRestartMarker(
                prior_highwater=bad_ref,
                gap_fingerprint=good_marker.gap_fingerprint,
            ),
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="SOURCE_RESTART_MARKER_MISMATCH"
        ):
            _record_source(journal, candidate)
        missing = replace(candidate, restart_marker=None)
        with pytest.raises(
            ExecutionDecisionJournalError, match="SOURCE_RESTART_MARKER_REQUIRED"
        ):
            _record_source(journal, missing)
        assert _highwater(journal) == old_head

        gapless = _receipt(
            _calendar(2),
            cohort_id="cohort-2",
            slot_index=0,
            tape_file_id="tape-2",
            tape_record_index=1,
            source_role="history",
            connection_generation="generation-1",
            feed_sequence=1,
            predecessor=old_head.reference,
            restart_marker=ExecutionSourceRestartMarker(
                prior_highwater=old_head.reference,
                gap_fingerprint=None,
            ),
        )
        _record_source(journal, gapless)
        assert _highwater(journal).receipt.epoch_id == 2
    finally:
        journal.close()


def test_source_highwater_and_decision_roll_back_together_on_capacity(tmp_path):
    journal = ExecutionDecisionJournal(
        tmp_path / "source-capacity.sqlite3",
        max_durable_base_records=1,
    )
    try:
        receipt = _receipt(
            _calendar(1),
            cohort_id="cohort-1",
            slot_index=0,
            tape_file_id="tape-1",
            tape_record_index=1,
            source_role="history",
            connection_generation="generation-1",
            feed_sequence=1,
        )
        with pytest.raises(
            ExecutionDecisionJournalError, match="DURABLE_BASE_RECORDS_EXHAUSTED"
        ):
            _record_source(journal, receipt)
        assert journal.decision_for_key(
            ExecutionDecisionKey(
                _ACCOUNT,
                _STRATEGY,
                _RUN,
                receipt.cohort_id,
                receipt.close_time,
                _SOURCE_KIND,
            )
        ) is None
        assert _highwater(journal) is None
        usage = _durable_usage(journal._connection)
        assert {row[0]: row[1] for row in usage} == {"BASE": 0, "SETTLEMENT": 0}
    finally:
        journal.close()


def test_source_receipt_enforces_member_and_serialized_byte_limits(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "bounded-source-receipt.sqlite3")
    try:
        base = _receipt(
            _calendar(1),
            cohort_id="cohort-1",
            slot_index=0,
            tape_file_id="tape-1",
            tape_record_index=1,
            source_role="history",
            connection_generation="generation-1",
            feed_sequence=1,
        )
        too_many_members = tuple(
            replace(base.members[0], member_id="member-{:04d}".format(index))
            for index in range(513)
        )
        with pytest.raises(ExecutionDecisionJournalError, match="INVALID_SOURCE_RECEIPT"):
            replace(base, members=too_many_members)

        large_members = tuple(
            replace(
                base.members[0],
                member_id="member-{:04d}".format(index),
                source_ref="s" * 2048,
            )
            for index in range(512)
        )
        oversized = replace(base, members=large_members)
        with pytest.raises(ExecutionDecisionJournalError, match="SOURCE_RECEIPT_TOO_LARGE"):
            _record_source(journal, oversized)
        assert _highwater(journal) is None
    finally:
        journal.close()


@pytest.mark.parametrize("generation", (0, -1, True))
def test_source_member_rejects_nonpositive_integer_generation(generation):
    member = ExecutionSourceMemberReceipt(
        member_id=_MEMBER,
        source_ref=_SOURCE_REF,
        source_role="live",
        connection_generation="generation-1",
        feed_sequence=1,
        bar_id="generation-validation",
        bucket_start=_time(_BASE),
        close_time=_time(_BASE + timedelta(minutes=1)),
        available_at=_time(_BASE + timedelta(minutes=1)),
        trading_day="20261026",
        session_segment="morning",
        timezone_id="UTC",
        clock_domain_id="synthetic-ctp-clock",
        complete=True,
        quality="GOOD",
        present=True,
    )
    with pytest.raises(
        ExecutionDecisionJournalError, match="INVALID_SOURCE_RECEIPT_MEMBER"
    ):
        replace(member, connection_generation=generation)


def test_v13_schema_upgrade_adds_empty_source_highwater_and_preserves_usage(tmp_path):
    path = tmp_path / "schema-v13-source-upgrade.sqlite3"
    journal = ExecutionDecisionJournal(path)
    journal.record_decision(
        ExecutionDecisionKey(_ACCOUNT, _STRATEGY, _RUN, "cohort-old", _time(_BASE), "bar"),
        {"legacy": "synthetic"},
    )
    before = _durable_usage(journal._connection)
    journal.close()

    with sqlite3.connect(path) as connection:
        _drop_v17_workflow_tables(connection)
        connection.execute(
            "DROP TABLE execution_fee_pair_candidate_capacity_reservations"
        )
        connection.execute("DROP TABLE execution_fee_pair_candidate_events")
        connection.execute("DROP TABLE execution_fee_pair_candidates")
        connection.execute("DROP TABLE execution_fee_pair_scope_events")
        connection.execute("DROP TABLE execution_fee_pair_required_scopes")
        connection.execute("DROP TABLE execution_source_highwaters")
        connection.execute("PRAGMA user_version=13")

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert _durable_usage(migrated._connection) == before
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_source_highwaters"
        ).fetchone()[0] == 0
    finally:
        migrated.close()


def test_v14_to_v16_migration_preserves_existing_journal_rows(tmp_path):
    path = tmp_path / "schema-v14-pair-scope-upgrade.sqlite3"
    journal = ExecutionDecisionJournal(path)
    receipt = _receipt(
        _calendar(1),
        cohort_id="cohort-v14",
        slot_index=0,
        tape_file_id="tape-v14",
        tape_record_index=1,
        source_role="history",
        connection_generation="generation-v14",
        feed_sequence=1,
    )
    _record_source(journal, receipt)
    expected_decisions = tuple(
        tuple(row)
        for row in journal._connection.execute(
            "SELECT * FROM execution_decisions ORDER BY decision_id"
        )
    )
    expected_source_highwaters = tuple(
        tuple(row)
        for row in journal._connection.execute(
            "SELECT * FROM execution_source_highwaters ORDER BY account_scope,strategy_scope,"
            "logical_run_id,source_kind"
        )
    )
    expected_usage = _durable_usage(journal._connection)
    expected_highwater = _highwater(journal)
    journal.close()

    # Remove the v15/v16 additions and present the exact previous user_version.
    with sqlite3.connect(path) as connection:
        _drop_v17_workflow_tables(connection)
        connection.execute(
            "DROP TABLE execution_fee_pair_candidate_capacity_reservations"
        )
        connection.execute("DROP TABLE execution_fee_pair_candidate_events")
        connection.execute("DROP TABLE execution_fee_pair_candidates")
        connection.execute("DROP TABLE execution_fee_pair_scope_events")
        connection.execute("DROP TABLE execution_fee_pair_required_scopes")
        connection.execute("PRAGMA user_version=14")

    migrated = ExecutionDecisionJournal(path)
    try:
        assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert tuple(
            tuple(row)
            for row in migrated._connection.execute(
                "SELECT * FROM execution_decisions ORDER BY decision_id"
            )
        ) == expected_decisions
        assert tuple(
            tuple(row)
            for row in migrated._connection.execute(
                "SELECT * FROM execution_source_highwaters ORDER BY account_scope,strategy_scope,"
                "logical_run_id,source_kind"
            )
        ) == expected_source_highwaters
        assert _durable_usage(migrated._connection) == expected_usage
        assert _highwater(migrated) == expected_highwater
        assert migrated.fee_pair_required_scope(_ACCOUNT, _STRATEGY) is None
        assert migrated._connection.execute(
            "SELECT COUNT(*) FROM execution_fee_pair_scope_events"
        ).fetchone()[0] == 0
    finally:
        migrated.close()

    # Reopening an already migrated current journal is idempotent.
    reopened = ExecutionDecisionJournal(path)
    try:
        assert reopened._connection.execute("PRAGMA user_version").fetchone()[0] == 17
        assert tuple(
            tuple(row)
            for row in reopened._connection.execute(
                "SELECT * FROM execution_decisions ORDER BY decision_id"
            )
        ) == expected_decisions
        assert tuple(
            tuple(row)
            for row in reopened._connection.execute(
                "SELECT * FROM execution_source_highwaters ORDER BY account_scope,strategy_scope,"
                "logical_run_id,source_kind"
            )
        ) == expected_source_highwaters
        assert _durable_usage(reopened._connection) == expected_usage
    finally:
        reopened.close()


def test_registered_pair_scope_blocks_grid_and_source_only_advances_across_batches(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "pair-scope-source-fence.sqlite3")
    try:
        registered = journal.register_fee_pair_required_scope(_ACCOUNT, _STRATEGY)
        assert registered.state == "REQUIRE_PAIR_FAIL_CLOSED"
        assert journal.fee_pair_required_scope(_ACCOUNT, _STRATEGY) == registered

        calendar = _calendar(1)
        receipt = _receipt(
            calendar,
            cohort_id="cohort-next",
            slot_index=0,
            tape_file_id="tape-next",
            tape_record_index=1,
            source_role="live",
            connection_generation="generation-next",
            feed_sequence=1,
        )
        changed_batch_key = ExecutionDecisionKey(
            account_scope=_ACCOUNT,
            strategy_scope=_STRATEGY,
            logical_run_id="different-run",
            cohort_id="cohort-next",
            close_time=receipt.close_time,
            decision_kind=_SOURCE_KIND,
        )
        before_decisions = journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0]
        before_usage = _durable_usage(journal._connection)

        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"
        ):
            journal.record_grid_decision(
                changed_batch_key,
                {"signal": "synthetic-source"},
                epoch_id=str(receipt.epoch_id),
                batch_id=receipt.batch_id,
                eligible=False,
                complete=True,
                live_ready=True,
                inputs_complete=True,
                source_receipt=receipt,
            )
        assert journal._connection.execute(
            "SELECT COUNT(*) FROM execution_decisions"
        ).fetchone()[0] == before_decisions
        assert journal.source_highwater(_ACCOUNT, _STRATEGY, "different-run", _SOURCE_KIND) is None
        assert _durable_usage(journal._connection) == before_usage

        # The old eligible-grid API is fenced at stable account/strategy scope,
        # even when the request contains no OPEN intents and changes run/cohort.
        with pytest.raises(
            ExecutionDecisionJournalError, match="FEE_PAIR_SCOPE_FAIL_CLOSED"
        ):
            journal.record_grid_decision(
                changed_batch_key,
                {"signal": "synthetic-flat"},
                epoch_id=str(receipt.epoch_id),
                batch_id=receipt.batch_id,
                eligible=True,
                complete=True,
                live_ready=True,
                inputs_complete=True,
            )

        # Scope registration does not silently affect a different account or
        # strategy; their source receipt path remains usable.
        other_scope_key = ExecutionDecisionKey(
            account_scope="unregistered-account",
            strategy_scope=_STRATEGY,
            logical_run_id="different-run",
            cohort_id="cohort-next",
            close_time=receipt.close_time,
            decision_kind=_SOURCE_KIND,
        )
        other = journal.record_grid_decision(
            other_scope_key,
            {"signal": "synthetic-source"},
            epoch_id=str(receipt.epoch_id),
            batch_id=receipt.batch_id,
            eligible=False,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            source_receipt=receipt,
        )
        assert other.eligible is False
        assert journal.source_highwater(
            "unregistered-account", _STRATEGY, "different-run", _SOURCE_KIND
        ) is not None
    finally:
        journal.close()


@pytest.mark.parametrize(
    "version,missing_table,expected_code",
    (
        (12, "execution_callback_query_dispositions", "CALLBACK_DELIVERY_SCHEMA_CORRUPT"),
        (13, "execution_run_loss_guards", "RUN_LOSS_GUARD_SCHEMA_CORRUPT"),
    ),
)
def test_upgrade_rejects_missing_required_previous_schema_table(
    tmp_path, version, missing_table, expected_code
):
    path = tmp_path / "missing-v{}-table.sqlite3".format(version)
    journal = ExecutionDecisionJournal(path)
    journal.close()
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE {}".format(missing_table))
        connection.execute("DROP TABLE execution_source_highwaters")
        if version == 12:
            connection.execute("DROP TABLE execution_run_loss_guards")
        connection.execute("PRAGMA user_version={}".format(version))

    with pytest.raises(ExecutionDecisionJournalError, match=expected_code):
        ExecutionDecisionJournal(path)


def test_source_highwater_archive_preserves_exact_anchor(tmp_path):
    path = tmp_path / "source-archive.sqlite3"
    archive_path = tmp_path / "source-archive-snapshot.sqlite3"
    journal = ExecutionDecisionJournal(path)
    try:
        receipt = _receipt(
            _calendar(1),
            cohort_id="cohort-1",
            slot_index=0,
            tape_file_id="tape-1",
            tape_record_index=1,
            source_role="history",
            connection_generation="generation-1",
            feed_sequence=1,
        )
        _record_source(journal, receipt)
        expected_row = tuple(
            journal._connection.execute(
                "SELECT * FROM execution_source_highwaters"
            ).fetchone()
        )
        archive_receipt = journal.archive_snapshot(archive_path)
        verified = archive_module.verify_execution_journal_archive(
            archive_path,
            expected_schema_version=ExecutionDecisionJournal._SCHEMA_VERSION,
            expected_sha256=archive_receipt.sha256,
        )
        assert verified == archive_receipt
        assert archive_receipt.schema_version == 17
        assert archive_receipt.table_row_counts["execution_source_highwaters"] == 1
    finally:
        journal.close()

    archived = sqlite3.connect(archive_path.as_uri() + "?mode=ro", uri=True)
    try:
        archived.execute("PRAGMA query_only=ON")
        actual_row = tuple(
            archived.execute("SELECT * FROM execution_source_highwaters").fetchone()
        )
        assert actual_row == expected_row
    finally:
        archived.close()


def test_current_schema_rejects_source_highwater_table_without_composite_primary_key(
    tmp_path,
):
    path = tmp_path / "source-highwater-no-primary-key.sqlite3"
    journal = ExecutionDecisionJournal(path)
    journal.close()
    with sqlite3.connect(path) as connection:
        _drop_v17_workflow_tables(connection)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DROP TABLE execution_source_highwaters")
        connection.execute(
            """CREATE TABLE execution_source_highwaters (
                account_scope TEXT NOT NULL,
                strategy_scope TEXT NOT NULL,
                logical_run_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                decision_id TEXT NOT NULL,
                anchor_kind TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                updated_at_ns INTEGER NOT NULL
            )"""
        )
        connection.execute("PRAGMA user_version=16")

    with pytest.raises(
        ExecutionDecisionJournalError, match="SOURCE_HIGHWATER_SCHEMA_CORRUPT"
    ):
        ExecutionDecisionJournal(path)
