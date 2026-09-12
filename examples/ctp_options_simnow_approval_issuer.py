"""Operator-owned Ed25519 issuer for the Iter23-25 entry approval artifact.

The SimNow operator is the approval authority in the demo governance model:
this tool generates the operator keypair, emits the matching trust root, and
signs ``ctp-execution-entry-approval-v1`` artifacts from a sealed SDK approval
context.  The private key never leaves the operator key file and is never
printed or logged.

Subcommands:

* ``keygen``: create ``<key-file>`` with one Ed25519 keypair (fails if exists).
* ``trust-root``: emit the deployment trust-root JSON for the SDK/Store.
* ``sign``: build and sign one entry approval artifact from an approval
  context JSON (as produced by the operator's ``approval_context`` purpose).

The signing payload exactly mirrors the SDK verifier contract: unknown or
missing fields fail closed, and the artifact-level schema matches the payload
schema.  The three entry hash fields (receipt/source/ctp package) bind the
operator admission receipt and the running deployment material.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ENTRY_SCHEMA = "ctp-execution-entry-approval-v1"
TRUST_ROOT_SCHEMA = "ctp-execution-trust-root-v1"
ALGORITHM = "Ed25519"
PURPOSE = "ctp_execution_approval"
_BUNDLE_SCOPE_VERSION = "ctp-contract-bundle-v1"

_CONTEXT_PAYLOAD_FIELDS = (
    "candidate_id",
    "strategy_id",
    "strategy_identity_sha256",
    "execution_cycle_id",
    "authorized_instruments",
    "primary_instrument",
    "account_fingerprint",
    "trading_day",
    "connection_generation",
    "environment_profile",
    "configuration_sha256",
    "backtrader_sha256",
    "bt_api_py_sha256",
    "bt_api_ctp_sha256",
    "bt_api_base_sha256",
    "native_sha256",
    "dependency_hashes_sha256",
    "preflight_sha256",
    "evidence_sha256",
    "budget_policy_id",
    "budget_limit",
    "future_reservation_id",
)


class IssuerError(RuntimeError):
    """A fail-closed issuer precondition."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _load_key(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise IssuerError(f"KEY_FILE_MISSING:{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IssuerError("KEY_FILE_INVALID") from exc
    if (
        not isinstance(data, dict)
        or data.get("algorithm") != ALGORITHM
        or not str(data.get("key_id") or "").strip()
        or not str(data.get("private_key") or "").strip()
        or not str(data.get("public_key") or "").strip()
    ):
        raise IssuerError("KEY_FILE_INVALID")
    return data


def _private_signing_key(material: Mapping[str, str]):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except (ImportError, ModuleNotFoundError) as exc:
        raise IssuerError("CRYPTOGRAPHY_UNAVAILABLE") from exc
    try:
        private_bytes = base64.urlsafe_b64decode(
            str(material["private_key"]) + "=" * (-len(str(material["private_key"])) % 4)
        )
        key = Ed25519PrivateKey.from_private_bytes(private_bytes)
    except Exception as exc:
        raise IssuerError("KEY_FILE_INVALID") from exc
    public_raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    expected = base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("=")
    if expected != str(material["public_key"]).strip():
        raise IssuerError("KEY_FILE_PUBLIC_MISMATCH")
    return key


def command_keygen(args: argparse.Namespace) -> int:
    key_file = Path(args.key_file)
    if key_file.exists():
        raise IssuerError(f"KEY_FILE_EXISTS:{key_file}")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    except (ImportError, ModuleNotFoundError) as exc:
        raise IssuerError("CRYPTOGRAPHY_UNAVAILABLE") from exc
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    private_raw = private.private_bytes_raw()
    material = {
        "algorithm": ALGORITHM,
        "key_id": str(args.key_id or f"simnow-operator-{uuid.uuid4().hex[:8]}"),
        "created_at_utc": _iso(_now()),
        "private_key": base64.urlsafe_b64encode(private_raw).decode("ascii").rstrip("="),
        "public_key": base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("="),
    }
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(
        json.dumps(material, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    key_file.chmod(0o600)
    print(
        json.dumps(
            {
                "status": "KEYGEN_OK",
                "key_file": str(key_file),
                "key_id": material["key_id"],
                "public_key": material["public_key"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_trust_root(args: argparse.Namespace) -> int:
    material = _load_key(Path(args.key_file))
    now = _now()
    root = {
        "schema_version": TRUST_ROOT_SCHEMA,
        "keys": {
            material["key_id"]: {
                "public_key": material["public_key"],
                "role": str(args.role or "independent_operator"),
                "purposes": [PURPOSE, "ctp_execution_recovery"],
                "not_before": _iso(now - timedelta(minutes=1)),
                "expires_at": _iso(now + timedelta(days=365)),
            }
        },
        "revocation_snapshot": {
            "version": 1,
            "issued_at": _iso(now - timedelta(minutes=1)),
            "expires_at": _iso(now + timedelta(days=365)),
            "revoked_approval_ids": [],
            "revoked_nonces": [],
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(root, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "TRUST_ROOT_OK",
                "output": str(output),
                "key_id": material["key_id"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_entry_payload(
    context: Mapping[str, Any],
    *,
    key_id: str,
    issuer_role: str,
    receipt_sha256: str,
    source_hashes_sha256: str,
    ctp_package_sha256: str,
    approval_id: str | None = None,
    nonce: str | None = None,
    validity_minutes: int = 30,
) -> dict[str, Any]:
    """Build the exact entry approval payload from one sealed context view."""

    missing = [field for field in _CONTEXT_PAYLOAD_FIELDS if field not in context]
    if missing:
        raise IssuerError(f"CONTEXT_MISSING:{','.join(missing)}")
    unknown = set(context) - set(_CONTEXT_PAYLOAD_FIELDS) - {"source", "context_source"}
    if unknown:
        raise IssuerError(f"CONTEXT_UNKNOWN_FIELDS:{','.join(sorted(unknown))}")
    for name, value in (
        ("receipt_sha256", receipt_sha256),
        ("source_hashes_sha256", source_hashes_sha256),
        ("ctp_package_sha256", ctp_package_sha256),
    ):
        if len(str(value)) != 64 or any(c not in "0123456789abcdef" for c in str(value)):
            raise IssuerError(f"{name.upper()}_INVALID")
    instruments = context["authorized_instruments"]
    if not isinstance(instruments, list) or not 2 <= len(instruments) <= 3:
        raise IssuerError("AUTHORIZED_INSTRUMENTS_INVALID")
    qualified = sorted(
        f"{leg['exchange_id']}.{leg['instrument_id']}" for leg in instruments
    )
    if qualified != [
        f"{leg['exchange_id']}.{leg['instrument_id']}" for leg in instruments
    ]:
        raise IssuerError("AUTHORIZED_INSTRUMENTS_NOT_SORTED_UNIQUE")
    primary = context["primary_instrument"]
    primary_qualified = f"{primary['exchange_id']}.{primary['instrument_id']}"
    if primary_qualified not in qualified:
        raise IssuerError("PRIMARY_NOT_IN_AUTHORIZED_SCOPE")
    if {item.partition(".")[0] for item in qualified} != {
        primary_qualified.partition(".")[0]
    }:
        raise IssuerError("AUTHORIZED_INSTRUMENTS_CROSS_EXCHANGE")
    now = _now()
    payload = {
        "schema_version": ENTRY_SCHEMA,
        "algorithm": ALGORITHM,
        "approval_id": str(approval_id or f"entry-{uuid.uuid4().hex[:12]}"),
        "nonce": str(nonce or f"nonce-{uuid.uuid4().hex}"),
        "issuer_key_id": str(key_id),
        "issuer_role": str(issuer_role),
        "purpose": PURPOSE,
        "context_source": "sdk_runtime",
        **{field: context[field] for field in _CONTEXT_PAYLOAD_FIELDS},
        "receipt_sha256": receipt_sha256,
        "source_hashes_sha256": source_hashes_sha256,
        "ctp_package_sha256": ctp_package_sha256,
        "issued_at": _iso(now - timedelta(seconds=1)),
        "not_before": _iso(now - timedelta(seconds=1)),
        "expires_at": _iso(now + timedelta(minutes=int(validity_minutes))),
        "revocation_snapshot_version": 1,
    }
    return payload


def sign_payload(payload: Mapping[str, Any], private_key: Any) -> dict[str, Any]:
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    signature = private_key.sign(payload_bytes)
    return {
        "schema_version": ENTRY_SCHEMA,
        "algorithm": ALGORITHM,
        "payload": dict(payload),
        "signature": base64.urlsafe_b64encode(signature).decode("ascii").rstrip("="),
    }


def command_sign(args: argparse.Namespace) -> int:
    material = _load_key(Path(args.key_file))
    private_key = _private_signing_key(material)
    context_path = Path(args.context)
    if not context_path.is_file():
        raise IssuerError(f"CONTEXT_FILE_MISSING:{context_path}")
    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IssuerError("CONTEXT_FILE_INVALID") from exc
    payload = build_entry_payload(
        context,
        key_id=material["key_id"],
        issuer_role=str(args.role or "independent_operator"),
        receipt_sha256=str(args.receipt_sha256),
        source_hashes_sha256=str(args.source_hashes_sha256),
        ctp_package_sha256=str(args.ctp_package_sha256),
        validity_minutes=int(args.validity_minutes),
    )
    artifact = sign_payload(payload, private_key)
    artifact["payload_sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "ARTIFACT_SIGNED",
                "output": str(output),
                "approval_id": payload["approval_id"],
                "expires_at": payload["expires_at"],
                "authorized_instruments": sorted(
                    f"{leg['exchange_id']}.{leg['instrument_id']}"
                    for leg in payload["authorized_instruments"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen = subparsers.add_parser("keygen")
    keygen.add_argument("--key-file", type=Path, required=True)
    keygen.add_argument("--key-id")

    trust_root = subparsers.add_parser("trust-root")
    trust_root.add_argument("--key-file", type=Path, required=True)
    trust_root.add_argument("--role")
    trust_root.add_argument("--output", type=Path, required=True)

    sign = subparsers.add_parser("sign")
    sign.add_argument("--key-file", type=Path, required=True)
    sign.add_argument("--context", type=Path, required=True)
    sign.add_argument("--role")
    sign.add_argument("--receipt-sha256", required=True)
    sign.add_argument("--source-hashes-sha256", required=True)
    sign.add_argument("--ctp-package-sha256", required=True)
    sign.add_argument("--validity-minutes", type=int, default=30)
    sign.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    handlers = {
        "keygen": command_keygen,
        "trust-root": command_trust_root,
        "sign": command_sign,
    }
    try:
        return handlers[args.command](args)
    except IssuerError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
