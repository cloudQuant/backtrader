from __future__ import annotations

import hashlib
import json
import multiprocessing
import sqlite3
from dataclasses import replace
from typing import Optional, Union

import pytest

from backtrader_runtime.ctp_f14_external_admission import (
    CtpF14ActionRequest,
    CtpF14AdmissionError,
    CtpF14SessionBinding,
    claim_f14_action,
)
from backtrader_runtime.ctp_f14_signed_receipt_contract import (
    CtpF14HostLocalSqliteObservationFence,
    CtpF14LocalReceiptObservationCache,
    CtpF14PinnedEd25519Verifier,
    CtpF14ReceiptContractError,
    CtpF14ReceiptContractObservation,
    CtpF14ReceiptTrustPolicy,
    CtpF14TrustedIssuerKey,
    verify_f14_receipt_contract,
)


_ACCOUNT = "a" * 64
_COVERAGE = ("account_funds", "open_orders", "positions", "trades")
_NOW = 1_790_000_010.0
_PIN = CtpF14TrustedIssuerKey(
    issuer_id="test-account-actor",
    key_id="test-ed25519-key-1",
    audience="backtrader-f14-contract-test",
    public_key_sha256="9" * 64,
)
_POLICY = CtpF14ReceiptTrustPolicy((_PIN,))


def _request(
    action_id: str = "action-52", *, connection_generation: int = 7
) -> CtpF14ActionRequest:
    return CtpF14ActionRequest(
        runtime_id="ctp_shared_runner",
        environment="simnow",
        mode="simulation",
        preset="sandbox",
        account_fingerprint_sha256=_ACCOUNT,
        config_digest="b" * 64,
        effective_digest="c" * 64,
        registration_digest="d" * 64,
        artifact_set_digest="e" * 64,
        session=CtpF14SessionBinding(
            session_id="session-7",
            trading_day="20260925",
            connection_generation=connection_generation,
            identity_digest="f" * 64,
        ),
        action_kind="SUBMIT",
        action_id=action_id,
        action_digest=hashlib.sha256(action_id.encode("ascii")).hexdigest(),
        approval_digest="2" * 64,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("ascii")


def _fake_signature(payload: bytes) -> bytes:
    # This deterministic test signature is not Ed25519 and is never production trust.
    return hashlib.sha512(b"test-only-untrusted-signer" + payload).digest()


def _real_test_keypair() -> tuple[object, bytes, CtpF14TrustedIssuerKey]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    pin = replace(_PIN, public_key_sha256=hashlib.sha256(public_key).hexdigest())
    return private_key, public_key, pin


class _FakeEd25519Verifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify_ed25519(
        self, pin: CtpF14TrustedIssuerKey, canonical_payload: bytes, signature: bytes
    ) -> bool:
        self.calls += 1
        return pin == _PIN and signature == _fake_signature(canonical_payload)


class _FakeExecutor:
    def __init__(self) -> None:
        self.dispatches = 0

    def dispatch(self, command: object) -> None:
        del command
        self.dispatches += 1


def _payload(
    request: CtpF14ActionRequest,
    *,
    claim_id: str = "claim-104",
    nonce: str = "nonce-104",
    fence_epoch: int = 41,
    changes: Optional[dict[str, object]] = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "backtrader.ctp_f14.authority_receipt.v1",
        "issuer_id": _PIN.issuer_id,
        "key_id": _PIN.key_id,
        "audience": _PIN.audience,
        "claim_id": claim_id,
        "nonce": nonce,
        "request_digest": request.request_digest,
        "account_fingerprint_sha256": request.account_fingerprint_sha256,
        "scope_digest": request.scope_digest,
        "action_id": request.action_id,
        "action_kind": request.action_kind,
        "action_digest": request.action_digest,
        "approval_digest": request.approval_digest,
        "target_digest": request.target_digest,
        "fence_id": "writer-fence-71",
        "fence_epoch": fence_epoch,
        "fence_scope_digest": request.scope_digest,
        "snapshot_id": "snapshot-903",
        "snapshot_version": "server-version-2204",
        "snapshot_digest": "4" * 64,
        "snapshot_coverage": list(_COVERAGE),
        "snapshot_collection_versions": dict.fromkeys(_COVERAGE, "server-version-2204"),
        "snapshot_pagination_complete": dict.fromkeys(_COVERAGE, True),
        "snapshot_account_fingerprint_sha256": request.account_fingerprint_sha256,
        "snapshot_fence_id": "writer-fence-71",
        "snapshot_fence_epoch": fence_epoch,
        "snapshot_trading_day": request.session.trading_day,
        "snapshot_connection_generation": request.session.connection_generation,
        "account_writer_exclusive": True,
        "snapshot_complete": True,
        "snapshot_consistent": True,
        "issued_at_utc": _NOW - 1.0,
        "expires_at_utc": _NOW + 10.0,
    }
    if changes:
        payload.update(changes)
    return payload


def _wire(payload: dict[str, object], *, signature: Optional[bytes] = None) -> bytes:
    payload_bytes = _canonical(payload)
    envelope = {
        "payload": payload,
        "signature_ed25519_hex": (signature or _fake_signature(payload_bytes)).hex(),
    }
    return _canonical(envelope)


def _ed25519_wire(payload: dict[str, object], private_key: object) -> bytes:
    payload_bytes = _canonical(payload)
    signature = private_key.sign(payload_bytes)  # type: ignore[attr-defined]
    return _canonical({"payload": payload, "signature_ed25519_hex": signature.hex()})


def _verify(
    request: CtpF14ActionRequest,
    wire: bytes,
    *,
    cache: Optional[
        Union[CtpF14LocalReceiptObservationCache, CtpF14HostLocalSqliteObservationFence]
    ] = None,
    verifier: Optional[_FakeEd25519Verifier] = None,
    now_utc: float = _NOW,
) -> CtpF14ReceiptContractObservation:
    return verify_f14_receipt_contract(
        request,
        wire,
        trust_policy=_POLICY,
        signature_verifier=verifier or _FakeEd25519Verifier(),
        observation_cache=cache or CtpF14LocalReceiptObservationCache(),
        now_utc=now_utc,
    )


def _verify_then_dispatch_if_admitted(
    request: CtpF14ActionRequest,
    wire: bytes,
    executor: _FakeExecutor,
    *,
    cache: Optional[
        Union[CtpF14LocalReceiptObservationCache, CtpF14HostLocalSqliteObservationFence]
    ] = None,
    now_utc: float = _NOW,
) -> None:
    observation = _verify(request, wire, cache=cache, now_utc=now_utc)
    admission = claim_f14_action(observation, request)  # type: ignore[arg-type]
    admission.assert_active()
    executor.dispatch(observation)


def _verify_ed25519_then_dispatch_if_admitted(
    request: CtpF14ActionRequest,
    wire: bytes,
    executor: _FakeExecutor,
    *,
    pin: CtpF14TrustedIssuerKey,
    resolved_public_key: bytes,
    cache: Optional[
        Union[CtpF14LocalReceiptObservationCache, CtpF14HostLocalSqliteObservationFence]
    ] = None,
    now_utc: float = _NOW,
) -> None:
    if cache is None:
        cache = CtpF14LocalReceiptObservationCache()
    observation = verify_f14_receipt_contract(
        request,
        wire,
        trust_policy=CtpF14ReceiptTrustPolicy((pin,)),
        signature_verifier=CtpF14PinnedEd25519Verifier(lambda _pin: resolved_public_key),
        observation_cache=cache,
        now_utc=now_utc,
    )
    admission = claim_f14_action(observation, request)  # type: ignore[arg-type]
    admission.assert_active()
    executor.dispatch(observation)


def _persistent_ed25519_worker(
    database_path: str,
    request: CtpF14ActionRequest,
    wire: bytes,
    pin: CtpF14TrustedIssuerKey,
    public_key: bytes,
    barrier: Optional[object],
    results: Optional[object],
    crash_after_observation: bool = False,
) -> None:
    try:
        fence = CtpF14HostLocalSqliteObservationFence(database_path)
        if barrier is not None:
            barrier.wait(timeout=10)  # type: ignore[attr-defined]
        observation = verify_f14_receipt_contract(
            request,
            wire,
            trust_policy=CtpF14ReceiptTrustPolicy((pin,)),
            signature_verifier=CtpF14PinnedEd25519Verifier(lambda _pin: public_key),
            observation_cache=fence,
            now_utc=_NOW,
        )
        if crash_after_observation:
            import os

            os._exit(73)
        result = ("observed", observation.receipt_digest)
    except CtpF14ReceiptContractError as error:
        result = ("rejected", error.reason)
    except Exception as error:
        result = ("unexpected", type(error).__name__)
    if results is not None:
        results.put(result)  # type: ignore[attr-defined]


def test_valid_signed_wire_is_only_a_shape_observation_and_never_dispatches() -> None:
    request = _request()
    executor = _FakeExecutor()
    wire = _wire(_payload(request))

    with pytest.raises(CtpF14AdmissionError, match="authority required"):
        _verify_then_dispatch_if_admitted(request, wire, executor)
    assert executor.dispatches == 0
    observation = _verify(request, wire)
    assert type(observation) is CtpF14ReceiptContractObservation
    assert observation.request_digest == request.request_digest
    assert observation.snapshot_coverage == _COVERAGE


def test_tampered_signed_payload_rejects_before_any_executor_dispatch() -> None:
    request = _request()
    payload = _payload(request)
    wire = _wire(payload)
    envelope = json.loads(wire)
    envelope["payload"]["snapshot_version"] = "tampered-version"
    tampered = _canonical(envelope)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="signature invalid"):
        _verify_then_dispatch_if_admitted(request, tampered, executor)
    assert executor.dispatches == 0


def test_same_receipt_is_replay_rejected_by_process_local_cache_only() -> None:
    request = _request()
    wire = _wire(_payload(request))
    cache = CtpF14LocalReceiptObservationCache()
    executor = _FakeExecutor()

    with pytest.raises(CtpF14AdmissionError, match="authority required"):
        _verify_then_dispatch_if_admitted(request, wire, executor, cache=cache)
    with pytest.raises(CtpF14ReceiptContractError, match="receipt replay"):
        _verify_then_dispatch_if_admitted(request, wire, executor, cache=cache)
    assert executor.dispatches == 0


def test_seen_newer_epoch_rejects_older_epoch_and_dispatches_nothing() -> None:
    first_request = _request("action-53")
    old_request = _request("action-54")
    cache = CtpF14LocalReceiptObservationCache()
    executor = _FakeExecutor()

    with pytest.raises(CtpF14AdmissionError, match="authority required"):
        _verify_then_dispatch_if_admitted(
            first_request,
            _wire(_payload(first_request, claim_id="claim-105", nonce="nonce-105", fence_epoch=42)),
            executor,
            cache=cache,
        )
    with pytest.raises(CtpF14ReceiptContractError, match="epoch rollback"):
        _verify_then_dispatch_if_admitted(
            old_request,
            _wire(_payload(old_request, claim_id="claim-106", nonce="nonce-106", fence_epoch=41)),
            executor,
            cache=cache,
        )
    assert executor.dispatches == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"snapshot_coverage": ["account_funds", "open_orders", "trades"]},
        {
            "snapshot_pagination_complete": {
                "account_funds": True,
                "open_orders": False,
                "positions": True,
                "trades": True,
            }
        },
        {"snapshot_collection_versions": dict.fromkeys(_COVERAGE, "mixed-version")},
    ],
)
def test_partial_or_mixed_snapshot_is_rejected_before_dispatch(changes: dict[str, object]) -> None:
    request = _request()
    payload = _payload(request, changes=changes)
    executor = _FakeExecutor()

    with pytest.raises(
        CtpF14ReceiptContractError, match="snapshot (coverage incomplete|partial or mixed)"
    ):
        _verify_then_dispatch_if_admitted(request, _wire(payload), executor)
    assert executor.dispatches == 0


def test_unknown_issuer_or_missing_verifier_fails_closed() -> None:
    request = _request()
    payload = _payload(request, changes={"issuer_id": "untrusted-service"})
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="untrusted receipt issuer or key"):
        _verify_then_dispatch_if_admitted(request, _wire(payload), executor)
    with pytest.raises(CtpF14ReceiptContractError, match="verifier required"):
        verify_f14_receipt_contract(
            request,
            _wire(_payload(request)),
            trust_policy=_POLICY,
            signature_verifier=None,  # type: ignore[arg-type]
            observation_cache=CtpF14LocalReceiptObservationCache(),
            now_utc=_NOW,
        )
    assert executor.dispatches == 0


def test_overlong_receipt_ttl_is_rejected_before_dispatch() -> None:
    request = _request()
    payload = _payload(
        request,
        changes={"issued_at_utc": _NOW - 1.0, "expires_at_utc": _NOW + 31.0},
    )
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="time window invalid"):
        _verify_then_dispatch_if_admitted(request, _wire(payload), executor)
    assert executor.dispatches == 0


def test_oversized_integer_trust_policy_ttl_is_rejected_without_raw_overflow() -> None:
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="ttl policy invalid"):
        CtpF14ReceiptTrustPolicy((_PIN,), max_ttl_seconds=10**400)
    assert executor.dispatches == 0


def test_oversized_injected_verification_time_is_rejected_without_raw_overflow() -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request), private_key)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="verification time invalid"):
        _verify_ed25519_then_dispatch_if_admitted(
            request,
            wire,
            executor,
            pin=pin,
            resolved_public_key=public_key,
            now_utc=10**400,
        )
    assert executor.dispatches == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"issued_at_utc": 10**400, "expires_at_utc": 10**400 + 10},
        {"issued_at_utc": _NOW - 1.0, "expires_at_utc": 10**400},
    ],
)
def test_oversized_signed_receipt_timestamps_reject_without_raw_overflow(
    changes: dict[str, object],
) -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request, changes=changes), private_key)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="time window invalid"):
        _verify_ed25519_then_dispatch_if_admitted(
            request, wire, executor, pin=pin, resolved_public_key=public_key
        )
    assert executor.dispatches == 0


def test_real_ed25519_signature_with_exact_public_key_pin_verifies_observation_only() -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request), private_key)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14AdmissionError, match="authority required"):
        _verify_ed25519_then_dispatch_if_admitted(
            request, wire, executor, pin=pin, resolved_public_key=public_key
        )
    assert executor.dispatches == 0


def test_ed25519_wrong_resolved_key_is_rejected_before_dispatch() -> None:
    request = _request()
    private_key, _public_key, pin = _real_test_keypair()
    _other_private_key, wrong_public_key, _other_pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request), private_key)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="signature invalid"):
        _verify_ed25519_then_dispatch_if_admitted(
            request, wire, executor, pin=pin, resolved_public_key=wrong_public_key
        )
    assert executor.dispatches == 0


def test_ed25519_bad_signature_is_rejected_before_dispatch() -> None:
    request = _request()
    _private_key, public_key, pin = _real_test_keypair()
    wrong_private_key, _wrong_public_key, _wrong_pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request), wrong_private_key)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="signature invalid"):
        _verify_ed25519_then_dispatch_if_admitted(
            request, wire, executor, pin=pin, resolved_public_key=public_key
        )
    assert executor.dispatches == 0


def test_ed25519_wrong_audience_is_rejected_by_trust_policy() -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    payload = _payload(request, changes={"audience": "other-audience"})
    wire = _ed25519_wire(payload, private_key)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="untrusted receipt issuer or key"):
        _verify_ed25519_then_dispatch_if_admitted(
            request, wire, executor, pin=pin, resolved_public_key=public_key
        )
    assert executor.dispatches == 0


def test_ed25519_payload_tamper_rejects_before_dispatch() -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    envelope = json.loads(_ed25519_wire(_payload(request), private_key))
    envelope["payload"]["snapshot_version"] = "changed-after-signing"
    wire = _canonical(envelope)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="signature invalid"):
        _verify_ed25519_then_dispatch_if_admitted(
            request, wire, executor, pin=pin, resolved_public_key=public_key
        )
    assert executor.dispatches == 0


def test_ed25519_boolean_snapshot_generation_is_not_accepted_as_integer() -> None:
    request = _request(connection_generation=1)
    private_key, public_key, pin = _real_test_keypair()
    payload = _payload(request, changes={"snapshot_connection_generation": True})
    wire = _ed25519_wire(payload, private_key)
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="snapshot connection generation invalid"):
        _verify_ed25519_then_dispatch_if_admitted(
            request, wire, executor, pin=pin, resolved_public_key=public_key
        )
    assert executor.dispatches == 0


def test_host_local_sqlite_fence_rejects_same_signed_receipt_after_reopen(tmp_path) -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request), private_key)
    database_path = tmp_path / "f14-observations.sqlite3"
    first_fence = CtpF14HostLocalSqliteObservationFence(database_path)
    first = verify_f14_receipt_contract(
        request,
        wire,
        trust_policy=CtpF14ReceiptTrustPolicy((pin,)),
        signature_verifier=CtpF14PinnedEd25519Verifier(lambda _pin: public_key),
        observation_cache=first_fence,
        now_utc=_NOW,
    )
    executor = _FakeExecutor()

    with pytest.raises(CtpF14ReceiptContractError, match="receipt replay"):
        _verify_ed25519_then_dispatch_if_admitted(
            request,
            wire,
            executor,
            pin=pin,
            resolved_public_key=public_key,
            cache=CtpF14HostLocalSqliteObservationFence(database_path),
        )
    assert first.receipt_digest == hashlib.sha256(wire).hexdigest()
    assert executor.dispatches == 0


def test_host_local_sqlite_fence_accepts_one_of_two_concurrent_process_observations(
    tmp_path,
) -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request), private_key)
    database_path = tmp_path / "f14-concurrent-observations.sqlite3"
    CtpF14HostLocalSqliteObservationFence(database_path)

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_persistent_ed25519_worker,
            args=(str(database_path), request, wire, pin, public_key, barrier, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    observed = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        assert process.exitcode == 0

    assert sum(result[0] == "observed" for result in observed) == 1
    assert sum(result[0] == "rejected" for result in observed) == 1
    executor = _FakeExecutor()
    with pytest.raises(CtpF14ReceiptContractError, match="receipt replay"):
        _verify_ed25519_then_dispatch_if_admitted(
            request,
            wire,
            executor,
            pin=pin,
            resolved_public_key=public_key,
            cache=CtpF14HostLocalSqliteObservationFence(database_path),
        )
    assert executor.dispatches == 0


def test_host_local_sqlite_fence_survives_process_crash_after_commit(tmp_path) -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request), private_key)
    database_path = tmp_path / "f14-crash-observations.sqlite3"
    CtpF14HostLocalSqliteObservationFence(database_path)

    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_persistent_ed25519_worker,
        args=(str(database_path), request, wire, pin, public_key, None, None, True),
    )
    process.start()
    process.join(timeout=15)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    assert process.exitcode == 73

    executor = _FakeExecutor()
    with pytest.raises(CtpF14ReceiptContractError, match="receipt replay"):
        _verify_ed25519_then_dispatch_if_admitted(
            request,
            wire,
            executor,
            pin=pin,
            resolved_public_key=public_key,
            cache=CtpF14HostLocalSqliteObservationFence(database_path),
        )
    assert executor.dispatches == 0


def test_host_local_sqlite_fence_fails_closed_on_schema_corruption(tmp_path) -> None:
    database_path = tmp_path / "f14-corrupt-observations.sqlite3"
    CtpF14HostLocalSqliteObservationFence(database_path)
    with sqlite3.connect(str(database_path)) as connection:
        connection.execute("DROP TABLE observed_receipts")

    with pytest.raises(
        CtpF14ReceiptContractError, match="persistent observation fence schema invalid"
    ):
        CtpF14HostLocalSqliteObservationFence(database_path)


def test_host_local_sqlite_fence_fails_closed_while_database_is_locked(tmp_path) -> None:
    request = _request()
    private_key, public_key, pin = _real_test_keypair()
    wire = _ed25519_wire(_payload(request), private_key)
    database_path = tmp_path / "f14-locked-observations.sqlite3"
    fence = CtpF14HostLocalSqliteObservationFence(database_path)
    connection = sqlite3.connect(str(database_path), isolation_level=None)
    connection.execute("BEGIN EXCLUSIVE")
    executor = _FakeExecutor()
    try:
        with pytest.raises(
            CtpF14ReceiptContractError,
            match="persistent observation fence unavailable",
        ):
            _verify_ed25519_then_dispatch_if_admitted(
                request,
                wire,
                executor,
                pin=pin,
                resolved_public_key=public_key,
                cache=fence,
            )
    finally:
        connection.rollback()
        connection.close()
    assert executor.dispatches == 0


def test_local_cache_is_not_shared_and_cannot_be_used_as_a_remote_fence() -> None:
    request = _request()
    wire = _wire(_payload(request))

    first = CtpF14LocalReceiptObservationCache()
    second = CtpF14LocalReceiptObservationCache()
    first_observation = _verify(request, wire, cache=first)
    # A fresh process-local cache accepts the wire again; this limitation is explicit.
    second_observation = _verify(request, wire, cache=second)
    assert first_observation.receipt_digest == second_observation.receipt_digest
