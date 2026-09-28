"""Unregistered I15 TD-only supervised read diagnostic candidate.

I15 is a fresh one-shot execution envelope for the corrected TD-only I12
diagnostic.  It uses a separate permanent marker and a receipt that names the
I15 candidate.  The reviewed I12 installed-artifact verifier and read-only TD
session primitives are reused because I15 exercises the same CTP wheel; the
I12 marker is never read, written, or reset by this module.

This module is intentionally absent from the default runtime inventory and
CLI.  Its only provider path is the sealed seven-query TD read-only path.  It
does not construct an MD client and has no settlement, order, cancel, or write
operation.
"""

from __future__ import annotations

import ctypes
import hmac
import json
import logging
import os
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import ctp_i12_td_only_readonly as i12
from .ctp_readonly_job_supervisor import (
    FailClosedLatch,
    FixedChildCommand,
    ProcessEvidence,
    SupervisedResult,
    ValueFreeReceiptSchema,
    parse_single_json_receipt,
    run_readonly_child,
)
from .ctp_i15_source_identity import (
    I15_EXCLUDED_SOURCE_PIN_PATHS,
    I15_SOURCE_MANIFEST_ENV,
    I15SourceIdentityBinding,
    I15SourceIdentityError,
    discover_i15_source_files,
    render_i15_source_verifier_bootstrap,
    verify_i15_source_identity,
)
from .ctp_i15_source_identity_pin import I15_REVIEWED_SOURCE_MANIFEST_SHA256
from .inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)


I15_CANDIDATE_ID = "i15_td_only_readonly"
I15_ARTIFACT_PIN_SOURCE = "i12_td_only_readonly_same_installed_ctp_wheel"
_I15_MARKER_CONTENT = b"i15-td-only-readonly-supervised-attempted-v1\n"
I15_LATCH_PATH = (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    / "state"
    / "i15-td-only-readonly-supervisor-no-retry.latch"
)
_I15_FIXED_SITE_PACKAGES = i12._I12_RUNTIME_ROOT / "Lib" / "site-packages"
_I15_JOB_HANDLE_ENV = "bt_i15_parent_job_handle"
_I15_TOTAL_DEADLINE_SECONDS = 90.0
_I15_TERMINATION_GRACE_SECONDS = 5.0
_I15_MAX_STDOUT_BYTES = 32 * 1024
_I15_RETAINED_JOB_CONTROL: Optional[object] = None
_I15_PINNED_SOURCE_DIGEST = (
    I15_REVIEWED_SOURCE_MANIFEST_SHA256
    if type(I15_REVIEWED_SOURCE_MANIFEST_SHA256) is str
    and len(I15_REVIEWED_SOURCE_MANIFEST_SHA256) == 64
    and all(character in "0123456789abcdef" for character in I15_REVIEWED_SOURCE_MANIFEST_SHA256)
    else None
)


def _source_digest_tokens(digest: Optional[str]) -> tuple[str, str]:
    if (
        type(digest) is str
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    ):
        return "a" + digest[:32], "b" + digest[32:]
    return "unavailable", "unavailable"


def _receipt_source_digest(receipt: Mapping[str, object]) -> Optional[str]:
    high = receipt.get("source_manifest_token_hi")
    low = receipt.get("source_manifest_token_lo")
    if (
        type(high) is str
        and type(low) is str
        and len(high) == 33
        and len(low) == 33
        and high.startswith("a")
        and low.startswith("b")
        and all(character in "0123456789abcdef" for character in high[1:] + low[1:])
    ):
        return high[1:] + low[1:]
    return None


def _verify_i15_parent_source_identity() -> Optional[I15SourceIdentityBinding]:
    """Verify source and already-loaded import origins before front precheck."""

    if _I15_PINNED_SOURCE_DIGEST is None:
        return None
    try:
        source_root = Path(__file__).resolve(strict=True).parents[1]
        binding = verify_i15_source_identity(
            source_root, expected_manifest_sha256=_I15_PINNED_SOURCE_DIGEST
        )
        source_files = set(discover_i15_source_files(source_root))
        for name, module in tuple(sys.modules.items()):
            if name == "backtrader" or name.startswith("backtrader."):
                return None
            if name != "backtrader_runtime" and not name.startswith("backtrader_runtime."):
                continue
            module_file = getattr(module, "__file__", None)
            if type(module_file) is not str:
                return None
            resolved_file = Path(module_file).resolve(strict=True)
            relative = resolved_file.relative_to(source_root).as_posix()
            if name in {
                "backtrader_runtime.ctp_i13_source_identity_pin",
                "backtrader_runtime.ctp_i15_source_identity_pin",
            }:
                if relative not in I15_EXCLUDED_SOURCE_PIN_PATHS:
                    return None
                continue
            if relative not in source_files:
                return None
            if os.path.normcase(os.path.abspath(resolved_file)) != os.path.normcase(
                os.path.abspath(source_root.joinpath(*Path(relative).parts))
            ):
                return None
            module_path = getattr(module, "__path__", None)
            if name == "backtrader_runtime":
                if type(module_path) not in (list, tuple) or tuple(
                    os.path.normcase(os.path.abspath(path)) for path in module_path
                ) != (os.path.normcase(os.path.abspath(source_root / "backtrader_runtime")),):
                    return None
        return binding
    except Exception:
        return None


def _new_i15_pycache_prefix() -> Optional[Path]:
    """Choose a unique absent prefix so isolated Jobs cannot read checkout pycs."""

    try:
        temporary_root = Path(tempfile.gettempdir())
        if not temporary_root.is_absolute() or not temporary_root.is_dir():
            return None
        for _ in range(8):
            candidate = temporary_root / ("bt-i15-pycache-" + uuid.uuid4().hex)
            if not os.path.lexists(candidate):
                return candidate
    except (OSError, TypeError, ValueError):
        return None
    return None


def _i15_child_receipt_schema(
    expected_digest: Optional[str] = None,
) -> ValueFreeReceiptSchema:
    token_hi, token_lo = _source_digest_tokens(expected_digest or _I15_PINNED_SOURCE_DIGEST)
    return ValueFreeReceiptSchema(
        enum_fields={
            **i12.I12_CHILD_RECEIPT_SCHEMA.enum_fields,
            "candidate_id": (I15_CANDIDATE_ID,),
            "marker_scope": ("i15_unique",),
            "source_identity": ("verified", "rejected", "unavailable"),
            "source_manifest_token_hi": (token_hi, "unavailable"),
            "source_manifest_token_lo": (token_lo, "unavailable"),
        },
        nullable_enum_fields=i12.I12_CHILD_RECEIPT_SCHEMA.nullable_enum_fields,
        bool_fields=i12.I12_CHILD_RECEIPT_SCHEMA.bool_fields,
        nullable_bool_fields=i12.I12_CHILD_RECEIPT_SCHEMA.nullable_bool_fields,
    )


def _i15_artifact_preflight_schema(
    expected_digest: Optional[str] = None,
) -> ValueFreeReceiptSchema:
    token_hi, token_lo = _source_digest_tokens(expected_digest)
    return ValueFreeReceiptSchema(
        enum_fields={
            "candidate_id": (I15_CANDIDATE_ID,),
            "reason": ("artifact_rejected", "artifact_verified", "source_identity_rejected"),
            "source_identity": ("verified", "rejected"),
            "source_manifest_token_hi": (token_hi,),
            "source_manifest_token_lo": (token_lo,),
            "status": ("rejected", "verified"),
        },
        nullable_enum_fields={},
        bool_fields=("credential_resolver_invoked", "native_join_pending", "sdk_imported"),
        nullable_bool_fields=(),
    )


I15_CHILD_RECEIPT_SCHEMA = _i15_child_receipt_schema()
I15_ARTIFACT_PREFLIGHT_SCHEMA = _i15_artifact_preflight_schema()


def parse_i15_child_receipt(
    raw: bytes, *, expected_source_digest: Optional[str] = None
) -> Optional[Mapping[str, object]]:
    """Parse one duplicate-free I15 receipt against its exact schema."""

    return parse_single_json_receipt(raw, _i15_child_receipt_schema(expected_source_digest))


def _complete_i15_receipt(
    value: object, *, expected_source_digest: Optional[str] = None
) -> Optional[dict[str, object]]:
    if type(value) is not dict:
        return None
    try:
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None
    parsed = parse_i15_child_receipt(raw, expected_source_digest=expected_source_digest)
    return parsed if type(parsed) is dict and parsed == value else None


def _emit_i15(fields: Mapping[str, object]) -> None:
    payload = _complete_i15_receipt(dict(fields))
    if payload is None:
        payload = i12._initial_receipt(reason="runtime_policy_rejected", stage="configuration")
        payload.update(
            candidate_id=I15_CANDIDATE_ID,
            marker_scope="i15_unique",
            source_identity="unavailable",
            source_manifest_token_hi="unavailable",
            source_manifest_token_lo="unavailable",
        )
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _i15_initial_receipt(
    *,
    reason: str,
    stage: str,
    source_identity: str = "unavailable",
    source_manifest_sha256: Optional[str] = None,
) -> dict[str, object]:
    fields = i12._initial_receipt(reason=reason, stage=stage)
    token_hi, token_lo = _source_digest_tokens(source_manifest_sha256)
    fields.update(
        candidate_id=I15_CANDIDATE_ID,
        marker_scope="i15_unique",
        source_identity=(
            source_identity
            if source_identity in {"verified", "rejected", "unavailable"}
            else "unavailable"
        ),
        source_manifest_token_hi=token_hi,
        source_manifest_token_lo=token_lo,
    )
    return fields


def _is_current_process_in_i15_job() -> bool:
    if os.name != "nt":
        return False
    raw_handle = os.environ.pop(_I15_JOB_HANDLE_ENV, None)
    if (
        type(raw_handle) is not str
        or not raw_handle.isdecimal()
        or len(raw_handle) > 20
        or int(raw_handle) <= 0
    ):
        return False
    job_handle = ctypes.c_void_p(int(raw_handle))
    kernel32 = None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.argtypes = ()
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        is_process_in_job = kernel32.IsProcessInJob
        is_process_in_job.argtypes = (
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_int),
        )
        is_process_in_job.restype = ctypes.c_int
        in_job = ctypes.c_int()
        return bool(
            is_process_in_job(kernel32.GetCurrentProcess(), job_handle, ctypes.byref(in_job))
            and in_job.value != 0
        )
    except Exception:
        return False
    finally:
        if kernel32 is not None:
            try:
                kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
                kernel32.CloseHandle.restype = ctypes.c_int
                kernel32.CloseHandle(job_handle)
            except Exception:
                pass


def _has_supervised_i15_attempt_context() -> bool:
    if not _is_current_process_in_i15_job():
        return False
    try:
        return PersistentI15TdOnlyAttemptLatch(I15_LATCH_PATH).is_tripped() is True
    except Exception:
        return False


def _run_i15_child_diagnostic() -> int:
    """Revalidate the exact I12-sealed TD contract under I15's own context."""

    if tuple(sys.argv[1:]):
        _emit_i15(_i15_initial_receipt(reason="arguments_not_allowed", stage="arguments"))
        return 2
    if not _has_supervised_i15_attempt_context():
        _emit_i15(_i15_initial_receipt(reason="supervisor_context_required", stage="arguments"))
        return 2

    expected_source_digest = os.environ.pop(I15_SOURCE_MANIFEST_ENV, None)
    if (
        _I15_PINNED_SOURCE_DIGEST is None
        or type(expected_source_digest) is not str
        or not hmac.compare_digest(expected_source_digest, _I15_PINNED_SOURCE_DIGEST)
    ):
        _emit_i15(
            _i15_initial_receipt(
                reason="runtime_policy_rejected",
                stage="configuration",
                source_identity="rejected",
                source_manifest_sha256=_I15_PINNED_SOURCE_DIGEST,
            )
        )
        return 2
    try:
        source_binding = verify_i15_source_identity(
            Path.cwd(), expected_manifest_sha256=expected_source_digest
        )
    except I15SourceIdentityError:
        _emit_i15(
            _i15_initial_receipt(
                reason="runtime_policy_rejected",
                stage="configuration",
                source_identity="rejected",
                source_manifest_sha256=expected_source_digest,
            )
        )
        return 2

    logging.disable(logging.CRITICAL)
    stage = "configuration"
    session_evidence: Optional[i12.I12TdOnlySessionEvidence] = None
    try:
        if i12.I12_SDK_SOURCE_COMMIT != "a6253a58b1ebca11f58c8836fbed757d0daf7582":
            raise RuntimeError("i15_sdk_source_mismatch")
        stage = "front_precheck"
        precheck = i12._child_recheck_precheck_binding()
        stage = "configuration"
        effective, registry, binding, private, front_pairs = i12._load_sealed_context()
        index = precheck.config_index
        if not 0 <= index < len(front_pairs):
            raise ValueError("fresh_seal_binding_mismatch")
        md_front, td_front = i12._candidate_front_pair(front_pairs[index])
        current = i12._front_binding_digest(
            effective_digest=effective.effective_digest,
            registration_digest=effective.registration.digest,
            config_index=index,
            md_front=md_front,
            td_front=td_front,
        )
        if not hmac.compare_digest(current.binding_sha256, precheck.binding_sha256):
            raise ValueError("fresh_seal_binding_mismatch")

        stage = "sdk_artifact"
        with i12.trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
            i12.verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts(
                td_front=td_front, md_front=md_front
            )

            # Construct the concrete typed pair at the Mapping boundary that
            # rejected I12's consumed one-shot before any credential access.
            stage = "route_binding"
            from .ctp_front_pair_probe import CtpConfiguredFrontPair
            from .ctp_sandbox_readonly_admission import (
                require_ctp_sandbox_readonly_runtime_contract,
            )

            selected_pair = CtpConfiguredFrontPair(md_front=md_front, td_front=td_front)
            admission, credential_scope = binding._route(
                effective,
                registry,
                selected_front_pair=selected_pair,
                selected_config_index=index,
            )
            i12._validate_bound_scope(private, admission, index, front_pairs)
            admission = require_ctp_sandbox_readonly_runtime_contract(
                effective, registry, admission
            )

            stage = "credentials"
            from .credential_resolver import (
                require_resolved_runtime_credentials_seal,
                resolve_runtime_credentials,
            )

            credentials = resolve_runtime_credentials(effective, registry, credential_scope)
            require_resolved_runtime_credentials_seal(
                credentials, effective, registry, credential_scope
            )
            stage = "td_session"
            from .ctp_preflight import CTP_PROVIDER, CtpReadOnlySessionRequest
            from .ctp_sdk_readonly import (
                CtpSdkReadOnlyScope,
                CtpSdkReadOnlySessionFactory,
            )

            credential_source = i12._I12SealedCredentialSource(
                credentials, effective, registry, credential_scope
            )
            sdk_scope = CtpSdkReadOnlyScope(
                environment=admission.environment,
                sdk_profile=admission.sdk_profile,
                td_front=admission.td_front,
                md_front=admission.md_front,
                account_fingerprint_sha256=admission.account_fingerprint_sha256,
                instrument_id=admission.instrument_id,
                exchange_id=admission.exchange_id,
                hedge_flag=admission.hedge_flag,
            )
            factory = CtpSdkReadOnlySessionFactory(
                sdk_scope,
                credential_source,
                connect_timeout=15.0,
                query_timeout=5.0,
            )
            request = CtpReadOnlySessionRequest(
                provider=CTP_PROVIDER,
                environment=admission.environment,
                account_fingerprint_sha256=admission.account_fingerprint_sha256,
                valid_until=time.time() + admission.session_ttl_seconds,
            )
            session_evidence = i12._run_i12_td_only_session_candidate(factory, request)

        fields = session_evidence.as_child_fields(stage=stage)
        fields.update(
            candidate_id=I15_CANDIDATE_ID,
            marker_scope="i15_unique",
            source_identity="verified",
            source_manifest_token_hi=_source_digest_tokens(source_binding.manifest_sha256)[0],
            source_manifest_token_lo=_source_digest_tokens(source_binding.manifest_sha256)[1],
        )
        _emit_i15(fields)
        return 0 if session_evidence.status == "td_readonly_complete" else 3
    except Exception as error:
        reason = i12._safe_reason_for_exception(error, stage)
        fields = _i15_initial_receipt(
            reason=reason,
            stage=stage,
            source_identity="verified",
            source_manifest_sha256=source_binding.manifest_sha256,
        )
        if session_evidence is not None:
            fields.update(session_evidence.as_child_fields(stage=stage))
            fields.update(
                candidate_id=I15_CANDIDATE_ID,
                marker_scope="i15_unique",
                source_identity="verified",
                source_manifest_token_hi=_source_digest_tokens(source_binding.manifest_sha256)[0],
                source_manifest_token_lo=_source_digest_tokens(source_binding.manifest_sha256)[1],
            )
        _emit_i15(fields)
        return 2


def _run_i15_child_entry() -> int:
    return _run_i15_child_diagnostic()


class _PersistentI15LatchPrimitive:
    """Use the hardened no-retry marker protocol with an I15-only payload."""

    def __init__(self, path: Path) -> None:
        from .ctp_i8_oneshot_md_diagnostic import _PersistentI8NoRetryLatch

        class _I15Marker(_PersistentI8NoRetryLatch):
            _latch_content = _I15_MARKER_CONTENT

            def _verify_ancestor_chain(self) -> None:
                path_key = os.path.normcase(os.path.normpath(os.fspath(self._path)))
                canonical_key = os.path.normcase(os.path.normpath(os.fspath(I15_LATCH_PATH)))
                if path_key != canonical_key:
                    super()._verify_ancestor_chain()
                    return
                registry = iteration41_runtime_registry()
                registration = registry.require_runtime_dir(
                    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
                )
                if registration.runtime_id != ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID:
                    raise OSError("latch_runtime_registration_invalid")
                with registry.verified_runtime_directory(registration):
                    super()._verify_ancestor_chain()

        self._delegate = _I15Marker(path)

    def begin_attempt(self) -> bool:
        return self._delegate.begin_attempt() is True

    def is_tripped(self) -> bool:
        return self._delegate.is_tripped() is True

    def trip(self, reason: str) -> bool:
        return self._delegate.trip(reason) is True


class PersistentI15TdOnlyAttemptLatch:
    """Lazy one-shot latch facade; production callers use the fixed I15 path."""

    def __init__(self, path: Path = I15_LATCH_PATH) -> None:
        self._path = Path(path)
        self._delegate: Optional[_PersistentI15LatchPrimitive] = None

    def _active(self) -> _PersistentI15LatchPrimitive:
        if self._delegate is None:
            self._delegate = _PersistentI15LatchPrimitive(self._path)
        return self._delegate

    def begin_attempt(self) -> bool:
        return self._active().begin_attempt()

    def is_tripped(self) -> bool:
        return self._active().is_tripped()

    def trip(self, reason: str) -> bool:
        return self._active().trip(reason)


@dataclass(frozen=True)
class I15DiagnosticReport:
    status: str
    reason: str
    artifact_pin_verified: Optional[bool]
    artifact_job_containment: str
    attempt_reserved: Optional[bool]
    supervised: Optional[SupervisedResult]
    source_identity_verified: bool = False
    source_manifest_sha256: Optional[str] = None

    def as_dict(self) -> dict[str, object]:
        result = self.supervised
        receipt = (
            _complete_i15_receipt(
                result.sdk_receipt,
                expected_source_digest=self.source_manifest_sha256,
            )
            if result is not None
            else None
        )
        evidence = result.process_evidence if result is not None else None
        return {
            "artifact_pin_source": I15_ARTIFACT_PIN_SOURCE,
            "artifact_job_containment": self.artifact_job_containment
            if self.artifact_job_containment
            in {"not_started", "unavailable", "uncertain", "verified"}
            else "unavailable",
            "artifact_pin_verified": self.artifact_pin_verified
            if type(self.artifact_pin_verified) is bool
            else None,
            "attempt_reserved": self.attempt_reserved
            if type(self.attempt_reserved) is bool
            else None,
            "candidate_id": I15_CANDIDATE_ID,
            "marker_scope": "i15_unique",
            "source_identity_verified": self.source_identity_verified is True,
            "source_manifest_sha256": self.source_manifest_sha256
            if _source_digest_tokens(self.source_manifest_sha256)[0] != "unavailable"
            else None,
            "process_evidence": {
                "containment": evidence.containment
                if evidence is not None
                and evidence.containment
                in {"latched", "not_started", "unavailable", "uncertain", "verified"}
                else "unavailable"
                if evidence is not None
                else "not_started",
                "job_assignment_observed": evidence.job_assignment_observed is True
                if evidence is not None
                else False,
                "job_empty_observed": evidence.job_empty_observed
                if evidence is not None and type(evidence.job_empty_observed) is bool
                else None,
                "job_termination_requested": evidence.job_termination_requested is True
                if evidence is not None
                else False,
                "process_created": evidence.process_created is True
                if evidence is not None
                else False,
                "process_exit_code": evidence.process_exit_code
                if evidence is not None and type(evidence.process_exit_code) is int
                else None,
                "process_exit_observed": evidence.process_exit_observed
                if evidence is not None and type(evidence.process_exit_observed) is bool
                else None,
                "process_resumed": evidence.process_resumed is True
                if evidence is not None
                else False,
            },
            "reason": self.reason,
            "sdk_receipt": receipt,
            "status": self.status,
        }


def _empty_evidence(containment: str) -> ProcessEvidence:
    return ProcessEvidence(False, False, False, None, None, False, None, None, containment)


def _expired(deadline_monotonic: float) -> bool:
    try:
        return time.monotonic() >= deadline_monotonic
    except Exception:
        return True


def _fixed_i15_child_command(
    binding: i12.I12FrontPrecheckBinding,
    *,
    source_digest: Optional[str] = None,
) -> Optional[FixedChildCommand]:
    """Bind the exact I12 pair and source digest into I15's fixed worker."""

    digest = source_digest or _I15_PINNED_SOURCE_DIGEST
    if type(binding) is not i12.I12FrontPrecheckBinding or digest is None:
        return None
    if not i12._is_concrete_path(_I15_FIXED_SITE_PACKAGES, directory=True):
        return None
    base = i12._fixed_i12_child_command(binding)
    if type(base) is not FixedChildCommand:
        return None
    try:
        cache_prefix = _new_i15_pycache_prefix()
        if cache_prefix is None:
            return None
        environment = dict(base.env)
        environment[I15_SOURCE_MANIFEST_ENV] = digest
        bootstrap = render_i15_source_verifier_bootstrap(
            source_root=base.cwd,
            expected_manifest_sha256=digest,
            cache_prefix=cache_prefix,
            site_packages_root=_I15_FIXED_SITE_PACKAGES,
        )
        child_source = (
            bootstrap
            + "\n"
            + f"if os.environ.get({I15_SOURCE_MANIFEST_ENV!r}) != _I15_SOURCE_EXPECTED or not _verify_i15_source_identity(): raise SystemExit(2)\n"
            + "import types\n"
            + "_i15_pin = types.ModuleType('backtrader_runtime.ctp_i15_source_identity_pin')\n"
            + "_i15_pin.I15_REVIEWED_SOURCE_MANIFEST_SHA256 = _I15_SOURCE_EXPECTED\n"
            + "sys.modules['backtrader_runtime.ctp_i15_source_identity_pin'] = _i15_pin\n"
            + "_install_i15_sealed_importer()\n"
            + "if not _i15_add_fixed_install_root() or not _i15_bind_fixed_artifact_install_root(): raise SystemExit(2)\n"
            + "import backtrader_runtime\n"
            + "from backtrader_runtime.ctp_i15_td_only_readonly import _run_i15_child_entry\n"
            + "if not _verify_i15_import_origins(): raise SystemExit(2)\n"
            + "raise SystemExit(_run_i15_child_entry())"
        )
        return FixedChildCommand(
            (
                base.argv[0],
                "-I",
                "-S",
                "-B",
                "-X",
                "pycache_prefix=" + os.fspath(cache_prefix),
                "-c",
                child_source,
            ),
            base.cwd,
            environment,
            job_handle_env_name=_I15_JOB_HANDLE_ENV,
        )
    except (OSError, TypeError, ValueError):
        return None


def _parse_i15_artifact_preflight_receipt(
    raw: bytes, *, expected_source_digest: Optional[str] = None
) -> Optional[Mapping[str, object]]:
    return parse_single_json_receipt(raw, _i15_artifact_preflight_schema(expected_source_digest))


def _i15_artifact_preflight_succeeded(result: object, *, expected_source_digest: str) -> bool:
    if type(result) is not SupervisedResult:
        return False
    receipt = result.sdk_receipt
    evidence = result.process_evidence
    try:
        valid_receipt = (
            type(receipt) is dict
            and _parse_i15_artifact_preflight_receipt(
                (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
                expected_source_digest=expected_source_digest,
            )
            == receipt
        )
    except (TypeError, ValueError, UnicodeError):
        valid_receipt = False
    return (
        valid_receipt
        and receipt["candidate_id"] == I15_CANDIDATE_ID
        and receipt["reason"] == "artifact_verified"
        and receipt["source_identity"] == "verified"
        and _receipt_source_digest(receipt) == expected_source_digest
        and receipt["status"] == "verified"
        and receipt["credential_resolver_invoked"] is False
        and receipt["sdk_imported"] is False
        and receipt["native_join_pending"] is False
        and type(evidence) is ProcessEvidence
        and result.status == "child_exited"
        and result.reason == "child_process_exited"
        and evidence.process_created is True
        and evidence.job_assignment_observed is True
        and evidence.process_resumed is True
        and evidence.process_exit_observed is True
        and evidence.process_exit_code == 0
        and evidence.job_termination_requested is False
        and evidence.job_termination_call_succeeded is None
        and evidence.job_empty_observed is True
        and evidence.containment == "verified"
        and result.retained_control is None
    )


def _fixed_i15_artifact_preflight_command(
    worker_command: FixedChildCommand,
    *,
    source_digest: Optional[str] = None,
) -> Optional[FixedChildCommand]:
    """Verify the I15 source set and I12 wheel metadata in the same Job."""

    digest = source_digest or _I15_PINNED_SOURCE_DIGEST
    if digest is None or type(worker_command) is not FixedChildCommand:
        return None
    if not i12._is_concrete_path(_I15_FIXED_SITE_PACKAGES, directory=True):
        return None
    base = i12._fixed_i12_artifact_preflight_command(worker_command)
    if type(base) is not FixedChildCommand or len(base.argv) != 5 or base.argv[3] != "-c":
        return None
    try:
        cache_prefix = _new_i15_pycache_prefix()
        if cache_prefix is None:
            return None
        token_hi, token_lo = _source_digest_tokens(digest)
        verifier = render_i15_source_verifier_bootstrap(
            source_root=base.cwd,
            expected_manifest_sha256=digest,
            cache_prefix=cache_prefix,
            site_packages_root=_I15_FIXED_SITE_PACKAGES,
        )
        base_code = base.argv[4]
        source_path_insertion = f"sys.path.insert(0, {str(base.cwd)!r})\n"
        if base_code.count(source_path_insertion) != 1:
            return None
        base_code = base_code.replace(source_path_insertion, "", 1)
        indented_base_code = "\n".join("    " + line for line in base_code.splitlines()) + "\n"
        code = (
            verifier
            + "\n"
            + "import contextlib, io\n"
            + "_i15_payload = {'candidate_id': 'i15_td_only_readonly', "
            + "'credential_resolver_invoked': False, 'native_join_pending': False, "
            + "'reason': 'source_identity_rejected', 'sdk_imported': False, "
            + "'source_identity': 'rejected', 'source_manifest_token_hi': "
            + repr(token_hi)
            + ", 'source_manifest_token_lo': "
            + repr(token_lo)
            + ", 'status': 'rejected'}\n"
            + f"_i15_env_digest = os.environ.pop({I15_SOURCE_MANIFEST_ENV!r}, None)\n"
            + "if _i15_env_digest == _I15_SOURCE_EXPECTED and _verify_i15_source_identity():\n"
            + "    _install_i15_sealed_importer()\n"
            + "    if not _i15_add_fixed_install_root() or not _i15_bind_fixed_artifact_install_root():\n"
            + "        _i15_payload.update(reason='artifact_rejected', source_identity='verified')\n"
            + "    else:\n"
            + "        _i15_capture = io.StringIO()\n"
            + "        _i15_exit = 2\n"
            + "        try:\n"
            + "            with contextlib.redirect_stdout(_i15_capture):\n"
            + f"                exec(compile({indented_base_code!r}, '<i15-i12-artifact-preflight>', 'exec'), {{}})\n"
            + "        except SystemExit as _i15_stopped:\n"
            + "            _i15_exit = _i15_stopped.code if type(_i15_stopped.code) is int else 2\n"
            + "        try:\n"
            + "            _i15_base = json.loads(_i15_capture.getvalue(), object_pairs_hook=lambda pairs: dict(pairs))\n"
            + "            if type(_i15_base) is not dict or set(_i15_base) != {'credential_resolver_invoked', 'native_join_pending', 'reason', 'sdk_imported', 'status'}: raise ValueError()\n"
            + "            if _i15_base['credential_resolver_invoked'] is not False or _i15_base['sdk_imported'] is not False or _i15_base['native_join_pending'] is not False: raise ValueError()\n"
            + "            if _i15_base['reason'] not in {'artifact_rejected', 'artifact_verified'} or _i15_base['status'] not in {'rejected', 'verified'}: raise ValueError()\n"
            + "            if (_i15_base['reason'], _i15_base['status']) == ('artifact_verified', 'verified') and _i15_exit == 0 and _verify_i15_source_identity() and _verify_i15_import_origins():\n"
            + "                _i15_payload.update(reason='artifact_verified', source_identity='verified', status='verified')\n"
            + "            else:\n"
            + "                _i15_payload.update(reason='artifact_rejected', source_identity='verified')\n"
            + "        except Exception:\n"
            + "            _i15_payload.update(reason='artifact_rejected', source_identity='verified')\n"
            + "sys.stdout.write(json.dumps(_i15_payload, sort_keys=True, separators=(',', ':')) + '\\n')\n"
            + "raise SystemExit(0 if _i15_payload['status'] == 'verified' else 2)\n"
        )
        environment = dict(base.env)
        environment[I15_SOURCE_MANIFEST_ENV] = digest
        return FixedChildCommand(
            (
                base.argv[0],
                "-I",
                "-S",
                "-B",
                "-X",
                "pycache_prefix=" + os.fspath(cache_prefix),
                "-c",
                code,
            ),
            base.cwd,
            environment,
        )
    except (OSError, TypeError, ValueError):
        return None


def _parse_i15_child_receipt(
    raw: bytes, *, expected_source_digest: Optional[str] = None
) -> Optional[Mapping[str, object]]:
    return parse_i15_child_receipt(raw, expected_source_digest=expected_source_digest)


def _parent_confirms_i15_readonly(
    result: object, *, expected_source_digest: Optional[str] = None
) -> bool:
    if type(result) is not SupervisedResult:
        return False
    digest = expected_source_digest or _I15_PINNED_SOURCE_DIGEST
    if digest is None:
        return False
    receipt = _complete_i15_receipt(result.sdk_receipt, expected_source_digest=digest)
    if (
        receipt is None
        or receipt["candidate_id"] != I15_CANDIDATE_ID
        or receipt["marker_scope"] != "i15_unique"
        or receipt["source_identity"] != "verified"
        or _receipt_source_digest(receipt) != digest
    ):
        return False
    normalized = dict(receipt)
    del normalized["candidate_id"]
    del normalized["marker_scope"]
    del normalized["source_identity"]
    del normalized["source_manifest_token_hi"]
    del normalized["source_manifest_token_lo"]
    base_result = SupervisedResult(
        result.status,
        result.reason,
        normalized,
        result.process_evidence,
        result.retained_control,
    )
    return i12._parent_confirms_i12_readonly(base_result)


def _report_from_child(
    result: SupervisedResult,
    *,
    artifact_containment: str,
    attempt_reserved: bool,
    source_digest: str,
) -> I15DiagnosticReport:
    def report(status: str, reason: str, *, source_verified: bool = True) -> I15DiagnosticReport:
        return I15DiagnosticReport(
            status,
            reason,
            source_verified,
            artifact_containment,
            attempt_reserved,
            result,
            True,
            source_digest,
        )

    if _parent_confirms_i15_readonly(result, expected_source_digest=source_digest):
        return report("td_readonly_complete", "td_readonly_query_bundle_closed")
    receipt = _complete_i15_receipt(result.sdk_receipt, expected_source_digest=source_digest)
    if receipt is not None and (
        receipt["source_identity"] != "verified" or _receipt_source_digest(receipt) != source_digest
    ):
        return report("rejected", "source_identity_rejected", source_verified=False)
    if receipt is not None and receipt["native_join_pending"] is True:
        return report("incomplete", "native_join_pending")
    if result.status == "timed_out":
        return report("incomplete", "child_deadline_exceeded")
    if result.status == "pending_native_join":
        return report("incomplete", "native_join_pending")
    if receipt is not None:
        status = "incomplete" if receipt["status"] == "incomplete" else "rejected"
        reason = (
            "child_diagnostic_incomplete" if status == "incomplete" else "child_diagnostic_rejected"
        )
        return report(status, reason)
    return report("supervisor_error", "i15_supervisor_failed")


def _supervise_i15_child(
    *,
    precheck: Optional[Callable[[float], i12.I12FrontPrecheckBinding]] = None,
    command_builder: Optional[
        Callable[[i12.I12FrontPrecheckBinding, str], Optional[FixedChildCommand]]
    ] = None,
    artifact_command_builder: Optional[
        Callable[[FixedChildCommand, str], Optional[FixedChildCommand]]
    ] = None,
    latch_factory: Optional[Callable[[Path], FailClosedLatch]] = None,
    runner: Optional[Callable[..., SupervisedResult]] = None,
) -> I15DiagnosticReport:
    """Seal source before precheck, verify artifacts, reserve I15, and supervise."""

    global _I15_RETAINED_JOB_CONTROL
    deadline = time.monotonic() + _I15_TOTAL_DEADLINE_SECONDS
    if os.name != "nt":
        return I15DiagnosticReport(
            "supervisor_error", "windows_required", None, "unavailable", None, None
        )
    if _expired(deadline):
        return I15DiagnosticReport(
            "incomplete", "child_deadline_exceeded", None, "not_started", None, None
        )
    source_binding = _verify_i15_parent_source_identity()
    if (
        type(source_binding) is not I15SourceIdentityBinding
        or _I15_PINNED_SOURCE_DIGEST is None
        or not hmac.compare_digest(source_binding.manifest_sha256, _I15_PINNED_SOURCE_DIGEST)
    ):
        return I15DiagnosticReport(
            "rejected", "source_identity_unavailable", None, "not_started", None, None
        )
    source_digest = source_binding.manifest_sha256

    def report(
        status: str,
        reason: str,
        artifact_verified: Optional[bool],
        containment: str,
        attempt_reserved: Optional[bool],
        supervised: Optional[SupervisedResult],
        *,
        source_verified: bool = True,
    ) -> I15DiagnosticReport:
        return I15DiagnosticReport(
            status,
            reason,
            artifact_verified,
            containment,
            attempt_reserved,
            supervised,
            source_verified,
            source_digest,
        )

    try:
        binding = (
            i12._parent_credential_free_precheck(deadline_monotonic=deadline)
            if precheck is None
            else precheck(deadline)
        )
    except Exception:
        return report("rejected", "front_precheck_failed", None, "not_started", None, None)
    if _expired(deadline):
        return report("incomplete", "child_deadline_exceeded", None, "not_started", None, None)
    if type(binding) is not i12.I12FrontPrecheckBinding:
        return report("rejected", "front_precheck_failed", None, "not_started", None, None)
    refreshed_source = _verify_i15_parent_source_identity()
    if (
        type(refreshed_source) is not I15SourceIdentityBinding
        or refreshed_source.manifest_sha256 != source_digest
    ):
        return report(
            "rejected",
            "source_identity_rejected",
            None,
            "not_started",
            None,
            None,
            source_verified=False,
        )
    try:
        command = (
            command_builder(binding, source_digest)
            if command_builder is not None
            else _fixed_i15_child_command(binding, source_digest=source_digest)
        )
        artifact_command = (
            artifact_command_builder(command, source_digest)
            if artifact_command_builder is not None and command is not None
            else _fixed_i15_artifact_preflight_command(command, source_digest=source_digest)
            if command is not None
            else None
        )
    except Exception:
        command = artifact_command = None
    if command is None or artifact_command is None:
        return report(
            "supervisor_error", "i15_runtime_unavailable", False, "not_started", None, None
        )
    if _expired(deadline):
        return report("incomplete", "child_deadline_exceeded", None, "not_started", None, None)

    active_runner = runner or run_readonly_child
    try:
        artifact_result = active_runner(
            artifact_command,
            lambda raw: _parse_i15_artifact_preflight_receipt(
                raw, expected_source_digest=source_digest
            ),
            receipt_schema=_i15_artifact_preflight_schema(source_digest),
            fail_closed_latch=i12._I12ArtifactPreflightLatch(),
            deadline_seconds=10.0,
            deadline_monotonic=deadline,
            max_stdout_bytes=4096,
            termination_grace_seconds=2.0,
        )
    except Exception:
        return report("supervisor_error", "i15_supervisor_failed", False, "unavailable", None, None)
    if type(artifact_result) is SupervisedResult and artifact_result.retained_control is not None:
        _I15_RETAINED_JOB_CONTROL = artifact_result.retained_control
    artifact_evidence = (
        artifact_result.process_evidence
        if type(artifact_result) is SupervisedResult
        and type(artifact_result.process_evidence) is ProcessEvidence
        else _empty_evidence("unavailable")
    )
    artifact_containment = artifact_evidence.containment
    if _expired(deadline):
        return report(
            "incomplete",
            "child_deadline_exceeded",
            False,
            artifact_containment,
            None,
            artifact_result if type(artifact_result) is SupervisedResult else None,
        )
    if not _i15_artifact_preflight_succeeded(artifact_result, expected_source_digest=source_digest):
        return report(
            "rejected" if artifact_containment == "verified" else "supervisor_error",
            "sdk_artifact_rejected"
            if artifact_containment == "verified"
            else "i15_supervisor_failed",
            False,
            artifact_containment,
            None,
            artifact_result if type(artifact_result) is SupervisedResult else None,
        )

    refreshed_source = _verify_i15_parent_source_identity()
    if (
        type(refreshed_source) is not I15SourceIdentityBinding
        or refreshed_source.manifest_sha256 != source_digest
    ):
        return report(
            "rejected",
            "source_identity_rejected",
            True,
            artifact_containment,
            None,
            None,
            source_verified=False,
        )

    make_latch = latch_factory or PersistentI15TdOnlyAttemptLatch
    try:
        latch = make_latch(I15_LATCH_PATH)
        is_tripped = getattr(latch, "is_tripped", None)
        begin_attempt = getattr(latch, "begin_attempt", None)
        if not callable(is_tripped) or not callable(begin_attempt):
            raise TypeError("i15_latch_unavailable")
        if _expired(deadline):
            return report(
                "incomplete", "child_deadline_exceeded", True, artifact_containment, None, None
            )
        if is_tripped() is True:
            return report(
                "latched",
                "prior_attempt_or_poisoned_latch",
                True,
                artifact_containment,
                False,
                None,
            )
        if _expired(deadline):
            return report(
                "incomplete", "child_deadline_exceeded", True, artifact_containment, None, None
            )
        if begin_attempt() is not True:
            return report(
                "latched",
                "prior_attempt_or_poisoned_latch",
                True,
                artifact_containment,
                False,
                None,
            )
    except Exception:
        return report(
            "supervisor_error", "i15_latch_unavailable", True, artifact_containment, None, None
        )
    if _expired(deadline):
        return report(
            "incomplete", "child_deadline_exceeded", True, artifact_containment, True, None
        )
    try:
        result = active_runner(
            command,
            lambda raw: _parse_i15_child_receipt(raw, expected_source_digest=source_digest),
            receipt_schema=_i15_child_receipt_schema(source_digest),
            fail_closed_latch=latch,
            deadline_seconds=_I15_TOTAL_DEADLINE_SECONDS,
            deadline_monotonic=deadline,
            max_stdout_bytes=_I15_MAX_STDOUT_BYTES,
            termination_grace_seconds=_I15_TERMINATION_GRACE_SECONDS,
        )
    except Exception:
        return report(
            "supervisor_error", "i15_supervisor_failed", True, artifact_containment, True, None
        )
    if type(result) is not SupervisedResult:
        return report(
            "supervisor_error",
            "i15_supervisor_result_invalid",
            True,
            artifact_containment,
            True,
            None,
        )
    if result.retained_control is not None:
        _I15_RETAINED_JOB_CONTROL = result.retained_control
    if _expired(deadline):
        result = SupervisedResult(
            "timed_out",
            "child_deadline_exceeded",
            result.sdk_receipt,
            result.process_evidence,
            result.retained_control,
        )
    refreshed_source = _verify_i15_parent_source_identity()
    if (
        type(refreshed_source) is not I15SourceIdentityBinding
        or refreshed_source.manifest_sha256 != source_digest
    ):
        return report(
            "rejected",
            "source_identity_rejected",
            True,
            artifact_containment,
            True,
            result,
            source_verified=False,
        )
    return _report_from_child(
        result,
        artifact_containment=artifact_containment,
        attempt_reserved=True,
        source_digest=source_digest,
    )


def supervise_i15_td_only_child() -> I15DiagnosticReport:
    """Explicit, unregistered operator candidate; absent from runtime routing."""

    return _supervise_i15_child()


def main() -> int:
    if tuple(sys.argv[1:]):
        report = I15DiagnosticReport(
            "rejected", "arguments_not_allowed", None, "not_started", None, None
        )
    else:
        report = supervise_i15_td_only_child()
    sys.stdout.write(json.dumps(report.as_dict(), sort_keys=True) + "\n")
    sys.stdout.flush()
    if report.status == "td_readonly_complete":
        return 0
    if report.reason in {"native_join_pending", "child_deadline_exceeded"}:
        return 3
    return 2


__all__ = [
    "I15_CANDIDATE_ID",
    "I15_LATCH_PATH",
    "I15_CHILD_RECEIPT_SCHEMA",
    "I15DiagnosticReport",
    "PersistentI15TdOnlyAttemptLatch",
    "parse_i15_child_receipt",
    "supervise_i15_td_only_child",
]


if __name__ == "__main__":  # pragma: no cover - explicit candidate entry only
    raise SystemExit(main())
