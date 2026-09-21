"""Fail-closed bounded-session supervisor for the Iteration 22 CTP pilot.

The normal runner owns all CTP authentication, admission-receipt validation,
execution arming, account reconciliation, and controlled shutdown.  This
module deliberately owns none of those privileges.  It only starts bounded
child sessions, checks the runner's sealed evidence manifest, and permits a
subsequent session only after that evidence proves a clean terminal state.

It is intentionally conservative:

* invoking this file without ``--execute`` is a dry run;
* the only read/write-capable request shape is explicit ``simnow`` plus
  ``natural_signal`` plus a regular admission-receipt file;
* every child receives a finite ``--run-seconds`` value and a hard outer
  timeout;
* a missing, malformed, non-success, or forward-unknown manifest creates a
  durable stop latch.  It is never cleared automatically.

The supervisor is a SimNow pilot tool, not a production-account switch.  A
futures-company production CTP account needs its own reviewed runner profile,
admission process, and evidence contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple


HERE = Path(__file__).resolve().parent
RUNNER_PATH = HERE / "run.py"
DEFAULT_STATE_DIRECTORY = HERE / "state" / "pilot-supervisor"
DEFAULT_OUTPUT_ROOT = HERE / "reports" / "pilot-supervisor"

MANIFEST_SCHEMA_VERSION = "iter22.manifest.v1"
JOURNAL_SCHEMA_VERSION = "iter22.pilot-supervisor-journal.v1"
STOP_SCHEMA_VERSION = "iter22.pilot-supervisor-stop.v1"
FIRST_SET_G3_ARTIFACT_SEAL_SCHEMA = "iter22.first-set-g3-artifact-seal.v1"
FIRST_SET_G3_PENDING_MANIFEST_SEAL = "PENDING_MANIFEST_SEAL"
FIRST_SET_G3_ARTIFACT_NAMES = (
    "daily_report.json",
    "daily_report.md",
    "reconciliation.json",
)

MIN_SESSION_SECONDS = 1.0
MAX_SESSION_SECONDS = 3600.0
MAX_SESSIONS = 24
MAX_GRACE_SECONDS = 600.0
MAX_RESTART_DELAY_SECONDS = 300.0
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024

EVIDENCE_STREAMS = (
    "bars",
    "orders",
    "quotes",
    "risk_events",
    "signals",
    "trades",
)
WRITE_REQUEST_COUNT_KEYS = (
    "settlement_confirm",
    "order_insert",
    "order_action",
)
SHUTDOWN_ZERO_COUNT_KEYS = (
    "active_order_count",
    "local_position_count",
    "remote_position_count",
    "unknown_intent_count",
    "unmatched_trade_count",
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TRADING_DAY = re.compile(r"^\d{8}$")
_ACCOUNT_FINGERPRINT = re.compile(r"^acct_[0-9a-f]{16}$")
_SA_INSTRUMENT = re.compile(r"^SA\d{3,4}$")
_SAFE_JOURNAL_TEXT = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")

_BASE_COMPONENT_MODULES = {
    "backtrader": "backtrader",
    "backtrader_trade_logger": "backtrader.observers.trade_logger",
    "backtrader_store": "backtrader.stores.btapistore",
    "backtrader_feed": "backtrader.feeds.btapifeed",
    "backtrader_broker": "backtrader.brokers.btapibroker",
    "bt_api_py": "bt_api_py",
    "bt_api_py_facade": "bt_api_py.bt_api",
    "bt_api_py_execution_session": "bt_api_py._execution_session",
}
_EXPECTED_COMPONENTS = frozenset(set(_BASE_COMPONENT_MODULES) | {"bt_api_ctp"})

# ``run.py`` finalizes a normal full network run with precisely these fields.
# Requiring the mode-specific exact set makes a runner schema extension stop
# safely until this independently reviewed parser has been updated.
_COMMON_NETWORK_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "iteration",
        "run_id",
        "purpose",
        "mode",
        "environment",
        "candidate_id",
        "config_hash",
        "code_hash",
        "data_hash",
        "account_fingerprint",
        "instrument_id",
        "trading_day",
        "started_at_utc",
        "ended_at_utc",
        "fee_source",
        "execution_basis",
        "hypothetical_fills",
        "research_status",
        "runtime",
        "exit_status",
        "environment_profile",
        "profile_basis",
        "market_alignment",
        "admission_receipt_sha256",
        "source_components",
        "engineering_strategy_observation",
        "g3_gate_status",
        "g4_gate_status",
        "retention",
        "preflight_sha256",
        "startup_account_observation_sha256",
        "network_data_identity",
        "controlled_drain",
        "observation_evidence",
        "evidence_counts",
        "evidence_enqueued_counts",
        "evidence_dropped_counts",
        "evidence_pending_counts",
        "evidence_max_pending_counts",
        "evidence_max_pending_total",
        "evidence_rotations",
        "evidence_health",
    }
)


class SupervisorError(RuntimeError):
    """Base class for non-recoverable local supervisor decisions."""


class InvocationError(SupervisorError):
    """The requested child command could cross a safety boundary."""


class SupervisorLockError(SupervisorError):
    """Another supervisor (or an unresolved stale lock) owns the pilot."""


class SupervisorStopped(SupervisorError):
    """A durable stop latch requires an operator review before any retry."""


class ManifestValidationError(SupervisorError):
    """The child did not publish the exact sealed-success contract."""

    def __init__(self, code: str):
        self.code = str(code)
        super().__init__(self.code)


class RunnerTimeout(SupervisorError):
    """The child exceeded the supervisor's hard bounded-session timeout."""


@dataclass(frozen=True)
class SessionPlan:
    """One safe, bounded class of child session.

    ``simnow`` is intentionally narrow: it can only carry the already
    runner-validated natural-signal admission receipt.  The receipt's HMAC,
    expiry, account/profile binding, source/dependency identities, gates, and
    execution arming remain the responsibility of ``run.py``.
    """

    mode: str = "shadow"
    purpose: str = "observation"
    session_seconds: float = MAX_SESSION_SECONDS
    max_sessions: int = 1
    admission_receipt: Optional[Path] = None
    grace_seconds: float = 180.0
    restart_delay_seconds: float = 5.0


@dataclass(frozen=True)
class ManifestSeal:
    """The safe subset retained after a complete manifest validation."""

    run_id: str
    exit_status: str
    mode: str
    purpose: str
    account_fingerprint: str
    trading_day: str
    instrument_id: str
    environment: str
    profile_basis: str
    environment_profile: str
    connection_generation: int

    def restart_identity(self) -> Tuple[str, str, str, str, str, str, int]:
        """Return the identity that must stay unchanged across child sessions."""

        return (
            self.account_fingerprint,
            self.trading_day,
            self.instrument_id,
            self.environment,
            self.profile_basis,
            self.environment_profile,
            self.connection_generation,
        )


@dataclass(frozen=True)
class SupervisorResult:
    """Non-sensitive result information for a dry run or completed sessions."""

    executed: bool
    completed_sessions: int
    seals: Tuple[ManifestSeal, ...]


Runner = Callable[[Sequence[str], Path, float], int]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]
RunNameFactory = Callable[[int, datetime], str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_iso(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SupervisorError("supervisor clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ManifestValidationError("manifest_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestValidationError("manifest_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise ManifestValidationError("manifest_timestamp_naive")
    return parsed.astimezone(timezone.utc)


def _require_mapping(value: Any, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(code)
    return value


def _is_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _require_hex64(value: Any, code: str) -> str:
    text = str(value or "").lower()
    if _HEX64.fullmatch(text) is None:
        raise ManifestValidationError(code)
    return text


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    """Match the runner's canonical evidence hash for simple JSON mappings."""

    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_state_directory(path: Path) -> Path:
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise SupervisorError("supervisor state directory must not be a symlink")
    directory = requested.resolve()
    if directory.exists() and not directory.is_dir():
        raise SupervisorError("supervisor state path is not a directory")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _safe_output_root(path: Path) -> Path:
    requested = Path(path).expanduser()
    if requested.is_symlink():
        raise SupervisorError("supervisor output root must not be a symlink")
    directory = requested.resolve()
    if directory.exists() and not directory.is_dir():
        raise SupervisorError("supervisor output root is not a directory")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class ExclusiveSupervisorLock:
    """A non-stealing O_EXCL lock.

    A stale lock is deliberately treated as live.  Breaking it automatically
    could start a second supervisor while the original CTP process still has
    an account session or a controlled drain in progress.
    """

    def __init__(self, path: Path, *, clock: Clock) -> None:
        self.path = path
        self._clock = clock
        self._token = uuid.uuid4().hex
        self._held = False
        self._preserve = False

    def acquire(self) -> None:
        if self.path.exists() and self.path.is_symlink():
            raise SupervisorLockError("supervisor lock path is a symlink")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            descriptor = os.open(str(self.path), flags, 0o600)
        except FileExistsError as exc:
            raise SupervisorLockError(
                "supervisor lock is already present; inspect it before any retry"
            ) from exc
        payload = {
            "schema_version": "iter22.pilot-supervisor-lock.v1",
            "created_at_utc": _as_utc_iso(self._clock()),
            "token": self._token,
        }
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        try:
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            try:
                self.path.unlink()
            except OSError:
                pass
            raise
        os.close(descriptor)
        self._held = True

    def preserve(self) -> None:
        """Keep the transient lock when a durable stop marker cannot be written."""

        self._preserve = True

    def release(self) -> None:
        if not self._held or self._preserve:
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            # A malformed/replaced lock must remain, rather than risking a
            # deletion of another owner's lock.
            self._preserve = True
            return
        if not isinstance(payload, Mapping) or payload.get("token") != self._token:
            self._preserve = True
            return
        try:
            self.path.unlink()
        except OSError:
            self._preserve = True
            return
        self._held = False


def _write_all(descriptor: int, value: bytes) -> None:
    """Write bytes completely; ``os.write`` is permitted to be partial."""

    offset = 0
    while offset < len(value):
        written = os.write(descriptor, value[offset:])
        if written <= 0:
            raise OSError("short durable write")
        offset += written


def _sanitize_key(key: Any) -> str:
    value = str(key).strip().lower()
    if any(
        token in value
        for token in ("password", "secret", "token", "auth", "credential", "key", "receipt")
    ):
        return "redacted_field"
    if _SAFE_JOURNAL_TEXT.fullmatch(value):
        return value
    return "unknown_field"


def _sanitize_for_journal(value: Any, *, key: str = "") -> Any:
    """Return a small, non-secret JSON value suitable for the append-only journal."""

    if any(
        token in key.lower()
        for token in ("password", "secret", "token", "auth", "credential", "key", "receipt")
    ):
        return "<redacted>"
    if value is None or type(value) is bool or type(value) is int:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "<redacted>"
    if isinstance(value, str):
        return value if _SAFE_JOURNAL_TEXT.fullmatch(value) else "<redacted>"
    if isinstance(value, Mapping):
        sanitized: Dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            safe_key = _sanitize_key(raw_key)
            # Classify values from the original key.  ``safe_key`` may itself
            # be the neutral ``redacted_field`` label and must not make a
            # password/token value look harmless on the second pass.
            sanitized[safe_key] = _sanitize_for_journal(raw_value, key=str(raw_key))
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_journal(item, key=key) for item in value]
    return "<redacted>"


def append_sanitized_journal(path: Path, payload: Mapping[str, Any]) -> None:
    """Durably append one sanitized JSONL record without rewriting prior records."""

    if path.exists() and path.is_symlink():
        raise SupervisorError("supervisor journal path is a symlink")
    safe = _sanitize_for_journal(dict(payload))
    if not isinstance(safe, Mapping):  # Defensive: the helper's contract above is strict.
        raise SupervisorError("supervisor journal sanitization failed")
    encoded = (
        json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(str(path), flags, 0o600)
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _validate_plan(plan: SessionPlan) -> SessionPlan:
    """Reject every command shape other than shadow or explicit admitted SimNow."""

    if plan.mode not in {"shadow", "simnow"}:
        raise InvocationError("supervisor accepts shadow or simnow mode only")
    if not math.isfinite(float(plan.session_seconds)) or not (
        MIN_SESSION_SECONDS <= float(plan.session_seconds) <= MAX_SESSION_SECONDS
    ):
        raise InvocationError("session duration must be finite and within the bounded pilot limit")
    if type(plan.max_sessions) is not int or not 1 <= plan.max_sessions <= MAX_SESSIONS:
        raise InvocationError("max sessions must be a bounded positive integer")
    if not math.isfinite(float(plan.grace_seconds)) or not (
        0.0 <= float(plan.grace_seconds) <= MAX_GRACE_SECONDS
    ):
        raise InvocationError("child grace duration is outside the bounded pilot limit")
    if not math.isfinite(float(plan.restart_delay_seconds)) or not (
        0.0 <= float(plan.restart_delay_seconds) <= MAX_RESTART_DELAY_SECONDS
    ):
        raise InvocationError("restart delay is outside the bounded pilot limit")

    receipt = plan.admission_receipt
    if plan.mode == "shadow":
        if plan.purpose != "observation" or receipt is not None:
            raise InvocationError("shadow supervisor sessions are read-only observation only")
    else:
        if plan.purpose != "natural_signal":
            raise InvocationError("SimNow supervisor sessions require natural_signal purpose")
        if receipt is None:
            raise InvocationError("SimNow supervisor sessions require an admission receipt path")
        requested_receipt = Path(receipt).expanduser()
        if requested_receipt.is_symlink():
            raise InvocationError("admission receipt must be a regular file")
        receipt = requested_receipt.resolve()
        if not receipt.is_file():
            raise InvocationError("admission receipt must be a regular file")
        try:
            size = receipt.stat().st_size
        except OSError as exc:
            raise InvocationError("admission receipt cannot be inspected") from exc
        if not 0 < size <= MAX_RECEIPT_BYTES:
            raise InvocationError("admission receipt size is outside the safe limit")

    return SessionPlan(
        mode=plan.mode,
        purpose=plan.purpose,
        session_seconds=float(plan.session_seconds),
        max_sessions=plan.max_sessions,
        admission_receipt=receipt,
        grace_seconds=float(plan.grace_seconds),
        restart_delay_seconds=float(plan.restart_delay_seconds),
    )


def _default_run_name(index: int, now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "pilot-{}-{:02d}-{}".format(stamp, index, uuid.uuid4().hex[:8])


def _default_runner(command: Sequence[str], _output_directory: Path, timeout: float) -> int:
    """Run the normal Iteration 22 runner without a shell or extra environment."""

    try:
        completed = subprocess.run(
            list(command),
            cwd=str(HERE),
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerTimeout("bounded child session exceeded its hard timeout") from exc
    return int(completed.returncode)


def _expected_manifest_fields(mode: str) -> frozenset:
    if mode == "shadow":
        return _COMMON_NETWORK_MANIFEST_FIELDS | {"first_set_g3_artifact_seal"}
    if mode == "simnow":
        return _COMMON_NETWORK_MANIFEST_FIELDS | {
            "execution_authorization_sha256",
            "execution_arming_sha256",
        }
    raise ManifestValidationError("manifest_mode_invalid")


def _validate_runtime(value: Any) -> None:
    runtime = _require_mapping(value, "manifest_runtime_invalid")
    if set(runtime) != {"python", "executable", "platform", "architecture"}:
        raise ManifestValidationError("manifest_runtime_fields_invalid")
    if not all(isinstance(runtime[name], str) and runtime[name] for name in runtime):
        raise ManifestValidationError("manifest_runtime_values_invalid")


def _validate_source_components(value: Any) -> None:
    components = _require_mapping(value, "manifest_components_invalid")
    if set(components) != _EXPECTED_COMPONENTS:
        raise ManifestValidationError("manifest_components_unknown_or_missing")
    for name, module_name in _BASE_COMPONENT_MODULES.items():
        component = _require_mapping(components[name], "manifest_component_invalid")
        if set(component) != {"module", "version", "path", "sha256", "found"}:
            raise ManifestValidationError("manifest_component_fields_invalid")
        if (
            component.get("module") != module_name
            or component.get("found") is not True
            or not isinstance(component.get("path"), str)
            or not component.get("path")
        ):
            raise ManifestValidationError("manifest_component_identity_invalid")
        _require_hex64(component.get("sha256"), "manifest_component_hash_invalid")
    ctp = _require_mapping(components["bt_api_ctp"], "manifest_ctp_component_invalid")
    if set(ctp) != {
        "module",
        "version",
        "path",
        "sha256",
        "package_manifest",
        "package_manifest_verified",
        "native_files",
        "native_loaded",
    }:
        raise ManifestValidationError("manifest_ctp_component_fields_invalid")
    if (
        ctp.get("module") != "bt_api_ctp"
        or not isinstance(ctp.get("path"), str)
        or not ctp.get("path")
        or ctp.get("package_manifest_verified") is not True
        or ctp.get("native_loaded") is not True
        or not isinstance(ctp.get("package_manifest"), list)
        or not isinstance(ctp.get("native_files"), list)
    ):
        raise ManifestValidationError("manifest_ctp_component_identity_invalid")
    _require_hex64(ctp.get("sha256"), "manifest_ctp_component_hash_invalid")


def _validate_evidence(value: Mapping[str, Any]) -> None:
    for field in (
        "evidence_counts",
        "evidence_enqueued_counts",
        "evidence_dropped_counts",
        "evidence_pending_counts",
        "evidence_max_pending_counts",
        "evidence_rotations",
    ):
        counts = _require_mapping(value.get(field), "manifest_{}_invalid".format(field))
        if set(counts) != set(EVIDENCE_STREAMS) or not all(
            _is_nonnegative_int(counts[name]) for name in EVIDENCE_STREAMS
        ):
            raise ManifestValidationError("manifest_{}_shape_invalid".format(field))
    counts = _require_mapping(value["evidence_counts"], "manifest_evidence_counts_invalid")
    enqueued = _require_mapping(
        value["evidence_enqueued_counts"], "manifest_evidence_enqueued_counts_invalid"
    )
    dropped = _require_mapping(
        value["evidence_dropped_counts"], "manifest_evidence_dropped_counts_invalid"
    )
    pending = _require_mapping(
        value["evidence_pending_counts"], "manifest_evidence_pending_counts_invalid"
    )
    if any(dropped[name] != 0 or pending[name] != 0 for name in EVIDENCE_STREAMS):
        raise ManifestValidationError("manifest_evidence_not_drained")
    if any(counts[name] != enqueued[name] for name in EVIDENCE_STREAMS):
        raise ManifestValidationError("manifest_evidence_count_mismatch")
    if not _is_nonnegative_int(value.get("evidence_max_pending_total")):
        raise ManifestValidationError("manifest_evidence_pending_total_invalid")
    health = _require_mapping(value.get("evidence_health"), "manifest_evidence_health_invalid")
    if set(health) != {"complete", "failure_reason", "queue_limit"}:
        raise ManifestValidationError("manifest_evidence_health_fields_invalid")
    if (
        health.get("complete") is not True
        or health.get("failure_reason") is not None
        or not _is_nonnegative_int(health.get("queue_limit"))
        or health.get("queue_limit") <= 0
    ):
        raise ManifestValidationError("manifest_evidence_health_incomplete")


def _validate_network_identity(value: Mapping[str, Any]) -> None:
    identity = _require_mapping(
        value.get("network_data_identity"), "manifest_network_identity_invalid"
    )
    expected = {
        "provider",
        "exchange",
        "schema_version",
        "account_fingerprint",
        "environment_profile",
        "trading_day",
        "connection_generation",
        "instrument",
        "native_sha256",
        "ctp_package_sha256",
    }
    if set(identity) != expected:
        raise ManifestValidationError("manifest_network_identity_fields_invalid")
    if (
        identity.get("provider") != "btapi"
        or identity.get("exchange") != "CTP___FUTURE"
        or identity.get("schema_version") != "ctp.quote.v2"
        or identity.get("account_fingerprint") != value.get("account_fingerprint")
        or identity.get("environment_profile") != value.get("environment_profile")
        or identity.get("trading_day") != value.get("trading_day")
        or identity.get("instrument") != value.get("instrument_id")
        or type(identity.get("connection_generation")) is not int
        or identity.get("connection_generation") <= 0
    ):
        raise ManifestValidationError("manifest_network_identity_mismatch")
    _require_hex64(identity.get("native_sha256"), "manifest_network_native_hash_invalid")
    _require_hex64(identity.get("ctp_package_sha256"), "manifest_network_ctp_hash_invalid")
    if value.get("data_hash") != _sha256_json(identity):
        raise ManifestValidationError("manifest_network_data_hash_mismatch")


def _validate_retention(value: Any) -> None:
    retention = _require_mapping(value, "manifest_retention_invalid")
    if set(retention) != {"status", "retain_trading_days"}:
        raise ManifestValidationError("manifest_retention_fields_invalid")
    if (
        retention.get("status") != "NOT_APPLICABLE_EXPLICIT_OUTPUT_DIRECTORY"
        or not _is_nonnegative_int(retention.get("retain_trading_days"))
        or retention.get("retain_trading_days") <= 0
    ):
        raise ManifestValidationError("manifest_retention_value_invalid")


def _validate_shadow_artifact(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ManifestValidationError("manifest_g3_artifact_missing")
    if path.name.endswith(".json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise ManifestValidationError("manifest_g3_artifact_invalid") from exc
        artifact = _require_mapping(payload, "manifest_g3_artifact_invalid")
        observation = _require_mapping(
            artifact.get("observation_evidence"), "manifest_g3_artifact_observation_invalid"
        )
        if (
            artifact.get("g3_gate_status") != FIRST_SET_G3_PENDING_MANIFEST_SEAL
            or observation.get("g3_gate_status") != FIRST_SET_G3_PENDING_MANIFEST_SEAL
            or artifact.get("manifest_seal_status") != "PENDING"
            or artifact.get("g3_verdict_source") != "manifest.json"
        ):
            raise ManifestValidationError("manifest_g3_artifact_not_pending")


def _validate_shadow_seal(manifest: Mapping[str, Any], output_directory: Path) -> None:
    seal = _require_mapping(manifest.get("first_set_g3_artifact_seal"), "manifest_g3_seal_invalid")
    if set(seal) != {"schema_version", "verdict_source", "artifact_state", "artifact_sha256"}:
        raise ManifestValidationError("manifest_g3_seal_fields_invalid")
    hashes = _require_mapping(seal.get("artifact_sha256"), "manifest_g3_hashes_invalid")
    if (
        seal.get("schema_version") != FIRST_SET_G3_ARTIFACT_SEAL_SCHEMA
        or seal.get("verdict_source") != "manifest.json"
        or seal.get("artifact_state") != FIRST_SET_G3_PENDING_MANIFEST_SEAL
        or set(hashes) != set(FIRST_SET_G3_ARTIFACT_NAMES)
    ):
        raise ManifestValidationError("manifest_g3_seal_mismatch")
    for filename in FIRST_SET_G3_ARTIFACT_NAMES:
        expected = _require_hex64(hashes.get(filename), "manifest_g3_artifact_hash_invalid")
        artifact_path = output_directory / filename
        _validate_shadow_artifact(artifact_path)
        try:
            actual = _sha256_file(artifact_path)
        except OSError as exc:
            raise ManifestValidationError("manifest_g3_artifact_unreadable") from exc
        if actual != expected:
            raise ManifestValidationError("manifest_g3_artifact_hash_mismatch")


def _validate_simnow_shutdown(value: Any) -> None:
    summary = _require_mapping(value, "manifest_shutdown_invalid")
    if (
        summary.get("status") != "PASS"
        or summary.get("remote_flat_proven") is not True
        or summary.get("store_shutdown_state") != "PASS"
        or any(
            type(summary.get(name)) is not int or summary.get(name) != 0
            for name in SHUTDOWN_ZERO_COUNT_KEYS
        )
    ):
        raise ManifestValidationError("manifest_shutdown_not_flat")


def validate_sealed_success_manifest(
    output_directory: Path,
    *,
    mode: str,
    purpose: str,
    admission_receipt: Optional[Path],
) -> ManifestSeal:
    """Accept only the exact final success manifests produced by a full child run.

    The schema is intentionally closed.  An unknown top-level field, an
    omitted expected field, a still-running state, an incomplete evidence
    lane, or a changed G3 artifact causes a durable stop rather than a retry.
    """

    requested_directory = Path(output_directory)
    if requested_directory.is_symlink():
        raise ManifestValidationError("manifest_directory_symlink")
    directory = requested_directory.resolve()
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ManifestValidationError("manifest_missing")
    try:
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ManifestValidationError("manifest_oversized")
        raw = manifest_path.read_bytes()
        manifest_value = json.loads(raw.decode("utf-8"))
    except ManifestValidationError:
        raise
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise ManifestValidationError("manifest_unreadable") from exc
    manifest = _require_mapping(manifest_value, "manifest_not_mapping")

    expected_fields = _expected_manifest_fields(mode)
    if set(manifest) != expected_fields:
        raise ManifestValidationError("manifest_unknown_or_missing_fields")
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or type(manifest.get("iteration")) is not int
        or manifest.get("iteration") != 22
        or manifest.get("mode") != mode
        or manifest.get("purpose") != purpose
        or manifest.get("candidate_id") != "iter22-sa-v0"
        or manifest.get("engineering_strategy_observation") is not False
        or manifest.get("hypothetical_fills") is not False
    ):
        raise ManifestValidationError("manifest_identity_invalid")

    run_id = manifest.get("run_id")
    expected_run_prefix = "iter22-{}-".format(mode)
    if not isinstance(run_id, str) or not run_id.startswith(expected_run_prefix):
        raise ManifestValidationError("manifest_run_id_invalid")
    if (
        manifest.get("environment") not in {"simnow_first_group1", "simnow_first_group2"}
        or manifest.get("profile_basis") != manifest.get("environment")
        or manifest.get("market_alignment") != "actual_market_hours"
        or manifest.get("environment_profile")
        not in {"set1_group1", "set1_group1_vpn", "set1_group2"}
    ):
        raise ManifestValidationError("manifest_profile_invalid")
    account = str(manifest.get("account_fingerprint") or "")
    instrument = str(manifest.get("instrument_id") or "").upper()
    trading_day = str(manifest.get("trading_day") or "")
    if (
        _ACCOUNT_FINGERPRINT.fullmatch(account) is None
        or _SA_INSTRUMENT.fullmatch(instrument) is None
        or _TRADING_DAY.fullmatch(trading_day) is None
        or not isinstance(manifest.get("fee_source"), str)
        or not manifest.get("fee_source")
    ):
        raise ManifestValidationError("manifest_trading_identity_invalid")
    for field in (
        "config_hash",
        "code_hash",
        "data_hash",
        "preflight_sha256",
        "startup_account_observation_sha256",
    ):
        _require_hex64(manifest.get(field), "manifest_{}_invalid".format(field))
    started = _parse_utc(manifest.get("started_at_utc"))
    ended = _parse_utc(manifest.get("ended_at_utc"))
    if ended < started:
        raise ManifestValidationError("manifest_timestamp_order_invalid")

    _validate_runtime(manifest.get("runtime"))
    _validate_source_components(manifest.get("source_components"))
    _validate_evidence(manifest)
    _validate_network_identity(manifest)
    _validate_retention(manifest.get("retention"))

    observation = _require_mapping(
        manifest.get("observation_evidence"), "manifest_observation_invalid"
    )
    if mode == "shadow":
        if (
            manifest.get("exit_status") != "PASS_SHADOW_G3"
            or manifest.get("execution_basis") != "none"
            or manifest.get("admission_receipt_sha256") is not None
            or manifest.get("research_status") != "RESEARCH_NOT_ESTABLISHED"
            or manifest.get("g3_gate_status") != "PASS"
            or observation.get("g3_gate_status") != "PASS"
            or manifest.get("g4_gate_status") != "NOT_RUN"
        ):
            raise ManifestValidationError("manifest_shadow_success_invalid")
        _validate_shadow_seal(manifest, directory)
    elif mode == "simnow":
        if admission_receipt is None:
            raise ManifestValidationError("manifest_receipt_missing")
        receipt_hash = _require_hex64(
            manifest.get("admission_receipt_sha256"), "manifest_receipt_hash_invalid"
        )
        try:
            expected_receipt_hash = _sha256_file(Path(admission_receipt))
        except OSError as exc:
            raise ManifestValidationError("manifest_receipt_unreadable") from exc
        if receipt_hash != expected_receipt_hash:
            raise ManifestValidationError("manifest_receipt_hash_mismatch")
        if (
            manifest.get("exit_status") != "COMPLETE_STOPPED_FLAT"
            or manifest.get("execution_basis") != "simnow_native"
            or manifest.get("research_status") != "RESEARCH_ADMITTED"
            or manifest.get("g3_gate_status") != "NOT_RUN"
            or manifest.get("g4_gate_status") not in {"PASS", "INCOMPLETE"}
        ):
            raise ManifestValidationError("manifest_simnow_success_invalid")
        _require_hex64(
            manifest.get("execution_authorization_sha256"),
            "manifest_authorization_hash_invalid",
        )
        _require_hex64(manifest.get("execution_arming_sha256"), "manifest_arming_hash_invalid")
        _validate_simnow_shutdown(manifest.get("controlled_drain"))
    else:  # ``_expected_manifest_fields`` also protects direct callers.
        raise ManifestValidationError("manifest_mode_invalid")
    return ManifestSeal(
        run_id=run_id,
        exit_status=str(manifest["exit_status"]),
        mode=mode,
        purpose=purpose,
        account_fingerprint=account,
        trading_day=trading_day,
        instrument_id=instrument,
        environment=str(manifest["environment"]),
        profile_basis=str(manifest["profile_basis"]),
        environment_profile=str(manifest["environment_profile"]),
        connection_generation=int(
            _require_mapping(
                manifest["network_data_identity"], "manifest_network_identity_invalid"
            )["connection_generation"]
        ),
    )


class PilotSupervisor:
    """Own a sequence of bounded child sessions under one exclusive lock."""

    def __init__(
        self,
        *,
        state_directory: Path = DEFAULT_STATE_DIRECTORY,
        output_root: Path = DEFAULT_OUTPUT_ROOT,
        runner: Runner = _default_runner,
        clock: Clock = _utc_now,
        sleeper: Sleeper = time.sleep,
        run_name_factory: RunNameFactory = _default_run_name,
    ) -> None:
        self.state_directory = Path(state_directory)
        self.output_root = Path(output_root)
        self._runner = runner
        self._clock = clock
        self._sleeper = sleeper
        self._run_name_factory = run_name_factory

    def _journal(self, state_directory: Path, event: str, **fields: Any) -> None:
        payload = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "at_utc": _as_utc_iso(self._clock()),
            "event": event,
            **fields,
        }
        append_sanitized_journal(state_directory / "journal.jsonl", payload)

    def _stop_latch(
        self,
        state_directory: Path,
        *,
        reason: str,
        plan: SessionPlan,
        session_index: int,
        run_directory: str,
    ) -> None:
        path = state_directory / "stop-latch.json"
        if path.exists():
            # Preserve the original stop decision; it may be the only durable
            # operator breadcrumb after a failed process.
            return
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        payload = {
            "schema_version": STOP_SCHEMA_VERSION,
            "stopped_at_utc": _as_utc_iso(self._clock()),
            "reason": reason,
            "mode": plan.mode,
            "purpose": plan.purpose,
            "session_index": session_index,
            "run_directory": run_directory,
        }
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        try:
            descriptor = os.open(str(path), flags, 0o600)
        except FileExistsError:
            return
        try:
            _write_all(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _new_output_directory(self, output_root: Path, index: int) -> Path:
        name = self._run_name_factory(index, self._clock())
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,127}", name):
            raise SupervisorError("supervisor run directory name is invalid")
        candidate = output_root / name
        if (
            candidate.exists()
            or candidate.is_symlink()
            or candidate.parent.resolve() != output_root
        ):
            raise SupervisorError("supervisor run directory is unavailable")
        return candidate

    @staticmethod
    def _child_command(plan: SessionPlan, output_directory: Path) -> Sequence[str]:
        command = [
            sys.executable,
            str(RUNNER_PATH),
            "--mode",
            plan.mode,
            "--purpose",
            plan.purpose,
            "--run-seconds",
            "{:.6f}".format(plan.session_seconds).rstrip("0").rstrip("."),
            "--output-dir",
            str(output_directory),
        ]
        if plan.admission_receipt is not None:
            command.extend(("--admission-receipt", str(plan.admission_receipt)))
        return command

    def run(self, plan: SessionPlan, *, execute: bool = False) -> SupervisorResult:
        """Validate, dry-run, or execute a finite number of safe child sessions."""

        plan = _validate_plan(plan)
        state_directory = _safe_state_directory(self.state_directory)
        output_root = _safe_output_root(self.output_root)
        stop_latch = state_directory / "stop-latch.json"
        if stop_latch.exists():
            raise SupervisorStopped(
                "supervisor is lock-stopped; inspect evidence and stop-latch before any retry"
            )
        lock = ExclusiveSupervisorLock(state_directory / "supervisor.lock", clock=self._clock)
        lock.acquire()
        session_index = 0
        directory_name = "not_started"
        try:
            if stop_latch.exists():
                raise SupervisorStopped(
                    "supervisor is lock-stopped; inspect evidence and stop-latch before any retry"
                )
            if not execute:
                self._journal(
                    state_directory,
                    "DRY_RUN",
                    mode=plan.mode,
                    purpose=plan.purpose,
                    max_sessions=plan.max_sessions,
                    session_seconds=plan.session_seconds,
                )
                return SupervisorResult(executed=False, completed_sessions=0, seals=())

            seals = []
            for index in range(1, plan.max_sessions + 1):
                session_index = index
                directory_name = "not_started"
                output_directory = self._new_output_directory(output_root, index)
                directory_name = output_directory.name
                timeout = plan.session_seconds + plan.grace_seconds
                self._journal(
                    state_directory,
                    "SESSION_STARTING",
                    mode=plan.mode,
                    purpose=plan.purpose,
                    session_index=index,
                    run_directory=directory_name,
                    timeout_seconds=timeout,
                )
                try:
                    return_code = int(
                        self._runner(
                            self._child_command(plan, output_directory),
                            output_directory,
                            timeout,
                        )
                    )
                except RunnerTimeout:
                    self._journal(
                        state_directory,
                        "SESSION_TIMEOUT",
                        mode=plan.mode,
                        purpose=plan.purpose,
                        session_index=index,
                        run_directory=directory_name,
                    )
                    self._stop_or_preserve(
                        lock,
                        state_directory,
                        reason="SUBPROCESS_TIMEOUT",
                        plan=plan,
                        session_index=index,
                        run_directory=directory_name,
                    )
                except BaseException as exc:
                    self._journal(
                        state_directory,
                        "SESSION_EXCEPTION",
                        mode=plan.mode,
                        purpose=plan.purpose,
                        session_index=index,
                        run_directory=directory_name,
                        exception_type=type(exc).__name__,
                    )
                    self._stop_or_preserve(
                        lock,
                        state_directory,
                        reason="SUBPROCESS_EXCEPTION",
                        plan=plan,
                        session_index=index,
                        run_directory=directory_name,
                    )
                if return_code != 0:
                    self._journal(
                        state_directory,
                        "SESSION_NONZERO_EXIT",
                        mode=plan.mode,
                        purpose=plan.purpose,
                        session_index=index,
                        run_directory=directory_name,
                        return_code=return_code,
                    )
                    self._stop_or_preserve(
                        lock,
                        state_directory,
                        reason="RUNNER_NONZERO_EXIT",
                        plan=plan,
                        session_index=index,
                        run_directory=directory_name,
                    )
                try:
                    seal = validate_sealed_success_manifest(
                        output_directory,
                        mode=plan.mode,
                        purpose=plan.purpose,
                        admission_receipt=plan.admission_receipt,
                    )
                except ManifestValidationError as exc:
                    self._journal(
                        state_directory,
                        "SESSION_MANIFEST_REJECTED",
                        mode=plan.mode,
                        purpose=plan.purpose,
                        session_index=index,
                        run_directory=directory_name,
                        reason=exc.code,
                    )
                    self._stop_or_preserve(
                        lock,
                        state_directory,
                        reason="SEALED_MANIFEST_REJECTED",
                        plan=plan,
                        session_index=index,
                        run_directory=directory_name,
                    )
                if seals and seal.restart_identity() != seals[0].restart_identity():
                    # A new account, TradingDay, generation, profile, or
                    # instrument is not a transparent restart.  It needs a
                    # fresh explicit operator decision and its own evidence.
                    self._journal(
                        state_directory,
                        "SESSION_IDENTITY_CHANGED",
                        mode=plan.mode,
                        purpose=plan.purpose,
                        session_index=index,
                        run_directory=directory_name,
                    )
                    self._stop_or_preserve(
                        lock,
                        state_directory,
                        reason="SESSION_IDENTITY_CHANGED",
                        plan=plan,
                        session_index=index,
                        run_directory=directory_name,
                    )
                seals.append(seal)
                self._journal(
                    state_directory,
                    "SESSION_SEALED_SUCCESS",
                    mode=plan.mode,
                    purpose=plan.purpose,
                    session_index=index,
                    run_directory=directory_name,
                    exit_status=seal.exit_status,
                )
                if index < plan.max_sessions:
                    self._journal(
                        state_directory,
                        "RESTART_AUTHORIZED",
                        mode=plan.mode,
                        purpose=plan.purpose,
                        session_index=index,
                        run_directory=directory_name,
                    )
                    if plan.restart_delay_seconds:
                        self._sleeper(plan.restart_delay_seconds)
            return SupervisorResult(
                executed=True, completed_sessions=len(seals), seals=tuple(seals)
            )
        except SupervisorStopped:
            raise
        except BaseException as exc:
            # This covers a journal/disk failure and a validator implementation
            # failure as well as an unexpected child-side exception.  Once a
            # supervisor has owned the pilot lock, no unclassified failure may
            # turn into an automatic retry.
            try:
                self._stop_latch(
                    state_directory,
                    reason="SUPERVISOR_INTERNAL_FAILURE",
                    plan=plan,
                    session_index=session_index,
                    run_directory=directory_name,
                )
            except BaseException as latch_exc:
                lock.preserve()
                raise SupervisorStopped(
                    "supervisor failed to persist its emergency stop latch; lock retained"
                ) from latch_exc
            try:
                self._journal(
                    state_directory,
                    "SUPERVISOR_FAIL_CLOSED",
                    mode=plan.mode,
                    purpose=plan.purpose,
                    session_index=session_index,
                    run_directory=directory_name,
                    exception_type=type(exc).__name__,
                )
            except BaseException:
                # The stop latch is already durable.  Do not obscure the
                # original failure by retrying a broken journal lane.
                pass
            raise SupervisorStopped("supervisor failed closed after an internal error") from exc
        finally:
            lock.release()

    def _stop_or_preserve(
        self,
        lock: ExclusiveSupervisorLock,
        state_directory: Path,
        *,
        reason: str,
        plan: SessionPlan,
        session_index: int,
        run_directory: str,
    ) -> None:
        """Persist a no-restart latch, retaining the active lock if that fails."""

        try:
            self._stop_latch(
                state_directory,
                reason=reason,
                plan=plan,
                session_index=session_index,
                run_directory=run_directory,
            )
            self._journal(
                state_directory,
                "LOCK_STOP",
                mode=plan.mode,
                purpose=plan.purpose,
                session_index=session_index,
                run_directory=run_directory,
                reason=reason,
            )
        except BaseException as exc:
            lock.preserve()
            raise SupervisorStopped(
                "supervisor failed to persist its stop latch; lock retained"
            ) from exc
        raise SupervisorStopped("supervisor lock-stopped after a non-success child session")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="start bounded child sessions; default is dry-run"
    )
    parser.add_argument("--mode", choices=("shadow", "simnow"), default="shadow")
    parser.add_argument(
        "--purpose", choices=("observation", "natural_signal"), default="observation"
    )
    parser.add_argument("--admission-receipt", type=Path)
    parser.add_argument("--session-seconds", type=float, default=MAX_SESSION_SECONDS)
    parser.add_argument("--max-sessions", type=int, default=1)
    parser.add_argument("--grace-seconds", type=float, default=180.0)
    parser.add_argument("--restart-delay-seconds", type=float, default=5.0)
    parser.add_argument("--state-directory", type=Path, default=DEFAULT_STATE_DIRECTORY)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    plan = SessionPlan(
        mode=args.mode,
        purpose=args.purpose,
        session_seconds=args.session_seconds,
        max_sessions=args.max_sessions,
        admission_receipt=args.admission_receipt,
        grace_seconds=args.grace_seconds,
        restart_delay_seconds=args.restart_delay_seconds,
    )
    supervisor = PilotSupervisor(
        state_directory=args.state_directory,
        output_root=args.output_root,
    )
    try:
        result = supervisor.run(plan, execute=bool(args.execute))
    except SupervisorError as exc:
        print("FAIL_CLOSED: {}".format(type(exc).__name__), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "executed": result.executed,
                "completed_sessions": result.completed_sessions,
                "exit_statuses": [seal.exit_status for seal in result.seals],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through ``main``.
    raise SystemExit(main())
