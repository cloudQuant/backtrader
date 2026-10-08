"""In-memory invocation and fresh C01 proof types for the unregistered M01 v2."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import secrets
import threading
from typing import Any


_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_CAPABILITY = object()
_ISSUED: dict[int, "CurrentReadProof"] = {}
_CONSUMED: set[int] = set()
_LOCK = threading.RLock()


class CurrentReadError(ValueError):
    """Fixed, value-free source-candidate failures."""

    def __init__(self, code: str):
        if type(code) is not str or not re.fullmatch(r"[a-z0-9_]{1,64}", code):
            code = "current_read_rejected"
        super().__init__(code)
        self.code = code


def fail(code: str) -> None:
    raise CurrentReadError(code)


@dataclass(frozen=True, repr=False, eq=False)
class M01Invocation:
    """Single-call identity. It deliberately cannot be serialized or copied."""

    nonce: str
    parent_pid: int
    started_ms: int
    source_map_sha256: str
    _seal: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("m01_invocation_not_serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("m01_invocation_not_serializable")


@dataclass(frozen=True, repr=False, eq=False)
class CurrentReadProof:
    """Factory-minted current C01 read bound to one M01 invocation.

    The proof is private, process-local and one-use. It carries no raw archive
    or caller-provided capture object; its credential and UID members are kept
    out of repr/serialization and are consumed only by the fixed M01 Job owner.
    """

    invocation: M01Invocation = field(repr=False)
    receipt_sha256: str
    account_scope_sha256: str = field(repr=False)
    credential_binding_sha256: str = field(repr=False)
    expected_rest_uid: str = field(repr=False)
    owner_invocation_sha256: str = field(repr=False)
    source_map_sha256: str
    completed_ms: int
    _credential_packet: bytes = field(repr=False)
    _lease_set: Any = field(repr=False)
    _audit_directory: Any = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __reduce__(self):
        raise TypeError("current_read_proof_not_serializable")

    def __reduce_ex__(self, _protocol):
        raise TypeError("current_read_proof_not_serializable")

    def __repr__(self) -> str:
        return "CurrentReadProof(<private>)"


def new_invocation(*, parent_pid: int, started_ms: int, source_map_sha256: str) -> M01Invocation:
    if type(parent_pid) is not int or parent_pid <= 0:
        fail("parent_pid")
    if type(started_ms) is not int or started_ms <= 0:
        fail("invocation_time")
    if type(source_map_sha256) is not str or not _HEX64.fullmatch(source_map_sha256):
        fail("source_map_digest")
    return M01Invocation(secrets.token_hex(16), parent_pid, started_ms, source_map_sha256, _CAPABILITY)


def invocation_digest(invocation: M01Invocation) -> str:
    if type(invocation) is not M01Invocation or invocation._seal is not _CAPABILITY:
        fail("invocation_type")
    if not _NONCE.fullmatch(invocation.nonce):
        fail("invocation_nonce")
    document = {
        "parent_pid": invocation.parent_pid,
        "run_nonce": invocation.nonce,
        "schema": "iteration41.okx.m01.invocation.v2",
        "source_map_sha256": invocation.source_map_sha256,
        "started_ms": invocation.started_ms,
    }
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()


def mint_current_read_proof(
    *,
    invocation: M01Invocation,
    receipt_sha256: str,
    account_scope_sha256: str,
    credential_binding_sha256: str,
    expected_rest_uid: str,
    completed_ms: int,
    credential_packet: bytes,
    lease_set: Any,
    audit_directory: Any,
) -> CurrentReadProof:
    """Private factory endpoint; caller must already have verified live C01 facts."""
    if type(invocation) is not M01Invocation or invocation._seal is not _CAPABILITY:
        fail("invocation_type")
    for name, value in (
        ("receipt_digest", receipt_sha256),
        ("account_scope", account_scope_sha256),
        ("credential_binding", credential_binding_sha256),
    ):
        if type(value) is not str or not _HEX64.fullmatch(value):
            fail(name)
    if type(expected_rest_uid) is not str or not re.fullmatch(r"[0-9]{1,32}", expected_rest_uid):
        fail("uid_shape")
    if type(completed_ms) is not int or completed_ms < invocation.started_ms:
        fail("completion_time")
    if type(credential_packet) is not bytes or not credential_packet:
        fail("credential_packet")
    if lease_set is None or not callable(getattr(lease_set, "close", None)):
        fail("source_leases_required")
    if audit_directory is None or not callable(getattr(audit_directory, "write_json", None)):
        fail("private_audit_directory_required")
    proof = CurrentReadProof(
        invocation=invocation,
        receipt_sha256=receipt_sha256,
        account_scope_sha256=account_scope_sha256,
        credential_binding_sha256=credential_binding_sha256,
        expected_rest_uid=expected_rest_uid,
        owner_invocation_sha256=invocation_digest(invocation),
        source_map_sha256=invocation.source_map_sha256,
        completed_ms=completed_ms,
        _credential_packet=credential_packet,
        _lease_set=lease_set,
        _audit_directory=audit_directory,
        _seal=_CAPABILITY,
    )
    with _LOCK:
        _ISSUED[id(proof)] = proof
    return proof


def consume_current_read_proof(
    proof: CurrentReadProof, invocation: M01Invocation, *, now_ms: int, max_age_ms: int = 30_000
) -> tuple[str, str, str, str, str, bytes]:
    """Atomically consume proof for one exact session; returns private launch facts."""
    if type(proof) is not CurrentReadProof or type(invocation) is not M01Invocation:
        fail("proof_type")
    with _LOCK:
        if proof._seal is not _CAPABILITY or _ISSUED.get(id(proof)) is not proof:
            fail("proof_not_factory_issued")
        if id(proof) in _CONSUMED:
            fail("proof_already_consumed")
        if proof.invocation is not invocation or invocation._seal is not _CAPABILITY:
            fail("proof_invocation_mismatch")
        if proof.source_map_sha256 != invocation.source_map_sha256:
            fail("proof_source_mismatch")
        if type(now_ms) is not int or now_ms < proof.completed_ms or now_ms - proof.completed_ms > max_age_ms:
            fail("proof_stale")
        _CONSUMED.add(id(proof))
    return (
        proof.account_scope_sha256,
        proof.credential_binding_sha256,
        proof.receipt_sha256,
        proof.owner_invocation_sha256,
        proof.expected_rest_uid,
        proof._credential_packet,
    )


def release_current_read_proof(proof: CurrentReadProof) -> None:
    """Release held source/credential leases after normal or failed M01 cleanup."""
    if type(proof) is not CurrentReadProof or proof._seal is not _CAPABILITY:
        fail("proof_type")
    with _LOCK:
        if _ISSUED.get(id(proof)) is not proof:
            fail("proof_not_factory_issued")
        _ISSUED.pop(id(proof), None)
        _CONSUMED.discard(id(proof))
    proof._lease_set.close()

