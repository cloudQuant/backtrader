"""Pre-import descriptor checks and an inert-only guardian IPC client.

This file is an unregistered library candidate, not an operator entry point.
``request_inert_guardian`` accepts only a caller-authenticated descriptor
that binds this source, the Python executable, fixed guardian service sources,
one AF_PIPE address, an authentication-key digest, and one fixed receipt
basename under a preselected output directory. The request contains only a
bounded sleep operation and absolute deadlines. It does not inspect
configuration, import the trading runtime or SDK, access a provider, consume
a marker, or enable writes.

Descriptor hashes are not a signature or an ACL proof. The IPC adapter bounds
the request owner's wait with a daemon thread, while CPython's AF_PIPE I/O may
remain blocked in that thread; a late request is rejected by the service's
absolute deadline check. The existing I13/I15 candidate preflight remains
separate and does not become an ordinary CLI route through this code.

The supported bootstrap shape is one externally captured and hashed byte blob
containing this source immediately after the sealed-import bootstrap source.
The latter preloads and captures the stdlib objects used here before taking its
import-closure snapshot; this module therefore does not use a future import or
add imports after that snapshot.
"""

import hashlib
import hmac
import json
import ntpath
import os
import re
import stat
import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Mapping, Optional, Sequence


SCHEMA = "ctp_i13_i15_parent_trust.v1"
MAX_DESCRIPTOR_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")
_CANDIDATE_LAYOUT = MappingProxyType(
    {
        "i13_md": (
            "backtrader_runtime/ctp_i13_source_manifest.json",
            "backtrader_runtime/ctp_i13_source_identity_pin.py",
            "backtrader_runtime/ctp_i13_md_oneshot_supervisor.py",
        ),
        "i15_td": (
            "backtrader_runtime/ctp_i15_source_manifest.json",
            "backtrader_runtime/ctp_i15_source_identity_pin.py",
            "backtrader_runtime/ctp_i15_td_only_readonly.py",
        ),
    }
)
_CODE_OWNED_PIN_NAMES = MappingProxyType(
    {
        "i13_md": "I13_SOURCE_MANIFEST_SHA256",
        "i15_td": "I15_REVIEWED_SOURCE_MANIFEST_SHA256",
    }
)
_RUNTIME_PACKAGE = "backtrader_runtime"
_PRIVATE_REGISTRATION = "examples/013_3_sa_midfreq_simnow/runtime-ctp-private"
_STRATEGY_ID = "example.013_3.sa_midfreq_simnow"
_RUNTIME_ID = "example.013_3.sa_midfreq_simnow.ctp_private"
_REPARSE_POINT = 0x400
_INERT_GUARDIAN_SCHEMA = "ctp_i13_i15_inert_guardian.v2"
_INERT_GUARDIAN_PIPE_RE = re.compile(
    r"\\\\\.\\pipe\\backtrader-ctp-i13-i15-[0-9a-f]{32}\Z"
)
_LEGACY_INERT_GUARDIAN_FILES = (
    "scripts/__init__.py",
    "scripts/ctp_i13_i15_outer_watchdog.py",
    "scripts/ctp_i13_i15_windows_job_backend.py",
    "scripts/ctp_i13_i15_windows_guardian.py",
    "scripts/ctp_i13_i15_windows_guardian_service.py",
)
_READONLY_PREFLIGHT_WORKER = "scripts/ctp_i13_i15_readonly_preflight_worker.py"
_READONLY_PREFLIGHT_BOOTSTRAP = "scripts/ctp_i13_i15_readonly_preflight_bootstrap.py"
_READONLY_REQUEST_COORDINATOR = "scripts/ctp_i13_i15_readonly_request_coordinator.py"
_READONLY_RECEIPT_WRITER = "scripts/ctp_i13_i15_readonly_receipt_writer.py"
_READONLY_TOKEN_BOOTSTRAP = "scripts/ctp_i13_i15_readonly_token_bootstrap.py"
_READONLY_SERVICE_ROLE_FILES = frozenset(
    {
        _READONLY_REQUEST_COORDINATOR,
        _READONLY_RECEIPT_WRITER,
        _READONLY_TOKEN_BOOTSTRAP,
    }
)
_READONLY_WORKER_DEPENDENCY_HELPER = (
    "backtrader_runtime/ctp_i13_worker_dependency_seal.py"
)
_INERT_GUARDIAN_FILES = _LEGACY_INERT_GUARDIAN_FILES + (_READONLY_PREFLIGHT_WORKER,)
_READONLY_GUARDIAN_FILES = _INERT_GUARDIAN_FILES + (
    "scripts/ctp_i13_i15_guardian_deployment_anchor.py",
    "scripts/ctp_i13_i15_dependency_seal.py",
    _READONLY_PREFLIGHT_BOOTSTRAP,
    _READONLY_REQUEST_COORDINATOR,
    _READONLY_RECEIPT_WRITER,
    _READONLY_TOKEN_BOOTSTRAP,
)


class ParentLaunchError(ValueError):
    """A redacted early launcher rejection."""


@dataclass(frozen=True)
class ParentTrustDescriptor:
    launcher_version: str
    launcher_sha256: str
    source_root: str
    candidates: Mapping[str, Mapping[str, str]]
    venv_root: str
    python_executable: str
    python_sha256: str
    python_version: str
    python_architecture: str
    python_home: str
    pyvenv_cfg_sha256: str
    stdlib_paths: tuple[str, ...]
    descriptor_sha256: str


@dataclass(frozen=True)
class ExternallyPinnedDescriptor:
    """Descriptor bytes plus the digest supplied by the trusted caller.

    This value is mandatory at the parent entry point. Its type cannot prove
    provenance: the caller must source ``sha256`` from a protected review
    receipt outside the checkout and pass the captured bytes it authenticated.
    Tests construct it only from temporary fake fixtures.
    """

    raw_bytes: bytes
    sha256: str
    external_anchor_id: str

    def __post_init__(self) -> None:
        if type(self.raw_bytes) is not bytes or not self.raw_bytes:
            raise ParentLaunchError("trusted_descriptor_required")
        _sha256(self.sha256, "descriptor_pin_invalid")
        if (
            type(self.external_anchor_id) is not str
            or not self.external_anchor_id
            or len(self.external_anchor_id) > 128
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.external_anchor_id)
        ):
            raise ParentLaunchError("external_descriptor_anchor_invalid")


@dataclass(frozen=True)
class ParentLaunchPlan:
    """Validated facts needed by the next sealed-source phase."""

    candidate: str
    source_root: str
    manifest_path: str
    manifest_sha256: str
    pin_path: str
    pin_sha256: str
    entrypoint: str
    python_executable: str
    python_sha256: str
    venv_root: str
    pyvenv_cfg_sha256: str
    stdlib_paths: tuple[str, ...]
    descriptor_sha256: str
    pin_source_sha256s: Mapping[str, str]


@dataclass(frozen=True)
class InertGuardianPlan:
    """Externally pinned IPC, source, interpreter and output scope."""

    source_root: str
    receipt_root: str
    python_executable: str
    python_sha256: str
    python_version: str
    python_architecture: str
    parent_launcher_sha256: str
    pipe_address: str
    service_authkey_sha256: str
    files: Mapping[str, str]
    descriptor_sha256: str


@dataclass(frozen=True)
class InertGuardianResponse:
    """A response from a prestarted guardian or explicit unknown outcome."""

    state: str
    reason: str
    service_pid: int
    request_id: str
    response: Optional[Mapping[str, object]]
    descriptor_sha256: str


@dataclass(frozen=True)
class PreparedCandidateImport:
    """Source-sealed candidate import kept alive through later Job stages."""

    plan: ParentLaunchPlan
    source_seal: object
    finder: object
    candidate_module: object
    metadata_job_setup_result: object

    def close(self) -> None:
        close = getattr(self.source_seal, "close", None)
        if not callable(close):
            raise ParentLaunchError("source_seal_cleanup_unavailable")
        close()


def _duplicate_rejecting_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ParentLaunchError("descriptor_duplicate_key")
        result[key] = value
    return result


def _sha256(value: object, reason: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None or value == "0" * 64:
        raise ParentLaunchError(reason)
    return value


def _canonical_windows_path(value: object, reason: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 1024
        or "/" in value
        or not ntpath.isabs(value)
        or ntpath.normpath(value) != value
        or any(part in {".", ".."} for part in value.split("\\"))
    ):
        raise ParentLaunchError(reason)
    return value


def _canonical_relative(value: object, expected: str, reason: str) -> str:
    if (
        type(value) is not str
        or value != expected
        or "\\" in value
        or PurePosixPath(value).is_absolute()
        or any(part in {"", ".", ".."} for part in PurePosixPath(value).parts)
    ):
        raise ParentLaunchError(reason)
    return value


def parse_trust_descriptor(
    trusted_descriptor: ExternallyPinnedDescriptor,
) -> ParentTrustDescriptor:
    """Verify and parse exact canonical descriptor bytes.

    The expected digest is deliberately an argument rather than a constant in
    this checkout.  A production caller must obtain it from an independently
    reviewed, protected source.
    """

    if type(trusted_descriptor) is not ExternallyPinnedDescriptor:
        raise ParentLaunchError("trusted_descriptor_required")
    raw = trusted_descriptor.raw_bytes
    expected = _sha256(trusted_descriptor.sha256, "descriptor_pin_invalid")
    if type(raw) is not bytes or not raw or len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ParentLaunchError("descriptor_size_invalid")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
        raise ParentLaunchError("descriptor_digest_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_rejecting_pairs)
    except ParentLaunchError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise ParentLaunchError("descriptor_invalid") from None
    if type(value) is not dict or set(value) != {"schema", "launcher", "source", "python"}:
        raise ParentLaunchError("descriptor_fields_invalid")
    if value["schema"] != SCHEMA:
        raise ParentLaunchError("descriptor_schema_invalid")

    launcher = value["launcher"]
    source = value["source"]
    python = value["python"]
    if type(launcher) is not dict or set(launcher) != {"version", "sha256"}:
        raise ParentLaunchError("descriptor_launcher_invalid")
    if type(source) is not dict or set(source) != {
        "root",
        "runtime_package",
        "private_registration",
        "strategy_id",
        "runtime_id",
        "candidates",
    }:
        raise ParentLaunchError("descriptor_source_invalid")
    if type(python) is not dict or set(python) != {
        "version",
        "architecture",
        "venv_root",
        "executable",
        "executable_sha256",
        "home",
        "pyvenv_cfg_sha256",
        "stdlib_paths",
    }:
        raise ParentLaunchError("descriptor_python_invalid")

    if type(launcher["version"]) is not str or _VERSION_RE.fullmatch(launcher["version"]) is None:
        raise ParentLaunchError("descriptor_launcher_version_invalid")
    launcher_hash = _sha256(launcher["sha256"], "descriptor_launcher_pin_invalid")

    root = _canonical_windows_path(source["root"], "source_root_invalid")
    if (
        source["runtime_package"] != _RUNTIME_PACKAGE
        or source["private_registration"] != _PRIVATE_REGISTRATION
        or source["strategy_id"] != _STRATEGY_ID
        or source["runtime_id"] != _RUNTIME_ID
    ):
        raise ParentLaunchError("source_layout_binding_invalid")
    candidates = source["candidates"]
    if type(candidates) is not dict or set(candidates) != set(_CANDIDATE_LAYOUT):
        raise ParentLaunchError("candidate_set_invalid")
    normalized_candidates = {}
    for name, (manifest_expected, pin_expected, entrypoint) in _CANDIDATE_LAYOUT.items():
        item = candidates[name]
        if type(item) is not dict or set(item) != {
            "manifest_path",
            "manifest_sha256",
            "pin_path",
            "pin_sha256",
        }:
            raise ParentLaunchError("candidate_descriptor_invalid")
        manifest_path = _canonical_relative(
            item["manifest_path"], manifest_expected, "candidate_manifest_path_invalid"
        )
        pin_path = _canonical_relative(item["pin_path"], pin_expected, "candidate_pin_path_invalid")
        normalized_candidates[name] = MappingProxyType(
            {
                "manifest_path": manifest_path,
                "manifest_sha256": _sha256(
                    item["manifest_sha256"], "candidate_manifest_pin_invalid"
                ),
                "pin_path": pin_path,
                "pin_sha256": _sha256(item["pin_sha256"], "candidate_pin_invalid"),
                "entrypoint": entrypoint,
            }
        )

    if python["version"] != "3.11.5" or python["architecture"] != "AMD64":
        raise ParentLaunchError("python_baseline_invalid")
    venv_root = _canonical_windows_path(python["venv_root"], "venv_root_invalid")
    executable = _canonical_windows_path(python["executable"], "python_executable_invalid")
    home = _canonical_windows_path(python["home"], "python_home_invalid")
    expected_executable = ntpath.join(venv_root, "Scripts", "python.exe")
    if ntpath.normcase(executable) != ntpath.normcase(expected_executable):
        raise ParentLaunchError("venv_executable_path_mismatch")
    stdlib_paths = python["stdlib_paths"]
    if type(stdlib_paths) is not list or not stdlib_paths:
        raise ParentLaunchError("stdlib_paths_invalid")
    checked_stdlib = []
    seen_stdlib = set()
    for path in stdlib_paths:
        checked = _canonical_windows_path(path, "stdlib_path_invalid")
        folded = ntpath.normcase(checked)
        if folded in seen_stdlib or "site-packages" in folded or "appdata" in folded:
            raise ParentLaunchError("stdlib_paths_invalid")
        seen_stdlib.add(folded)
        checked_stdlib.append(checked)

    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    if raw != canonical:
        raise ParentLaunchError("descriptor_not_canonical")
    return ParentTrustDescriptor(
        launcher_version=launcher["version"],
        launcher_sha256=launcher_hash,
        source_root=root,
        candidates=MappingProxyType(normalized_candidates),
        venv_root=venv_root,
        python_executable=executable,
        python_sha256=_sha256(python["executable_sha256"], "python_executable_pin_invalid"),
        python_version=python["version"],
        python_architecture=python["architecture"],
        python_home=home,
        pyvenv_cfg_sha256=_sha256(python["pyvenv_cfg_sha256"], "pyvenv_cfg_pin_invalid"),
        stdlib_paths=tuple(checked_stdlib),
        descriptor_sha256=expected,
    )


def _has_reparse_point(details: os.stat_result) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _assert_no_reparse_components(path: Path, *, final_kind: str) -> None:
    if not path.is_absolute():
        raise ParentLaunchError("path_not_absolute")
    current = Path(path.anchor)
    relative = path.parts[1:] if path.anchor else path.parts
    for index, part in enumerate(relative):
        current = current / part
        try:
            details = os.lstat(current)
        except OSError:
            raise ParentLaunchError("path_unavailable") from None
        if _has_reparse_point(details):
            raise ParentLaunchError("path_reparse_point")
        if index < len(relative) - 1 and not stat.S_ISDIR(details.st_mode):
            raise ParentLaunchError("path_parent_not_directory")
    try:
        final = os.lstat(path)
    except OSError:
        raise ParentLaunchError("path_unavailable") from None
    if final_kind == "directory" and not stat.S_ISDIR(final.st_mode):
        raise ParentLaunchError("path_not_directory")
    if final_kind == "file" and not stat.S_ISREG(final.st_mode):
        raise ParentLaunchError("path_not_regular_file")


def _read_pinned_file(path: Path, expected_hash: str, reason: str) -> bytes:
    _assert_no_reparse_components(path, final_kind="file")
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            raw = stream.read(16 * 1024 * 1024 + 1)
            after = os.fstat(stream.fileno())
        path_after = os.lstat(path)
    except OSError:
        raise ParentLaunchError("pinned_file_unavailable") from None
    if (
        len(raw) > 16 * 1024 * 1024
        or not stat.S_ISREG(before.st_mode)
        or (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size)
        or (after.st_dev, after.st_ino) != (path_after.st_dev, path_after.st_ino)
        or not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_hash)
    ):
        raise ParentLaunchError(reason)
    return raw


def parse_inert_guardian_descriptor(
    trusted_descriptor: ExternallyPinnedDescriptor,
) -> InertGuardianPlan:
    """Validate an externally pinned inert-guardian source and receipt scope.

    The anchor is supplied by the caller and must be authenticated outside this
    checkout. This descriptor is a hash binding, not a signature or a proof of
    ACL protection for the selected receipt directory.
    """

    if type(trusted_descriptor) is not ExternallyPinnedDescriptor:
        raise ParentLaunchError("trusted_descriptor_required")
    raw = trusted_descriptor.raw_bytes
    expected = _sha256(trusted_descriptor.sha256, "descriptor_pin_invalid")
    if type(raw) is not bytes or not raw or len(raw) > MAX_DESCRIPTOR_BYTES:
        raise ParentLaunchError("descriptor_size_invalid")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected):
        raise ParentLaunchError("descriptor_digest_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_rejecting_pairs)
    except ParentLaunchError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise ParentLaunchError("descriptor_invalid") from None
    if type(value) is not dict or set(value) != {
        "schema",
        "source_root",
        "receipt_root",
        "python",
        "parent_launcher_sha256",
        "pipe_address",
        "service_authkey_sha256",
        "files",
    }:
        raise ParentLaunchError("guardian_descriptor_fields_invalid")
    if value["schema"] != _INERT_GUARDIAN_SCHEMA:
        raise ParentLaunchError("guardian_descriptor_schema_invalid")
    source_root = _canonical_windows_path(value["source_root"], "source_root_invalid")
    receipt_root = _canonical_windows_path(value["receipt_root"], "receipt_root_invalid")
    parent_hash = _sha256(
        value["parent_launcher_sha256"], "guardian_parent_launcher_pin_invalid"
    )
    pipe_address = value["pipe_address"]
    if type(pipe_address) is not str or _INERT_GUARDIAN_PIPE_RE.fullmatch(pipe_address) is None:
        raise ParentLaunchError("guardian_pipe_address_invalid")
    authkey_hash = _sha256(
        value["service_authkey_sha256"], "guardian_service_authkey_pin_invalid"
    )
    python = value["python"]
    if type(python) is not dict or set(python) != {
        "executable",
        "sha256",
        "version",
        "architecture",
    }:
        raise ParentLaunchError("guardian_python_descriptor_invalid")
    executable = _canonical_windows_path(python["executable"], "python_executable_invalid")
    if python["version"] != "3.11.5" or python["architecture"] != "AMD64":
        raise ParentLaunchError("guardian_python_baseline_invalid")
    files = value["files"]
    if type(files) is not dict or set(files) not in (
        set(_LEGACY_INERT_GUARDIAN_FILES),
        set(_INERT_GUARDIAN_FILES),
        set(_READONLY_GUARDIAN_FILES),
    ):
        raise ParentLaunchError("guardian_source_set_invalid")
    checked_files = {}
    for relative in files:
        _canonical_relative(relative, relative, "guardian_source_path_invalid")
        checked_files[relative] = _sha256(files[relative], "guardian_source_pin_invalid")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    if raw != canonical:
        raise ParentLaunchError("descriptor_not_canonical")
    return InertGuardianPlan(
        source_root=source_root,
        receipt_root=receipt_root,
        python_executable=executable,
        python_sha256=_sha256(python["sha256"], "guardian_python_pin_invalid"),
        python_version=python["version"],
        python_architecture=python["architecture"],
        parent_launcher_sha256=parent_hash,
        pipe_address=pipe_address,
        service_authkey_sha256=authkey_hash,
        files=MappingProxyType(checked_files),
        descriptor_sha256=expected,
    )


def request_inert_guardian(
    trusted_descriptor: ExternallyPinnedDescriptor,
    *,
    captured_launcher_bytes: bytes,
    actual_executable: str,
    actual_version: str,
    actual_architecture: str,
    child_seconds: float,
    stop_deadline_monotonic: float,
    deadline_monotonic: float,
    service_pid: int,
    service_auth_key: bytes,
    request_id: str,
    ipc_requester,
    monotonic,
) -> InertGuardianResponse:
    """Ask an independently prestarted service to run the sole inert worker.

    This code never creates the guardian/service process. ``ipc_requester`` is
    expected to use bounded caller waiting and authenticate both the pipe
    server PID and its HMAC challenge. The request contains no process command
    or path. The external supervisor must have started the service from the
    descriptor-pinned source bundle and supplied its PID and key.
    """

    plan = parse_inert_guardian_descriptor(trusted_descriptor)
    if type(captured_launcher_bytes) is not bytes or not hmac.compare_digest(
        hashlib.sha256(captured_launcher_bytes).hexdigest(), plan.parent_launcher_sha256
    ):
        raise ParentLaunchError("guardian_parent_launcher_digest_mismatch")
    if (
        type(actual_executable) is not str
        or type(actual_version) is not str
        or type(actual_architecture) is not str
        or ntpath.normcase(actual_executable) != ntpath.normcase(plan.python_executable)
        or actual_version != plan.python_version
        or actual_architecture != plan.python_architecture
    ):
        raise ParentLaunchError("guardian_running_python_binding_mismatch")
    if not callable(ipc_requester) or not callable(monotonic):
        raise ParentLaunchError("guardian_ipc_adapter_invalid")
    if type(service_pid) is not int or service_pid <= 0:
        raise ParentLaunchError("guardian_service_pid_invalid")
    if (
        type(service_auth_key) is not bytes
        or not hmac.compare_digest(
            hashlib.sha256(service_auth_key).hexdigest(), plan.service_authkey_sha256
        )
    ):
        raise ParentLaunchError("guardian_service_authkey_mismatch")
    if type(request_id) is not str or re.fullmatch(r"[0-9a-f]{32}", request_id) is None:
        raise ParentLaunchError("guardian_request_id_invalid")
    child_value = float(child_seconds) if type(child_seconds) in (int, float) else float("nan")
    stop_value = (
        float(stop_deadline_monotonic)
        if type(stop_deadline_monotonic) in (int, float)
        else float("nan")
    )
    deadline_value = (
        float(deadline_monotonic)
        if type(deadline_monotonic) in (int, float)
        else float("nan")
    )
    if not 0.0 < child_value <= 300.0 or child_value == float("inf"):
        raise ParentLaunchError("guardian_child_duration_invalid")
    if (
        not 0.0 < stop_value <= deadline_value
        or stop_value == float("inf")
        or deadline_value == float("inf")
    ):
        raise ParentLaunchError("guardian_deadline_invalid")

    source_root = Path(plan.source_root)
    receipt_root = Path(plan.receipt_root)
    _assert_no_reparse_components(source_root, final_kind="directory")
    _assert_no_reparse_components(receipt_root, final_kind="directory")
    receipt_path = receipt_root / "guardian-receipt.json"
    if os.path.lexists(receipt_path):
        raise ParentLaunchError("guardian_receipt_already_exists")
    _read_pinned_file(
        Path(plan.python_executable), plan.python_sha256, "guardian_python_digest_mismatch"
    )
    for relative, digest in plan.files.items():
        path = source_root.joinpath(*relative.split("/"))
        _read_pinned_file(path, digest, "guardian_source_digest_mismatch")
    current = float(monotonic())
    if current >= stop_value:
        raise ParentLaunchError("guardian_request_deadline_expired")
    request = {
        "schema": "ctp_i13_i15_inert_guardian_request.v1",
        "operation": "sleep_probe",
        "request_id": request_id,
        "child_seconds": child_value,
        "stop_deadline_monotonic": stop_value,
        "deadline_monotonic": deadline_value,
    }
    request_bytes = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    try:
        exchange = ipc_requester(
            address=plan.pipe_address,
            expected_service_pid=service_pid,
            auth_key=service_auth_key,
            request_bytes=request_bytes,
            deadline_monotonic=deadline_value,
            monotonic=monotonic,
        )
    except BaseException:
        return InertGuardianResponse(
            state="unknown",
            reason="guardian_ipc_exchange_failed",
            service_pid=service_pid,
            request_id=request_id,
            response=None,
            descriptor_sha256=plan.descriptor_sha256,
        )
    if getattr(exchange, "state", None) != "response":
        return InertGuardianResponse(
            state="unknown",
            reason=getattr(exchange, "reason", "guardian_ipc_outcome_unknown"),
            service_pid=service_pid,
            request_id=request_id,
            response=None,
            descriptor_sha256=plan.descriptor_sha256,
        )
    raw_response = getattr(exchange, "response_bytes", None)
    if type(raw_response) is not bytes or not raw_response or len(raw_response) > 4096:
        raise ParentLaunchError("guardian_response_invalid")
    try:
        response = json.loads(
            raw_response.decode("ascii"), object_pairs_hook=_duplicate_rejecting_pairs
        )
    except ParentLaunchError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise ParentLaunchError("guardian_response_invalid") from None
    required_response_fields = {
        "schema",
        "state",
        "reason",
        "process_created",
        "job_assignment_observed",
        "launcher_resumed",
        "launcher_exit_observed",
        "job_termination_requested",
        "job_termination_call_succeeded",
        "job_empty_observed",
        "containment",
        "controls_retained",
        "service_schema",
        "request_id",
        "service_pid",
    }
    if (
        type(response) is not dict
        or set(response) != required_response_fields
        or response["service_schema"] != "ctp_i13_i15_inert_guardian_service_response.v1"
        or response["request_id"] != request_id
        or response["service_pid"] != service_pid
        or type(response["state"]) is not str
        or type(response["reason"]) is not str
    ):
        raise ParentLaunchError("guardian_response_binding_invalid")
    if float(monotonic()) >= deadline_value:
        return InertGuardianResponse(
            state="unknown",
            reason="guardian_response_after_deadline",
            service_pid=service_pid,
            request_id=request_id,
            response=None,
            descriptor_sha256=plan.descriptor_sha256,
        )
    return InertGuardianResponse(
        state=response["state"],
        reason=response["reason"],
        service_pid=service_pid,
        request_id=request_id,
        response=MappingProxyType(response),
        descriptor_sha256=plan.descriptor_sha256,
    )


def _parse_candidate_manifest(candidate: str, raw: bytes, expected_hash: str) -> Mapping[str, str]:
    """Validate the candidate manifest before any runtime module can load."""

    if not raw or len(raw) > 1024 * 1024:
        raise ParentLaunchError("manifest_invalid")
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), expected_hash):
        raise ParentLaunchError("manifest_digest_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_rejecting_pairs)
    except ParentLaunchError:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise ParentLaunchError("manifest_invalid") from None

    files = {}
    if candidate == "i13_md":
        if type(value) is not dict or set(value) != {"schema", "source_files"}:
            raise ParentLaunchError("manifest_invalid")
        if type(value["schema"]) is not int or value["schema"] != 1:
            raise ParentLaunchError("manifest_invalid")
        rows = value["source_files"]
        if type(rows) is not dict or not 1 <= len(rows) <= 4096 or list(rows) != sorted(rows):
            raise ParentLaunchError("manifest_order_invalid")
        for path, digest in rows.items():
            files[path] = _sha256(digest, "manifest_file_pin_invalid")
        canonical_value = {"schema": 1, "source_files": files}
    else:
        if type(value) is not dict or set(value) != {"files", "schema"}:
            raise ParentLaunchError("manifest_invalid")
        if value["schema"] != "ctp_i15_source_manifest.v2":
            raise ParentLaunchError("manifest_invalid")
        rows = value["files"]
        if type(rows) is not list or not 1 <= len(rows) <= 4096:
            raise ParentLaunchError("manifest_invalid")
        previous = None
        for row in rows:
            if type(row) is not dict or set(row) != {"path", "sha256"}:
                raise ParentLaunchError("manifest_invalid")
            path = row["path"]
            if type(path) is not str:
                raise ParentLaunchError("manifest_path_invalid")
            if path in files or (previous is not None and path <= previous):
                raise ParentLaunchError("manifest_order_invalid")
            files[path] = _sha256(row["sha256"], "manifest_file_pin_invalid")
            previous = path
        canonical_value = {
            "files": [{"path": path, "sha256": digest} for path, digest in files.items()],
            "schema": value["schema"],
        }

    for path in files:
        is_runtime_source = path.startswith("backtrader_runtime/")
        is_fixed_worker = candidate == "i13_md" and path == _READONLY_PREFLIGHT_WORKER
        is_fixed_bootstrap = candidate == "i13_md" and path == _READONLY_PREFLIGHT_BOOTSTRAP
        is_fixed_service_role = candidate == "i13_md" and path in _READONLY_SERVICE_ROLE_FILES
        if (
            type(path) is not str
            or "\\" in path
            or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(path).parts)
            or not (
                is_runtime_source
                or is_fixed_worker
                or is_fixed_bootstrap
                or is_fixed_service_role
            )
            or not path.endswith(".py")
            or path in {"backtrader_runtime/ctp_i13_source_identity_pin.py", "backtrader_runtime/ctp_i15_source_identity_pin.py"}
        ):
            raise ParentLaunchError("manifest_path_invalid")
    required = {
        "backtrader_runtime/__init__.py",
        "backtrader_runtime/inventory.py",
        _CANDIDATE_LAYOUT[candidate][2],
    }
    if not required.issubset(files):
        raise ParentLaunchError("manifest_required_source_unpinned")
    if _READONLY_PREFLIGHT_BOOTSTRAP in files:
        if _READONLY_PREFLIGHT_WORKER not in files:
            raise ParentLaunchError("readonly_worker_source_unpinned")
        if _READONLY_WORKER_DEPENDENCY_HELPER not in files:
            raise ParentLaunchError("readonly_dependency_helper_source_unpinned")
    present_service_roles = files.keys() & _READONLY_SERVICE_ROLE_FILES
    if present_service_roles and present_service_roles != _READONLY_SERVICE_ROLE_FILES:
        raise ParentLaunchError("readonly_service_roles_incomplete")
    if present_service_roles and _READONLY_PREFLIGHT_BOOTSTRAP not in files:
        raise ParentLaunchError("readonly_service_roles_without_bootstrap")
    canonical = json.dumps(
        canonical_value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    if raw != canonical:
        raise ParentLaunchError("manifest_not_canonical")
    return MappingProxyType(files)


def _parse_code_owned_manifest_pin(candidate: str, raw: bytes) -> str:
    """Read a literal pin without importing or executing its source module."""

    if type(raw) is not bytes or not raw or len(raw) > 64 * 1024:
        raise ParentLaunchError("candidate_pin_source_invalid")
    try:
        module = ast.parse(raw.decode("utf-8"), mode="exec")
    except (UnicodeError, SyntaxError, ValueError, TypeError):
        raise ParentLaunchError("candidate_pin_source_invalid") from None
    pin_name = _CODE_OWNED_PIN_NAMES[candidate]
    bindings = []
    for node in module.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == pin_name for target in node.targets):
                bindings.append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == pin_name:
                bindings.append(node.value)
    if len(bindings) != 1 or not isinstance(bindings[0], ast.Constant):
        raise ParentLaunchError("candidate_pin_source_invalid")
    value = bindings[0].value
    if value is None or value == "0" * 64:
        raise ParentLaunchError("candidate_source_pin_unset")
    return _sha256(value, "candidate_pin_source_invalid")


def inspect_local_source_pin_gaps(source_root: str | os.PathLike[str]) -> Mapping[str, tuple[str, ...]]:
    """Report local source-pin gaps without treating local bytes as trusted.

    This is an offline diagnostic. Even an empty result means only that both
    local pin/manifest pairs are present and agree; an external review receipt
    and descriptor anchor are still required before preflight can authorize a
    launch plan.
    """

    root = Path(source_root)
    if not root.is_absolute():
        raise ParentLaunchError("source_root_invalid")
    results = {}
    for candidate, (manifest_relative, pin_relative, _) in _CANDIDATE_LAYOUT.items():
        issues = []
        manifest_path = root.joinpath(*manifest_relative.split("/"))
        pin_path = root.joinpath(*pin_relative.split("/"))
        manifest_bytes = None
        try:
            manifest_bytes = manifest_path.read_bytes()
        except OSError:
            issues.append("manifest_missing")
        try:
            pin_bytes = pin_path.read_bytes()
        except OSError:
            issues.append("candidate_pin_missing")
        else:
            try:
                pin_digest = _parse_code_owned_manifest_pin(candidate, pin_bytes)
            except ParentLaunchError as error:
                issues.append(str(error))
            else:
                if manifest_bytes is not None and not hmac.compare_digest(
                    hashlib.sha256(manifest_bytes).hexdigest(), pin_digest
                ):
                    issues.append("candidate_source_pin_manifest_mismatch")
        issues.append("external_review_receipt_required")
        results[candidate] = tuple(issues)
    return MappingProxyType(results)


def _parse_pyvenv_cfg(raw: bytes, *, expected_home: str) -> None:
    if len(raw) > 16 * 1024:
        raise ParentLaunchError("pyvenv_cfg_invalid")
    values = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        raise ParentLaunchError("pyvenv_cfg_invalid") from None
    for line in lines:
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise ParentLaunchError("pyvenv_cfg_invalid")
        key, value = key.strip().casefold(), value.strip()
        if key in values:
            raise ParentLaunchError("pyvenv_cfg_duplicate_key")
        values[key] = value
    if (
        values.get("include-system-site-packages", "").casefold() != "false"
        or values.get("version") != "3.11.5"
        or not values.get("home")
        or ntpath.normcase(values["home"]) != ntpath.normcase(expected_home)
    ):
        raise ParentLaunchError("pyvenv_cfg_binding_invalid")


def preflight_parent_launch(
    trusted_descriptor: ExternallyPinnedDescriptor,
    *,
    candidate: object,
    captured_launcher_bytes: bytes,
    actual_executable: str,
    actual_version: str,
    actual_architecture: str,
    actual_sys_path: Sequence[str],
) -> ParentLaunchPlan:
    """Validate descriptor, launcher, interpreter, and source anchors.

    Call this before importing any ``backtrader_runtime`` module.  All reads
    are limited to the fixed interpreter facts and the selected candidate's
    two pinned source artifacts; this function has no config/marker/provider
    behavior.
    """

    if type(candidate) is not str or candidate not in _CANDIDATE_LAYOUT:
        raise ParentLaunchError("candidate_invalid")
    descriptor = parse_trust_descriptor(trusted_descriptor)
    if type(captured_launcher_bytes) is not bytes or not hmac.compare_digest(
        hashlib.sha256(captured_launcher_bytes).hexdigest(), descriptor.launcher_sha256
    ):
        raise ParentLaunchError("launcher_digest_mismatch")
    if (
        type(actual_executable) is not str
        or type(actual_version) is not str
        or type(actual_architecture) is not str
        or ntpath.normcase(actual_executable) != ntpath.normcase(descriptor.python_executable)
        or actual_version != descriptor.python_version
        or actual_architecture != descriptor.python_architecture
    ):
        raise ParentLaunchError("running_python_binding_mismatch")

    venv_root = Path(descriptor.venv_root)
    executable = Path(descriptor.python_executable)
    _read_pinned_file(executable, descriptor.python_sha256, "python_executable_digest_mismatch")
    cfg_path = venv_root / "pyvenv.cfg"
    cfg = _read_pinned_file(cfg_path, descriptor.pyvenv_cfg_sha256, "pyvenv_cfg_digest_mismatch")
    _parse_pyvenv_cfg(cfg, expected_home=descriptor.python_home)

    if type(actual_sys_path) not in (tuple, list) or any(
        type(value) is not str or not ntpath.isabs(value) for value in actual_sys_path
    ):
        raise ParentLaunchError("running_sys_path_invalid")
    actual = tuple(ntpath.normcase(value) for value in actual_sys_path)
    expected = tuple(ntpath.normcase(value) for value in descriptor.stdlib_paths)
    if actual != expected:
        raise ParentLaunchError("running_sys_path_mismatch")

    _assert_no_reparse_components(Path(descriptor.source_root), final_kind="directory")
    package_root = Path(descriptor.source_root) / _RUNTIME_PACKAGE
    registration_root = Path(descriptor.source_root).joinpath(*_PRIVATE_REGISTRATION.split("/"))
    _assert_no_reparse_components(package_root, final_kind="directory")
    _assert_no_reparse_components(registration_root, final_kind="directory")

    spec = descriptor.candidates[candidate]
    manifest_path = Path(descriptor.source_root).joinpath(*spec["manifest_path"].split("/"))
    pin_path = Path(descriptor.source_root).joinpath(*spec["pin_path"].split("/"))
    manifest = _read_pinned_file(
        manifest_path, spec["manifest_sha256"], "manifest_digest_mismatch"
    )
    _parse_candidate_manifest(candidate, manifest, spec["manifest_sha256"])
    pin_source = _read_pinned_file(pin_path, spec["pin_sha256"], "candidate_pin_digest_mismatch")
    code_owned_pin = _parse_code_owned_manifest_pin(candidate, pin_source)
    if not hmac.compare_digest(code_owned_pin, spec["manifest_sha256"]):
        raise ParentLaunchError("candidate_source_pin_manifest_mismatch")
    return ParentLaunchPlan(
        candidate=candidate,
        source_root=descriptor.source_root,
        manifest_path=str(manifest_path),
        manifest_sha256=spec["manifest_sha256"],
        pin_path=str(pin_path),
        pin_sha256=spec["pin_sha256"],
        entrypoint=spec["entrypoint"],
        python_executable=descriptor.python_executable,
        python_sha256=descriptor.python_sha256,
        venv_root=descriptor.venv_root,
        pyvenv_cfg_sha256=descriptor.pyvenv_cfg_sha256,
        stdlib_paths=descriptor.stdlib_paths,
        descriptor_sha256=descriptor.descriptor_sha256,
        pin_source_sha256s=MappingProxyType(
            {
                "i13": descriptor.candidates["i13_md"]["pin_sha256"],
                "i15": descriptor.candidates["i15_td"]["pin_sha256"],
            }
        ),
    )


def prepare_candidate_import_and_job_setup(
    trusted_descriptor: ExternallyPinnedDescriptor,
    *,
    candidate: object,
    captured_launcher_bytes: bytes,
    actual_executable: str,
    actual_version: str,
    actual_architecture: str,
    actual_sys_path: Sequence[str],
    sealed_importer: object,
    metadata_job_setup,
) -> PreparedCandidateImport:
    """Offline parent ordering seam; all effects are caller-injected.

    The trusted descriptor is mandatory. Source and interpreter checks finish
    before the clean-bootstrap check. The existing sealed importer then seals
    source, installs its finder, and imports only the fixed candidate through
    that finder. Metadata Job setup is invoked only after that import boundary
    returns successfully. This function has no marker/config/provider calls.
    """

    if type(trusted_descriptor) is not ExternallyPinnedDescriptor:
        raise ParentLaunchError("trusted_descriptor_required")
    if not callable(metadata_job_setup):
        raise ParentLaunchError("metadata_job_setup_required")
    plan = preflight_parent_launch(
        trusted_descriptor,
        candidate=candidate,
        captured_launcher_bytes=captured_launcher_bytes,
        actual_executable=actual_executable,
        actual_version=actual_version,
        actual_architecture=actual_architecture,
        actual_sys_path=actual_sys_path,
    )

    clean_check = getattr(sealed_importer, "validate_clean_bootstrap_import_state", None)
    seal_source = getattr(sealed_importer, "seal_candidate_source_tree", None)
    install_finder = getattr(sealed_importer, "install_sealed_source_finder", None)
    import_candidate = getattr(sealed_importer, "import_sealed_candidate_module", None)
    if not all(callable(value) for value in (clean_check, seal_source, install_finder, import_candidate)):
        raise ParentLaunchError("sealed_importer_api_invalid")

    clean_check()
    seal = seal_source(
        candidate,
        plan.source_root,
        expected_manifest_sha256=plan.manifest_sha256,
        expected_pin_sha256s=dict(plan.pin_source_sha256s),
        stdlib_paths=plan.stdlib_paths,
    )
    if (
        getattr(seal, "candidate", None) != plan.candidate
        or getattr(seal, "manifest_sha256", None) != plan.manifest_sha256
        or _normalized_seal_source_root(getattr(seal, "source_root", None))
        != ntpath.normcase(ntpath.normpath(plan.source_root))
        or _normalized_seal_stdlib_paths(getattr(seal, "stdlib_paths", None))
        != tuple(
            ntpath.normcase(ntpath.normpath(path)) for path in plan.stdlib_paths
        )
    ):
        try:
            close = getattr(seal, "close", None)
            if not callable(close):
                raise ParentLaunchError("source_seal_cleanup_failed")
            close()
        except Exception:
            raise ParentLaunchError("source_seal_cleanup_failed") from None
        raise ParentLaunchError("sealed_importer_binding_mismatch")
    try:
        finder = install_finder(seal)
        module = import_candidate(seal, finder)
        job_result = metadata_job_setup(plan, module)
    except BaseException:
        try:
            seal.close()
        except Exception:
            raise ParentLaunchError("source_seal_cleanup_failed") from None
        raise
    return PreparedCandidateImport(plan, seal, finder, module, job_result)


def _normalized_seal_source_root(value: object) -> str:
    if not isinstance(value, (str, Path)):
        return ""
    return ntpath.normcase(ntpath.normpath(os.fspath(value)))


def _normalized_seal_stdlib_paths(value: object) -> tuple[str, ...]:
    if type(value) not in (tuple, list) or any(type(path) is not str for path in value):
        return ()
    return tuple(ntpath.normcase(ntpath.normpath(path)) for path in value)


__all__ = [
    "ParentLaunchError",
    "ParentLaunchPlan",
    "ParentTrustDescriptor",
    "ExternallyPinnedDescriptor",
    "InertGuardianPlan",
    "InertGuardianResponse",
    "PreparedCandidateImport",
    "inspect_local_source_pin_gaps",
    "parse_inert_guardian_descriptor",
    "request_inert_guardian",
    "parse_trust_descriptor",
    "preflight_parent_launch",
    "prepare_candidate_import_and_job_setup",
]
