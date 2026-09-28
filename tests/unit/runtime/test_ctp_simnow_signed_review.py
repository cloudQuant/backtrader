from __future__ import annotations

import hashlib
import hmac
import multiprocessing
import os
import sqlite3
import tempfile
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Callable

import pytest

from backtrader_runtime import ctp_simnow_signed_review as signed_review
from backtrader_runtime.ctp_simnow_operational_window import (
    CtpSimNowOperationalActionRequest,
    CtpSimNowOperationalRiskLimits,
    CtpSimNowOperationalWindowError,
    CtpSimNowOperationalWindowPermit,
    CtpSimNowOperationalWindowScope,
    require_active_simnow_operational_window_permit,
    require_simnow_operational_window_permit,
)
from backtrader_runtime.ctp_simnow_signed_review import (
    CtpSimNowOperationalReviewKeyPolicy,
    CtpSimNowSignedOperationalReview,
    HmacCtpSimNowOperationalWindowReviewer,
    LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard,
)


_KEY_ID = "simnow-review-test-key"
_AUTHORITY = "simnow-test-review-authority"
_KEY = b"offline-test-only-secret-key-32bytes!!"
_NOW = 1_790_000_001.0


def _claim_from_process(path: str, barrier: object, result_queue: object, permit_id: str) -> None:
    try:
        barrier.wait(timeout=10)  # type: ignore[attr-defined]
        result = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(Path(path)).claim_once(
            permit_id, "a" * 64, "b" * 64
        )
        result_queue.put(("ok", result))  # type: ignore[attr-defined]
    except BaseException as exc:
        result_queue.put(("error", type(exc).__name__, str(exc), repr(exc.__cause__)))  # type: ignore[attr-defined]


def _crash_after_permit_claim_insert(path: str) -> None:
    connection = sqlite3.connect(path, timeout=2.0, isolation_level=None)
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        "INSERT INTO simnow_review_permit_claims (permit_id, request_digest) VALUES (?, ?)",
        ("crash-permit", "c" * 64),
    )
    os._exit(23)


def _scope(**changes: object) -> CtpSimNowOperationalWindowScope:
    values: dict[str, object] = {
        "window_id": "simnow-window-7",
        "runtime_id": "iteration41.ctp.simnow-test",
        "environment": "simnow",
        "mode": "simulation",
        "preset": "sandbox",
        "account_fingerprint_sha256": "a" * 64,
        "config_digest": "b" * 64,
        "effective_digest": "c" * 64,
        "registration_digest": "d" * 64,
        "artifact_set_digest": "e" * 64,
        "session_id": "session-7",
        "trading_day": "20260925",
        "connection_generation": 7,
        "session_identity_digest": "f" * 64,
        "selected_front_pair": ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
        "instrument_id": "rb2701",
        "exchange_id": "SHFE",
        "hedge_flag": "1",
        "risk_limits": CtpSimNowOperationalRiskLimits(
            max_order_quantity=1,
            max_gross_position_quantity=1,
            max_live_test_orders=1,
            max_order_notional=Decimal("5000"),
        ),
    }
    values.update(changes)
    return CtpSimNowOperationalWindowScope(**values)  # type: ignore[arg-type]


def _request(
    *,
    scope: CtpSimNowOperationalWindowScope | None = None,
    action_kind: str = "SUBMIT",
    **changes: object,
) -> CtpSimNowOperationalActionRequest:
    values: dict[str, object] = {
        "scope": scope or _scope(),
        "action_kind": action_kind,
        "action_id": "action-52",
        "action_digest": "1" * 64,
        "approval_digest": "2" * 64,
        "requested_quantity": 1 if action_kind == "SUBMIT" else None,
        "requested_notional": Decimal("3450") if action_kind == "SUBMIT" else None,
        "target_digest": "3" * 64 if action_kind == "CANCEL" else None,
        "target_remaining_quantity": 1 if action_kind == "CANCEL" else None,
    }
    values.update(changes)
    return CtpSimNowOperationalActionRequest(**values)  # type: ignore[arg-type]


def _signed_review(
    request: CtpSimNowOperationalActionRequest,
    *,
    permit_id: str = "permit-100",
    issued_at_utc: float = _NOW - 1.0,
    expires_at_utc: float = _NOW + 29.0,
    revocation_epoch: int = 3,
    review_authority_id: str = _AUTHORITY,
    key_id: str = _KEY_ID,
    key: bytes = _KEY,
) -> CtpSimNowSignedOperationalReview:
    permit = CtpSimNowOperationalWindowPermit(
        binding=request,
        permit_id=permit_id,
        review_authority_id=review_authority_id,
        review_digest="4" * 64,
        revocation_epoch=revocation_epoch,
        issued_at_utc=issued_at_utc,
        expires_at_utc=expires_at_utc,
    )
    unsigned = CtpSimNowSignedOperationalReview(
        permit=permit, key_id=key_id, signature_hex="0" * 64
    )
    signature = hmac.new(key, unsigned.signed_payload(), hashlib.sha256).hexdigest()
    return replace(unsigned, signature_hex=signature)


def _policy(
    request: CtpSimNowOperationalActionRequest,
    **changes: object,
) -> CtpSimNowOperationalReviewKeyPolicy:
    values: dict[str, object] = {
        "key_id": _KEY_ID,
        "review_authority_id": _AUTHORITY,
        "key_bytes": _KEY,
        "current_revocation_epoch": 3,
        "allowed_account_fingerprints": frozenset((request.scope.account_fingerprint_sha256,)),
        "allowed_window_ids": frozenset((request.scope.window_id,)),
        "allowed_session_identity_digests": frozenset((request.scope.session_identity_digest,)),
        "allowed_trading_days": frozenset((request.scope.trading_day,)),
        "allowed_risk_limits_digests": frozenset((request.scope.risk_limits.digest,)),
        "allowed_action_kinds": frozenset((request.action_kind,)),
    }
    values.update(changes)
    return CtpSimNowOperationalReviewKeyPolicy(**values)  # type: ignore[arg-type]


class _Clock:
    def __init__(self, now: object = _NOW) -> None:
        self.now = now

    def __call__(self) -> object:
        return self.now


class _Source:
    def __init__(self, *reviews: CtpSimNowSignedOperationalReview) -> None:
        self.reviews = list(reviews)
        self.calls = 0

    def issue_action_review(
        self, request: CtpSimNowOperationalActionRequest
    ) -> CtpSimNowSignedOperationalReview:
        del request
        self.calls += 1
        return self.reviews[min(self.calls - 1, len(self.reviews) - 1)]


class _Resolver:
    def __init__(self, *policies: CtpSimNowOperationalReviewKeyPolicy) -> None:
        self.policies = {policy.key_id: policy for policy in policies}

    def resolve(self, key_id: str) -> CtpSimNowOperationalReviewKeyPolicy | None:
        return self.policies.get(key_id)


class _ReplayGuard:
    """Explicit in-memory fake; production must inject a durable atomic guard."""

    def __init__(self) -> None:
        self.permit_ids: set[str] = set()
        self.action_keys: set[str] = set()
        self.claims: list[tuple[str, str, str]] = []

    def claim_once(self, permit_id: str, action_replay_key: str, request_digest: str) -> bool:
        self.claims.append((permit_id, action_replay_key, request_digest))
        if permit_id in self.permit_ids or action_replay_key in self.action_keys:
            return False
        self.permit_ids.add(permit_id)
        self.action_keys.add(action_replay_key)
        return True


def _reviewer(
    request: CtpSimNowOperationalActionRequest,
    envelope: CtpSimNowSignedOperationalReview | None = None,
    *,
    clock: _Clock | None = None,
    replay_guard: _ReplayGuard | None = None,
    source: _Source | None = None,
) -> tuple[HmacCtpSimNowOperationalWindowReviewer, _Resolver, _ReplayGuard, _Clock]:
    actual_clock = clock or _Clock()
    actual_guard = replay_guard or _ReplayGuard()
    actual_source = source or _Source(envelope or _signed_review(request))
    resolver = _Resolver(_policy(request))
    reviewer = HmacCtpSimNowOperationalWindowReviewer(
        review_source=actual_source,
        key_resolver=resolver,
        trusted_utc=actual_clock,
        replay_guard=actual_guard,
    )
    return reviewer, resolver, actual_guard, actual_clock


def test_hmac_review_verifies_exact_scope_and_remains_non_authorizing() -> None:
    request = _request(action_kind="CANCEL")
    envelope = _signed_review(request)
    reviewer, _resolver, replay_guard, _clock = _reviewer(request, envelope)

    permit = require_simnow_operational_window_permit(reviewer, request, now_utc=_NOW)
    require_active_simnow_operational_window_permit(reviewer, permit, request, now_utc=_NOW + 1.0)

    assert permit.binding == request
    assert permit.scope_digest == request.scope.scope_digest
    assert permit.request_digest == request.request_digest
    assert permit.cryptographic_signature_verified is False
    assert permit.write_authorized is False
    assert permit.account_writer_exclusive is False
    assert len(replay_guard.claims) == 1


def test_unsigned_or_tampered_review_is_rejected_before_permit_is_returned() -> None:
    request = _request()
    envelope = _signed_review(request)
    altered = replace(envelope, signature_hex="0" * 64)
    reviewer, _resolver, guard, _clock = _reviewer(request, altered)

    with pytest.raises(CtpSimNowOperationalWindowError, match="signature invalid"):
        reviewer.issue_action_review(request)
    assert guard.claims == []


@pytest.mark.parametrize(
    "scope_change",
    [
        {"account_fingerprint_sha256": "9" * 64},
        {"window_id": "other-window"},
        {"session_id": "other-session"},
        {"trading_day": "20260926"},
        {"connection_generation": 8},
        {"session_identity_digest": "8" * 64},
        {
            "risk_limits": CtpSimNowOperationalRiskLimits(
                max_order_quantity=1,
                max_gross_position_quantity=1,
                max_live_test_orders=1,
                max_order_notional=Decimal("4000"),
            )
        },
    ],
)
def test_signed_envelope_cannot_be_replayed_for_a_different_account_window_or_scope(
    scope_change: dict[str, object],
) -> None:
    original = _request()
    changed = _request(scope=_scope(**scope_change))
    reviewer, _resolver, guard, _clock = _reviewer(original, _signed_review(original))

    with pytest.raises(CtpSimNowOperationalWindowError, match="scope mismatch"):
        reviewer.issue_action_review(changed)
    assert guard.claims == []


def test_issuer_allowlist_rejects_other_account_action_session_day_and_risk() -> None:
    request = _request()
    denied_request = _request(
        scope=_scope(
            account_fingerprint_sha256="9" * 64,
            window_id="unapproved-window",
            session_identity_digest="8" * 64,
            trading_day="20260926",
            risk_limits=CtpSimNowOperationalRiskLimits(
                max_order_quantity=1,
                max_gross_position_quantity=1,
                max_live_test_orders=1,
                max_order_notional=Decimal("4200"),
            ),
        ),
        action_kind="CANCEL",
        action_id="other-action",
    )
    signed = _signed_review(denied_request)
    reviewer, _resolver, guard, _clock = _reviewer(
        denied_request,
        signed,
    )
    reviewer._key_resolver.policies[_KEY_ID] = _policy(request)

    with pytest.raises(CtpSimNowOperationalWindowError, match="issuer policy rejected"):
        reviewer.issue_action_review(denied_request)
    assert guard.claims == []


def test_key_id_and_issuer_identity_are_bound_to_the_resolved_policy() -> None:
    request = _request()
    envelope = _signed_review(request, review_authority_id="other-authority")
    reviewer, _resolver, guard, _clock = _reviewer(request, envelope)

    with pytest.raises(CtpSimNowOperationalWindowError, match="issuer policy rejected"):
        reviewer.issue_action_review(request)
    assert guard.claims == []


def test_unknown_or_revoked_key_and_changed_revocation_epoch_fail_closed() -> None:
    request = _request()
    envelope = _signed_review(request)
    reviewer, resolver, _guard, _clock = _reviewer(request, envelope)
    resolver.policies.clear()
    with pytest.raises(CtpSimNowOperationalWindowError, match="key unavailable"):
        reviewer.issue_action_review(request)

    reviewer, resolver, _guard, _clock = _reviewer(request, envelope)
    resolver.policies[_KEY_ID] = replace(_policy(request), revoked=True)
    with pytest.raises(CtpSimNowOperationalWindowError, match="key unavailable"):
        reviewer.issue_action_review(request)

    reviewer, resolver, _guard, _clock = _reviewer(request, envelope)
    permit = reviewer.issue_action_review(request)
    resolver.policies[_KEY_ID] = replace(_policy(request), current_revocation_epoch=4)
    with pytest.raises(CtpSimNowOperationalWindowError, match="issuer policy rejected"):
        reviewer.assert_action_review_current(permit, request=request)


@pytest.mark.parametrize(
    "now,issued,expires",
    [
        (_NOW + 30.0, _NOW - 1.0, _NOW + 29.0),
        (_NOW - 2.0, _NOW - 1.0, _NOW + 29.0),
    ],
)
def test_expired_or_not_yet_valid_reviews_use_injected_trusted_utc(
    now: float, issued: float, expires: float
) -> None:
    request = _request()
    envelope = _signed_review(request, issued_at_utc=issued, expires_at_utc=expires)
    reviewer, _resolver, guard, _clock = _reviewer(request, envelope, clock=_Clock(now))

    with pytest.raises(CtpSimNowOperationalWindowError, match="expired"):
        reviewer.issue_action_review(request)
    assert guard.claims == []


def test_nonfinite_trusted_utc_and_policy_ttl_ceiling_fail_closed() -> None:
    request = _request()
    envelope = _signed_review(request)
    reviewer, resolver, guard, clock = _reviewer(request, envelope)
    clock.now = float("nan")
    with pytest.raises(CtpSimNowOperationalWindowError, match="trusted utc unavailable"):
        reviewer.issue_action_review(request)
    assert guard.claims == []

    reviewer, resolver, guard, _clock = _reviewer(request, envelope)
    resolver.policies[_KEY_ID] = replace(_policy(request), max_ttl_seconds=5.0)
    with pytest.raises(CtpSimNowOperationalWindowError, match="expired"):
        reviewer.issue_action_review(request)
    assert guard.claims == []


def test_replay_guard_rejects_reused_permit_and_second_permit_for_same_action() -> None:
    request = _request()
    first = _signed_review(request, permit_id="permit-one")
    second = _signed_review(request, permit_id="permit-two")
    source = _Source(first, first, second)
    reviewer, _resolver, guard, _clock = _reviewer(request, source=source)

    reviewer.issue_action_review(request)
    with pytest.raises(CtpSimNowOperationalWindowError, match="replayed"):
        reviewer.issue_action_review(request)
    with pytest.raises(CtpSimNowOperationalWindowError, match="replayed"):
        reviewer.issue_action_review(request)
    assert len(guard.claims) == 2


def test_replay_guard_failure_or_unavailable_guard_never_returns_a_permit() -> None:
    request = _request()
    envelope = _signed_review(request)
    guard = _ReplayGuard()
    guard.claim_once = lambda *_args: None  # type: ignore[method-assign]
    reviewer, _resolver, _guard, _clock = _reviewer(request, envelope, replay_guard=guard)

    with pytest.raises(CtpSimNowOperationalWindowError, match="replayed"):
        reviewer.issue_action_review(request)


def test_policy_is_immutable_and_no_default_trust_material_is_created() -> None:
    request = _request()
    accounts = {request.scope.account_fingerprint_sha256}
    policy = _policy(request, allowed_account_fingerprints=accounts)
    accounts.add("9" * 64)
    assert policy.allowed_account_fingerprints == frozenset(("a" * 64,))

    reviewer = HmacCtpSimNowOperationalWindowReviewer(
        review_source=_Source(_signed_review(request)),
        key_resolver=_Resolver(),
        trusted_utc=_Clock(),
        replay_guard=_ReplayGuard(),
    )
    with pytest.raises(CtpSimNowOperationalWindowError, match="key unavailable"):
        reviewer.issue_action_review(request)


@pytest.fixture
def review_state_dir(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    if os.name == "nt":
        temporary = tempfile.TemporaryDirectory(prefix="codex-simnow-review-", dir=str(Path.home()))
        state_dir = Path(temporary.name)
        request.addfinalizer(temporary.cleanup)
        signed_review._protect_windows_path_acl(state_dir, is_directory=True)
    else:
        state_dir = tmp_path / "private-review-state"
        state_dir.mkdir()
        state_dir.chmod(0o700)
    return state_dir


def test_local_sqlite_guard_persists_both_replay_keys_across_instances(
    review_state_dir: Path,
) -> None:
    state_dir = review_state_dir
    database = state_dir / "review-replay.sqlite3"
    first = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database)
    assert first.LOCAL_ONLY is True
    assert first.NO_WRITE is True
    assert first.claim_once("permit-persist", "1" * 64, "2" * 64) is True

    restarted = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database)
    assert restarted.claim_once("permit-persist", "3" * 64, "4" * 64) is False
    assert restarted.claim_once("permit-new", "1" * 64, "5" * 64) is False
    assert restarted.claim_once("permit-new", "6" * 64, "7" * 64) is True


def test_reviewer_rejects_signed_review_replayed_after_guard_restart(
    review_state_dir: Path,
) -> None:
    request = _request()
    envelope = _signed_review(request)
    database = review_state_dir / "review-replay.sqlite3"
    first = HmacCtpSimNowOperationalWindowReviewer(
        review_source=_Source(envelope),
        key_resolver=_Resolver(_policy(request)),
        trusted_utc=_Clock(),
        replay_guard=LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database),
    )
    first.issue_action_review(request)

    restarted = HmacCtpSimNowOperationalWindowReviewer(
        review_source=_Source(envelope),
        key_resolver=_Resolver(_policy(request)),
        trusted_utc=_Clock(),
        replay_guard=LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database),
    )
    with pytest.raises(CtpSimNowOperationalWindowError, match="replayed"):
        restarted.issue_action_review(request)


def test_local_sqlite_guard_recovers_uncommitted_half_claim_after_process_crash(
    review_state_dir: Path,
) -> None:
    database = review_state_dir / "review-replay.sqlite3"
    guard = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database)
    assert guard.claim_once("seed-permit", "8" * 64, "9" * 64) is True

    context = multiprocessing.get_context("spawn")
    process = context.Process(target=_crash_after_permit_claim_insert, args=(str(database),))
    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        pytest.fail("crash-recovery subprocess did not exit")
    assert process.exitcode == 23

    restarted = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database)
    assert restarted.claim_once("crash-permit", "a" * 64, "b" * 64) is True


def test_local_sqlite_guard_serializes_cross_process_race(review_state_dir: Path) -> None:
    database = review_state_dir / "review-replay.sqlite3"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_claim_from_process,
            args=(str(database), barrier, result_queue, permit_id),
        )
        for permit_id in ("race-permit-a", "race-permit-b")
    ]
    try:
        for process in processes:
            process.start()
        results = [result_queue.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(timeout=15)
        assert all(not process.is_alive() and process.exitcode == 0 for process in processes)
        assert sorted(results) == [("ok", False), ("ok", True)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        result_queue.close()


def test_local_sqlite_guard_rejects_unsafe_path_identity_and_permissions(
    tmp_path: Path, review_state_dir: Path
) -> None:
    state_dir = review_state_dir
    target = state_dir / "real.sqlite3"
    link = state_dir / "link.sqlite3"
    if os.name != "nt":
        link.symlink_to(target)
        with pytest.raises(RuntimeError, match="operational_review_replay_path_invalid"):
            LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(link).claim_once(
                "permit-link", "a" * 64, "b" * 64
            )
        link.unlink()

        state_dir.chmod(0o755)
        with pytest.raises(RuntimeError, match="operational_review_replay_permissions_invalid"):
            LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(target).claim_once(
                "permit-parent-mode", "a" * 64, "b" * 64
            )
        state_dir.chmod(0o700)

    guard = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(target)
    assert guard.claim_once("permit-file-mode", "a" * 64, "b" * 64) is True
    if os.name != "nt":
        target.chmod(0o644)
        with pytest.raises(RuntimeError, match="operational_review_replay_permissions_invalid"):
            guard.claim_once("permit-insecure-file", "c" * 64, "d" * 64)

    if os.name == "nt":
        shared_directory = tmp_path / "shared-directory"
        shared_directory.mkdir()
        shared_database = shared_directory / "review-replay.sqlite3"
        with pytest.raises(RuntimeError):
            LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(shared_database).claim_once(
                "permit-shared", "e" * 64, "f" * 64
            )
        assert not shared_database.exists()


def test_windows_acl_policies_accept_only_private_state_and_safe_ancestors() -> None:
    owner = "S-1-5-21-10-20-30-1001"
    private_entries = (
        (0, 0, 0x001F01FF, owner),
        (0, 0, 0x001F01FF, "S-1-5-18"),
        (0, 0, 0x001F01FF, "S-1-5-32-544"),
    )
    signed_review._validate_windows_private_acl(owner, owner, True, private_entries)
    with pytest.raises(RuntimeError, match="windows_acl_invalid"):
        signed_review._validate_windows_private_acl(owner, owner, False, private_entries)
    with pytest.raises(RuntimeError, match="windows_acl_invalid"):
        signed_review._validate_windows_private_acl(
            owner, owner, True, private_entries + ((0, 0, 0x001F01FF, "S-1-1-0"),)
        )

    safe_ancestor_entries = (
        (0, 0, 0x001200A9, "S-1-5-11"),
        (0, 0, 0x001F01FF, owner),
    )
    signed_review._validate_windows_ancestor_acl(owner, owner, safe_ancestor_entries)
    with pytest.raises(RuntimeError, match="ancestor_acl_invalid"):
        signed_review._validate_windows_ancestor_acl(
            owner, owner, safe_ancestor_entries + ((0, 0, 0x00000040, "S-1-5-11"),)
        )
    with pytest.raises(RuntimeError, match="ancestor_acl_invalid"):
        signed_review._validate_windows_ancestor_acl(
            owner, owner, safe_ancestor_entries + ((0, 0, 0x40000000, "S-1-5-11"),)
        )

    inherited_sidecar_entries = (
        (0, 0x13, 0x001F01FF, owner),
        (0, 0x13, 0x001F01FF, "S-1-5-18"),
        (0, 0x13, 0x001F01FF, "S-1-5-32-544"),
    )
    signed_review._validate_windows_sidecar_acl(owner, owner, inherited_sidecar_entries)
    with pytest.raises(RuntimeError, match="sidecar_acl_invalid"):
        signed_review._validate_windows_sidecar_acl(
            owner, owner, inherited_sidecar_entries + ((0, 0x13, 0x001F01FF, "S-1-1-0"),)
        )


def test_windows_local_sqlite_path_rejects_unc_remote_and_unknown_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unc_path = Path(r"\\server\share\review-replay.sqlite3")
    with pytest.raises(RuntimeError, match="operational_review_replay_local_volume_required"):
        signed_review._require_windows_local_volume(
            unc_path,
            drive_type_getter=lambda _root: pytest.fail("UNC must reject before DriveTypeW"),
        )

    local_drive_path = Path(r"Z:\runtime\review-replay.sqlite3")

    def make_drive_type_getter(
        volume_type: int,
    ) -> tuple[list[str], Callable[[str], int]]:
        seen_roots: list[str] = []

        def get_drive_type(root: str) -> int:
            seen_roots.append(root)
            return volume_type

        return seen_roots, get_drive_type

    for volume_type in (0, 4):  # DRIVE_UNKNOWN and DRIVE_REMOTE
        seen_roots, get_drive_type = make_drive_type_getter(volume_type)
        with pytest.raises(RuntimeError, match="operational_review_replay_local_volume_required"):
            signed_review._require_windows_local_volume(
                local_drive_path, drive_type_getter=get_drive_type
            )
        assert seen_roots == ["Z:\\"]

    signed_review._require_windows_local_volume(
        local_drive_path, drive_type_getter=lambda root: 3 if root == "Z:\\" else 0
    )
    if os.name == "nt":
        monkeypatch.setattr(signed_review, "_windows_drive_type", lambda _root: 4)
        with pytest.raises(ValueError, match="operational_review_replay_local_volume_required"):
            LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(local_drive_path)


def test_local_sqlite_guard_rejects_changed_database_or_parent_identity(
    review_state_dir: Path,
) -> None:
    database = review_state_dir / "review-replay.sqlite3"
    guard = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database)
    assert guard.claim_once("permit-identity", "a" * 64, "b" * 64) is True
    parent_identity, database_identity = guard._prepare_database_file()

    changed_database_identity = (
        parent_identity,
        (database_identity[0], database_identity[1] + 1),
    )
    with pytest.raises(RuntimeError, match="operational_review_replay_path_changed"):
        guard._require_current_identity(changed_database_identity)

    changed_parent_identity = list(parent_identity)
    path, device, inode = changed_parent_identity[-1]
    changed_parent_identity[-1] = (path, device, inode + 1)
    with pytest.raises(RuntimeError, match="operational_review_replay_path_changed"):
        guard._require_current_identity((tuple(changed_parent_identity), database_identity))


def test_local_sqlite_guard_fails_closed_on_locked_or_corrupt_database(
    review_state_dir: Path,
) -> None:
    state_dir = review_state_dir
    database = state_dir / "review-replay.sqlite3"
    guard = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database)
    assert guard.claim_once("permit-unlocked", "a" * 64, "b" * 64) is True

    locker = sqlite3.connect(str(database), timeout=1.0, isolation_level=None)
    try:
        locker.execute("BEGIN EXCLUSIVE")
        with pytest.raises(RuntimeError, match="operational_review_replay_unavailable"):
            guard.claim_once("permit-locked", "c" * 64, "d" * 64)
    finally:
        locker.execute("ROLLBACK")
        locker.close()
    assert guard.claim_once("permit-after-lock", "e" * 64, "f" * 64) is True

    corrupt = state_dir / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a sqlite database")
    if os.name != "nt":
        corrupt.chmod(0o600)
    else:
        signed_review._protect_windows_path_acl(corrupt, is_directory=False)
    with pytest.raises(RuntimeError, match="operational_review_replay_unavailable"):
        LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(corrupt).claim_once(
            "permit-corrupt", "1" * 64, "2" * 64
        )


def test_local_sqlite_guard_rejects_unavailable_permissions_and_schema_corruption(
    review_state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = review_state_dir
    database = state_dir / "review-replay.sqlite3"
    guard = LocalOnlySqliteCtpSimNowOperationalReviewReplayGuard(database)
    assert guard.claim_once("permit-schema", "a" * 64, "b" * 64) is True

    connection = sqlite3.connect(str(database))
    connection.execute("DELETE FROM simnow_review_replay_meta")
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="operational_review_replay_unavailable"):
        guard.claim_once("permit-bad-schema", "c" * 64, "d" * 64)

    # A permission error from the SQLite open path is converted to an
    # unavailable guard result; it can never be interpreted as a fresh claim.
    original_connect = sqlite3.connect

    def denied_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise PermissionError("injected")

    monkeypatch.setattr(
        "backtrader_runtime.ctp_simnow_signed_review.sqlite3.connect", denied_connect
    )
    with pytest.raises(RuntimeError, match="operational_review_replay_unavailable"):
        guard.claim_once("permit-denied", "e" * 64, "f" * 64)
    monkeypatch.setattr(
        "backtrader_runtime.ctp_simnow_signed_review.sqlite3.connect", original_connect
    )
