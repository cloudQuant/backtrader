"""Offline contracts for the unregistered read-only guardian request journal."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import pytest

from backtrader_runtime import ctp_guardian_request_journal as journal_module
from backtrader_runtime.ctp_guardian_request_journal import (
    GUARDIAN_FIXED_OPERATION,
    GUARDIAN_REQUEST_BUDGET_NS,
    GUARDIAN_REQUEST_DATABASE_NAME,
    GUARDIAN_REQUEST_TRADING_CAPABILITIES,
    GUARDIAN_REQUEST_WRITE_AUTHORIZED,
    GuardianRequestJournal,
    GuardianRequestJournalError,
)


@pytest.fixture
def private_state_dir(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    if os.name == "nt":
        state_dir = Path(tempfile.mkdtemp(prefix="guardian-journal-", dir=str(Path.home())))
        request.addfinalizer(
            lambda: __import__("shutil").rmtree(str(state_dir), ignore_errors=True)
        )
        from backtrader_runtime.ctp_simnow_signed_review import _protect_windows_path_acl

        _protect_windows_path_acl(state_dir, is_directory=True)
    else:
        state_dir = tmp_path / "private-guardian-state"
        state_dir.mkdir()
        state_dir.chmod(0o700)
    return state_dir


def _accepted(
    journal: GuardianRequestJournal,
    request_id: str = "a" * 32,
    *,
    t0_ns: Optional[int] = None,
) -> None:
    if t0_ns is None:
        t0_ns = journal_module.time.monotonic_ns()
    accepted = journal.persist_accepted(
        request_id,
        service_t0_monotonic_ns=t0_ns,
        deadline_monotonic_ns=t0_ns + GUARDIAN_REQUEST_BUDGET_NS,
    )
    assert accepted is True


def test_acceptance_is_durable_and_read_back_before_service_can_start_worker(
    private_state_dir: Path,
) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    t0_ns = journal_module.time.monotonic_ns()

    assert (
        journal.persist_accepted(
            "a" * 32,
            service_t0_monotonic_ns=t0_ns,
            deadline_monotonic_ns=t0_ns + GUARDIAN_REQUEST_BUDGET_NS,
        )
        is True
    )

    record = journal.get_request("a" * 32)
    assert record is not None
    assert record.identity == "account-a"
    assert record.operation == GUARDIAN_FIXED_OPERATION == "ctp_readonly_preflight"
    assert record.state == "RUNNING"
    assert record.accepted_monotonic_ns == t0_ns
    assert record.deadline_monotonic_ns == t0_ns + GUARDIAN_REQUEST_BUDGET_NS
    assert journal.has_blocker() is True
    assert GUARDIAN_REQUEST_WRITE_AUTHORIZED is False
    assert GUARDIAN_REQUEST_TRADING_CAPABILITIES == ()


def test_duplicate_request_id_never_creates_a_second_acceptance(
    private_state_dir: Path,
) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    _accepted(journal)
    original = journal.get_request("a" * 32)

    with pytest.raises(GuardianRequestJournalError, match="guardian_request_id_duplicate"):
        _accepted(journal)

    assert journal.get_request("a" * 32) == original


def test_concurrent_duplicate_request_id_has_one_durable_acceptance(
    private_state_dir: Path,
) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    t0_ns = journal_module.time.monotonic_ns()
    barrier = threading.Barrier(2)

    def attempt() -> object:
        barrier.wait()
        try:
            return journal.persist_accepted(
                "a" * 32,
                service_t0_monotonic_ns=t0_ns,
                deadline_monotonic_ns=t0_ns + GUARDIAN_REQUEST_BUDGET_NS,
            )
        except GuardianRequestJournalError as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _index: attempt(), range(2)))

    assert sorted(results, key=str) == [True, "guardian_request_id_duplicate"]
    record = journal.get_request("a" * 32)
    assert record is not None and record.state == "RUNNING"


def test_acceptance_readback_failure_keeps_a_durable_blocker(
    private_state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    original_connect = sqlite3.connect
    connect_calls = [0]

    def fail_readback(*args: object, **kwargs: object) -> sqlite3.Connection:
        connect_calls[0] += 1
        if connect_calls[0] == 2:
            raise PermissionError("injected read-back failure")
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(journal_module.sqlite3, "connect", fail_readback)
    t0_ns = journal_module.time.monotonic_ns()
    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_unavailable"):
        journal.persist_accepted(
            "a" * 32,
            service_t0_monotonic_ns=t0_ns,
            deadline_monotonic_ns=t0_ns + GUARDIAN_REQUEST_BUDGET_NS,
        )
    monkeypatch.setattr(journal_module.sqlite3, "connect", original_connect)

    assert journal.has_blocker() is True
    journal.close()
    restarted = GuardianRequestJournal(private_state_dir, "account-a")
    record = restarted.get_request("a" * 32)
    assert record is not None and record.state == "UNKNOWN"


def test_restart_turns_in_flight_request_unknown_and_late_receipt_cannot_upgrade_it(
    private_state_dir: Path,
) -> None:
    first = GuardianRequestJournal(private_state_dir, "account-a")
    _accepted(first)
    first.close()

    restarted = GuardianRequestJournal(private_state_dir, "account-a")
    recovered = restarted.get_request("a" * 32)
    assert recovered is not None
    assert recovered.state == "UNKNOWN"
    assert recovered.terminal_reason == "restart_recovery"
    assert recovered.receipt_digest is not None
    assert len(recovered.receipt_digest) == 64
    assert restarted.has_blocker() is True

    with pytest.raises(GuardianRequestJournalError, match="guardian_request_unknown_terminal"):
        restarted.record_observed("a" * 32, hashlib.sha256(b"late").hexdigest())
    with pytest.raises(GuardianRequestJournalError, match="guardian_request_unknown_blocks"):
        _accepted(restarted, "b" * 32)
    assert restarted.get_request("a" * 32) == recovered


def test_explicit_timeout_and_late_completion_keep_unknown_terminal(
    private_state_dir: Path,
) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    _accepted(journal)

    unknown = journal.mark_unknown("a" * 32, "transport_uncertain")
    late_digest = hashlib.sha256(b"verified-looking-late-receipt").hexdigest()
    with pytest.raises(GuardianRequestJournalError, match="guardian_request_unknown_terminal"):
        journal.record_observed("a" * 32, late_digest)

    assert journal.get_request("a" * 32) == unknown
    assert unknown.state == "UNKNOWN"
    assert journal.has_blocker() is True


def test_deadline_expiry_persists_unknown_and_late_completion_is_rejected(
    private_state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    t0_ns = 10_000_000_000
    fake_now = [t0_ns + 1, t0_ns + 2]

    monkeypatch.setattr(journal_module.time, "monotonic_ns", lambda: fake_now[0])
    assert (
        journal.persist_accepted(
            "a" * 32,
            service_t0_monotonic_ns=t0_ns,
            deadline_monotonic_ns=t0_ns + GUARDIAN_REQUEST_BUDGET_NS,
        )
        is True
    )

    fake_now[0] = t0_ns + GUARDIAN_REQUEST_BUDGET_NS
    with pytest.raises(GuardianRequestJournalError, match="guardian_request_deadline_expired"):
        journal.record_observed("a" * 32, hashlib.sha256(b"late").hexdigest())

    record = journal.get_request("a" * 32)
    assert record is not None and record.state == "UNKNOWN"
    assert record.terminal_reason == "deadline_expired"
    with pytest.raises(GuardianRequestJournalError, match="guardian_request_unknown_terminal"):
        journal.record_observed("a" * 32, hashlib.sha256(b"even-later").hexdigest())


def test_commit_readback_crossing_deadline_downgrades_observation_to_unknown(
    private_state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    t0_ns = 20_000_000_000
    fake_now = [t0_ns + 1]
    monkeypatch.setattr(journal_module.time, "monotonic_ns", lambda: fake_now[0])
    assert (
        journal.persist_accepted(
            "a" * 32,
            service_t0_monotonic_ns=t0_ns,
            deadline_monotonic_ns=t0_ns + GUARDIAN_REQUEST_BUDGET_NS,
        )
        is True
    )

    deadline_ns = t0_ns + GUARDIAN_REQUEST_BUDGET_NS
    # record_observed samples just before D; the post-commit check sees D+1.
    calls = iter((deadline_ns - 1, deadline_ns + 1, deadline_ns + 2))
    monkeypatch.setattr(journal_module.time, "monotonic_ns", lambda: next(calls))
    with pytest.raises(GuardianRequestJournalError, match="guardian_request_deadline_expired"):
        journal.record_observed("a" * 32, hashlib.sha256(b"candidate").hexdigest())

    record = journal.get_request("a" * 32)
    assert record is not None
    assert record.state == "UNKNOWN"
    assert record.terminal_reason == "deadline_expired"


def test_observed_receipt_is_terminal_across_restart(private_state_dir: Path) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    _accepted(journal)
    digest = hashlib.sha256(b"externally-verified-receipt").hexdigest()

    observed = journal.record_observed("a" * 32, digest)
    assert observed.state == "OBSERVED"
    assert observed.receipt_digest == digest
    journal.close()

    reopened = GuardianRequestJournal(private_state_dir, "account-a")
    assert reopened.get_request("a" * 32) == observed
    assert reopened.has_blocker() is False


def test_database_identity_is_fixed_and_mismatch_fails_closed(private_state_dir: Path) -> None:
    journal = GuardianRequestJournal(private_state_dir, "account-a")
    _accepted(journal)

    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_identity_mismatch"):
        GuardianRequestJournal(private_state_dir, "account-b")

    assert journal.get_request("a" * 32) is not None


def test_unsafe_configuration_and_nonfixed_deadline_fail_closed(
    tmp_path: Path, private_state_dir: Path
) -> None:
    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_config_invalid"):
        GuardianRequestJournal(Path("relative-state"), "account-a")

    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_identity_invalid"):
        GuardianRequestJournal(private_state_dir, "account/a")

    journal = GuardianRequestJournal(private_state_dir, "account-a")
    with pytest.raises(GuardianRequestJournalError, match="guardian_request_id_invalid"):
        journal.persist_accepted(
            "not-a-uuid",
            service_t0_monotonic_ns=1,
            deadline_monotonic_ns=1 + GUARDIAN_REQUEST_BUDGET_NS,
        )
    with pytest.raises(GuardianRequestJournalError, match="guardian_request_deadline_invalid"):
        journal.persist_accepted(
            "a" * 32,
            service_t0_monotonic_ns=1,
            deadline_monotonic_ns=1 + GUARDIAN_REQUEST_BUDGET_NS - 1,
        )

    if os.name != "nt":
        shared_dir = tmp_path / "shared-state"
        shared_dir.mkdir()
        shared_dir.chmod(0o755)
        with pytest.raises(
            GuardianRequestJournalError, match="guardian_journal_permissions_invalid"
        ):
            GuardianRequestJournal(shared_dir, "account-a")


def test_corrupt_database_or_database_open_failure_is_never_treated_as_empty(
    private_state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = private_state_dir / GUARDIAN_REQUEST_DATABASE_NAME
    database.write_bytes(b"not a sqlite database")
    if os.name != "nt":
        database.chmod(0o600)
    else:
        from backtrader_runtime.ctp_simnow_signed_review import _protect_windows_path_acl

        _protect_windows_path_acl(database, is_directory=False)
    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_unavailable"):
        GuardianRequestJournal(private_state_dir, "account-a")

    database.unlink()
    journal = GuardianRequestJournal(private_state_dir, "account-a")

    def denied_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise PermissionError("injected database open failure")

    monkeypatch.setattr(journal_module.sqlite3, "connect", denied_connect)
    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_unavailable"):
        journal.has_blocker()


def test_database_acl_verifier_failure_fails_closed_on_windows(
    private_state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name != "nt":
        pytest.skip("Windows file-handle ACL check")
    journal = GuardianRequestJournal(private_state_dir, "account-a")

    def denied_acl(_entry: os.stat_result) -> None:
        raise GuardianRequestJournalError("guardian_journal_permissions_invalid")

    monkeypatch.setattr(journal, "_verify_windows_private_database", denied_acl)
    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_permissions_invalid"):
        journal.has_blocker()


def test_windows_sqlite_sidecar_acl_policy_rejects_broad_or_wrong_owner() -> None:
    user_sid = "S-1-5-21-10-20-30-1001"
    private_entries = (
        (0, 0x10, 0x001F01FF, user_sid),
        (0, 0x10, 0x001F01FF, "S-1-5-18"),
        (0, 0x10, 0x001F01FF, "S-1-5-32-544"),
    )
    journal_module._validate_windows_sqlite_sidecar_acl(user_sid, user_sid, private_entries)

    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_permissions_invalid"):
        journal_module._validate_windows_sqlite_sidecar_acl(
            user_sid,
            user_sid,
            private_entries + ((0, 0x10, 0x001F01FF, "S-1-1-0"),),
        )
    with pytest.raises(GuardianRequestJournalError, match="guardian_journal_permissions_invalid"):
        journal_module._validate_windows_sqlite_sidecar_acl(
            "S-1-5-21-10-20-30-1002", user_sid, private_entries
        )
