"""Pure-local V2 CTP bundle authorization and arming-proof builder.

The caller supplies already-collected public snapshots and the trust root.
This module never loads files, environment variables, SDK clients, or
accounts.  The secret is used only for the one HMAC operation and is never
stored in an object, returned, logged, or interpolated into an exception.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from backtrader.stores.btapistore import (
    _CTP_EXECUTION_ARM_BUNDLE_FIELDS,
    _CTP_EXECUTION_ARM_BUNDLE_SCOPE_VERSION,
    _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS,
)


STAGE_A_QUERY_NAMES = ("account", "positions", "orders", "trades", "instruments")
STAGE_B_QUERY_NAMES = STAGE_A_QUERY_NAMES + ("margin_rate", "commission_rate")
AUTHORIZATION_SCHEMA = "backtrader.ctp.execution-authorization.v1"
AUTHORIZATION_KIND = "hmac_sha256"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*$")


class AuthorizationBuildError(ValueError):
    """A fail-closed local builder validation error."""


@dataclass(frozen=True)
class BundleAuthorizationArtifacts:
    """Grant, proof, and safe metadata; never contains the HMAC secret."""

    grant: dict[str, Any]
    arming_proof: dict[str, Any]
    summary: dict[str, Any]


def _fail(message: str) -> None:
    raise AuthorizationBuildError(message)


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field} must be lowercase sha256")
    return value


def _aware_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _fail(f"{field} must be timezone-aware ISO time")
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail(f"{field} must be timezone-aware ISO time")
    return value.astimezone(timezone.utc)


def _account_fingerprint(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} account identity is missing")
    account = value.strip().lower()
    return account if account.startswith("acct_") else f"acct_{account}"


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AuthorizationBuildError("authorization payload is not canonical JSON") from error


def _snapshot_session(snapshot: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    session = snapshot.get("session_after") or snapshot.get("session")
    if not isinstance(session, Mapping):
        _fail(f"{field} session evidence is missing")
    return session


def _identity(snapshot: Mapping[str, Any], field: str) -> dict[str, Any]:
    session = _snapshot_session(snapshot, field)
    account = snapshot.get("account_fingerprint")
    day = snapshot.get("trading_day")
    generation = snapshot.get("connection_generation")
    profile = session.get("environment_profile")
    account = _account_fingerprint(account, field)
    if not isinstance(day, str) or not day.strip():
        _fail(f"{field} trading day is missing")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation <= 0:
        _fail(f"{field} connection generation is invalid")
    if not isinstance(profile, str) or not profile.strip():
        _fail(f"{field} environment profile is missing")
    return {
        "account_fingerprint": account,
        "trading_day": day,
        "connection_generation": generation,
        "environment_profile": profile,
    }


def _runtime_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("runtime identity is not a mapping")
    account = value.get("account_fingerprint")
    day = value.get("trading_day")
    generation = value.get("connection_generation")
    profile = value.get("environment_profile")
    account = _account_fingerprint(account, "runtime")
    if not isinstance(day, str) or not day.strip():
        _fail("runtime trading day is missing")
    if isinstance(generation, bool) or not isinstance(generation, int) or generation <= 0:
        _fail("runtime connection generation is invalid")
    if not isinstance(profile, str) or not profile.strip():
        _fail("runtime environment profile is missing")
    return {
        "account_fingerprint": account,
        "trading_day": day,
        "connection_generation": generation,
        "environment_profile": profile,
    }


def _validate_public_snapshot(
    snapshot: Any,
    field: str,
    query_names: Sequence[str],
    *,
    allow_stage_a_reference_gap: bool = False,
) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        _fail(f"{field} snapshot is not a mapping")
    expected_schema = "backtrader.ctp.preflight.v1"
    if snapshot.get("schema_version") != expected_schema:
        _fail(f"{field} schema is invalid")
    evidence_errors = set(snapshot.get("evidence_errors") or ())
    allowed_stage_a_errors = {
        "margin_rate_query_incomplete",
        "commission_rate_query_incomplete",
    }
    evidence_complete = snapshot.get("evidence_complete") is True
    if not evidence_complete and not (
        allow_stage_a_reference_gap and evidence_errors and evidence_errors <= allowed_stage_a_errors
    ):
        _fail(f"{field} evidence_complete is not proven")
    for key in ("read_only_safe", "write_request_free"):
        if snapshot.get(key) is not True:
            _fail(f"{field} {key} is not proven")
    if evidence_errors - allowed_stage_a_errors:
        _fail(f"{field} contains evidence errors")
    query_results = snapshot.get("query_results")
    if not isinstance(query_results, Mapping) or not set(query_names).issubset(query_results):
        _fail(f"{field} query evidence is incomplete")
    request_ids: dict[str, Any] = {}
    for name in query_names:
        result = query_results[name]
        if not isinstance(result, Mapping) or result.get("complete") is not True:
            _fail(f"{field} query {name} is incomplete")
        request_id = result.get("request_id")
        if request_id in (None, ""):
            _fail(f"{field} query {name} request id is missing")
        request_ids[name] = request_id
    if len(set(request_ids.values())) != len(request_ids):
        _fail(f"{field} query request ids are not unique")
    return {**_identity(snapshot, field), "snapshot_sha256": _sha256(snapshot.get("snapshot_sha256"), f"{field}.snapshot_sha256"), "request_ids": request_ids}


def _bundle_scope(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        _fail("bundle snapshot is not a mapping")
    if snapshot.get("schema_version") != "backtrader.ctp.bundle-preflight.v2":
        _fail("bundle schema is invalid")
    for key in ("evidence_complete", "read_only_safe", "write_request_free", "flat"):
        if snapshot.get(key) is not True:
            _fail(f"bundle {key} is not proven")
    if snapshot.get("evidence_errors"):
        _fail("bundle contains evidence errors")
    legs = snapshot.get("legs")
    if not isinstance(legs, list) or len(legs) not in (2, 3):
        _fail("bundle must contain exactly two or three legs")
    authorized: list[str] = []
    primaries: list[str] = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            _fail("bundle leg is invalid")
        exchange = leg.get("exchange_id")
        instrument = leg.get("instrument_id")
        if not isinstance(exchange, str) or not isinstance(instrument, str):
            _fail("bundle leg identity is invalid")
        if not _IDENTIFIER_RE.fullmatch(exchange) or not _IDENTIFIER_RE.fullmatch(instrument):
            _fail("bundle leg identity is invalid")
        qualified = f"{exchange}.{instrument}"
        authorized.append(qualified)
        if leg.get("is_primary") is True:
            primaries.append(qualified)
        elif leg.get("is_primary") not in (False, None):
            _fail("bundle primary marker is invalid")
    if len(set(authorized)) != len(authorized) or authorized != sorted(authorized):
        _fail("bundle legs must be sorted and unique")
    if len(primaries) != 1:
        _fail("bundle must have exactly one primary leg")
    identity = _identity(snapshot, "bundle")
    return {
        **identity,
        "instrument": primaries[0],
        "authorized_instruments": authorized,
        "snapshot_sha256": _sha256(snapshot.get("snapshot_sha256"), "bundle.snapshot_sha256"),
    }


def _validate_gates(gates: Any) -> None:
    if gates != {"G1": "PASS", "G2": "PASS", "G3": "PASS"}:
        _fail("gate_statuses must be exactly G1/G2/G3 PASS")


def build_bundle_authorization(
    *,
    stage_a: Mapping[str, Any],
    stage_b: Mapping[str, Any],
    bundle_preflight: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
    strategy_id: str,
    strategy_identity_sha256: str,
    authorization_key_id: str,
    authorization_secret: str,
    issued_at_utc: Any,
    expires_at_utc: Any,
    receipt_sha256: str,
    native_sha256: str,
    ctp_package_sha256: str,
    source_hashes_sha256: str,
    dependency_hashes_sha256: str,
    evidence_hashes_sha256: str,
    runtime_executable_sha256: str,
    gate_statuses: Mapping[str, str],
) -> BundleAuthorizationArtifacts:
    """Build exact V2 grant/proof objects from caller-supplied evidence."""
    if not isinstance(strategy_id, str) or not strategy_id.strip():
        _fail("strategy_id is required")
    strategy_identity_sha256 = _sha256(strategy_identity_sha256, "strategy_identity_sha256")
    if not isinstance(authorization_key_id, str) or not authorization_key_id.strip():
        _fail("authorization_key_id is required")
    if not isinstance(authorization_secret, str) or len(authorization_secret.encode("utf-8")) < 32:
        _fail("authorization secret is unavailable")
    issued = _aware_datetime(issued_at_utc, "issued_at_utc")
    expires = _aware_datetime(expires_at_utc, "expires_at_utc")
    if issued >= expires or expires <= datetime.now(timezone.utc):
        _fail("authorization expiry is invalid")
    _validate_gates(gate_statuses)
    hashes = {
        "receipt_sha256": _sha256(receipt_sha256, "receipt_sha256"),
        "native_sha256": _sha256(native_sha256, "native_sha256"),
        "ctp_package_sha256": _sha256(ctp_package_sha256, "ctp_package_sha256"),
        "source_hashes_sha256": _sha256(source_hashes_sha256, "source_hashes_sha256"),
        "dependency_hashes_sha256": _sha256(dependency_hashes_sha256, "dependency_hashes_sha256"),
        "evidence_hashes_sha256": _sha256(evidence_hashes_sha256, "evidence_hashes_sha256"),
        "runtime_executable_sha256": _sha256(runtime_executable_sha256, "runtime_executable_sha256"),
    }
    a = _validate_public_snapshot(
        stage_a, "stage_a", STAGE_A_QUERY_NAMES, allow_stage_a_reference_gap=True
    )
    b = _validate_public_snapshot(stage_b, "stage_b", STAGE_B_QUERY_NAMES)
    bundle = _bundle_scope(bundle_preflight)
    identity = _runtime_identity(runtime_identity)
    if any(a[key] != b[key] or a[key] != bundle[key] or a[key] != identity[key] for key in identity):
        _fail("snapshot and runtime identities do not match")
    stage_b_primary = f"{stage_b.get('exchange_id')}.{stage_b.get('instrument_id')}"
    if stage_b_primary.casefold() != bundle["instrument"].casefold():
        _fail("Stage B primary does not match bundle primary")
    if set(a["request_ids"].values()).intersection(b["request_ids"].values()):
        _fail("Stage A/B query request ids are not independent")

    proof = {
        "account_fingerprint": identity["account_fingerprint"],
        "trading_day": identity["trading_day"],
        "instrument": bundle["instrument"],
        "connection_generation": identity["connection_generation"],
        "environment_profile": identity["environment_profile"],
        **{
            key: hashes[key]
            for key in (
                "receipt_sha256",
                "native_sha256",
                "ctp_package_sha256",
                "source_hashes_sha256",
                "dependency_hashes_sha256",
            )
        },
        "preflight_sha256": bundle["snapshot_sha256"],
        "scope_version": _CTP_EXECUTION_ARM_BUNDLE_SCOPE_VERSION,
        "authorized_instruments": bundle["authorized_instruments"],
    }
    if set(proof) != _CTP_EXECUTION_ARM_BUNDLE_FIELDS:
        _fail("internal V2 arming proof shape mismatch")
    unsigned_grant = {
        "schema_version": AUTHORIZATION_SCHEMA,
        "authorization_kind": AUTHORIZATION_KIND,
        "authorization_key_id": authorization_key_id,
        "issued_at_utc": issued.isoformat(),
        "expires_at_utc": expires.isoformat(),
        **proof,
        "stage_a_snapshot_sha256": a["snapshot_sha256"],
        "stage_a_query_request_ids": a["request_ids"],
        "stage_b_snapshot_sha256": b["snapshot_sha256"],
        "stage_b_query_request_ids": b["request_ids"],
        "runtime_executable_sha256": hashes["runtime_executable_sha256"],
        "evidence_hashes_sha256": hashes["evidence_hashes_sha256"],
        "gate_statuses": dict(gate_statuses),
    }
    if set(unsigned_grant) | {"signature_hmac_sha256"} != _CTP_EXECUTION_AUTHORIZATION_BUNDLE_FIELDS:
        _fail("internal V2 authorization grant shape mismatch")
    signature = hmac.new(authorization_secret.encode("utf-8"), _canonical(unsigned_grant), hashlib.sha256).hexdigest()
    grant = {**unsigned_grant, "signature_hmac_sha256": signature}
    summary = {
        "status": "BUILT_NOT_ARMED",
        "grant_sha256": hashlib.sha256(_canonical(grant)).hexdigest(),
        "arming_proof_sha256": hashlib.sha256(_canonical(proof)).hexdigest(),
        "account_fingerprint_sha256": hashlib.sha256(identity["account_fingerprint"].encode()).hexdigest(),
        "scope_version": proof["scope_version"],
        "authorized_instruments": list(proof["authorized_instruments"]),
        "strategy_identity_sha256": strategy_identity_sha256,
        "issued_at_utc": grant["issued_at_utc"],
        "expires_at_utc": grant["expires_at_utc"],
        "gate_statuses": dict(gate_statuses),
    }
    return BundleAuthorizationArtifacts(grant=grant, arming_proof=proof, summary=summary)
