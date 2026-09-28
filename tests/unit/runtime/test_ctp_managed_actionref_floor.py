"""Offline contracts for the account-wide CTP ActionRef admission snapshot."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backtrader_runtime import ctp_managed_actionref_floor as actionref_floor


NOW = 1_800_000_000_000_000_000
ACCOUNT = "account:" + "a" * 64
OTHER_ACCOUNT = "account:" + "b" * 64
SCOPE = "scope:" + "c" * 64
ACTION = "action.cancel.1"
COMMAND = "command.cancel.1"


def _row(
    *,
    action_ref: int = 17,
    command_id: str = COMMAND,
    scope_key: str = SCOPE,
    managed_action_id: str = ACTION,
    status: str = "READY",
    account_key: str = ACCOUNT,
) -> actionref_floor.CtpManagedActionRefAllocationV1:
    return actionref_floor.CtpManagedActionRefAllocationV1(
        account_key=account_key,
        native_action_ref=action_ref,
        command_id=command_id,
        scope_key=scope_key,
        managed_action_id=managed_action_id,
        status=status,
    )


def _snapshot(
    rows: tuple,
    *,
    counter: int | None = None,
    observed_native_high_water: int = 16,
    unresolved_unknown_count: int = 0,
    observed_at_ns: int = NOW - 1_000_000,
    sources: tuple = ("g5", "v21"),
) -> actionref_floor.CtpManagedActionRefLedgerSnapshotV1:
    return actionref_floor.CtpManagedActionRefLedgerSnapshotV1(
        account_key=ACCOUNT,
        cutover_id="cutover.account.20260928",
        cutover_floor=12,
        observed_native_high_water=observed_native_high_water,
        counter_high_water=max((row.native_action_ref for row in rows), default=12)
        if counter is None
        else counter,
        ledger_epoch=8,
        ledger_sources=sources,
        allocations=rows,
        unresolved_unknown_count=unresolved_unknown_count,
        observed_at_ns=observed_at_ns,
        valid_until_ns=NOW + 1_000_000_000,
        native_floor_source_digest_sha256="d" * 64,
        merged_ledger_source_digest_sha256="e" * 64,
        mapping_sha256=actionref_floor.ctp_managed_action_ref_mapping_sha256(rows),
    )


def _require(snapshot, *, action_ref: int = 17, command_id: str = COMMAND) -> None:
    snapshot.require_current_cancel(
        now_ns=NOW,
        account_key=ACCOUNT,
        command_id=command_id,
        scope_key=SCOPE,
        managed_action_id=ACTION,
        native_action_ref=action_ref,
        expected_status="READY",
    )


def test_account_wide_snapshot_checks_merged_map_counter_floor_and_current_cancel():
    prior = _row(
        action_ref=16,
        command_id="command.cancel.prior",
        managed_action_id="action.cancel.prior",
        status="COMPLETED",
    )
    current = _row(action_ref=17)
    snapshot = _snapshot((current, prior), counter=17)

    _require(snapshot)

    assert snapshot.ledger_sources == ("g5", "v21")
    assert snapshot.fresh_until_ns == NOW + 249_000_000
    assert len(snapshot.digest) == 64


@pytest.mark.parametrize(
    ("rows", "counter", "native_high_water", "unknown_count", "code"),
    [
        (
            (_row(action_ref=17), _row(action_ref=17, command_id="command.other")),
            17,
            16,
            0,
            "account_action_mapping_conflict",
        ),
        ((_row(action_ref=17, status="UNKNOWN"),), 17, 16, 1, "account_unknown_actions_present"),
        ((_row(action_ref=17),), 18, 16, 0, "account_counter_mapping_mismatch"),
        ((_row(action_ref=17),), 17, 18, 0, "counter_below_native_floor"),
    ],
)
def test_account_conflict_unknown_or_floor_mismatch_fails_closed(
    rows, counter, native_high_water, unknown_count, code
):
    snapshot = _snapshot(
        rows,
        counter=counter,
        observed_native_high_water=native_high_water,
        unresolved_unknown_count=unknown_count,
    )

    with pytest.raises(actionref_floor.CtpManagedActionRefLedgerError) as error:
        _require(snapshot)

    assert error.value.code == code


def test_stale_or_expired_snapshot_does_not_authorize_cancel():
    stale = _snapshot((_row(),), observed_at_ns=NOW - 251_000_000)
    expired = replace(stale, observed_at_ns=NOW - 10, valid_until_ns=NOW)

    for snapshot in (stale, expired):
        with pytest.raises(actionref_floor.CtpManagedActionRefLedgerError) as error:
            _require(snapshot)
        assert error.value.code == "snapshot_stale"


def test_action_mapping_must_be_account_local_and_match_exact_current_target():
    wrong_account = _snapshot((_row(account_key=OTHER_ACCOUNT),))
    with pytest.raises(actionref_floor.CtpManagedActionRefLedgerError) as error:
        _require(wrong_account)
    assert error.value.code == "allocation_account_mismatch"

    missing = _snapshot((_row(command_id="command.other"),))
    with pytest.raises(actionref_floor.CtpManagedActionRefLedgerError) as error:
        _require(missing)
    assert error.value.code == "current_action_mapping_missing_or_duplicate"

    wrong_target = _snapshot((_row(managed_action_id="action.other"),))
    with pytest.raises(actionref_floor.CtpManagedActionRefLedgerError) as error:
        _require(wrong_target)
    assert error.value.code == "current_action_mapping_mismatch"


def test_current_ref_must_be_above_trusted_native_high_water():
    snapshot = _snapshot((_row(action_ref=17),), observed_native_high_water=17)

    with pytest.raises(actionref_floor.CtpManagedActionRefLedgerError) as error:
        _require(snapshot)

    assert error.value.code == "current_action_ref_not_above_native_floor"


def test_incomplete_ledger_sources_and_tampered_mapping_digest_are_rejected():
    with pytest.raises(actionref_floor.CtpManagedActionRefLedgerError) as error:
        _snapshot((_row(),), sources=("v21",))
    assert error.value.code == "snapshot_sources_incomplete"

    snapshot = _snapshot((_row(),))
    with pytest.raises(actionref_floor.CtpManagedActionRefLedgerError) as error:
        replace(snapshot, mapping_sha256="f" * 64)
    assert error.value.code == "snapshot_mapping_digest_mismatch"
