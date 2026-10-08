"""One-shot Root driver for Optional16 source preparation only.

The driver opens the fixed R2/V4 held-source scope on the calling Root thread,
then delegates the complete-map derivation, profiler proof, source transforms,
postverify, and close to the already reviewed preparation call adapter and R1
helper. It has no CLI entry point and remains closed unless ``requested=True``
is passed explicitly. It never enters the R5 worker installer or activation.

This file is a source-only preparation candidate. It does not confer account,
provider, SDK, native, or Optional16 acceptance authority.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import math
from pathlib import Path
import re
import sys
import threading
import time
import types


ROOT = Path(r"D:\source_code\backtrader")
SCHEMA = "iteration41.optional16.r33.root-preparation-driver.r2"
CALL_SCHEMA = "iteration41.optional16.r33.root-preparation-call.r2"
MAX_SOURCE_BYTES = 256 * 1024
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
_SAFE_CODE = re.compile(r"[a-z0-9_:]{1,96}\Z")
_ATTEMPT_STARTED = False
_RETAINED_ATTEMPTS: list[tuple[object, ...]] = []
_OWNER_THREAD: int | None = None

ENTRY_REL = Path("scripts/iteration41_optional16_r33_root_held_entry_r2.py")
ENTRY_SHA256 = "80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead"
V3_REL = Path("scripts/iteration41_root_held_source_scope_v3.py")
V3_SHA256 = "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677"
V4_REL = Path("scripts/iteration41_root_held_source_scope_v4.py")
V4_SHA256 = "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830"
R5_REL = Path("scripts/iteration41_optional16_r33_root_held_invoke_r28_r5.py")
R5_SHA256 = "710452c8358887faa152cd2c6d11333ccf8ecb18fbe64d511ce86eb8f112c99c"
R27_INVOKE_REL = Path("scripts/iteration41_optional16_r33_root_held_invoke_r27.py")
R27_INVOKE_SHA256 = "ea0a4f9ec5978508b854fe457dd1cfc3c0e9c41b7b23b89ec461bfed4d798339"
R27_WHOLE_REL = Path("scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py")
R27_WHOLE_SHA256 = "bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876"
PREPARATION_REL = Path("scripts/iteration41_optional16_r33_root_preparation_r1.py")
PREPARATION_SHA256 = "a626001a9f80bee26996a0fd3effb0e670c96ffd7a167ba154d23521eca64aa4"
CALL_REL = Path("scripts/iteration41_optional16_r33_root_preparation_call_r2.py")
CALL_SHA256 = "f569bf401ee164758000f49bd3c98c0bafd67beda3d3fed05b91fd76c1faf5b2"

_DIAGNOSTIC_PHASES = frozenset(
    {
        "input_shape", "module_binding", "scope_reread", "helper_load",
        "helper_call", "result_check", "root_preflight", "root_entry_load",
        "root_scope_bootstrap", "root_held_sources", "root_call_adapter",
    }
)
_DIAGNOSTIC_CATEGORIES = frozenset(
    {"source_contract", "preparation_result", "scope_state", "unexpected", "none", "root_setup"}
)
_DIAGNOSTIC_CODES = frozenset(
    {
        "input_rejected", "module_binding_rejected", "scope_reread_rejected",
        "helper_pin_rejected", "helper_load_rejected", "preparation_rejected",
        "scope_not_closed", "unexpected_exception", "preparation_complete",
        "root_setup_failed", "root_scope_failed", "root_sources_failed", "root_call_failed",
    }
)

_PUBLIC_SOURCE_PINS = (
    (ENTRY_REL, ENTRY_SHA256),
    (V3_REL, V3_SHA256),
    (V4_REL, V4_SHA256),
    (R5_REL, R5_SHA256),
    (R27_INVOKE_REL, R27_INVOKE_SHA256),
    (R27_WHOLE_REL, R27_WHOLE_SHA256),
    (PREPARATION_REL, PREPARATION_SHA256),
    (CALL_REL, CALL_SHA256),
)


class RootPreparationDriverError(RuntimeError):
    """Finite status codes only; never carries paths, bytes, or OS text."""


def _need(condition: object, code: str) -> None:
    if not condition:
        raise RootPreparationDriverError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_key(path: str | Path) -> str:
    return str(path).replace("/", "\\").casefold()


def _read_public_source(relative: Path, expected_sha256: str) -> tuple[Path, bytes]:
    path = ROOT / relative
    _need(path.is_absolute() and path == ROOT / relative, "public_source_path_invalid")
    try:
        resolved_root = ROOT.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        _need(resolved_path.is_relative_to(resolved_root), "public_source_outside_repository")
        with path.open("rb") as stream:
            raw = stream.read(MAX_SOURCE_BYTES + 1)
    except RootPreparationDriverError:
        raise
    except BaseException:
        raise RootPreparationDriverError("public_source_unavailable") from None
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_SOURCE_BYTES, "public_source_size_invalid")
    _need(_sha(raw) == expected_sha256, "public_source_pin_mismatch")
    return path, raw


def _load_exact_public_module(
    relative: Path, expected_sha256: str, raw: bytes, name: str
) -> types.ModuleType:
    path = ROOT / relative
    _need(type(raw) is bytes and _sha(raw) == expected_sha256, "module_source_pin_invalid")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__loader__ = None
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module.__verified_source_sha256__ = expected_sha256
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
    except BaseException:
        raise RootPreparationDriverError("pinned_public_module_load_failed") from None
    return module


def _build_payload() -> tuple[bytes, tuple[types.ModuleType, ...]]:
    """Build the exact R27 payload from fixed public modules without scope I/O."""
    loaded: list[types.ModuleType] = []
    by_rel = {}
    for relative, digest in _PUBLIC_SOURCE_PINS:
        path, raw = _read_public_source(relative, digest)
        by_rel[relative] = (path, raw)

    r5 = _load_exact_public_module(
        R5_REL, R5_SHA256, by_rel[R5_REL][1], "_optional16_r33_r5_payload_builder"
    )
    invoke = _load_exact_public_module(
        R27_INVOKE_REL,
        R27_INVOKE_SHA256,
        by_rel[R27_INVOKE_REL][1],
        "_optional16_r33_r27_invoke_payload_source",
    )
    whole = _load_exact_public_module(
        R27_WHOLE_REL,
        R27_WHOLE_SHA256,
        by_rel[R27_WHOLE_REL][1],
        "_optional16_r33_r27_whole_payload_source",
    )
    _need(
        getattr(invoke, "ROOT_ACTUAL_ENABLED", None) is False
        and getattr(invoke, "ROOT_REVIEW_READY", None) is False
        and getattr(invoke, "ROOT_REVIEWED_ACTIVATION", None) is False
        and getattr(whole, "ROOT_ACTUAL_ENABLED", None) is False
        and getattr(whole, "ROOT_REVIEW_READY", None) is False
        and getattr(whole, "ROOT_REVIEWED_ACTIVATION", None) is False
        and getattr(whole, "ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED", None) is False
        and getattr(whole, "ROOT_NATIVE_ENABLED", None) is False
        and getattr(r5, "ROOT_ACTUAL_ENABLED", None) is False
        and getattr(r5, "ROOT_EXTERNAL_SOURCE_HOLDS_VERIFIED", None) is False,
        "pinned_modules_not_default_closed",
    )
    wait_seconds = getattr(whole, "WHOLE_CALL_SECONDS", None)
    _need(type(wait_seconds) is float and wait_seconds == 100.0, "r27_deadline_bound_invalid")
    now = time.monotonic()
    deadline = now + wait_seconds
    _need(math.isfinite(now) and math.isfinite(deadline) and deadline > now,
          "monotonic_deadline_invalid")
    try:
        payload = r5.build_child_payload(invoke, whole, deadline)
        payload_raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    except BaseException:
        raise RootPreparationDriverError("fixed_payload_build_failed") from None
    _need(type(payload) is dict and type(payload_raw) is bytes, "fixed_payload_shape_invalid")
    _need(0 < len(payload_raw) <= MAX_PAYLOAD_BYTES, "fixed_payload_size_invalid")
    loaded.extend((r5, invoke, whole))
    return payload_raw, tuple(loaded)


def _root_runtime_matches(invoke: types.ModuleType) -> bool:
    return (
        sys.platform == "win32"
        and sys.implementation.name == "cpython"
        and tuple(sys.version_info[:3]) == (3, 11, 5)
        and getattr(invoke, "PARENT_DEADLINE_CLOCK_DOMAIN", None)
        == "windows-cpython-3.11.5-monotonic-v1"
    )


def _safe_failure_code(error: BaseException, entry=None, v4=None) -> str:
    allowed = [RootPreparationDriverError]
    if entry is not None:
        allowed.append(getattr(entry, "RootHeldEntryError", None))
    if v4 is not None:
        allowed.append(getattr(v4, "RootHeldScopeV4Error", None))
        v3 = getattr(v4, "_V3_MODULE", None)
        if v3 is not None:
            allowed.append(getattr(v3, "RootHeldSourceError", None))
    allowed_types = tuple(item for item in allowed if isinstance(item, type))
    if type(error) not in allowed_types or not error.args:
        return "root_preparation_failed"
    value = error.args[0]
    if type(value) is str and _SAFE_CODE.fullmatch(value):
        return value
    return "root_preparation_failed"


def _blocked(
    code: str,
    *,
    opened: bool,
    state: str,
    diagnostic_phase: str = "root_preflight",
    diagnostic_category: str = "root_setup",
    diagnostic_code: str = "root_setup_failed",
) -> dict[str, object]:
    retained = opened and state not in {"CLOSED", "CLOSED_RECEIPT_INVALID"}
    if type(diagnostic_phase) is not str or diagnostic_phase not in _DIAGNOSTIC_PHASES:
        diagnostic_phase = "root_call_adapter"
    if type(diagnostic_category) is not str or diagnostic_category not in _DIAGNOSTIC_CATEGORIES:
        diagnostic_category = "unexpected"
    if type(diagnostic_code) is not str or diagnostic_code not in _DIAGNOSTIC_CODES:
        diagnostic_code = "unexpected_exception"
    return {
        "schema": SCHEMA,
        "status": "BLOCKED_RETAINED" if retained else "BLOCKED",
        "reason_code": code if _SAFE_CODE.fullmatch(code) else "root_preparation_failed",
        "evidence_level": "ROOT_HELD_PREPARATION_ONLY" if opened else "NONE",
        "scope_state": state,
        "authority": "NONE",
        "installer": "NOT_ENTERED",
        "worker": "NOT_ENTERED",
        "activation": "NOT_ENTERED",
        "control": "NOT_ENTERED",
        "child": "NOT_ENTERED",
        "retry": "DO_NOT_RETRY_IN_THIS_PROCESS" if opened else "NO_SCOPE_OPENED",
        "diagnostic_phase": diagnostic_phase,
        "diagnostic_category": diagnostic_category,
        "diagnostic_code": diagnostic_code,
    }


def _diagnostic_from_receipt(receipt: object) -> dict[str, str]:
    if type(receipt) is not dict:
        return {
            "diagnostic_phase": "root_call_adapter",
            "diagnostic_category": "unexpected",
            "diagnostic_code": "unexpected_exception",
        }
    phase = receipt.get("diagnostic_phase")
    category = receipt.get("diagnostic_category")
    code = receipt.get("diagnostic_code")
    if (
        type(phase) is str and phase in _DIAGNOSTIC_PHASES
        and type(category) is str and category in _DIAGNOSTIC_CATEGORIES
        and type(code) is str and code in _DIAGNOSTIC_CODES
    ):
        return {
            "diagnostic_phase": phase,
            "diagnostic_category": category,
            "diagnostic_code": code,
        }
    return {
        "diagnostic_phase": "root_call_adapter",
        "diagnostic_category": "unexpected",
        "diagnostic_code": "unexpected_exception",
    }


def _scope_state(scope: object) -> str:
    value = getattr(scope, "state", None)
    allowed = {"NEW", "OPENING", "OPEN", "POSTVERIFIED", "RETAINED", "CLOSED"}
    return value if value in allowed else "UNKNOWN"


def _verified_receipt(receipt: object, scope: object) -> bool:
    if type(receipt) is not dict:
        return False
    expected_keys = {
        "schema", "status", "reason_code", "evidence_level", "public_rows",
        "full_union_rows", "software_rows", "held_rows", "profiler_modules",
        "boundary", "scope_state", "authority", "activation", "control", "child",
        "diagnostic_phase", "diagnostic_category", "diagnostic_code",
    }
    return (
        set(receipt) == expected_keys
        and receipt.get("schema") == CALL_SCHEMA
        and receipt.get("status") == "PREPARATION_VERIFIED_NO_AUTHORITY"
        and receipt.get("reason_code") == "held_source_preparation_complete"
        and receipt.get("evidence_level") == "ROOT_HELD_PREPARATION_ONLY"
        and receipt.get("public_rows") == 582
        and type(receipt.get("full_union_rows")) is int
        and receipt["full_union_rows"] >= 582
        and receipt.get("software_rows") == 5
        and type(receipt.get("held_rows")) is int
        and receipt["held_rows"] >= 587
        and receipt.get("profiler_modules") == 3
        and receipt.get("boundary") == "before_r5_worker_installer"
        and receipt.get("scope_state") == "CLOSED"
        and getattr(scope, "state", None) == "CLOSED"
        and receipt.get("authority") == "NONE"
        and receipt.get("activation") == "NOT_ENTERED"
        and receipt.get("control") == "NOT_ENTERED"
        and receipt.get("child") == "NOT_ENTERED"
        and receipt.get("diagnostic_phase") == "result_check"
        and receipt.get("diagnostic_category") == "none"
        and receipt.get("diagnostic_code") == "preparation_complete"
    )


def _extra_support_rows(entry: types.ModuleType, scope: object) -> None:
    pins = {
        _path_key(ROOT / PREPARATION_REL): PREPARATION_SHA256,
        _path_key(ROOT / CALL_REL): CALL_SHA256,
    }
    manifest = {_path_key(path): digest for path, digest in scope.manifest().items()}
    pending = {}
    for path, digest in pins.items():
        prior = manifest.get(path)
        _need(prior is None or prior == digest, "preparation_helper_scope_pin_conflict")
        if prior is None:
            pending[path] = digest
    if pending:
        scope.resolve_and_hold(
            entry._binding_rows(pending, category="public", prefix="root-preparation-r2")
        )
    current = {_path_key(path): digest for path, digest in scope.manifest().items()}
    _need(all(current.get(path) == digest for path, digest in pins.items()),
          "preparation_helper_scope_binding_missing")


def prepare_root_held_source_gate(*, requested: bool = False) -> dict[str, object]:
    """Open one Root V4 scope and run preparation only when explicitly requested.

    Call from the current Root owner thread. Any uncertainty after scope-open
    is retained and returns a closed finite receipt; this function never tries
    to close a scope outside the frozen R1 postverify/release path.
    """
    global _ATTEMPT_STARTED, _OWNER_THREAD
    if requested is not True:
        return _blocked("preparation_request_required", opened=False, state="NOT_OPENED")
    if _ATTEMPT_STARTED:
        if _RETAINED_ATTEMPTS:
            retained = _RETAINED_ATTEMPTS[-1]
            prior_scope = retained[4] if len(retained) > 4 else None
            prior_state = _scope_state(prior_scope) if prior_scope is not None else "UNKNOWN"
            return _blocked("one_shot_attempt_already_used", opened=True, state=prior_state)
        return _blocked("one_shot_attempt_already_used", opened=False, state="NOT_OPENED")
    _ATTEMPT_STARTED = True
    _OWNER_THREAD = threading.get_ident()
    entry = None
    v4 = None
    scope = None
    payload_raw = None
    preloaded: tuple[types.ModuleType, ...] = ()
    retained: tuple[object, ...] = ()
    stage = "runtime_preflight"
    opened_attempt = False
    try:
        # The payload's deadline is the frozen R27 100-second monotonic limit.
        # This preflight does no scope, control, claim, or child operation.
        payload_raw, preloaded = _build_payload()
        r27_invoke = preloaded[1]
        _need(_root_runtime_matches(r27_invoke), "required_root_runtime_mismatch")

        stage = "root_entry_load"
        entry_path, entry_raw = _read_public_source(ENTRY_REL, ENTRY_SHA256)
        entry = _load_exact_public_module(
            ENTRY_REL, ENTRY_SHA256, entry_raw, "_optional16_r33_root_entry_preparation_driver"
        )
        _need(entry.__file__ == str(entry_path), "root_entry_origin_invalid")
        _need(
            entry.ROOT_ACTUAL_ENABLED is False and entry.ROOT_ENTRY_SOURCE_SHA256 is None,
            "root_entry_default_not_closed",
        )
        # This is only the exact self-source pin needed by the R2 bootstrap
        # map. The root activation switch stays false and run() is never used.
        entry.ROOT_ENTRY_SOURCE_SHA256 = ENTRY_SHA256
        v4, _v4_raw = entry._load_v4_module()
        _need(type(v4) is types.ModuleType, "v4_module_load_invalid")
        retained = (entry, v4, payload_raw, preloaded)

        # Keep strong references before the physical scope open. If __enter__
        # fails, V3's own retained-scope registry and this tuple preserve state.
        _RETAINED_ATTEMPTS.append(retained)
        stage = "production_scope_bootstrap"
        scope = entry._bootstrap_scope(v4, payload_raw)
        opened_attempt = True
        retained = (*retained, scope)
        _RETAINED_ATTEMPTS[-1] = retained
        _need(
            type(scope) is v4.RootHeldScopeV4
            and scope.state == "OPEN"
            and scope.test_only is False
            and threading.get_ident() == _OWNER_THREAD,
            "production_scope_identity_invalid",
        )

        stage = "held_preparation_helpers"
        _extra_support_rows(entry, scope)
        prep_raw = scope.read_held(ROOT / PREPARATION_REL, PREPARATION_SHA256, MAX_SOURCE_BYTES)
        call_raw = scope.read_held(ROOT / CALL_REL, CALL_SHA256, MAX_SOURCE_BYTES)
        v3_raw = scope.read_held(ROOT / V3_REL, V3_SHA256, MAX_SOURCE_BYTES)
        v4_raw = scope.read_held(ROOT / V4_REL, V4_SHA256, MAX_SOURCE_BYTES)
        _need(all(type(raw) is bytes for raw in (prep_raw, call_raw, v3_raw, v4_raw)),
              "held_preparation_bytes_invalid")
        call_module = _load_exact_public_module(
            CALL_REL, CALL_SHA256, call_raw, "_optional16_r33_root_preparation_call_r2"
        )
        retained = (*retained, call_module, prep_raw, call_raw, v3_raw, v4_raw)
        _RETAINED_ATTEMPTS[-1] = retained

        stage = "reviewed_preparation_call"
        receipt = call_module.prepare_root_source_verification(
            scope,
            v4,
            payload_raw,
            {"v3": v3_raw, "v4": v4_raw},
            prep_raw,
            requested=True,
        )
        if _verified_receipt(receipt, scope):
            _RETAINED_ATTEMPTS.pop()
            return {
                "schema": SCHEMA,
                "status": "PREPARATION_VERIFIED_NO_AUTHORITY",
                "reason_code": "root_held_preparation_closed",
                "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
                "public_rows": 582,
                "full_union_rows": receipt["full_union_rows"],
                "software_rows": 5,
                "held_rows": receipt["held_rows"],
                "profiler_modules": 3,
                "boundary": "before_r5_worker_installer",
                "scope_state": "CLOSED",
                "authority": "NONE",
                "installer": "NOT_ENTERED",
                "worker": "NOT_ENTERED",
                "activation": "NOT_ENTERED",
                "control": "NOT_ENTERED",
                "child": "NOT_ENTERED",
                "retry": "NEW_ROOT_PROCESS_REQUIRED",
                "diagnostic_phase": receipt["diagnostic_phase"],
                "diagnostic_category": receipt["diagnostic_category"],
                "diagnostic_code": receipt["diagnostic_code"],
            }

        code = (
            receipt.get("reason_code")
            if type(receipt) is dict and type(receipt.get("reason_code")) is str
            else "preparation_receipt_invalid"
        )
        if type(code) is not str or not _SAFE_CODE.fullmatch(code):
            code = "preparation_receipt_invalid"
        scope_state = _scope_state(scope)
        diagnostic = _diagnostic_from_receipt(receipt)
        if scope_state == "CLOSED":
            _RETAINED_ATTEMPTS.pop()
            return _blocked(
                code, opened=True, state="CLOSED_RECEIPT_INVALID", **diagnostic
            )
        return _blocked(code, opened=True, state=scope_state, **diagnostic)
    except BaseException as error:
        if opened_attempt:
            # Deliberately retain; do not add a second cleanup path around R1.
            if retained:
                _RETAINED_ATTEMPTS[-1] = retained
            state = _scope_state(scope)
            return _blocked(_safe_failure_code(error, entry, v4), opened=True, state=state)
        if scope is not None:
            # Bootstrap may have partially opened and retained handles before
            # raising. Keep the exact references and require Root reconciliation.
            _RETAINED_ATTEMPTS.append((entry, v4, scope, payload_raw, preloaded))
            return _blocked(_safe_failure_code(error, entry, v4), opened=True, state="UNKNOWN")
        if stage == "production_scope_bootstrap" and entry is not None and v4 is not None:
            # Entry/V3 keep their own scope registry if __enter__ failed before
            # bootstrap returned a Python reference to this driver.
            _RETAINED_ATTEMPTS.append((entry, v4, payload_raw, preloaded))
            return _blocked(_safe_failure_code(error, entry, v4), opened=True, state="UNKNOWN")
        return _blocked(_safe_failure_code(error, entry, v4), opened=False, state="NOT_OPENED")


__all__ = ("SCHEMA", "prepare_root_held_source_gate")
