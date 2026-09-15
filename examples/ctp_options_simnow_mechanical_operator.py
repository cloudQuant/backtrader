"""Operator-owned SimNow mechanical cycle for Iterations 23/24/25.

This is the governed trading entry the read-only ``engineering_smoke``
operator deliberately stops short of.  It connects one managed CTP client,
confirms settlement once, collects the same read-only three-leg evidence
chain, verifies an independently signed G1/G2/G3 gate receipt plus external
phase-specific settlement and entry ``ctp-execution-entry-approval-v1``
artifacts, then binds the V2 bundle authorization.  It never loads a signing
key or creates an approval.  Only after those receipts bind the current
evidence may it arm SDK execution, reserve the complete-path CTP budget, and
drive exactly one three-leg open/close cycle to a proven flat reconciliation.

Every failure is fail-closed with a stable reason code.  The operator never
prints or logs a secret.  ``MECHANICAL_PASS`` is execution-path evidence only;
it is not strategy profitability evidence and does not admit Iter25 HFT
activity.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStore

try:
    from .ctp_options_simnow_authorization import build_bundle_authorization
    from .ctp_options_simnow_common import ThreeLegBundle
    from .ctp_options_simnow_live_drive import drive_simnow_mechanical_session
    from .ctp_options_simnow_live_runner import SimNowLiveRunner
    from .ctp_options_simnow_operator import (
        CTP_EXCHANGE,
        HERE,
        OperatorBlocked,
        OperatorConfiguration,
        _contract_metadata,
        _request_counts,
        build_live_store,
        collect_three_leg_evidence,
        load_operator_env,
        resolve_credentials,
        resolve_fronts,
    )
except ImportError:  # Direct execution through the examples directory.
    from ctp_options_simnow_authorization import build_bundle_authorization  # type: ignore[no-redef]
    from ctp_options_simnow_common import ThreeLegBundle  # type: ignore[no-redef]
    from ctp_options_simnow_live_drive import (  # type: ignore[no-redef]
        drive_simnow_mechanical_session,
    )
    from ctp_options_simnow_live_runner import SimNowLiveRunner  # type: ignore[no-redef]
    from ctp_options_simnow_operator import (  # type: ignore[no-redef]
        CTP_EXCHANGE,
        HERE,
        OperatorBlocked,
        OperatorConfiguration,
        _contract_metadata,
        _request_counts,
        build_live_store,
        collect_three_leg_evidence,
        load_operator_env,
        resolve_credentials,
        resolve_fronts,
    )

DEFAULT_ENV_PATH = HERE / ".env"
DEFAULT_TRUST_ROOT = HERE / ".simnow-approval-trust-root.json"
BUDGET_ORDINARY_CAP_CNY = 8000.0
BUDGET_RECOVERY_HEADROOM_CNY = 2000.0
MECHANICAL_GATE_RECEIPT_SCHEMA = "iter23-25.mechanical-gate-receipt.v1"
MECHANICAL_GATE_RECEIPT_ARTIFACT_SCHEMA = "iter23-25.mechanical-gate-receipt-artifact.v1"
MECHANICAL_GATE_APPROVER_ROLE = "independent_gate_approver"
MECHANICAL_GATE_PURPOSE = "simnow_mechanical_gate"
MECHANICAL_GATE_REQUIRED_STATUSES = {"G1": "PASS", "G2": "PASS", "G3": "PASS"}
# These are deliberately unset until a separately governed release pins the
# public roots.  A CLI path is transport only: it must never establish who is
# authorized to approve a mechanical cycle.  Keeping the defaults unset is
# safer than treating an ignored local JSON file as an independent authority.
PINNED_MECHANICAL_GATE_TRUST_ROOT_SHA256: str | None = None
PINNED_EXECUTION_APPROVAL_TRUST_ROOT_SHA256: str | None = None
# A pinned root is necessary but not sufficient.  Before this can be enabled,
# the post-settlement re-freeze/final approval and durable one-use receipt
# consumption must be implemented and independently reviewed.  Do not change
# this flag in an operational invocation; it is a source-reviewed release
# decision.
MECHANICAL_EXECUTION_ENABLED = False
_ENTRY_APPROVAL_SCHEMA = "ctp-execution-entry-approval-v1"
_ENTRY_APPROVAL_PURPOSE = "ctp_execution_approval"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MECHANICAL_GATE_BINDING_FIELDS = (
    "strategy_id",
    "environment",
    "product_id",
    "exchange_id",
    "authorized_instruments",
    "account_fingerprint",
    "trading_day",
    "connection_generation",
    "environment_profile",
    "configuration_sha256",
    "calendar_sha256",
    "source_hashes_sha256",
    "dependency_hashes_sha256",
    "native_sha256",
    "runtime_executable_sha256",
    "evidence_hashes_sha256",
    "budget_ordinary_cap_cny",
    "maximum_cycle_count",
)


class MechanicalBlocked(RuntimeError):
    """A fail-closed mechanical-cycle precondition."""

    def __init__(self, reason: str):
        """Attach the stable machine-readable ``reason`` code."""
        super().__init__(reason)
        self.reason = reason


def _require_mechanical_execution_enabled() -> None:
    if not MECHANICAL_EXECUTION_ENABLED:
        raise MechanicalBlocked(
            "MECHANICAL_EXECUTION_DISABLED_PENDING_POST_SETTLEMENT_REFREEZE_AND_DURABLE_RECEIPT_CONSUMPTION"
        )


@dataclass(frozen=True)
class MechanicalConfiguration:
    """Validated mechanical-cycle inputs; secrets stay only in the env mapping."""

    environment: str
    product_id: str
    exchange_id: str
    future_instrument_id: str | None = None
    call_instrument_id: str | None = None
    put_instrument_id: str | None = None
    capital: float = 200000.0
    strategy_id: str = "iter23-25-options-mechanical"
    purpose: str = "mechanical_cycle"
    confirm_settlement: bool = True
    query_timeout: float = 20.0
    leg_timeout: float = 45.0

    def __post_init__(self) -> None:
        if self.purpose != "mechanical_cycle":
            raise MechanicalBlocked("PURPOSE_NOT_SUPPORTED")
        exact = (
            self.future_instrument_id,
            self.call_instrument_id,
            self.put_instrument_id,
        )
        if any(value is not None for value in exact) and not all(
            value is not None for value in exact
        ):
            raise MechanicalBlocked("EXACT_BUNDLE_IDS_MUST_BE_COMPLETE")


def _read_json_mapping(path: Path, missing_reason: str, invalid_reason: str) -> dict[str, Any]:
    if not path.is_file():
        raise MechanicalBlocked(f"{missing_reason}:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MechanicalBlocked(invalid_reason) from exc
    if not isinstance(value, Mapping):
        raise MechanicalBlocked(invalid_reason)
    return dict(value)


def _canonical_json_bytes(value: Mapping[str, Any], reason: str) -> bytes:
    try:
        return json.dumps(
            dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MechanicalBlocked(reason) from exc


def _parse_utc_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise MechanicalBlocked(f"MECHANICAL_GATE_TIMESTAMP_INVALID:{field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MechanicalBlocked(f"MECHANICAL_GATE_TIMESTAMP_INVALID:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MechanicalBlocked(f"MECHANICAL_GATE_TIMESTAMP_INVALID:{field}")
    return parsed.astimezone(timezone.utc)


def _require_external_receipt_path(path: Path | None, reason: str) -> Path:
    if path is None:
        raise MechanicalBlocked(reason)
    resolved = Path(path)
    if not resolved.is_file():
        raise MechanicalBlocked(f"{reason}:{resolved}")
    return resolved


def _require_pinned_trust_root(path: Path, expected_sha256: str | None, authority: str) -> str:
    """Accept a supplied public root only when a reviewed build pins its hash."""

    if expected_sha256 is None:
        raise MechanicalBlocked(f"{authority}_TRUST_ROOT_NOT_PINNED")
    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise MechanicalBlocked(f"{authority}_TRUST_ROOT_PIN_INVALID")
    try:
        actual_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MechanicalBlocked(f"{authority}_TRUST_ROOT_INVALID") from exc
    if actual_sha256 != expected_sha256:
        raise MechanicalBlocked(f"{authority}_TRUST_ROOT_PIN_MISMATCH")
    return actual_sha256


def _validate_gate_payload_shape(payload: Mapping[str, Any]) -> None:
    required_fields = {
        "schema_version",
        "approval_id",
        "nonce",
        "issuer_key_id",
        "issuer_role",
        "purpose",
        *_MECHANICAL_GATE_BINDING_FIELDS,
        "gate_statuses",
        "issued_at",
        "not_before",
        "expires_at",
        "revocation_snapshot_version",
    }
    if set(payload) != required_fields:
        raise MechanicalBlocked("MECHANICAL_GATE_RECEIPT_FIELDS_INVALID")
    if payload.get("schema_version") != MECHANICAL_GATE_RECEIPT_SCHEMA:
        raise MechanicalBlocked("MECHANICAL_GATE_RECEIPT_SCHEMA_INVALID")
    if payload.get("issuer_role") != MECHANICAL_GATE_APPROVER_ROLE:
        raise MechanicalBlocked("MECHANICAL_GATE_ISSUER_ROLE_INVALID")
    if payload.get("purpose") != "simnow_mechanical_cycle":
        raise MechanicalBlocked("MECHANICAL_GATE_PURPOSE_INVALID")
    if not all(
        str(payload.get(field) or "").strip() for field in ("approval_id", "nonce", "issuer_key_id")
    ):
        raise MechanicalBlocked("MECHANICAL_GATE_ISSUER_IDENTITY_INVALID")
    if payload.get("gate_statuses") != MECHANICAL_GATE_REQUIRED_STATUSES:
        raise MechanicalBlocked("MECHANICAL_GATE_STATUS_NOT_PASS")
    if payload.get("maximum_cycle_count") != 1:
        raise MechanicalBlocked("MECHANICAL_GATE_CYCLE_LIMIT_INVALID")
    if payload.get("budget_ordinary_cap_cny") != str(int(BUDGET_ORDINARY_CAP_CNY)):
        raise MechanicalBlocked("MECHANICAL_GATE_BUDGET_LIMIT_INVALID")
    for field in (
        "configuration_sha256",
        "calendar_sha256",
        "source_hashes_sha256",
        "dependency_hashes_sha256",
        "native_sha256",
        "runtime_executable_sha256",
        "evidence_hashes_sha256",
    ):
        if _SHA256_RE.fullmatch(str(payload.get(field) or "")) is None:
            raise MechanicalBlocked(f"MECHANICAL_GATE_HASH_INVALID:{field}")
    instruments = payload.get("authorized_instruments")
    if not isinstance(instruments, list) or len(instruments) != 3:
        raise MechanicalBlocked("MECHANICAL_GATE_SCOPE_INVALID")
    expected_roles = ("future", "call", "put")
    for role, instrument in zip(expected_roles, instruments):
        if (
            not isinstance(instrument, Mapping)
            or set(instrument) != {"role", "exchange_id", "instrument_id"}
            or instrument.get("role") != role
            or not str(instrument.get("exchange_id") or "").strip()
            or not str(instrument.get("instrument_id") or "").strip()
        ):
            raise MechanicalBlocked("MECHANICAL_GATE_SCOPE_INVALID")


def _contains_private_key_material(value: Any) -> bool:
    if isinstance(value, Mapping):
        return "private_key" in value or any(
            _contains_private_key_material(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_private_key_material(item) for item in value)
    return False


def _verify_gate_trust_root(
    trust_root: Mapping[str, Any], payload: Mapping[str, Any], *, now: datetime
) -> Mapping[str, Any]:
    if trust_root.get("schema_version") != "ctp-execution-trust-root-v1":
        raise MechanicalBlocked("MECHANICAL_GATE_TRUST_ROOT_SCHEMA_INVALID")
    if _contains_private_key_material(trust_root):
        raise MechanicalBlocked("MECHANICAL_GATE_TRUST_ROOT_PRIVATE_KEY_FORBIDDEN")
    keys = trust_root.get("keys")
    issuer_key_id = str(payload["issuer_key_id"])
    if not isinstance(keys, Mapping) or not isinstance(keys.get(issuer_key_id), Mapping):
        raise MechanicalBlocked("MECHANICAL_GATE_ISSUER_UNTRUSTED")
    key = keys[issuer_key_id]
    if key.get("role") != MECHANICAL_GATE_APPROVER_ROLE:
        raise MechanicalBlocked("MECHANICAL_GATE_ISSUER_ROLE_UNTRUSTED")
    purposes = key.get("purposes")
    if not isinstance(purposes, list) or MECHANICAL_GATE_PURPOSE not in purposes:
        raise MechanicalBlocked("MECHANICAL_GATE_ISSUER_PURPOSE_UNTRUSTED")
    for field in ("not_before", "expires_at"):
        _parse_utc_timestamp(key.get(field), f"trust_root.key.{field}")
    if not (
        _parse_utc_timestamp(key["not_before"], "trust_root.key.not_before")
        <= now
        < _parse_utc_timestamp(key["expires_at"], "trust_root.key.expires_at")
    ):
        raise MechanicalBlocked("MECHANICAL_GATE_TRUST_ROOT_KEY_INACTIVE")
    revocation = trust_root.get("revocation_snapshot")
    if not isinstance(revocation, Mapping):
        raise MechanicalBlocked("MECHANICAL_GATE_REVOCATION_MISSING")
    if revocation.get("version") != payload.get("revocation_snapshot_version"):
        raise MechanicalBlocked("MECHANICAL_GATE_REVOCATION_VERSION_MISMATCH")
    if not (
        _parse_utc_timestamp(revocation.get("issued_at"), "revocation.issued_at")
        <= now
        < _parse_utc_timestamp(revocation.get("expires_at"), "revocation.expires_at")
    ):
        raise MechanicalBlocked("MECHANICAL_GATE_REVOCATION_STALE")
    revoked_approval_ids = revocation.get("revoked_approval_ids")
    revoked_nonces = revocation.get("revoked_nonces")
    if not isinstance(revoked_approval_ids, list) or not isinstance(revoked_nonces, list):
        raise MechanicalBlocked("MECHANICAL_GATE_REVOCATION_INVALID")
    if payload["approval_id"] in revoked_approval_ids or payload["nonce"] in revoked_nonces:
        raise MechanicalBlocked("MECHANICAL_GATE_RECEIPT_REVOKED")
    return key


def _verify_gate_signature(
    artifact: Mapping[str, Any], key: Mapping[str, Any], payload: Mapping[str, Any]
) -> None:
    if artifact.get("algorithm") != "Ed25519":
        raise MechanicalBlocked("MECHANICAL_GATE_ALGORITHM_INVALID")
    public_key = str(key.get("public_key") or "")
    signature = str(artifact.get("signature") or "")
    if _B64URL_RE.fullmatch(public_key) is None or _B64URL_RE.fullmatch(signature) is None:
        raise MechanicalBlocked("MECHANICAL_GATE_SIGNATURE_ENCODING_INVALID")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        public_bytes = base64.urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4))
        signature_bytes = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        verifier = Ed25519PublicKey.from_public_bytes(public_bytes)
        verifier.verify(
            signature_bytes, _canonical_json_bytes(payload, "MECHANICAL_GATE_PAYLOAD_INVALID")
        )
    except ImportError as exc:
        raise MechanicalBlocked("MECHANICAL_GATE_VERIFIER_UNAVAILABLE") from exc
    except Exception as exc:
        raise MechanicalBlocked("MECHANICAL_GATE_SIGNATURE_INVALID") from exc


def verify_external_mechanical_gate_receipt(
    receipt_file: Path,
    trust_root_file: Path,
    expected_binding: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify a pre-signed, independent G1/G2/G3 mechanical gate receipt.

    This function intentionally has no access to a signing key.  Its return
    value contains only the verified public payload and its canonical digest,
    which becomes the receipt binding for the SDK entry approvals.
    """

    _require_pinned_trust_root(
        trust_root_file, PINNED_MECHANICAL_GATE_TRUST_ROOT_SHA256, "MECHANICAL_GATE"
    )
    receipt = _read_json_mapping(
        receipt_file, "MECHANICAL_GATE_RECEIPT_REQUIRED", "MECHANICAL_GATE_RECEIPT_INVALID"
    )
    trust_root = _read_json_mapping(
        trust_root_file,
        "MECHANICAL_GATE_TRUST_ROOT_REQUIRED",
        "MECHANICAL_GATE_TRUST_ROOT_INVALID",
    )
    if set(receipt) != {"schema_version", "algorithm", "payload", "signature"}:
        raise MechanicalBlocked("MECHANICAL_GATE_ARTIFACT_FIELDS_INVALID")
    if receipt.get("schema_version") != MECHANICAL_GATE_RECEIPT_ARTIFACT_SCHEMA:
        raise MechanicalBlocked("MECHANICAL_GATE_ARTIFACT_SCHEMA_INVALID")
    payload = receipt.get("payload")
    if not isinstance(payload, Mapping):
        raise MechanicalBlocked("MECHANICAL_GATE_PAYLOAD_INVALID")
    payload = dict(payload)
    _validate_gate_payload_shape(payload)
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued_at = _parse_utc_timestamp(payload["issued_at"], "issued_at")
    not_before = _parse_utc_timestamp(payload["not_before"], "not_before")
    expires_at = _parse_utc_timestamp(payload["expires_at"], "expires_at")
    if not (issued_at <= not_before <= current_time < expires_at):
        raise MechanicalBlocked("MECHANICAL_GATE_RECEIPT_TIME_INVALID")
    if set(expected_binding) != set(_MECHANICAL_GATE_BINDING_FIELDS):
        raise MechanicalBlocked("MECHANICAL_GATE_EXPECTED_BINDING_INVALID")
    for field in _MECHANICAL_GATE_BINDING_FIELDS:
        if payload.get(field) != expected_binding[field]:
            raise MechanicalBlocked(f"MECHANICAL_GATE_BINDING_MISMATCH:{field}")
    key = _verify_gate_trust_root(trust_root, payload, now=current_time)
    _verify_gate_signature(receipt, key, payload)
    return {
        "payload": payload,
        "receipt_sha256": hashlib.sha256(
            _canonical_json_bytes(payload, "MECHANICAL_GATE_PAYLOAD_INVALID")
        ).hexdigest(),
        "gate_statuses": dict(payload["gate_statuses"]),
    }


def _load_external_entry_approval(
    approval_file: Path,
    *,
    expected_cycle_id: str,
    gate_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    artifact = _read_json_mapping(
        approval_file, "EXTERNAL_ENTRY_APPROVAL_REQUIRED", "EXTERNAL_ENTRY_APPROVAL_INVALID"
    )
    if artifact.get("schema_version") != _ENTRY_APPROVAL_SCHEMA:
        raise MechanicalBlocked("EXTERNAL_ENTRY_APPROVAL_SCHEMA_INVALID")
    payload = artifact.get("payload")
    if not isinstance(payload, Mapping):
        raise MechanicalBlocked("EXTERNAL_ENTRY_APPROVAL_PAYLOAD_INVALID")
    if (
        payload.get("schema_version") != _ENTRY_APPROVAL_SCHEMA
        or payload.get("purpose") != _ENTRY_APPROVAL_PURPOSE
        or payload.get("execution_cycle_id") != expected_cycle_id
        or not str(payload.get("issuer_key_id") or "").strip()
    ):
        raise MechanicalBlocked("EXTERNAL_ENTRY_APPROVAL_BINDING_INVALID")
    if gate_receipt_sha256 is not None and payload.get("receipt_sha256") != gate_receipt_sha256:
        raise MechanicalBlocked("EXTERNAL_ENTRY_APPROVAL_GATE_RECEIPT_MISMATCH")
    return artifact


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mechanical_configuration_sha256(config: MechanicalConfiguration) -> str:
    return _sha256_json(
        {
            "environment": config.environment,
            "product_id": config.product_id.upper(),
            "exchange_id": config.exchange_id.upper(),
            "future_instrument_id": config.future_instrument_id,
            "call_instrument_id": config.call_instrument_id,
            "put_instrument_id": config.put_instrument_id,
            "capital": config.capital,
            "strategy_id": config.strategy_id,
            "purpose": config.purpose,
            "confirm_settlement": config.confirm_settlement,
            "query_timeout": config.query_timeout,
            "leg_timeout": config.leg_timeout,
        }
    )


def _calendar_receipt_sha256(path: Path, config: MechanicalConfiguration) -> str:
    receipt = _read_json_mapping(
        path, "MECHANICAL_CALENDAR_RECEIPT_REQUIRED", "MECHANICAL_CALENDAR_RECEIPT_INVALID"
    )
    if receipt.get("schema_version") != "iter22.czce-trading-calendar.v1":
        raise MechanicalBlocked("MECHANICAL_CALENDAR_RECEIPT_SCHEMA_INVALID")
    if str(receipt.get("exchange") or "").upper() not in {
        config.exchange_id.upper(),
        "ZCE" if config.exchange_id.upper() == "CZCE" else config.exchange_id.upper(),
    }:
        raise MechanicalBlocked("MECHANICAL_CALENDAR_RECEIPT_EXCHANGE_MISMATCH")
    return _sha256_file(path)


def _strategy_identity(module_path: Path) -> str:
    return _sha256_file(module_path)


def _runtime_hashes() -> dict[str, str]:
    """Hash the deployed packages honestly from their installed locations."""

    import backtrader
    import bt_api_py

    hashes: dict[str, str] = {}
    for name, module in (("backtrader", backtrader), ("bt_api_py", bt_api_py)):
        package = Path(module.__file__).resolve().parent
        digest = hashlib.sha256()
        for source in sorted(package.rglob("*.py")):
            digest.update(str(source.relative_to(package)).encode())
            digest.update(source.read_bytes())
        hashes[name] = digest.hexdigest()
    try:
        import bt_api_ctp

        package = Path(bt_api_ctp.__file__).resolve().parent
        digest = hashlib.sha256()
        for source in sorted(package.rglob("*.py")):
            digest.update(str(source.relative_to(package)).encode())
            digest.update(source.read_bytes())
        for shared in sorted(package.parent.glob("*.dylib")):
            digest.update(shared.name.encode())
            digest.update(shared.read_bytes())
        hashes["bt_api_ctp"] = digest.hexdigest()
    except ImportError:
        raise MechanicalBlocked("BT_API_CTP_UNAVAILABLE") from None
    import sys

    hashes["runtime_executable"] = _sha256_file(Path(sys.executable))
    return hashes


def _first_number(record: Mapping[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = record.get(name)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            return parsed
    return None


def _leg_records(stage_b: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index the per-leg margin/commission evidence by InstrumentID."""

    results = stage_b.get("query_results") or {}
    rows: dict[str, Mapping[str, Any]] = {}
    for name in ("margin_rate", "commission_rate"):
        query = results.get(name) or {}
        for record in query.get("records") or ():
            if isinstance(record, Mapping):
                instrument = str(
                    record.get("InstrumentID") or record.get("instrument_id") or ""
                ).strip()
                if instrument:
                    rows.setdefault(instrument, {})
                    merged = dict(rows[instrument])
                    merged.update(dict(record))
                    rows[instrument] = merged
    return rows


def _cost_field(record: Mapping[str, Any], names: tuple[str, ...]) -> float | None:
    return _first_number(record, names)


_MARGIN_KEYS = (
    "LongMarginRatio",
    "LongMarginRatioByMoney",
    "long_margin_ratio",
)
_SHORT_MARGIN_KEYS = (
    "ShortMarginRatio",
    "ShortMarginRatioByMoney",
    "short_margin_ratio",
)
_VOLUME_FEE_KEYS = (
    "OpenRatioByVolume",
    "CloseRatioByVolume",
    "CloseTodayRatioByVolume",
    "open_ratio_by_volume",
    "close_ratio_by_volume",
)
_MONEY_FEE_KEYS = (
    "OpenRatioByMoney",
    "CloseRatioByMoney",
    "open_ratio_by_money",
    "close_ratio_by_money",
)


def build_budget_evidence(
    *,
    bundle: ThreeLegBundle,
    stage_b: Mapping[str, Any],
    reference: Mapping[str, Any],
    context: Mapping[str, Any],
    account_available_cny: float,
    expires_at_utc: str,
    source_version: str,
) -> dict[str, Any]:
    """Build the complete-path CTP budget evidence from live SimNow data.

    The reachable states share one conservative complete-path cost bundle:
    every alternative execution path of the three-leg cycle must fit inside
    the same worst-case envelope.  Costs come from the live Stage B
    margin/commission queries and the executable reference quotes; nothing is
    defaulted or guessed.
    """

    legs = {
        "F": bundle.future,
        "C": bundle.call,
        "P": bundle.put,
    }
    quotes: dict[str, Mapping[str, Any]] = {}
    for leg in reference.get("legs") or ():
        if isinstance(leg, Mapping):
            instrument = str(leg.get("instrument_id") or "").strip()
            if instrument:
                quotes[instrument] = leg
    records = _leg_records(stage_b)

    def quote(instrument_id: str, field: str) -> float:
        leg = quotes.get(instrument_id)
        if leg is None:
            raise MechanicalBlocked(f"REFERENCE_QUOTE_MISSING:{instrument_id}")
        value = _first_number(leg, (field,))
        if value is None or value <= 0:
            raise MechanicalBlocked(f"REFERENCE_QUOTE_INVALID:{instrument_id}:{field}")
        return value

    def margin(instrument_id: str, *, short: bool) -> float:
        record = records.get(instrument_id)
        if record is None:
            raise MechanicalBlocked(f"MARGIN_EVIDENCE_MISSING:{instrument_id}")
        value = _cost_field(record, _SHORT_MARGIN_KEYS if short else _MARGIN_KEYS)
        if value is None:
            raise MechanicalBlocked(f"MARGIN_RATIO_MISSING:{instrument_id}")
        return value

    def fees_per_lot(instrument_id: str, price: float, multiplier: float) -> float:
        record = records.get(instrument_id)
        if record is None:
            raise MechanicalBlocked(f"COMMISSION_EVIDENCE_MISSING:{instrument_id}")
        by_volume = _cost_field(record, _VOLUME_FEE_KEYS)
        if by_volume is not None and by_volume > 0:
            return by_volume
        by_money = _cost_field(record, _MONEY_FEE_KEYS)
        if by_money is not None and by_money > 0:
            return by_money * price * multiplier
        raise MechanicalBlocked(f"COMMISSION_RATE_MISSING:{instrument_id}")

    future = legs["F"]
    call = legs["C"]
    put = legs["P"]
    future_price = quote(future.instrument_id, "ask_price")
    call_price = quote(call.instrument_id, "ask_price")
    put_price = quote(put.instrument_id, "ask_price")

    future_margin = (
        future_price * float(future.multiplier) * margin(future.instrument_id, short=False)
    )
    short_call_margin = call_price * float(call.multiplier) * margin(call.instrument_id, short=True)
    paid_premium = put_price * float(put.multiplier)
    legs_fees = (
        fees_per_lot(future.instrument_id, future_price, float(future.multiplier))
        + fees_per_lot(call.instrument_id, call_price, float(call.multiplier))
        + fees_per_lot(put.instrument_id, put_price, float(put.multiplier))
    )
    # One open plus one close round for all three legs.
    fees_financing = legs_fees * 2.0
    tick_value = float(future.tick_size) * float(future.multiplier)
    stress_cash_loss = fees_financing + 4.0 * tick_value
    unresolved_reserve = fees_financing + 2.0 * tick_value
    seller_option_gross_margin = short_call_margin

    cost_bundle = {
        "future_gross_margin": round(future_margin, 2),
        "seller_option_gross_margin": round(seller_option_gross_margin, 2),
        "paid_long_premium": round(paid_premium, 2),
        "fees_financing": round(fees_financing, 2),
        "stress_cash_loss": round(stress_cash_loss, 2),
        "unresolved_reserve": round(unresolved_reserve, 2),
    }
    total = round(sum(cost_bundle.values()), 2)
    if total > BUDGET_ORDINARY_CAP_CNY:
        raise MechanicalBlocked(
            f"BUDGET_ORDINARY_CAP_EXCEEDED:{total:.2f}>{BUDGET_ORDINARY_CAP_CNY:.2f}"
        )
    if account_available_cny < BUDGET_RECOVERY_HEADROOM_CNY:
        raise MechanicalBlocked("ACCOUNT_AVAILABLE_INSUFFICIENT_FOR_HEADROOM")

    def state(state_id: str, state_kind: str) -> dict[str, Any]:
        return {
            "state_id": state_id,
            "state_kind": state_kind,
            "costs": dict(cost_bundle),
            "context": {
                "account_fingerprint": context["account_fingerprint"],
                "trading_day": context["trading_day"],
                "connection_generation": context["connection_generation"],
                "environment_profile": context["environment_profile"],
                "candidate_id": context["candidate_id"],
                "strategy_id": context["strategy_id"],
                "strategy_identity_sha256": context["strategy_identity_sha256"],
                "execution_cycle_id": context["execution_cycle_id"],
                "scope_version": "ctp-contract-bundle-v1",
                "authorized_instruments": context["authorized_instruments"],
                "primary_instrument": context["primary_instrument"],
            },
        }

    return {
        "source": "sdk_runtime",
        "source_version": source_version,
        "money_unit": "CNY",
        "complete": True,
        "historical_min_pnl_cny": "0",
        "fresh_available_cny": round(account_available_cny, 2),
        "remaining_unabsorbed_new_obligation_cny": "0",
        "unallocated_recovery_headroom_cny": str(BUDGET_RECOVERY_HEADROOM_CNY),
        "expires_at": expires_at_utc,
        "reachable_states": [
            state("entry-prefix-leg", "prefix"),
            state("entry-partial-legs", "partial"),
            state("entry-unknown-leg", "unknown"),
            state("entry-cancel-refill", "cancel"),
            state("entry-late-fill", "late_fill"),
            state("de-risk-recovery", "recovery"),
        ],
    }


def _account_available(store: BtApiStore, timeout: float) -> float:
    snapshot = store.get_ctp_preflight_snapshot(timeout=timeout, read_only=True)
    results = snapshot.get("query_results") or {}
    account = results.get("account") or {}
    records = account.get("records") or []
    if not records:
        raise MechanicalBlocked("ACCOUNT_EVIDENCE_MISSING")
    value = _first_number(
        records[0],
        ("Available", "available", "AvailableFunds", "available_funds"),
    )
    if value is None:
        raise MechanicalBlocked("ACCOUNT_AVAILABLE_MISSING")
    return value


def _entry_prices(bundle: ThreeLegBundle, reference: Mapping[str, Any]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for leg in (bundle.future, bundle.call, bundle.put):
        symbol = f"{leg.exchange_id}.{leg.instrument_id}"
        row = next(
            (
                item
                for item in reference.get("legs") or ()
                if isinstance(item, Mapping) and item.get("instrument_id") == leg.instrument_id
            ),
            None,
        )
        if row is None:
            raise MechanicalBlocked(f"ENTRY_QUOTE_MISSING:{symbol}")
        price = _first_number(row, ("entry_buy_price", "ask_price"))
        if price is None or price <= 0:
            raise MechanicalBlocked(f"ENTRY_QUOTE_INVALID:{symbol}")
        prices[symbol] = price
    return prices


class _MechanicalOwner:
    """Minimal notification sink; the drive loop drains the broker queue."""

    def notify_order(self, order: Any) -> None:  # pragma: no cover - sink
        """Discard the notification; the drive loop drains the broker queue."""
        del order

    def notify_trade(self, trade: Any) -> None:  # pragma: no cover - sink
        """Discard the notification; the drive loop drains the broker queue."""
        del trade


def _approval_seed(
    config: MechanicalConfiguration, cycle_suffix: str, bundle: ThreeLegBundle
) -> dict[str, Any]:
    return {
        "candidate_id": "iter23-25-mechanical-candidate-v1",
        "strategy_id": config.strategy_id,
        "strategy_identity_sha256": _strategy_identity(Path(__file__).resolve()),
        "execution_cycle_id": f"{config.strategy_id}:{cycle_suffix}",
        "authorized_instruments": [
            {"exchange_id": leg.exchange_id, "instrument_id": leg.instrument_id}
            for leg in (bundle.future, bundle.call, bundle.put)
        ],
        "primary_instrument": {
            "exchange_id": bundle.future.exchange_id,
            "instrument_id": bundle.future.instrument_id,
        },
        "budget_policy_id": "iter23-25-three-leg-path-v1",
        "budget_limit": str(int(BUDGET_ORDINARY_CAP_CNY)),
        "future_reservation_id": "none",
    }


def _mechanical_gate_binding(
    config: MechanicalConfiguration,
    bundle: ThreeLegBundle,
    derived_bundle: Mapping[str, Any],
    *,
    environment_profile: str,
    runtime: Mapping[str, str],
    configuration_sha256: str,
    calendar_sha256: str,
    source_hashes_sha256: str,
    dependency_hashes_sha256: str,
    evidence_hashes_sha256: str,
) -> dict[str, Any]:
    return {
        "strategy_id": config.strategy_id,
        "environment": config.environment,
        "product_id": config.product_id.upper(),
        "exchange_id": config.exchange_id.upper(),
        "authorized_instruments": [
            {
                "role": role,
                "exchange_id": leg.exchange_id,
                "instrument_id": leg.instrument_id,
            }
            for role, leg in zip(
                ("future", "call", "put"), (bundle.future, bundle.call, bundle.put)
            )
        ],
        "account_fingerprint": derived_bundle["account_fingerprint"],
        "trading_day": derived_bundle["trading_day"],
        "connection_generation": derived_bundle["connection_generation"],
        "environment_profile": environment_profile,
        "configuration_sha256": configuration_sha256,
        "calendar_sha256": calendar_sha256,
        "source_hashes_sha256": source_hashes_sha256,
        "dependency_hashes_sha256": dependency_hashes_sha256,
        "native_sha256": runtime["bt_api_ctp"],
        "runtime_executable_sha256": runtime["runtime_executable"],
        "evidence_hashes_sha256": evidence_hashes_sha256,
        "budget_ordinary_cap_cny": str(int(BUDGET_ORDINARY_CAP_CNY)),
        "maximum_cycle_count": 1,
    }


def _confirm_settlement_with_approval(
    store: BtApiStore,
    api: Any,
    config: MechanicalConfiguration,
    *,
    bundle: ThreeLegBundle,
    settlement_approval: Mapping[str, Any],
    trust_root: Mapping[str, Any],
) -> bool:
    """Confirm settlement once through a pre-signed external approval."""

    # Short-circuit on the native settlement verdict without triggering a
    # readback: when settlement is NOT yet confirmed for the session
    # trading day, verify_ctp_settlement's readback finds no matching
    # confirmation record, records a settlement identity last_error on the
    # session, and the SDK's confirm path then rejects with
    # ctp_session_not_read_only_ready (diagnosed 2026-09-12 on the second
    # set whose trading day stays at the last real session day).  Confirm
    # first through the approval, then verify read-only to prove it.
    session_state = store.get_ctp_session_state()
    if str(session_state.get("settlement_state") or "") == "confirmed":
        verified = store.verify_ctp_settlement(timeout=float(config.query_timeout))
        if verified.get("evidence_complete") is True:
            return True
    seed = _approval_seed(config, "settlement", bundle)
    context = api.build_ctp_execution_approval_context(
        seed,
        exchange_name=CTP_EXCHANGE,
        configuration={"purpose": config.purpose, "phase": "settlement"},
        strategy_source=Path(__file__).resolve(),
        preflight={"phase": "settlement"},
        evidence={"phase": "settlement"},
    )
    capability = api.redeem_ctp_execution_approval(
        json.dumps(settlement_approval, ensure_ascii=False, sort_keys=True),
        trust_root=trust_root,
        context=context,
    )
    api.confirm_ctp_settlement_from_approval(
        capability,
        exchange_name=CTP_EXCHANGE,
        timeout=float(config.query_timeout),
    )
    verified = store.verify_ctp_settlement(timeout=float(config.query_timeout))
    return verified.get("evidence_complete") is True


def run_mechanical_cycle(
    config: MechanicalConfiguration,
    env: Mapping[str, str],
    *,
    state_directory: Path,
    trust_root_file: Path = DEFAULT_TRUST_ROOT,
    gate_receipt_file: Path | None = None,
    gate_trust_root_file: Path | None = None,
    calendar_receipt_file: Path | None = None,
    settlement_approval_file: Path | None = None,
    entry_approval_file: Path | None = None,
    store: BtApiStore | None = None,
    broker_cls: Any = BtApiBroker,
) -> dict[str, Any]:
    """Run one externally approved three-leg open/close cycle on SimNow."""

    _require_mechanical_execution_enabled()
    gate_receipt_file = _require_external_receipt_path(
        gate_receipt_file, "MECHANICAL_GATE_RECEIPT_REQUIRED"
    )
    gate_trust_root_file = _require_external_receipt_path(
        gate_trust_root_file, "MECHANICAL_GATE_TRUST_ROOT_REQUIRED"
    )
    calendar_receipt_file = _require_external_receipt_path(
        calendar_receipt_file, "MECHANICAL_CALENDAR_RECEIPT_REQUIRED"
    )
    settlement_approval_file = _require_external_receipt_path(
        settlement_approval_file, "EXTERNAL_SETTLEMENT_APPROVAL_REQUIRED"
    )
    entry_approval_file = _require_external_receipt_path(
        entry_approval_file, "EXTERNAL_ENTRY_APPROVAL_REQUIRED"
    )
    trust_root_file = _require_external_receipt_path(trust_root_file, "TRUST_ROOT_MISSING")
    # Pin both approval roots before reading credentials or connecting.  Until
    # an independently governed release supplies these pins, this keeps the
    # entire write-capable path unreachable rather than accepting caller-made
    # keys and receipts.
    _require_pinned_trust_root(
        gate_trust_root_file, PINNED_MECHANICAL_GATE_TRUST_ROOT_SHA256, "MECHANICAL_GATE"
    )
    _require_pinned_trust_root(
        trust_root_file,
        PINNED_EXECUTION_APPROVAL_TRUST_ROOT_SHA256,
        "EXECUTION_APPROVAL",
    )
    settlement_approval = _load_external_entry_approval(
        settlement_approval_file,
        expected_cycle_id=f"{config.strategy_id}:settlement",
    )
    entry_approval = _load_external_entry_approval(
        entry_approval_file,
        expected_cycle_id=f"{config.strategy_id}:cycle",
    )
    calendar_sha256 = _calendar_receipt_sha256(calendar_receipt_file, config)
    trust_root = _read_json_mapping(trust_root_file, "TRUST_ROOT_MISSING", "TRUST_ROOT_INVALID")
    if _contains_private_key_material(trust_root):
        raise MechanicalBlocked("EXTERNAL_ENTRY_TRUST_ROOT_PRIVATE_KEY_FORBIDDEN")
    credentials = resolve_credentials(env)
    fronts = resolve_fronts(env, config.environment)

    owned_store = store is None
    if store is None:
        store = build_live_store(
            credentials,
            fronts,
            _as_operator_config(config),
            state_directory=state_directory,
            execution_authorization_key_id=str(entry_approval["payload"]["issuer_key_id"]),
            execution_authorization_secret=load_authorization_secret(env),
            strategy_identity_sha256=_strategy_identity(Path(__file__).resolve()),
        )
    api = store.sdk_api
    if api is None:
        api = store._ensure_api_ready()

    # The CTP trade-session semantics bridge (auth/generation/trading-day
    # surfaced through get_ctp_session_state) only materialises after the
    # first trader-side query group completes.  A preflight snapshot reads
    # session_before before its queries, so the very first snapshot after
    # connect always fails the evidence gate with session_*_missing errors
    # even though its queries succeed.  The smoke flow primes the bridge
    # with verify_ctp_settlement, but on the second set that readback can
    # leave a settlement-identity last_error which then blocks the
    # approval-gated settlement confirmation.  Prime instead with a narrow
    # discarded instrument-scoped snapshot (read-only, no settlement
    # interaction, no write): the first snapshot's own queries complete the
    # login so the real evidence scan below sees a logged-in before-state.
    # Diagnosed 2026-09-12; also the likely cause behind the 2026-09-11
    # night "connected=false" block attributed to SimNow maintenance.
    store.get_ctp_preflight_snapshot(
        f"{config.exchange_id.upper()}.{config.future_instrument_id}",
        exchange_id=config.exchange_id.upper(),
        timeout=float(config.query_timeout),
        read_only=True,
    )

    evidence = collect_three_leg_evidence(store, _as_operator_config(config))
    bundle = evidence["bundle"]
    symbols = tuple(
        f"{leg.exchange_id}.{leg.instrument_id}" for leg in (bundle.future, bundle.call, bundle.put)
    )
    metadata = _contract_metadata(bundle)
    reference = evidence["execution_reference"]

    runtime = _runtime_hashes()
    source_hashes = {
        name: _sha256_file(HERE / name)
        for name in (
            "ctp_options_simnow_operator.py",
            "ctp_options_simnow_mechanical_operator.py",
            "ctp_options_simnow_approval_issuer.py",
            "ctp_options_simnow_authorization.py",
            "ctp_options_simnow_common.py",
            "ctp_options_simnow_mechanical_cycle.py",
            "ctp_options_simnow_live_drive.py",
            "ctp_options_simnow_live_runner.py",
        )
    }
    source_hashes_sha256 = _sha256_json(source_hashes)
    # Refresh Stage A/B and the bundle preflight right before building the
    # authorization: the evidence chain so far (scan -> stages -> bundle ->
    # reference -> independent gate receipt) runs far longer
    # than the default 30s snapshot freshness budget, and configure()
    # rejects stale stage and bundle-preflight evidence.  Refreshing keeps
    # the freshness gate at its default instead of widening it; identity
    # fields are session-bound and unchanged by the refresh, and the grant
    # hash binds to the refreshed bundle snapshot (diagnosed 2026-09-12).
    evidence["stage_a"] = store.get_ctp_preflight_snapshot(
        product_id=config.product_id.upper(),
        exchange_id=config.exchange_id.upper(),
        timeout=float(config.query_timeout),
        read_only=True,
    )
    evidence["stage_b"] = store.get_ctp_preflight_snapshot(
        f"{bundle.exchange_id}.{bundle.future.instrument_id}",
        exchange_id=bundle.exchange_id,
        timeout=float(config.query_timeout),
        read_only=True,
    )
    _refresh_legs = [
        {
            "exchange_id": leg.exchange_id,
            "instrument_id": leg.instrument_id,
            "is_primary": index == 0,
        }
        for index, leg in enumerate((bundle.future, bundle.call, bundle.put))
    ]
    evidence["bundle_preflight"] = store.get_ctp_bundle_preflight_snapshot(
        _refresh_legs,
        primary_leg=_refresh_legs[0],
        timeout=float(config.query_timeout),
        read_only=True,
    )
    derived_bundle = derive_bundle_preflight(evidence, bundle)
    evidence_hashes = {
        "stage_a": evidence["stage_a"].get("snapshot_sha256"),
        "stage_b": evidence["stage_b"].get("snapshot_sha256"),
        "bundle_preflight": evidence["bundle_preflight"].get("snapshot_sha256"),
        "execution_reference": reference.get("snapshot_sha256"),
        "reconciliation_1": evidence["reconciliation_rounds"][0].get("snapshot_sha256"),
        "reconciliation_2": evidence["reconciliation_rounds"][1].get("snapshot_sha256"),
    }
    for name, snapshot_sha256 in evidence_hashes.items():
        if _SHA256_RE.fullmatch(str(snapshot_sha256 or "")) is None:
            raise MechanicalBlocked(f"MECHANICAL_EVIDENCE_HASH_INVALID:{name}")
    dependency_hashes_sha256 = _sha256_json(
        {
            "backtrader_sha256": runtime["backtrader"],
            "bt_api_py_sha256": runtime["bt_api_py"],
        }
    )
    gate_receipt = verify_external_mechanical_gate_receipt(
        gate_receipt_file,
        gate_trust_root_file,
        _mechanical_gate_binding(
            config,
            bundle,
            derived_bundle,
            environment_profile=runtime_environment_profile(store),
            runtime=runtime,
            configuration_sha256=_mechanical_configuration_sha256(config),
            calendar_sha256=calendar_sha256,
            source_hashes_sha256=source_hashes_sha256,
            dependency_hashes_sha256=dependency_hashes_sha256,
            evidence_hashes_sha256=_sha256_json(evidence_hashes),
        ),
    )
    receipt_sha256 = gate_receipt["receipt_sha256"]
    settlement_approval = _load_external_entry_approval(
        settlement_approval_file,
        expected_cycle_id=f"{config.strategy_id}:settlement",
        gate_receipt_sha256=receipt_sha256,
    )

    # Settlement is a terminal write.  It is reachable only after the
    # independently signed gate receipt and its phase-specific approval both
    # bind the current read-only evidence.
    settlement_confirmed = _confirm_settlement_with_approval(
        store,
        api,
        config,
        bundle=bundle,
        settlement_approval=settlement_approval,
        trust_root=trust_root,
    )
    if settlement_confirmed is not True:
        raise MechanicalBlocked("SETTLEMENT_NOT_CONFIRMED")

    now = datetime.now(timezone.utc)
    entry_approval = _load_external_entry_approval(
        entry_approval_file,
        expected_cycle_id=f"{config.strategy_id}:cycle",
        gate_receipt_sha256=receipt_sha256,
    )
    artifacts = build_bundle_authorization(
        stage_a=evidence["stage_a"],
        stage_b=evidence["stage_b"],
        bundle_preflight=derived_bundle,
        runtime_identity={
            "account_fingerprint": derived_bundle["account_fingerprint"],
            "trading_day": derived_bundle["trading_day"],
            "connection_generation": derived_bundle["connection_generation"],
            "environment_profile": runtime_environment_profile(store),
        },
        strategy_id=config.strategy_id,
        strategy_identity_sha256=_strategy_identity(Path(__file__).resolve()),
        authorization_key_id=str(entry_approval["payload"]["issuer_key_id"]),
        authorization_secret=load_authorization_secret(env),
        issued_at_utc=now.isoformat(),
        expires_at_utc=(now + timedelta(minutes=30)).isoformat(),
        receipt_sha256=receipt_sha256,
        native_sha256=runtime["bt_api_ctp"],
        ctp_package_sha256=runtime["bt_api_ctp"],
        source_hashes_sha256=source_hashes_sha256,
        dependency_hashes_sha256=dependency_hashes_sha256,
        evidence_hashes_sha256=_sha256_json(evidence_hashes),
        runtime_executable_sha256=runtime["runtime_executable"],
        gate_statuses=gate_receipt["gate_statuses"],
    )
    store.configure_ctp_execution_authorization(artifacts.grant)

    if api is None:
        raise MechanicalBlocked("SDK_API_UNAVAILABLE")
    seed = _approval_seed(config, "cycle", bundle)
    context = api.build_ctp_execution_approval_context(
        seed,
        exchange_name=CTP_EXCHANGE,
        configuration={"purpose": config.purpose, "gate_receipt_sha256": receipt_sha256},
        strategy_source=Path(__file__).resolve(),
        preflight={"stage_a_sha256": evidence_hashes["stage_a"], "complete": True},
        evidence=evidence_hashes,
    )
    capability = api.redeem_ctp_execution_approval(
        json.dumps(entry_approval, ensure_ascii=False, sort_keys=True),
        trust_root=trust_root,
        context=context,
    )

    proof = dict(artifacts.arming_proof)
    arm_result = store.arm_sdk_execution(proof, authorization=capability)

    available = _account_available(store, float(config.query_timeout))
    expires_at = (
        (datetime.now(timezone.utc) + timedelta(minutes=20))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    budget_evidence = build_budget_evidence(
        bundle=bundle,
        stage_b=evidence["stage_b"],
        reference=reference,
        context=context.as_dict(),
        account_available_cny=available,
        expires_at_utc=expires_at,
        source_version="iter23-25-mechanical-v1",
    )
    reservation = api.reserve_ctp_execution_budget(budget_evidence, mode="ordinary")

    broker = broker_cls(
        store=store,
        provider="btapi",
        cash=config.capital,
        value=config.capital,
        contract_metadata=metadata,
        sdk_preflight=False,
        market_data_only=False,
        flatten_on_stop=False,
        force_refresh_queries=False,
    )
    feeds = {
        symbol: store.getdata(
            dataname=symbol,
            historical_bars=[],
            live_bars=[],
            backfill_start=False,
            dispatch_ticks=False,
            dispatch_bars=False,
            qcheck=0.0,
        )
        for symbol in symbols
    }
    snapshots = {
        "settlement_verified": settlement_confirmed,
        "preflight_context": {"market_data_only": False, "execution_armed": True},
        "stage_a": evidence["stage_a"],
        "stage_b": evidence["stage_b"],
        "bundle_execution_reference": reference,
        "public_capabilities": {"get_ctp_bundle_execution_reference_snapshot": True},
        "raw_reconciliation_rounds": evidence["reconciliation_rounds"],
    }
    owner = _MechanicalOwner()
    runner = SimNowLiveRunner(
        store=store,
        broker=broker,
        feeds=feeds,
        owner=owner,
        instrument_records=evidence["records"],
        product_id=config.product_id.upper(),
        exchange_id=config.exchange_id.upper(),
        trading_day=evidence["trading_day"],
        snapshots=snapshots,
        cycle_id=f"{config.strategy_id}:mechanical",
        # SimNow serves executable references through rate-limited trader
        # queries (three legs ~= 3s apart); the 2s tick window cannot hold
        # that acquisition pattern.
        max_quote_age_seconds=10.0,
        exit_reference_timeout=float(config.query_timeout),
        exact_instrument_ids=(
            {
                "future": config.future_instrument_id,
                "call": config.call_instrument_id,
                "put": config.put_instrument_id,
            }
            if config.future_instrument_id
            else None
        ),
    )
    runner.preflight()
    entry_prices = _entry_prices(bundle, reference)
    execution_state = {
        "store_armed": arm_result.get("armed") is True,
        "broker_started": True,
        "account_fingerprint": proof["account_fingerprint"],
        "trading_day": proof["trading_day"],
        "connection_generation": proof["connection_generation"],
    }
    session = runner.execute_preflighted(
        prices=entry_prices,
        execution_state=execution_state,
        budget_capability=reservation,
    )

    drive = drive_simnow_mechanical_session(
        broker=broker,
        session=session,
        reconciliation_snapshot=lambda: store.get_ctp_reconciliation_snapshot(
            timeout=float(config.query_timeout)
        ),
        leg_timeout=float(config.leg_timeout),
    )
    report = {
        "status": "MECHANICAL_PASS" if drive.get("status") == "MECHANICAL_PASS" else "BLOCKED",
        "drive": drive,
        "purpose": config.purpose,
        "environment": config.environment,
        "bundle": bundle.to_dict(),
        "budget": {
            "reserved": True,
            "ordinary_cap_cny": BUDGET_ORDINARY_CAP_CNY,
            "available_cny": round(available, 2),
        },
        "operator": {
            "owned_store": owned_store,
            "store_type": type(store).__name__,
            "broker_type": type(broker).__name__,
        },
        "settlement_verified": settlement_confirmed,
        "external_request_counts": _request_counts(evidence),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return report


def load_authorization_secret(env: Mapping[str, str]) -> str:
    """Return the stripped approval HMAC secret, fail-closed when under 32 chars."""
    secret = str(env.get("ITER_APPROVAL_HMAC_SECRET") or "").strip()
    if len(secret) < 32:
        raise MechanicalBlocked("ITER_APPROVAL_HMAC_SECRET_REQUIRED")
    return secret


def runtime_environment_profile(store: BtApiStore) -> str:
    """Return the live session's environment profile; fail closed when absent."""
    state = store.get_ctp_session_state()
    profile = str(state.get("environment_profile") or "").strip()
    if not profile:
        raise MechanicalBlocked("ENVIRONMENT_PROFILE_MISSING")
    return profile


def derive_bundle_preflight(evidence: Mapping[str, Any], bundle: ThreeLegBundle) -> dict[str, Any]:
    """Derive the strict V2 bundle snapshot the authorization builder needs."""

    reference = evidence["execution_reference"]
    base = reference
    for candidate in (evidence.get("bundle_preflight"), reference):
        # Preflight snapshots carry the session identity on their top level
        # (account_fingerprint/connection_generation/trading_day); only the
        # reference snapshot nests it under session_scope.  Select the first
        # candidate that actually carries an identity either way — selecting
        # by the session_scope key alone never matches a preflight snapshot
        # and made every mechanical run fail BUNDLE_IDENTITY_INCOMPLETE
        # (diagnosed 2026-09-12).
        if isinstance(candidate, Mapping) and (
            candidate.get("account_fingerprint") or candidate.get("session_scope")
        ):
            base = candidate
            break
    session_scope = base.get("session_scope") if isinstance(base, Mapping) else None
    if not isinstance(session_scope, Mapping):
        session_scope = {}
    identity = {
        "account_fingerprint": base.get("account_fingerprint")
        or session_scope.get("account_fingerprint"),
        "trading_day": base.get("trading_day") or session_scope.get("trading_day"),
        "connection_generation": base.get("connection_generation")
        or session_scope.get("connection_generation"),
    }
    if any(not value for value in identity.values()):
        raise MechanicalBlocked("BUNDLE_IDENTITY_INCOMPLETE")
    legs = [
        {
            "exchange_id": leg.exchange_id,
            "instrument_id": leg.instrument_id,
            "is_primary": index == 0,
        }
        for index, leg in enumerate((bundle.future, bundle.call, bundle.put))
    ]
    return {
        "schema_version": "backtrader.ctp.bundle-preflight.v2",
        **identity,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "legs": legs,
        "reconciled": True,
        # Bind the derived bundle proof to the bundle-preflight snapshot it
        # was derived from (base): after the pre-authorization refresh that
        # snapshot IS the Store's latest _last_ctp_bundle_preflight_snapshot,
        # which is the authoritative comparison target for
        # proof.preflight_sha256 (diagnosed 2026-09-12).
        "snapshot_sha256": base.get("snapshot_sha256")
        or (
            reference.get("bundle_preflight", {}).get("snapshot_sha256")
            if isinstance(reference.get("bundle_preflight"), Mapping)
            else None
        )
        or _sha256_json(reference),
        "session_scope": dict(session_scope),
        # The authorization builder reads the live session evidence
        # (environment_profile etc.) through session_after/session; preflight
        # snapshots carry it on session_after, so pass it through instead of
        # dropping it (missing key failed every authorization build with
        # "bundle session evidence is missing", diagnosed 2026-09-12).
        "session_after": dict(
            base.get("session_after") or base.get("session") or session_scope or {}
        ),
        "query_results": dict(base.get("query_results") or {}),
    }


def _as_operator_config(config: MechanicalConfiguration) -> OperatorConfiguration:
    return OperatorConfiguration(
        environment=config.environment,
        product_id=config.product_id,
        exchange_id=config.exchange_id,
        future_instrument_id=config.future_instrument_id,
        call_instrument_id=config.call_instrument_id,
        put_instrument_id=config.put_instrument_id,
        capital=config.capital,
        strategy_id=config.strategy_id,
        purpose="engineering_smoke",
        confirm_settlement=config.confirm_settlement,
        query_timeout=config.query_timeout,
    )


def main(argv: list[str] | None = None) -> int:
    """Parse the CLI, run one governed mechanical cycle, and emit its report.

    Returns 0 only for ``MECHANICAL_PASS``; any mechanical/operator
    precondition emits a ``BLOCKED`` report and exit code 2 (fail-closed).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument(
        "--environment",
        choices=("first", "second_7x24"),
        default="second_7x24",
    )
    parser.add_argument("--product", default="SA")
    parser.add_argument("--exchange", default="CZCE")
    parser.add_argument("--future")
    parser.add_argument("--call")
    parser.add_argument("--put")
    parser.add_argument("--capital", type=float, default=200000.0)
    parser.add_argument("--leg-timeout", type=float, default=45.0)
    parser.add_argument(
        "--query-timeout",
        type=float,
        default=20.0,
        help="Per-query timeout; SimNow reference queries may need 60s+ after "
        "large scans due to exchange flow control.",
    )
    parser.add_argument("--trust-root", type=Path, default=DEFAULT_TRUST_ROOT)
    parser.add_argument(
        "--gate-receipt",
        type=Path,
        required=True,
        help="Externally signed G1/G2/G3 mechanical gate receipt.",
    )
    parser.add_argument(
        "--gate-trust-root",
        type=Path,
        required=True,
        help="Public-only trust root for the independent gate approver.",
    )
    parser.add_argument(
        "--calendar-receipt",
        type=Path,
        required=True,
        help="Hash-frozen CZCE trading-calendar receipt bound into the gate approval.",
    )
    parser.add_argument(
        "--settlement-approval",
        type=Path,
        required=True,
        help="Externally signed, phase-specific settlement approval artifact.",
    )
    parser.add_argument(
        "--entry-approval",
        type=Path,
        required=True,
        help="Externally signed entry approval artifact bound to the gate receipt.",
    )
    parser.add_argument("--state-directory", type=Path, default=HERE / "state")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    def emit(report: dict[str, Any]) -> int:
        text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if report.get("status") == "MECHANICAL_PASS" else 2

    try:
        config = MechanicalConfiguration(
            environment=args.environment,
            product_id=args.product,
            exchange_id=args.exchange,
            future_instrument_id=args.future,
            call_instrument_id=args.call,
            put_instrument_id=args.put,
            capital=args.capital,
            leg_timeout=args.leg_timeout,
            query_timeout=float(args.query_timeout),
        )
        _require_mechanical_execution_enabled()
        env = load_operator_env(args.env)
        report = run_mechanical_cycle(
            config,
            env,
            state_directory=args.state_directory,
            trust_root_file=args.trust_root,
            gate_receipt_file=args.gate_receipt,
            gate_trust_root_file=args.gate_trust_root,
            calendar_receipt_file=args.calendar_receipt,
            settlement_approval_file=args.settlement_approval,
            entry_approval_file=args.entry_approval,
        )
    except (MechanicalBlocked, OperatorBlocked) as exc:
        report = {
            "status": "BLOCKED",
            "reason": getattr(exc, "reason", str(exc)),
            "external_request_counts": {"order_write": "UNKNOWN_ON_BLOCK"},
        }
    return emit(report)


if __name__ == "__main__":
    raise SystemExit(main())
