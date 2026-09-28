"""Local fake-only tests for restart-persistent ActionRef snapshot checkpoints."""

from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from backtrader_runtime.ctp_managed_actionref_floor import (
    CtpManagedActionRefAllocationV1,
    CtpManagedActionRefLedgerSnapshotV1,
    ctp_managed_action_ref_mapping_sha256,
)
from backtrader_runtime._local_fake_actionref_checkpoint_candidate import (
    CtpLocalActionRefCheckpointError,
    CtpLocalActionRefCheckpointSource,
)


ACCOUNT = "account:" + "a" * 64
SCOPE = "scope:" + "b" * 64
NOW = 1_800_000_000_000_000_000


class _FakeSnapshotSource:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def read_action_ref_ledger(self, _account_key):
        return self.snapshot


def _snapshot(*, epoch=8, cutover_id="cutover.20260928", observed_at_ns=NOW - 1_000_000):
    allocations = (
        CtpManagedActionRefAllocationV1(
            account_key=ACCOUNT,
            native_action_ref=17,
            command_id="command.cancel.17",
            scope_key=SCOPE,
            managed_action_id="action.cancel.17",
            status="READY",
        ),
    )
    return CtpManagedActionRefLedgerSnapshotV1(
        account_key=ACCOUNT,
        cutover_id=cutover_id,
        cutover_floor=12,
        observed_native_high_water=16,
        counter_high_water=17,
        ledger_epoch=epoch,
        ledger_sources=("g5", "v21"),
        allocations=allocations,
        unresolved_unknown_count=0,
        observed_at_ns=observed_at_ns,
        valid_until_ns=NOW + 1_000_000_000,
        native_floor_source_digest_sha256="c" * 64,
        merged_ledger_source_digest_sha256="d" * 64,
        mapping_sha256=ctp_managed_action_ref_mapping_sha256(allocations),
    )


def test_checkpoint_rejects_epoch_rollback_after_process_restart(tmp_path):
    checkpoint = tmp_path / "actionref-checkpoint.sqlite3"
    seed_script = r"""
import sys
from backtrader_runtime.ctp_managed_actionref_floor import (
    CtpManagedActionRefAllocationV1,
    CtpManagedActionRefLedgerSnapshotV1,
    ctp_managed_action_ref_mapping_sha256,
)
from backtrader_runtime._local_fake_actionref_checkpoint_candidate import (
    CtpLocalActionRefCheckpointSource,
)

account = "account:" + "a" * 64
rows = (CtpManagedActionRefAllocationV1(
    account_key=account,
    native_action_ref=17,
    command_id="command.cancel.17",
    scope_key="scope:" + "b" * 64,
    managed_action_id="action.cancel.17",
    status="READY",
),)
snapshot = CtpManagedActionRefLedgerSnapshotV1(
    account_key=account,
    cutover_id="cutover.20260928",
    cutover_floor=12,
    observed_native_high_water=16,
    counter_high_water=17,
    ledger_epoch=8,
    ledger_sources=("g5", "v21"),
    allocations=rows,
    unresolved_unknown_count=0,
    observed_at_ns=1_799_999_999_999_000_000,
    valid_until_ns=1_800_000_001_000_000_000,
    native_floor_source_digest_sha256="c" * 64,
    merged_ledger_source_digest_sha256="d" * 64,
    mapping_sha256=ctp_managed_action_ref_mapping_sha256(rows),
)
class Source:
    def read_action_ref_ledger(self, _account_key):
        return snapshot
CtpLocalActionRefCheckpointSource(
    source=Source(), database_path=sys.argv[1]
).read_action_ref_ledger(account)
"""
    subprocess.run(
        [sys.executable, "-c", seed_script, str(checkpoint)],
        cwd=Path(__file__).resolve().parents[3],
        check=True,
        capture_output=True,
        text=True,
    )

    restarted_source = _FakeSnapshotSource(_snapshot(epoch=7))
    restarted_consumer = CtpLocalActionRefCheckpointSource(
        source=restarted_source, database_path=checkpoint
    )
    with pytest.raises(CtpLocalActionRefCheckpointError) as error:
        restarted_consumer.read_action_ref_ledger(ACCOUNT)

    assert error.value.code == "snapshot_epoch_regressed"


def test_checkpoint_rejects_same_epoch_rewrite_and_cutover_replacement(tmp_path):
    checkpoint = tmp_path / "actionref-checkpoint.sqlite3"
    source = _FakeSnapshotSource(_snapshot(epoch=8))
    consumer = CtpLocalActionRefCheckpointSource(source=source, database_path=checkpoint)
    consumer.read_action_ref_ledger(ACCOUNT)

    source.snapshot = _snapshot(epoch=8, observed_at_ns=NOW - 2_000_000)
    with pytest.raises(CtpLocalActionRefCheckpointError) as error:
        consumer.read_action_ref_ledger(ACCOUNT)
    assert error.value.code == "snapshot_same_epoch_changed"

    source.snapshot = _snapshot(epoch=9, cutover_id="replacement-cutover")
    with pytest.raises(CtpLocalActionRefCheckpointError) as error:
        consumer.read_action_ref_ledger(ACCOUNT)
    assert error.value.code == "snapshot_cutover_changed_without_transition_proof"


def test_checkpoint_keeps_other_account_state_independent(tmp_path):
    checkpoint = tmp_path / "actionref-checkpoint.sqlite3"
    account_a = _FakeSnapshotSource(_snapshot(epoch=8))
    consumer_a = CtpLocalActionRefCheckpointSource(source=account_a, database_path=checkpoint)
    assert consumer_a.read_action_ref_ledger(ACCOUNT).ledger_epoch == 8

    other_account = "account:" + "e" * 64
    other_row = replace(_snapshot().allocations[0], account_key=other_account)
    other_snapshot = replace(
        _snapshot(),
        account_key=other_account,
        allocations=(other_row,),
        mapping_sha256=ctp_managed_action_ref_mapping_sha256((other_row,)),
    )
    consumer_b = CtpLocalActionRefCheckpointSource(
        source=_FakeSnapshotSource(other_snapshot), database_path=checkpoint
    )
    assert consumer_b.read_action_ref_ledger(other_account).ledger_epoch == 8
