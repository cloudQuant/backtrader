"""Source-only composition of the 028 tape with the v17 fee-pair Journal API."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from backtrader.stores import execution_decision_journal as journal_api
from tests.integration import test_alpha003_decision_tape_capacity as capacity
from tests.integration import test_factor_decision_replay_economics as economics


_RUNNER = capacity._RUNNER
_TARGETS = capacity._TARGETS
_THREE_TARGETS = ("rb", "i", "cu")
_TEST_ROUTES = {**economics.ROUTES, "cu": ("cu2610", "SHFE")}
_CALENDAR_FINGERPRINT = "c" * 64
_ACCOUNT_SCOPE = "source-only-account"
_STRATEGY_SCOPE = "source-only-strategy"
_RUN_ID = "alpha003-source-only-run"
_SOURCE_KIND = "ALPHA003_GRID"
_OWNER_TOKEN = "source-only-owner-" + "x" * 40
_SELECTION_SOURCES = (
    "saved_bundle_legacy",
    "ctp_query_snapshot_equal_weight_v1",
)


def _test_route(target):
    return _TEST_ROUTES.get(target, ("synthetic-" + target, "SYNTH"))


class _Manifest:
    def __init__(self):
        self._row = {
            "schema": "synthetic.alpha003.selection_manifest.v1",
            "selection_id": "source-only-selection",
        }
        self.manifest_sha256 = hashlib.sha256(
            _RUNNER._canonical_json_bytes(self._row).rstrip(b"\n")
        ).hexdigest()

    def to_dict(self):
        return dict(self._row)


def _selection_binding(selection_source, *, targets=_TARGETS):
    targets = tuple(targets)
    manifest = _Manifest()
    product_by_target = {target: target for target in targets}
    routes = {target: _test_route(target)[0] for target in targets}
    plan = {
        "selection_source": selection_source,
        "selection_path": "synthetic://" + selection_source,
        "source_snapshot_id": "source-only-synthetic-snapshot",
        "manifest": manifest,
        "targets": targets,
        "authorized_targets": targets,
        "product_by_target": product_by_target,
        "routes": routes,
    }
    if selection_source == "ctp_query_snapshot_equal_weight_v1":
        plan["grid"] = SimpleNamespace(
            to_dict=lambda: {
                "schema": "synthetic.alpha003.grid.v1",
                "status": "READY",
                "decision_at": "2026-10-24T00:00:00Z",
                "target_products": [],
                "product_trading_days": [],
                "calendar_hashes": [],
                "minutes": [],
            }
        )
    evidence = _RUNNER._selection_evidence(plan, 1, max_bytes=1_000_000)
    identity = {
        "schema": "backtrader.alpha003.live_restart_identity.v1",
        "epoch_id": 1,
        "mode": "live",
        "factor_mode": "native",
        "direction": 1,
        "scope_sha256": {
            "account_scope": hashlib.sha256(_ACCOUNT_SCOPE.encode("utf-8")).hexdigest(),
            "strategy_scope": hashlib.sha256(_STRATEGY_SCOPE.encode("utf-8")).hexdigest(),
            "logical_run_id": hashlib.sha256(_RUN_ID.encode("utf-8")).hexdigest(),
        },
        "selection_source": selection_source,
        "source_snapshot_id": plan["source_snapshot_id"],
        "targets": sorted(targets),
        "authorized_targets": sorted(targets),
        "routes": {target: routes[target] for target in sorted(targets)},
        "calendar": {"calendar_id": "alpha003-calendar-v1", "grid_sha256": "a" * 64},
    }
    return evidence, identity


def _with_origin_partitions(batch, *, slot_index=0):
    slot_id = "slot-{:04d}".format(slot_index)
    members = {}
    for member_id, receipt in batch.members.items():
        envelope = receipt.envelope
        partition = MappingProxyType(
            {
                "schema": _RUNNER.SOURCE_ORIGIN_PARTITION_SCHEMA,
                "cohort_id": envelope.cohort_id,
                "epoch_id": envelope.epoch_id,
                "member_id": member_id,
                "source_ref": envelope.source_ref,
                "source_role": envelope.source_role,
                "connection_generation": envelope.connection_generation,
            }
        )
        members[member_id] = replace(
            receipt,
            slot_index=slot_index,
            envelope=replace(
                envelope,
                slot_index=slot_index,
                slot_id=slot_id,
                origin_partition=partition,
            ),
        )
    return replace(batch, slot_index=slot_index, members=members)


def _writer(path: Path, *, selection_source: str, targets=_TARGETS):
    targets = tuple(targets)
    selection_evidence, restart_identity = _selection_binding(selection_source, targets=targets)
    return _RUNNER.DecisionTapeWriter(
        path,
        1_000_000,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=targets,
        calendar_id="alpha003-calendar-v1",
        grid_sha256="a" * 64,
        source_snapshot_id="source-only-synthetic-snapshot",
        calendar_fingerprint=_CALENDAR_FINGERPRINT,
        restart_identity=restart_identity,
        selection_evidence=selection_evidence,
    )


def _fixture(
    tmp_path,
    *,
    filename="source-only.jsonl",
    selection_source="saved_bundle_legacy",
):
    # The first durable source anchor has no predecessor; Journal v17
    # requires the initial grid slot and tape row to both start at zero/one.
    slot_index = 0
    cohort_id = "cohort-one"
    calendar_id = "alpha003-calendar-v1"
    calendar_version = "rules-v1"
    batch_id = "{}:{}:{}:{}:{}".format(cohort_id, calendar_id, 1, calendar_version, slot_index)
    target_decision = economics._target_decision(
        mode="native",
        cohort_id=cohort_id,
        batch_id=batch_id,
        close=economics.CLOSE,
        epoch=1,
    )
    batch, snapshot = capacity._complete_batch_snapshot(target_decision)
    batch = _with_origin_partitions(batch)
    writer = _writer(tmp_path / filename, selection_source=selection_source)
    row = _RUNNER._decision_tape_record(
        batch,
        snapshot,
        target_decision,
        None,
        file_id=writer.file_id,
        index=writer.summary()["record_count"] + 1,
        targets=writer.targets,
        calendar_fingerprint=writer.calendar_fingerprint,
    )
    source_members = _RUNNER._fee_pair_source_members_from_tape_row(row, journal_api)
    key = journal_api.ExecutionDecisionKey(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_STRATEGY_SCOPE,
        logical_run_id=_RUN_ID,
        cohort_id=cohort_id,
        close_time=target_decision.close_time.isoformat().replace("+00:00", "Z"),
        decision_kind=_SOURCE_KIND,
    )
    candidate = journal_api.ExecutionFeePairCandidate(
        key=key,
        source_kind=_SOURCE_KIND,
        calendar_id=calendar_id,
        calendar_version=calendar_version,
        calendar_fingerprint=_CALENDAR_FINGERPRINT,
        epoch_id=1,
        slot_index=slot_index,
        slot_id=row["slot_id"],
        batch_id=batch_id,
        readiness="LIVE_READY",
        expected_tape_file_id=writer.file_id,
        expected_tape_record_index=writer.summary()["record_count"] + 1,
        source_candidate_sha256="d" * 64,
        source_predecessor_sha256=None,
        source_predecessor=None,
        source_restart_marker=None,
        source_members=source_members,
        signal_sha256="e" * 64,
        factor_snapshot_sha256="f" * 64,
        target_ids=("rb", "i"),
        directions=(1, -1),
        quote_identity_sha256s=("1" * 64, "2" * 64),
        account_session_id="synthetic-session",
        account_session_generation="synthetic-generation-1",
    )
    journal = journal_api.ExecutionDecisionJournal(tmp_path / "journal.sqlite3")
    journal.register_fee_pair_required_scope(_ACCOUNT_SCOPE, _STRATEGY_SCOPE)
    return writer, journal, candidate, batch, snapshot, target_decision


def _multi_target_decision(targets):
    targets = tuple(targets)
    assert targets[:2] == ("rb", "i")
    close = economics.CLOSE
    available = close + economics.timedelta(seconds=2)
    batch_id = "cohort-one:alpha003-calendar-v1:1:rules-v1:0"
    cohort = economics._STRATEGY.CohortBatchFacts(
        status="COMPLETE",
        batch_id=batch_id,
        cohort_id="cohort-one",
        calendar_id="alpha003-calendar-v1",
        epoch_id=1,
        close_time=close,
        available_at=available,
    )
    points = []
    for index, target in enumerate(targets):
        if target == "rb":
            product_key, value = ("SHFE", "rb"), 1.25
        elif target == "i":
            product_key, value = ("DCE", "i"), -0.75
        else:
            product_key = ("SHFE", "cu") if target == "cu" else ("SYNTH", "p{:03d}".format(index))
            value = 0.1 + (index % 5) * 0.1
        points.append(
            economics._STRATEGY.FactorPoint(
                target_id=target,
                product_key=product_key,
                value=value,
                status="OUTPUT_AVAILABLE",
                present=True,
                complete=True,
                quality="GOOD",
            )
        )
    factor = economics._STRATEGY.FactorSnapshotFacts(
        readiness="LIVE_READY",
        batch_complete=True,
        batch_id=batch_id,
        cohort_id="cohort-one",
        calendar_id="alpha003-calendar-v1",
        epoch_id=1,
        close_time=close,
        available_at=available,
        factor_name="alpha003",
        mode="native",
        direction=1,
        source_sha256="a" * 64,
        points=tuple(points),
    )
    return economics._STRATEGY.select_alpha003_targets(
        economics._STRATEGY.Alpha003PolicyInput(
            cohort=cohort,
            factor=factor,
            required_targets=targets,
            authorized_targets=frozenset(targets),
            eligible_grid_index=5,
            rebalance_every=5,
            execution_mode="LIVE",
        )
    )


def _three_target_decision():
    return _multi_target_decision(_THREE_TARGETS)


def _multi_target_fixture(tmp_path, *, targets, filename):
    targets = tuple(targets)
    target_decision = _multi_target_decision(targets)
    assert tuple((item.target_id, item.target_position) for item in target_decision.targets) == (
        ("rb", 1),
        ("i", -1),
    )
    batch, snapshot = capacity._complete_batch_snapshot(target_decision)
    base_receipt = batch.members["rb"]
    members = dict(batch.members)
    batch = replace(
        batch,
        members=MappingProxyType(members),
    )
    factor_result = snapshot.factors["alpha003"]
    factor_values = dict(factor_result.values)
    for sequence, target in enumerate(targets[2:], start=3):
        route = _test_route(target)
        source_ref = "capacity-source-" + target
        feed = object()
        envelope = replace(
            base_receipt.envelope,
            member_id=target,
            feed_ref=feed,
            instrument=route[0],
            source_ref=source_ref,
            feed_sequence=sequence,
            bar_id="capacity-bar-" + target,
        )
        members[target] = replace(
            base_receipt,
            member_id=target,
            feed_ref=feed,
            source_ref=source_ref,
            envelope=envelope,
            feed_sequence=sequence,
        )
        value = 0.1 + (sequence % 5) * 0.1
        factor_values[target] = capacity.LiveFactorOutput(
            value=value,
            status=capacity.LiveFactorOutputStatus.OUTPUT_AVAILABLE,
            reason=None,
            present=True,
            complete=True,
            quality="GOOD",
            source_role="live",
            member_id=target,
            source_ref=source_ref,
            sequence=sequence,
            generation=1,
        )
    batch = replace(batch, members=MappingProxyType(members))
    snapshot = replace(
        snapshot,
        factors=MappingProxyType(
            {
                "alpha003": replace(
                    factor_result,
                    values=MappingProxyType(factor_values),
                )
            }
        ),
    )
    batch = _with_origin_partitions(batch)
    writer = _writer(
        tmp_path / filename,
        selection_source="saved_bundle_legacy",
        targets=targets,
    )
    row = _RUNNER._decision_tape_record(
        batch,
        snapshot,
        target_decision,
        None,
        file_id=writer.file_id,
        index=1,
        targets=writer.targets,
        calendar_fingerprint=writer.calendar_fingerprint,
    )
    source_members = _RUNNER._fee_pair_source_members_from_tape_row(row, journal_api)
    key = journal_api.ExecutionDecisionKey(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_STRATEGY_SCOPE,
        logical_run_id=_RUN_ID,
        cohort_id=target_decision.cohort_id,
        close_time=target_decision.close_time.isoformat().replace("+00:00", "Z"),
        decision_kind=_SOURCE_KIND,
    )
    pair = tuple(item.target_id for item in target_decision.targets)
    candidate = journal_api.ExecutionFeePairCandidate(
        key=key,
        source_kind=_SOURCE_KIND,
        calendar_id=batch.calendar_id,
        calendar_version=batch.calendar_version,
        calendar_fingerprint=_CALENDAR_FINGERPRINT,
        epoch_id=batch.epoch_id,
        slot_index=batch.slot_index,
        slot_id=row["slot_id"],
        batch_id=batch.batch_id,
        readiness="LIVE_READY",
        expected_tape_file_id=writer.file_id,
        expected_tape_record_index=1,
        source_candidate_sha256="d" * 64,
        source_predecessor_sha256=None,
        source_predecessor=None,
        source_restart_marker=None,
        source_members=source_members,
        signal_sha256="e" * 64,
        factor_snapshot_sha256="f" * 64,
        target_ids=pair,
        directions=tuple(item.target_position for item in target_decision.targets),
        quote_identity_sha256s=("1" * 64, "2" * 64),
        account_session_id="synthetic-session",
        account_session_generation="synthetic-generation-1",
    )
    journal = journal_api.ExecutionDecisionJournal(tmp_path / (filename + ".sqlite3"))
    journal.register_fee_pair_required_scope(_ACCOUNT_SCOPE, _STRATEGY_SCOPE)
    return writer, journal, candidate, batch, snapshot, target_decision


def _three_target_fixture(tmp_path, *, filename="three-target.jsonl"):
    return _multi_target_fixture(
        tmp_path,
        targets=_THREE_TARGETS,
        filename=filename,
    )


def _close(writer, journal):
    try:
        if not writer.summary()["closed"]:
            writer.close()
    except _RUNNER.RunnerError:
        pass
    journal.close()


@pytest.mark.integration
@pytest.mark.parametrize("selection_source", _SELECTION_SOURCES)
def test_v17_candidate_is_appended_once_and_receipt_comes_from_strict_reread(
    tmp_path, monkeypatch, selection_source
):
    writer, journal, candidate, batch, snapshot, target_decision = _fixture(
        tmp_path,
        filename=selection_source + ".jsonl",
        selection_source=selection_source,
    )
    strict_reader = _RUNNER.iter_decision_tape
    strict_readbacks = []

    def capture_strict_reader(path, **kwargs):
        summary = {"row_count": 0, "last": None}
        strict_readbacks.append(summary)

        def stream():
            for row in strict_reader(path, **kwargs):
                summary["row_count"] += 1
                summary["last"] = row
                yield row

        return stream()

    monkeypatch.setattr(_RUNNER, "iter_decision_tape", capture_strict_reader)
    try:
        result = writer.record_fee_pair_source_only(
            candidate,
            batch,
            snapshot,
            target_decision,
            journal,
            owner_token=_OWNER_TOKEN,
            ttl_seconds=10,
        )
        monkeypatch.setattr(_RUNNER, "iter_decision_tape", strict_reader)

        row = None
        for row in _RUNNER.iter_decision_tape(writer.path, max_bytes=writer.max_bytes):
            pass
        receipt = result["source_receipt"]
        workflow = journal.fee_pair_workflow_candidate(result["candidate_id"])
        highwater = journal.source_highwater(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, _RUN_ID, _SOURCE_KIND)
        decision = result["decision"]

        assert len(strict_readbacks) == 2
        assert strict_readbacks[0]["row_count"] == 1
        assert strict_readbacks[-1]["row_count"] == 2
        assert strict_readbacks[-1]["last"] == row
        assert result["candidate_sha256"] == workflow.candidate_sha256
        assert row["fee_pair_workflow"] == {
            "candidate_id": result["candidate_id"],
            "candidate_sha256": result["candidate_sha256"],
        }
        assert row["file_id"] == receipt.tape_file_id == writer.file_id
        assert row["record_id"] == receipt.tape_record_id
        assert row["record_index"] == receipt.tape_record_index == 1
        header = next(iter(_RUNNER.iter_decision_tape(writer.path, max_bytes=writer.max_bytes)))
        assert row["header_record_id"] == header["record_id"]
        assert row["selection_evidence_sha256"] == header["selection_evidence"]["binding_sha256"]
        assert row["selection_evidence_sha256"] == writer._selection_evidence_sha256
        assert (
            receipt.cohort_id,
            receipt.calendar_id,
            receipt.calendar_version,
            receipt.calendar_fingerprint,
            receipt.epoch_id,
            receipt.slot_index,
            receipt.slot_id,
            receipt.close_time,
            receipt.batch_id,
            receipt.readiness,
        ) == tuple(
            row[name]
            for name in (
                "cohort_id",
                "calendar_id",
                "calendar_version",
                "calendar_fingerprint",
                "epoch_id",
                "slot_index",
                "slot_id",
                "close_time",
                "batch_id",
                "readiness",
            )
        )
        assert receipt.members == candidate.source_members
        assert receipt == highwater.receipt
        assert highwater.anchor_kind == "SOURCE_ONLY"
        assert workflow.state == "SOURCE_ONLY"
        assert workflow.source_only_decision_id == decision.decision_id
        assert decision.key == candidate.key
        assert decision.is_noop and decision.intent_keys == ()
        assert decision.economic_payload["_execution_source_anchor_only"] is True
        assert row["order_plan"] == {
            "status": "SOURCE_ONLY",
            "reason": "FEE_PAIR_NOT_AUTHORIZED",
            "decision_batch_id": batch.batch_id,
            "decision_available_at": _RUNNER._json_time(batch.available_at),
            "actions": [],
        }
        assert writer.summary()["record_count"] == 1
        assert writer.summary()["failed"] is False

        before = writer.path.read_bytes()
        with pytest.raises(_RUNNER.RunnerError) as duplicate:
            writer.record_fee_pair_source_only(
                candidate,
                batch,
                snapshot,
                target_decision,
                journal,
                owner_token=_OWNER_TOKEN,
                ttl_seconds=10,
            )
        assert duplicate.value.code == "FEE_PAIR_TAPE_SLOT_ALREADY_CONSUMED"
        assert writer.path.read_bytes() == before
        assert writer.summary()["record_count"] == 1
        assert (
            tuple(
                row[0]
                for row in journal._connection.execute(
                    """SELECT event_kind FROM execution_fee_pair_workflow_events
                   WHERE candidate_id=? ORDER BY event_sequence""",
                    (result["candidate_id"],),
                )
            )
            == ("RESERVED", "APPEND_CLAIMED", "RECEIPT_VERIFIED", "SOURCE_ONLY")
        )
    finally:
        _close(writer, journal)


@pytest.mark.integration
def test_three_target_tape_keeps_all_members_but_sources_only_selected_pair(tmp_path):
    writer, journal, candidate, batch, snapshot, target_decision = _three_target_fixture(tmp_path)
    try:
        result = writer.record_fee_pair_source_only(
            candidate,
            batch,
            snapshot,
            target_decision,
            journal,
            owner_token=_OWNER_TOKEN,
            ttl_seconds=10,
        )
        rows = tuple(_RUNNER.iter_decision_tape(writer.path, max_bytes=writer.max_bytes))
        row = rows[-1]
        receipt = result["source_receipt"]

        assert writer.targets == tuple(sorted(_THREE_TARGETS))
        assert set(row["members"]) == set(_THREE_TARGETS)
        assert tuple(item["target_id"] for item in row["target_decision"]["targets"]) == (
            "rb",
            "i",
        )
        assert candidate.target_ids == ("rb", "i")
        assert candidate.directions == (1, -1)
        assert len(candidate.quote_identity_sha256s) == 2
        assert tuple(member.member_id for member in receipt.members) == tuple(
            sorted(_THREE_TARGETS)
        )
        assert receipt.members == candidate.source_members
        assert row["order_plan"]["actions"] == []
        assert "fee_amount" not in row and "commission" not in row
        assert (
            journal.source_highwater(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, _RUN_ID, _SOURCE_KIND).receipt
            == receipt
        )
    finally:
        _close(writer, journal)


@pytest.mark.integration
@pytest.mark.parametrize(
    "invalid_projection",
    (
        "missing_pair_member",
        "unselected_cohort_member_pair",
        "wrong_candidate_direction",
        "duplicate_pair_rows",
    ),
)
def test_three_target_invalid_pair_projection_rejects_before_reservation(
    tmp_path, invalid_projection
):
    writer, journal, candidate, batch, snapshot, target_decision = _three_target_fixture(
        tmp_path,
        filename=invalid_projection + ".jsonl",
    )
    original_tape = writer.path.read_bytes()
    if invalid_projection == "missing_pair_member":
        candidate = replace(candidate, target_ids=("rb", "ghost"))
        expected_code = "FEE_PAIR_TAPE_PLAN_BINDING_MISMATCH"
    elif invalid_projection == "unselected_cohort_member_pair":
        # ``cu`` is a valid source member and writer target, but this GRID row
        # selected only rb/i. It must not be treated as a substitute pair leg.
        candidate = replace(candidate, target_ids=("rb", "cu"))
        expected_code = "FEE_PAIR_TAPE_CANDIDATE_PROJECTION_MISMATCH"
    elif invalid_projection == "wrong_candidate_direction":
        candidate = replace(candidate, directions=(-1, 1))
        expected_code = "FEE_PAIR_TAPE_CANDIDATE_PROJECTION_MISMATCH"
    else:
        target_decision = replace(
            target_decision,
            targets=(target_decision.targets[0], target_decision.targets[0]),
        )
        expected_code = "FEE_PAIR_TAPE_TARGET_PROJECTION_INVALID"
    try:
        with pytest.raises(_RUNNER.RunnerError) as rejected:
            writer.record_fee_pair_source_only(
                candidate,
                batch,
                snapshot,
                target_decision,
                journal,
                owner_token=_OWNER_TOKEN,
                ttl_seconds=10,
            )

        assert rejected.value.code == expected_code
        assert writer.path.read_bytes() == original_tape
        assert writer.summary()["record_count"] == 0
        assert writer.summary()["failed"] is False
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM execution_fee_pair_workflows"
            ).fetchone()[0]
            == 0
        )
        assert (
            journal.source_highwater(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, _RUN_ID, _SOURCE_KIND) is None
        )
    finally:
        _close(writer, journal)


@pytest.mark.integration
def test_fee_pair_candidate_rejects_duplicate_target_ids(tmp_path):
    writer, journal, candidate, batch, snapshot, target_decision = _three_target_fixture(
        tmp_path,
        filename="duplicate-candidate-pair.jsonl",
    )
    try:
        with pytest.raises(journal_api.ExecutionDecisionJournalError) as rejected:
            replace(candidate, target_ids=("rb", "rb"))
        assert rejected.value.code == "INVALID_FEE_PAIR_CANDIDATE"
        assert writer.summary()["record_count"] == 0
        assert (
            journal.source_highwater(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, _RUN_ID, _SOURCE_KIND) is None
        )
    finally:
        _close(writer, journal)


@pytest.mark.integration
def test_eighty_seven_target_candidate_reaches_source_only_terminal(tmp_path):
    targets = ("rb", "i") + tuple("synthetic-{:03d}".format(index) for index in range(85))
    writer, journal, candidate, batch, snapshot, target_decision = _multi_target_fixture(
        tmp_path,
        targets=targets,
        filename="eighty-seven-target.jsonl",
    )
    original_tape = writer.path.read_bytes()
    try:
        preappend_row = _RUNNER._decision_tape_record(
            batch,
            snapshot,
            target_decision,
            None,
            file_id=writer.file_id,
            index=1,
            targets=writer.targets,
            calendar_fingerprint=writer.calendar_fingerprint,
        )
        assert (
            len(
                _RUNNER._validate_fee_pair_candidate_projection(
                    None, preappend_row, journal_api, allow_missing_candidate=True
                )
            )
            == 87
        )
        result = writer.record_fee_pair_source_only(
            candidate,
            batch,
            snapshot,
            target_decision,
            journal,
            owner_token=_OWNER_TOKEN,
            ttl_seconds=10,
        )
        row = tuple(_RUNNER.iter_decision_tape(writer.path, max_bytes=writer.max_bytes))[-1]
        workflow = journal.fee_pair_workflow_candidate(result["candidate_id"])
        highwater = journal.source_highwater(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, _RUN_ID, _SOURCE_KIND)
        assert len(row["members"]) == len(targets) == 87
        assert candidate.target_ids == ("rb", "i")
        assert set(row["members"]) == set(targets)
        assert {item["target_id"] for item in row["target_decision"]["targets"]} == {
            "rb",
            "i",
        }
        assert len(candidate.quote_identity_sha256s) == 2
        assert len(result["source_receipt"].members) == 87
        assert result["source_receipt"] == highwater.receipt
        assert workflow.state == "SOURCE_ONLY"
        assert result["decision"].is_noop
        assert result["decision"].intent_keys == ()
        assert row["order_plan"]["actions"] == []
        assert writer.path.read_bytes() != original_tape
        assert writer.summary()["record_count"] == 1
        assert writer.summary()["failed"] is False
        assert (
            tuple(
                item[0]
                for item in journal._connection.execute(
                    """SELECT event_kind FROM execution_fee_pair_workflow_events
                   WHERE candidate_id=? ORDER BY event_sequence""",
                    (result["candidate_id"],),
                )
            )
            == ("RESERVED", "APPEND_CLAIMED", "RECEIPT_VERIFIED", "SOURCE_ONLY")
        )
    finally:
        _close(writer, journal)


@pytest.mark.integration
def test_v17_rehashed_candidate_extension_failure_keeps_claim_unresolved(tmp_path):
    writer, journal, candidate, batch, snapshot, target_decision = _fixture(
        tmp_path,
        filename="unresolved.jsonl",
        selection_source="ctp_query_snapshot_equal_weight_v1",
    )
    actual_append = writer._append

    def append_with_rehashed_candidate_mismatch(raw, *, count_record):
        if count_record:
            row = json.loads(raw.decode("utf-8"))
            row["fee_pair_workflow"]["candidate_sha256"] = "0" * 64
            row.pop("record_id")
            row["record_id"] = hashlib.sha256(
                _RUNNER._canonical_json_bytes(row).rstrip(b"\n")
            ).hexdigest()
            raw = _RUNNER._canonical_json_bytes(row)
        return actual_append(raw, count_record=count_record)

    writer._append = append_with_rehashed_candidate_mismatch
    try:
        with pytest.raises(_RUNNER.RunnerError) as rejected:
            writer.record_fee_pair_source_only(
                candidate,
                batch,
                snapshot,
                target_decision,
                journal,
                owner_token=_OWNER_TOKEN,
                ttl_seconds=10,
            )
        assert rejected.value.code == "FEE_PAIR_TAPE_EXTENSION_BINDING_MISMATCH"
        rows = tuple(_RUNNER.iter_decision_tape(writer.path, max_bytes=writer.max_bytes))
        assert len(rows) == 2
        assert rows[-1]["fee_pair_workflow"]["candidate_sha256"] == "0" * 64
        assert writer.summary()["record_count"] == 1
        assert writer.summary()["failed"] is True

        candidate_id = rows[-1]["fee_pair_workflow"]["candidate_id"]
        workflow = journal.fee_pair_workflow_candidate(candidate_id)
        assert workflow is not None
        assert workflow.state == "APPEND_CLAIMED"
        assert (
            journal.source_highwater(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, _RUN_ID, _SOURCE_KIND) is None
        )
        with pytest.raises(_RUNNER.RunnerError) as retry:
            writer.record_fee_pair_source_only(
                candidate,
                batch,
                snapshot,
                target_decision,
                journal,
                owner_token=_OWNER_TOKEN,
                ttl_seconds=10,
            )
        assert retry.value.code == "DECISION_TAPE_UNAVAILABLE"
        assert writer.summary()["record_count"] == 1
        assert len(tuple(_RUNNER.iter_decision_tape(writer.path, max_bytes=writer.max_bytes))) == 2
    finally:
        _close(writer, journal)


@pytest.mark.integration
def test_fee_pair_total_capacity_rejects_before_durable_claim(tmp_path, monkeypatch):
    writer, journal, candidate, batch, snapshot, target_decision = _fixture(
        tmp_path,
        filename="total-capacity.jsonl",
        selection_source="saved_bundle_legacy",
    )
    original_header = writer.path.read_bytes()
    monkeypatch.setattr(
        _RUNNER,
        "_FEE_PAIR_SOURCE_ONLY_MAX_TAPE_BYTES",
        len(original_header),
    )
    try:
        with pytest.raises(_RUNNER.RunnerError) as rejected:
            writer.record_fee_pair_source_only(
                candidate,
                batch,
                snapshot,
                target_decision,
                journal,
                owner_token=_OWNER_TOKEN,
                ttl_seconds=10,
            )
        assert rejected.value.code == "FEE_PAIR_TAPE_BYTE_LIMIT_EXCEEDED"
        assert writer.path.read_bytes() == original_header
        assert writer.summary()["record_count"] == 0
        assert writer.summary()["failed"] is False
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM execution_fee_pair_workflows"
            ).fetchone()[0]
            == 0
        )
        assert (
            journal.source_highwater(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, _RUN_ID, _SOURCE_KIND) is None
        )
    finally:
        _close(writer, journal)


@pytest.mark.integration
def test_fee_pair_oversized_candidate_row_rejects_before_durable_claim(tmp_path, monkeypatch):
    writer, journal, candidate, batch, snapshot, target_decision = _fixture(
        tmp_path,
        filename="record-capacity.jsonl",
        selection_source="saved_bundle_legacy",
    )
    original_tape = writer.path.read_bytes()
    # The cap must still admit the existing header during strict prefix
    # verification; it is intentionally lower than this synthetic candidate
    # row so rejection exercises the pre-reservation size projection.
    monkeypatch.setattr(
        _RUNNER,
        "_FEE_PAIR_SOURCE_ONLY_MAX_RECORD_BYTES",
        len(original_tape),
    )
    try:
        with pytest.raises(_RUNNER.RunnerError) as rejected:
            writer.record_fee_pair_source_only(
                candidate,
                batch,
                snapshot,
                target_decision,
                journal,
                owner_token=_OWNER_TOKEN,
                ttl_seconds=10,
            )

        assert rejected.value.code == "FEE_PAIR_TAPE_RECORD_BYTE_LIMIT_EXCEEDED"
        assert writer.path.read_bytes() == original_tape
        assert writer.summary()["record_count"] == 0
        assert writer.summary()["failed"] is False
        assert (
            journal._connection.execute(
                "SELECT COUNT(*) FROM execution_fee_pair_workflows"
            ).fetchone()[0]
            == 0
        )
        assert (
            journal.source_highwater(_ACCOUNT_SCOPE, _STRATEGY_SCOPE, _RUN_ID, _SOURCE_KIND) is None
        )
    finally:
        _close(writer, journal)


@pytest.mark.integration
def test_fee_pair_helper_preflight_keeps_default_v2_row_unchanged(tmp_path):
    target_decision = economics._target_decision(mode="native", batch_id="legacy-batch")
    batch, snapshot = capacity._complete_batch_snapshot(target_decision)
    batch = _with_origin_partitions(batch)
    writer = capacity._writer(
        tmp_path / "ordinary.jsonl",
        max_bytes=1_000_000,
        calendar_id=batch.calendar_id,
    )
    try:
        assert writer.record_decision(batch, snapshot, target_decision, None) is True
        rows = tuple(_RUNNER.iter_decision_tape(writer.path, max_bytes=writer.max_bytes))
        row = rows[-1]
        expected = _RUNNER._decision_tape_record(
            batch,
            snapshot,
            target_decision,
            None,
            file_id=writer.file_id,
            index=1,
            targets=writer.targets,
            calendar_fingerprint=writer.calendar_fingerprint,
        )
        expected["header_record_id"] = writer._header_record_id
        expected["record_id"] = hashlib.sha256(
            _RUNNER._canonical_json_bytes(expected).rstrip(b"\n")
        ).hexdigest()
        assert row["schema"] == _RUNNER.DECISION_TAPE_SCHEMA
        assert row["record_index"] == 1
        assert row["order_plan"] is None
        assert "fee_pair_workflow" not in row
        assert row["header_record_id"] == rows[0]["record_id"]
        assert "selection_evidence_sha256" not in row
        assert dict(row) == expected
        assert writer.path.read_bytes().splitlines(keepends=True)[
            1
        ] == _RUNNER._canonical_json_bytes(expected)
        assert writer.summary()["record_count"] == 1
    finally:
        if not writer.summary()["closed"]:
            writer.close()
