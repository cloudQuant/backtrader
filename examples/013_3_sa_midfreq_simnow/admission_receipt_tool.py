#!/usr/bin/env python
"""Build and explicitly sign secret-safe Iteration 22 admission receipts.

This is an offline approval artifact tool.  It does not load a ``.env`` file,
construct a CTP client, create a Store, open a socket, submit an order, or
generate an approval key.  The only secret it ever reads is the already
provisioned ``ITER22_APPROVAL_HMAC_KEY`` from the *process environment*, and
only on the explicit ``--sign`` path.  It never emits that value (or any CTP
credential) to stdout/stderr or to an artifact.

The workflow is deliberately two-step:

1. ``--input`` accepts a strict, non-secret fact document and writes a review
   request containing the current config/code/source/dependency bindings.
2. ``--request ... --sign`` revalidates that request against the current tree,
   signs it with the existing operator trust root, and asks ``run.py`` to
   validate the final receipt before it is published.

The resulting receipt is still only an admission input.  ``run.py`` performs
the live account, TradingDay, generation, preflight and execution-arming
checks at the irreversible CTP boundary.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from . import run as runner
except ImportError:  # Direct execution from this example directory.
    import run as runner


HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.yaml"
FACTS_SCHEMA = "iter22.admission-facts.v1"
REQUEST_SCHEMA = "iter22.admission-request.v1"
REQUEST_BINDING_SCHEMA = "iter22.admission-request-binding.v1"
RECEIPT_SCHEMA = "iter22.simnow-admission.v2"
MAX_RECEIPT_TTL_SECONDS = 2 * 60 * 60
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
PURPOSES = frozenset({"engineering_smoke", "natural_signal"})
GATES = frozenset({"G1", "G2", "G3"})
RUNTIME_FIELDS = frozenset(
    {
        "account_fingerprint",
        "trading_day",
        "instrument",
        "connection_generation",
        "environment_profile",
        "native_sha256",
        "ctp_package_sha256",
        "preflight_sha256",
        "stage_a_snapshot_sha256",
        "stage_b_snapshot_sha256",
        "stage_a_query_request_ids",
        "stage_b_query_request_ids",
    }
)
EVIDENCE_FIELDS = frozenset(
    {
        "gates",
        "evidence_hashes",
        "session_calendar_sha256",
        "signal_preregistration_sha256",
        "engineering_trigger",
    }
)
LIMIT_FIELDS = frozenset(
    {
        "maximum_lots",
        "maximum_write_requests",
        "remaining_smoke_attempts",
    }
)
REVIEWER_FIELDS = frozenset({"id", "approval_sha256"})
FACTS_FIELDS = frozenset(
    {
        "schema_version",
        "request_id",
        "purpose",
        "issued_at_utc",
        "expires_at_utc",
        "limits",
        "runtime",
        "evidence",
        "reviewer",
    }
)
REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "facts",
        "facts_sha256",
        "unsigned_receipt",
        "unsigned_receipt_sha256",
    }
)
TRIGGER_FIELDS = frozenset(
    {
        "trigger_id",
        "instrument",
        "trading_day",
        "side",
        "not_before_utc",
        "not_after_utc",
        "minimum_ingest_seq",
    }
)


class ReceiptToolError(RuntimeError):
    """A stable, non-secret failure code for the command-line wrapper."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise ReceiptToolError(code)


def _canonical_json(value: Any) -> bytes:
    """Encode a value exactly as the runner's HMAC contract requires."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code)
    return dict(value)


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], code: str) -> None:
    if set(value) != expected:
        _fail(code)


def _text(value: object, code: str, *, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        _fail(code)
    return result


def _hash(value: object, code: str) -> str:
    result = str(value or "").lower()
    if HEX64.fullmatch(result) is None:
        _fail(code)
    return result


def _positive_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail(code)
    return value


def _nonnegative_int(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(code)
    return value


def _parse_utc(value: object, code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        _fail(code)
    if parsed.tzinfo is None:
        _fail(code)
    return parsed.astimezone(timezone.utc)


def _positive_request_ids(value: object, code: str) -> dict[str, int]:
    mapping = _mapping(value, code)
    if not mapping:
        _fail(code)
    result: dict[str, int] = {}
    for name, request_id in mapping.items():
        key = _text(name, code, maximum=128)
        result[key] = _positive_int(request_id, code)
    return result


def _load_json_object(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _fail(code)
    return _mapping(payload, code)


def load_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    """Load the runner's frozen config without creating a CTP-facing object."""

    try:
        config, _ = runner.load_config(path)
    except Exception:
        _fail("config_unavailable_or_invalid")
    return config


def _validate_local_calendar(config: Mapping[str, Any]) -> None:
    """Require the runner's local hash-bound calendar before approval work.

    ``_load_trading_calendar`` only reads a local JSON artifact and verifies
    its contract/hash.  It neither discovers a calendar from the network nor
    constructs any CTP-facing object.
    """

    try:
        calendar = runner._load_trading_calendar(config)
    except Exception:
        _fail("calendar_artifact_unavailable_or_invalid")
    if calendar is None:
        _fail("calendar_artifact_unavailable_or_invalid")


def _validate_runtime(runtime: object, config: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(runtime, "runtime_mapping_invalid")
    _exact_keys(value, RUNTIME_FIELDS, "runtime_fields_invalid")
    account = _text(value.get("account_fingerprint"), "runtime_account_invalid", maximum=64)
    if re.fullmatch(r"acct_[0-9a-f]{16}", account) is None:
        _fail("runtime_account_invalid")
    trading_day = _text(value.get("trading_day"), "runtime_trading_day_invalid", maximum=8)
    if len(trading_day) != 8 or not trading_day.isdigit():
        _fail("runtime_trading_day_invalid")
    instrument = _text(value.get("instrument"), "runtime_instrument_invalid", maximum=16).upper()
    if runner.SA_PATTERN.fullmatch(instrument) is None:
        _fail("runtime_instrument_invalid")
    environment = _text(
        value.get("environment_profile"), "runtime_environment_invalid", maximum=128
    )
    if environment != str(config.get("environment") or ""):
        _fail("runtime_environment_mismatch")
    profile = _mapping(
        _mapping(config.get("profiles"), "config_profiles_invalid").get(environment),
        "config_profile_invalid",
    )
    if profile.get("kind") != "simnow" or profile.get("market_alignment") != "actual_market_hours":
        _fail("runtime_environment_not_actual_market_simnow")
    normalized = {
        "account_fingerprint": account,
        "trading_day": trading_day,
        "instrument": instrument,
        "connection_generation": _positive_int(
            value.get("connection_generation"), "runtime_generation_invalid"
        ),
        "environment_profile": environment,
        "native_sha256": _hash(value.get("native_sha256"), "runtime_native_hash_invalid"),
        "ctp_package_sha256": _hash(
            value.get("ctp_package_sha256"), "runtime_ctp_package_hash_invalid"
        ),
        "preflight_sha256": _hash(value.get("preflight_sha256"), "runtime_preflight_hash_invalid"),
        "stage_a_snapshot_sha256": _hash(
            value.get("stage_a_snapshot_sha256"), "runtime_stage_a_hash_invalid"
        ),
        "stage_b_snapshot_sha256": _hash(
            value.get("stage_b_snapshot_sha256"), "runtime_stage_b_hash_invalid"
        ),
        "stage_a_query_request_ids": _positive_request_ids(
            value.get("stage_a_query_request_ids"), "runtime_stage_a_request_ids_invalid"
        ),
        "stage_b_query_request_ids": _positive_request_ids(
            value.get("stage_b_query_request_ids"), "runtime_stage_b_request_ids_invalid"
        ),
    }
    return normalized


def _validate_trigger(value: object, runtime: Mapping[str, Any]) -> dict[str, Any]:
    trigger = _mapping(value, "engineering_trigger_invalid")
    _exact_keys(trigger, TRIGGER_FIELDS, "engineering_trigger_fields_invalid")
    if _text(trigger.get("trigger_id"), "engineering_trigger_id_invalid", maximum=256) == "":
        _fail("engineering_trigger_id_invalid")
    if str(trigger.get("instrument") or "").upper() != runtime["instrument"]:
        _fail("engineering_trigger_identity_mismatch")
    if str(trigger.get("trading_day") or "") != runtime["trading_day"]:
        _fail("engineering_trigger_identity_mismatch")
    if trigger.get("side") not in {"long", "short"}:
        _fail("engineering_trigger_side_invalid")
    before = _parse_utc(trigger.get("not_before_utc"), "engineering_trigger_time_invalid")
    after = _parse_utc(trigger.get("not_after_utc"), "engineering_trigger_time_invalid")
    if before >= after:
        _fail("engineering_trigger_time_invalid")
    minimum_sequence = _positive_int(
        trigger.get("minimum_ingest_seq"), "engineering_trigger_sequence_invalid"
    )
    return {
        "trigger_id": str(trigger["trigger_id"]),
        "instrument": runtime["instrument"],
        "trading_day": runtime["trading_day"],
        "side": str(trigger["side"]),
        "not_before_utc": str(trigger["not_before_utc"]),
        "not_after_utc": str(trigger["not_after_utc"]),
        "minimum_ingest_seq": minimum_sequence,
    }


def _validate_evidence(
    value: object, *, purpose: str, runtime: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    evidence = _mapping(value, "evidence_mapping_invalid")
    _exact_keys(evidence, EVIDENCE_FIELDS, "evidence_fields_invalid")
    gates = _mapping(evidence.get("gates"), "evidence_gates_invalid")
    _exact_keys(gates, GATES, "evidence_gates_invalid")
    if any(gates[name] != "PASS" for name in GATES):
        _fail("evidence_gates_not_pass")
    hashes = _mapping(evidence.get("evidence_hashes"), "evidence_hashes_invalid")
    _exact_keys(hashes, GATES, "evidence_hashes_invalid")
    normalized_hashes = {
        name: _hash(hashes[name], "evidence_hashes_invalid") for name in sorted(GATES)
    }
    calendar_hash = _hash(evidence.get("session_calendar_sha256"), "calendar_hash_invalid")
    configured_calendar_hash = str(
        _mapping(config.get("trading_calendar"), "config_calendar_invalid").get("sha256") or ""
    ).lower()
    if calendar_hash != configured_calendar_hash:
        _fail("calendar_hash_mismatch")
    signal_hash = evidence.get("signal_preregistration_sha256")
    trigger = evidence.get("engineering_trigger")
    if purpose == "natural_signal":
        signal_preregistration_hash = _hash(signal_hash, "signal_preregistration_hash_invalid")
        if trigger is not None:
            _fail("natural_signal_engineering_trigger_forbidden")
        return {
            "gates": dict.fromkeys(sorted(GATES), "PASS"),
            "evidence_hashes": normalized_hashes,
            "session_calendar_sha256": calendar_hash,
            "signal_preregistration_sha256": signal_preregistration_hash,
            "engineering_trigger": None,
        }
    if signal_hash is not None:
        _fail("engineering_smoke_signal_preregistration_forbidden")
    return {
        "gates": dict.fromkeys(sorted(GATES), "PASS"),
        "evidence_hashes": normalized_hashes,
        "session_calendar_sha256": calendar_hash,
        "signal_preregistration_sha256": None,
        "engineering_trigger": _validate_trigger(trigger, runtime),
    }


def _validate_limits(value: object, *, purpose: str, config: Mapping[str, Any]) -> dict[str, int]:
    limits = _mapping(value, "limits_mapping_invalid")
    _exact_keys(limits, LIMIT_FIELDS, "limits_fields_invalid")
    maximum_lots = _positive_int(limits.get("maximum_lots"), "maximum_lots_invalid")
    if maximum_lots != 1:
        _fail("maximum_lots_must_be_one")
    maximum_writes = _positive_int(
        limits.get("maximum_write_requests"), "maximum_write_requests_invalid"
    )
    config_maximum = _positive_int(
        _mapping(config.get("risk"), "config_risk_invalid").get("maximum_write_requests"),
        "config_risk_invalid",
    )
    if maximum_writes > config_maximum:
        _fail("maximum_write_requests_exceeds_config")
    remaining = _nonnegative_int(
        limits.get("remaining_smoke_attempts"), "remaining_smoke_attempts_invalid"
    )
    if purpose == "natural_signal" and remaining != 0:
        _fail("natural_signal_smoke_attempts_must_be_zero")
    if purpose == "engineering_smoke" and remaining <= 0:
        _fail("engineering_smoke_attempts_required")
    return {
        "maximum_lots": maximum_lots,
        "maximum_write_requests": maximum_writes,
        "remaining_smoke_attempts": remaining,
    }


def _validate_reviewer(value: object) -> dict[str, str]:
    reviewer = _mapping(value, "reviewer_mapping_invalid")
    _exact_keys(reviewer, REVIEWER_FIELDS, "reviewer_fields_invalid")
    return {
        "id": _text(reviewer.get("id"), "reviewer_id_invalid", maximum=256),
        "approval_sha256": _hash(reviewer.get("approval_sha256"), "reviewer_approval_hash_invalid"),
    }


def _validate_facts(facts: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    _exact_keys(facts, FACTS_FIELDS, "facts_fields_invalid")
    if facts.get("schema_version") != FACTS_SCHEMA:
        _fail("facts_schema_invalid")
    request_id = _text(facts.get("request_id"), "request_id_invalid", maximum=128)
    if REQUEST_ID.fullmatch(request_id) is None:
        _fail("request_id_invalid")
    purpose = str(facts.get("purpose") or "")
    if purpose not in PURPOSES:
        _fail("purpose_invalid")
    research = str(_mapping(config.get("research"), "config_research_invalid").get("status") or "")
    if research == "RESEARCH_REJECTED":
        _fail("research_rejected")
    if purpose == "natural_signal" and research != "RESEARCH_ADMITTED":
        _fail("natural_signal_requires_research_admitted")
    issued = _parse_utc(facts.get("issued_at_utc"), "receipt_validity_invalid")
    expires = _parse_utc(facts.get("expires_at_utc"), "receipt_validity_invalid")
    now = datetime.now(timezone.utc)
    if issued > now or expires <= now or issued >= expires:
        _fail("receipt_validity_invalid")
    if (expires - issued).total_seconds() > MAX_RECEIPT_TTL_SECONDS:
        _fail("receipt_ttl_exceeds_two_hours")
    runtime = _validate_runtime(facts.get("runtime"), config)
    evidence = _validate_evidence(
        facts.get("evidence"), purpose=purpose, runtime=runtime, config=config
    )
    limits = _validate_limits(facts.get("limits"), purpose=purpose, config=config)
    reviewer = _validate_reviewer(facts.get("reviewer"))
    return {
        "schema_version": FACTS_SCHEMA,
        "request_id": request_id,
        "purpose": purpose,
        "issued_at_utc": str(facts["issued_at_utc"]),
        "expires_at_utc": str(facts["expires_at_utc"]),
        "limits": limits,
        "runtime": runtime,
        "evidence": evidence,
        "reviewer": reviewer,
    }


def _current_source_identity() -> tuple[str, str, dict[str, str], dict[str, str]]:
    """Collect only local file/import metadata; no SDK client is constructed."""

    try:
        return (
            runner.code_hash(),
            _sha256_file(Path(__file__).resolve()),
            runner.source_file_hashes(),
            runner.dependency_identity_hashes(),
        )
    except Exception:
        _fail("current_source_identity_unavailable")


def build_request(facts: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    """Create a review request bound to the present runner configuration/tree.

    The returned object contains no signature or approval secret.  Its nested
    ``runtime_evidence`` preserves the complete, caller-supplied runtime
    snapshot, while runner-recognized fields preserve the immutable contract
    needed for final ``validate_receipt`` validation.
    """

    normalized = _validate_facts(_mapping(facts, "facts_mapping_invalid"), config)
    _validate_local_calendar(config)
    code_hash, tool_hash, source_hashes, dependency_hashes = _current_source_identity()
    runtime = normalized["runtime"]
    evidence = normalized["evidence"]
    binding = {
        "schema_version": REQUEST_BINDING_SCHEMA,
        "request_id": normalized["request_id"],
        "facts_sha256": _sha256_json(normalized),
        "runtime_sha256": _sha256_json(runtime),
        "evidence_sha256": _sha256_json(evidence),
        "config_hash": runner.config_hash(config),
        "code_hash": code_hash,
        "source_hashes_sha256": _sha256_json(source_hashes),
        "dependency_hashes_sha256": _sha256_json(dependency_hashes),
        "tool_source_sha256": tool_hash,
    }
    unsigned: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "candidate_id": config.get("candidate_id"),
        "config_hash": runner.config_hash(config),
        "code_hash": code_hash,
        "mode": "simnow",
        "purpose": normalized["purpose"],
        "environment": config.get("environment"),
        "issued_at_utc": normalized["issued_at_utc"],
        "expires_at_utc": normalized["expires_at_utc"],
        "gates": evidence["gates"],
        "maximum_lots": normalized["limits"]["maximum_lots"],
        "maximum_write_requests": normalized["limits"]["maximum_write_requests"],
        "remaining_smoke_attempts": normalized["limits"]["remaining_smoke_attempts"],
        "research_status": _mapping(config.get("research"), "config_research_invalid").get(
            "status"
        ),
        "instrument": runtime["instrument"],
        "account_fingerprint": runtime["account_fingerprint"],
        "trading_day": runtime["trading_day"],
        "source_hashes": source_hashes,
        "dependency_hashes": dependency_hashes,
        "native_sha256": runtime["native_sha256"],
        "ctp_package_sha256": runtime["ctp_package_sha256"],
        "reviewer": normalized["reviewer"],
        "evidence_hashes": evidence["evidence_hashes"],
        "research_config_sha256": _sha256_json(
            _mapping(config.get("research"), "config_research_invalid")
        ),
        "session_calendar_sha256": evidence["session_calendar_sha256"],
        "runtime_evidence": copy.deepcopy(runtime),
        "request_binding": binding,
    }
    if normalized["purpose"] == "natural_signal":
        unsigned["signal_preregistration_sha256"] = evidence["signal_preregistration_sha256"]
    else:
        trigger = evidence["engineering_trigger"]
        unsigned["engineering_trigger"] = trigger
        unsigned["engineering_trigger_sha256"] = _sha256_json(trigger)
    request = {
        "schema_version": REQUEST_SCHEMA,
        "facts": normalized,
        "facts_sha256": _sha256_json(normalized),
        "unsigned_receipt": unsigned,
        "unsigned_receipt_sha256": _sha256_json(unsigned),
    }
    return request


def validate_request(
    request: Mapping[str, Any], config: Mapping[str, Any]
) -> tuple[dict[str, Any], str]:
    """Rebuild an envelope from its facts and reject any stale/tampered field."""

    envelope = _mapping(request, "request_mapping_invalid")
    _exact_keys(envelope, REQUEST_FIELDS, "request_fields_invalid")
    if envelope.get("schema_version") != REQUEST_SCHEMA:
        _fail("request_schema_invalid")
    facts = _mapping(envelope.get("facts"), "request_facts_invalid")
    expected = build_request(facts, config)
    if not hmac.compare_digest(
        _hash(envelope.get("facts_sha256"), "request_facts_hash_invalid"), expected["facts_sha256"]
    ):
        _fail("request_facts_hash_mismatch")
    if not hmac.compare_digest(
        _hash(envelope.get("unsigned_receipt_sha256"), "request_unsigned_hash_invalid"),
        expected["unsigned_receipt_sha256"],
    ):
        _fail("request_unsigned_hash_mismatch")
    if not hmac.compare_digest(
        _canonical_json(_mapping(envelope.get("unsigned_receipt"), "request_unsigned_invalid")),
        _canonical_json(expected["unsigned_receipt"]),
    ):
        _fail("request_unsigned_receipt_mismatch")
    return copy.deepcopy(expected["unsigned_receipt"]), str(expected["facts"]["purpose"])


def _approval_trust_root(environment: Mapping[str, str]) -> tuple[str, str]:
    key_id = str(environment.get("ITER22_APPROVAL_KEY_ID") or "").strip()
    key = str(environment.get("ITER22_APPROVAL_HMAC_KEY") or "")
    if not key_id or len(key.encode("utf-8")) < 32:
        _fail("approval_trust_root_unavailable")
    return key_id, key


def sign_request(
    request: Mapping[str, Any],
    config: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    """Sign a validated review request using an existing process trust root."""

    unsigned, purpose = validate_request(request, config)
    key_id, key = _approval_trust_root(os.environ)
    receipt = {**unsigned, "approval_key_id": key_id}
    receipt["signature_hmac_sha256"] = hmac.new(
        key.encode("utf-8"), _canonical_json(receipt), hashlib.sha256
    ).hexdigest()
    return receipt, purpose


def _write_json(path: Path, payload: Mapping[str, Any], *, overwrite: bool) -> None:
    destination = path.resolve()
    if destination.exists() and not overwrite:
        _fail("output_already_exists")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.iter22-tmp")
        if temporary.exists():
            _fail("output_temporary_path_exists")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
    except ReceiptToolError:
        raise
    except OSError:
        try:
            if "temporary" in locals() and temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        _fail("output_write_failed")


def write_request(
    facts: Mapping[str, Any],
    config: Mapping[str, Any],
    output: Path | str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a non-secret, unsigned review request at ``output``."""

    request = build_request(facts, config)
    _write_json(Path(output), request, overwrite=overwrite)
    return request


def sign_validate_and_write_request(
    request: Mapping[str, Any],
    config: Mapping[str, Any],
    output: Path | str,
    *,
    overwrite: bool = False,
) -> tuple[dict[str, Any], str]:
    """Sign, runner-validate, then atomically publish a final receipt.

    Validation intentionally happens against a temporary file before the final
    destination is replaced.  A bad signature, expired time window, source
    drift, or runner-contract mismatch therefore never becomes a published
    receipt.
    """

    receipt, purpose = sign_request(request, config)
    destination = Path(output).resolve()
    if destination.exists() and not overwrite:
        _fail("output_already_exists")
    temporary = destination.with_name(f".{destination.name}.iter22-validation-tmp")
    if temporary.exists():
        _fail("output_temporary_path_exists")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            runner.validate_receipt(
                temporary,
                config=config,
                mode="simnow",
                purpose=purpose,
            )
        except Exception:
            _fail("runner_contract_validation_failed")
        temporary.replace(destination)
    except ReceiptToolError:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        raise
    except OSError:
        try:
            if temporary.exists():
                temporary.unlink()
        except OSError:
            pass
        _fail("output_write_failed")
    return receipt, _sha256_file(destination)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input", type=Path, help="non-secret facts JSON; creates a review request"
    )
    source.add_argument("--request", type=Path, help="review request JSON; only valid with --sign")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sign",
        action="store_true",
        help="explicitly sign --request with existing ITER22_APPROVAL_* process variables",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _safe_stdout(payload: Mapping[str, Any]) -> None:
    """Emit operation metadata only; never echo facts, receipts, or environment values."""

    sys.stdout.write(json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n")


def _safe_stderr(code: str) -> None:
    sys.stderr.write(json.dumps({"status": "ERROR", "code": code}, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.input is not None:
            if args.sign:
                _fail("sign_requires_review_request")
            facts = _load_json_object(Path(args.input), "facts_input_unavailable_or_invalid")
            request = write_request(facts, config, args.output, overwrite=args.overwrite)
            _safe_stdout(
                {
                    "status": "REQUEST_WRITTEN",
                    "purpose": request["facts"]["purpose"],
                    "request_sha256": _sha256_json(request),
                    "contains_credentials": False,
                }
            )
            return 0
        if not args.sign:
            _fail("sign_flag_required")
        if Path(args.request).resolve() == Path(args.output).resolve():
            _fail("request_and_output_must_differ")
        request = _load_json_object(Path(args.request), "request_input_unavailable_or_invalid")
        receipt, receipt_hash = sign_validate_and_write_request(
            request,
            config,
            args.output,
            overwrite=args.overwrite,
        )
        _safe_stdout(
            {
                "status": "RECEIPT_SIGNED_AND_VALIDATED",
                "purpose": receipt["purpose"],
                "receipt_sha256": receipt_hash,
                "runner_contract_validated": True,
                "contains_credentials": False,
            }
        )
        return 0
    except ReceiptToolError as exc:
        _safe_stderr(exc.code)
        return 2
    except Exception:
        _safe_stderr("internal_error")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
