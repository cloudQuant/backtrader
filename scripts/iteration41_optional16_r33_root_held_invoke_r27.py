"""Closed R27 invocation bridge for the reviewed R19 Optional16 chain.

The child payload binds the R19 source/review and the frozen R16 plus reviewed
R17 composites before main can select the actual path. Disk activation remains
closed; the held-source path repeats aggregate validation.
"""

from __future__ import annotations

import hashlib
import ast
import importlib.machinery
import json
import math
import ntpath
import os
from pathlib import Path
import re
import sys
import threading
import time
import types


ROOT = Path(r"D:\source_code\backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"

R2_GLUE = ROOT / "scripts/iteration41_optional16_r33_root_held_glue_r15.py"
R2_GLUE_SHA256 = "f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98"
ROOT_BINDING_HELPER = ROOT / "scripts/iteration41_optional16_r33_deadline_r19_binding.py"
ROOT_BINDING_HELPER_SHA256 = "1774b2776c9c03c0e10574fda4f58093f3c2947d902d78c2d41bac9d4c47ba58"
R16_BINDING_HELPER = ROOT / "scripts/iteration41_optional16_r33_deadline_r15_root_binding_r1.py"
R16_BINDING_HELPER_SHA256 = "5b30bb4a1516fcc632362a8be9073b4dfbdaafe8476b8d73c5b300ca05433a75"
R17_BINDING_HELPER = ROOT / "scripts/iteration41_optional16_r33_deadline_r17_binding.py"
R17_BINDING_HELPER_SHA256 = "f4526bd40433fb74fe0c3d360c863d07e5613924a9bba243611026c058b442bd"
R18_BINDING_HELPER = ROOT / "scripts/iteration41_optional16_r33_deadline_r18_binding.py"
R18_BINDING_HELPER_SHA256 = "5977009ff0d6bfafb98f5e9eace3e49cd9e49a15c760237ff5cee4d0f9c2fb43"
CUV2 = Path(r"D:\temp\iteration41-root-public-custody-v2.py")
CUV2_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"

DRIVER = ROOT / "scripts/iteration41_optional16_r33_root_driver_r19.py"
DRIVER_SHA256 = None
DRIVER_TEST = (
    ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r19_source_fake.py"
)
DRIVER_TEST_SHA256 = None
DRIVER_PACKET = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r19-source-candidate-2026-10-07"
)
DRIVER_PACKET_PINS = {
    "source-bundle.zip": None,
    "source-index.json": None,
    "source-pins.json": None,
    "checkpoint.json": None,
    "README.md": None,
    "qa/qa-summary.json": None,
}
DRIVER_REVIEW = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r19-independent-review-2026-10-07"
)
DRIVER_REVIEW_PINS = {
    "review.json": None,
    "review-bundle.zip": None,
    "review-index.json": None,
    "review-checkpoint.json": None,
    "README.md": None,
}
DRIVER_ACTIVE_PATH = Path(r"D:\temp\iteration41-optional16-r33-root-driver-r27.py")

ROOT_CONTROL = Path(r"D:\temp\iteration41-optional16-r33-root-held-activation-r27")
ROOT_SCRATCH = Path(r"D:\temp\iteration41-optional16-r33-root-held-scratch-r27")
ROOT_DRIVER_CONTROL = Path(r"D:\temp\iteration41-optional16-r33-root-control-r27")
ROOT_DRIVER_SCRATCH = Path(r"D:\temp\iteration41-optional16-r33-matrix-scratch-r27")
# These identify the frozen R19 source namespace. Dynamic R27 outputs use the
# separate ROOT_DRIVER_* paths above after the exact source pins are checked.
PINNED_R5_DRIVER_CONTROL = Path(r"D:\temp\iteration41-optional16-r33-root-control-r19")
PINNED_R5_DRIVER_SCRATCH = Path(r"D:\temp\iteration41-optional16-r33-matrix-scratch-r19")
PINNED_R5_DRIVER_PROGRESS_PATH = (
    Path(r"D:\temp\iteration41-optional16-r33-root-control-r19") / "r33-r19-progress.frames"
)
ROOT_OUTPUT = EVIDENCE / "iteration41-optional16-r33-root-held-invocation-r27-2026-10-08"
ROOT_PRECHECK_OUTPUT = EVIDENCE / "iteration41-optional16-r33-root-held-precheck-r27-2026-10-08"
ROOT_SELF_PATH = ROOT / "scripts/iteration41_optional16_r33_root_held_invoke_r27.py"
ROOT_TEST_PATH = (
    ROOT / "tests/unit/scripts/test_iteration41_optional16_r33_activation_r27_source_fake.py"
)
ROOT_PACKET = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r19-source-candidate-2026-10-07"
)
ROOT_REVIEW = (
    EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r19-independent-review-2026-10-07"
)

ROOT_SELF_SHA256 = None
ROOT_TEST_SHA256 = None
ROOT_PACKET_PINS = {
    "source-bundle.zip": None,
    "source-index.json": None,
    "source-pins.json": None,
    "checkpoint.json": None,
    "README.md": None,
    "qa/qa-summary.json": None,
}
ROOT_REVIEW_PINS = {
    "review.json": None,
    "review-bundle.zip": None,
    "review-index.json": None,
    "review-checkpoint.json": None,
    "README.md": None,
}
ROOT_REVIEW_README_SHA256 = None
ROOT_ACTUAL_ENABLED = False
ROOT_REVIEW_READY = False
ROOT_REVIEWED_ACTIVATION = False

OUTER_WAIT_SECONDS = 100.0  # Maximum only; R15 glue caps at the inherited parent deadline.
PARENT_DEADLINE_CLOCK_DOMAIN = "windows-cpython-3.11.5-monotonic-v1"
PARENT_DEADLINE_MONOTONIC = None
PARENT_DEADLINE_DOMAIN = None
INERT_DRIVER_PUBLIC_PATH_COUNT = None
ACTIVE_DRIVER_PUBLIC_PATH_COUNT = None
ACTIVE_DRIVER_ALIAS_COUNT = None
R2_INERT_DRIVER_PIN_COUNT = None
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[a-z0-9_]{1,96}\Z")
_CHILD_ACTIVATION_SCHEMA = "iteration41.optional16.r33.whole-call.r27-child-activation.v1"
_DIAGNOSTIC_PHASES = frozenset(
    {
        "r2_invocation",
        "public_map_assembly",
        "reviewed_root_contract",
        "source_contract_validation",
        "source_custody_enter",
        "source_custody_entered",
        "current_image_check",
        "current_image_checked",
        "profiler_cache_verify",
        "profiler_cache_verified",
        "source_postverify_release",
        "source_released",
        "r5_driver_main",
        "r5_driver_returned",
    }
)
_SOURCE_CUSTODY_ENTERED_ROOT_CODES = frozenset(
    {
        "held_map_type",
        "path_type",
        "path_text",
        "path_not_absolute",
        "path_shape",
        "held_bytes_type",
        "held_path_bytes_conflict",
        "held_path_missing",
        "complete_held_source_mismatch",
        "root_review_gate_closed",
        "root_packet_pins_shape",
        "root_review_pins_shape",
        "aggregate_binding_helper_pin_mismatch",
        "r17_helper_pin_mismatch",
        "r16_helper_pin_mismatch",
        "r18_helper_pin_mismatch",
    }
)
_PHASE_DIAGNOSTIC_SCHEMA = "iteration41.optional16.r33.root-invoke-r12.phase-diagnostic.v1"
_PHASE_ORDINAL_MAX = 64
_PHASE_ELAPSED_MS_MAX = 120_000
_LOCK_TYPE = type(threading.Lock())
_MONOTONIC = time.monotonic
_EXCEPTION_TYPE_ENUM = {
    RuntimeError: "RuntimeError",
    OSError: "OSError",
    FileNotFoundError: "FileNotFoundError",
    PermissionError: "PermissionError",
    TimeoutError: "TimeoutError",
    ValueError: "ValueError",
    TypeError: "TypeError",
    KeyError: "KeyError",
    UnicodeError: "UnicodeError",
}
_R2_ALIAS = "_root_r32_r12_enclosing"
_R2_CU_ALIAS = "_root_r32_r2_enclosing_custody"
_R2_IMAGE_ALIAS = "_root_r32_r2_image"
_R2_ACTIVE_DRIVER_ALIAS = "_root_r32_r2_driver_held_active"
_R2_INERT_DRIVER_ALIAS = "_root_r32_r2_enclosing_inert"
_R2_PARENT_SCHEMA_V1 = "iteration41.optional16.r32.root-matrix-projection.v3"
_R5_PARENT_SCHEMA_V1 = "iteration41.optional16.r33.root-matrix-projection.v3"
_REVIEW_REQUIRED = frozenset(
    {"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json", "README.md"}
)
_R2_REVIEW_MAP_REQUIRED = frozenset(
    {"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json"}
)
_PACKET_REQUIRED = frozenset(
    {
        "source-bundle.zip",
        "source-index.json",
        "source-pins.json",
        "checkpoint.json",
        "README.md",
        "qa/qa-summary.json",
    }
)
_RETAINED: list[dict[str, object]] = []


class RootEnvelopeError(RuntimeError):
    """A fixed R12 source, review, or lifecycle contract did not match."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise RootEnvelopeError(code)


def _validated_parent_deadline(now: float | None = None) -> float | None:
    """Accept only the bounded shared monotonic deadline from the R15 parent."""
    if (
        sys.platform != "win32"
        or sys.implementation.name != "cpython"
        or sys.version_info[:3] != (3, 11, 5)
    ):
        return None
    if now is None:
        now = time.monotonic()
    deadline = PARENT_DEADLINE_MONOTONIC
    if (
        type(now) is not float
        or type(deadline) is not float
        or PARENT_DEADLINE_DOMAIN != PARENT_DEADLINE_CLOCK_DOMAIN
        or not math.isfinite(now)
        or not math.isfinite(deadline)
    ):
        return None
    remaining = deadline - now
    if not math.isfinite(remaining) or not 0.0 < remaining <= 100.0:
        return None
    return deadline


def _set_diagnostic_phase(context: dict[str, object], phase: str) -> None:
    lock = context.get("diagnostic_phase_lock")
    state = context.get("diagnostic_phase_state")
    if type(lock) is not _LOCK_TYPE or type(state) is not dict:
        return
    if type(phase) is not str or phase not in _DIAGNOSTIC_PHASES:
        try:
            with lock:
                state.clear()
                state.update(available=False)
                context["diagnostic_phase"] = "UNOBSERVED"
        except BaseException:
            pass
        return
    safe_phase = phase
    try:
        now = _MONOTONIC()
    except BaseException:
        with lock:
            state.clear()
            state.update(available=False)
            context["diagnostic_phase"] = "UNOBSERVED"
        return
    if type(now) is not float or not math.isfinite(now):
        with lock:
            state.clear()
            state.update(available=False)
            context["diagnostic_phase"] = "UNOBSERVED"
        return
    with lock:
        ordinal = state.get("transition_ordinal")
        if type(ordinal) is not int or not 0 <= ordinal < _PHASE_ORDINAL_MAX:
            state.clear()
            state.update(available=False)
            context["diagnostic_phase"] = "UNOBSERVED"
            return
        state.update(
            available=True,
            phase=safe_phase,
            transition_ordinal=ordinal + 1,
            phase_started_monotonic=now,
        )
        context["diagnostic_phase"] = safe_phase


def _initialize_phase_diagnostic(context: dict[str, object]) -> None:
    try:
        started = _MONOTONIC()
    except BaseException:
        context["diagnostic_phase_lock"] = threading.Lock()
        context["diagnostic_phase"] = "UNOBSERVED"
        context["diagnostic_phase_state"] = {"available": False}
        return
    if type(started) is not float or not math.isfinite(started):
        context["diagnostic_phase_lock"] = threading.Lock()
        context["diagnostic_phase"] = "UNOBSERVED"
        context["diagnostic_phase_state"] = {"available": False}
        return
    context["diagnostic_phase_lock"] = threading.Lock()
    context["diagnostic_phase"] = "r2_invocation"
    context["diagnostic_phase_state"] = {
        "available": True,
        "phase": "r2_invocation",
        "transition_ordinal": 0,
        "invocation_started_monotonic": started,
        "phase_started_monotonic": started,
    }


def _phase_diagnostic_snapshot(context: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "schema": _PHASE_DIAGNOSTIC_SCHEMA,
        "availability": "UNOBSERVED",
        "phase": "UNOBSERVED",
        "transition_ordinal": None,
        "invocation_elapsed_ms": None,
        "phase_elapsed_ms": None,
    }
    lock = context.get("diagnostic_phase_lock")
    state = context.get("diagnostic_phase_state")
    if type(lock) is not _LOCK_TYPE or type(state) is not dict:
        return result
    try:
        if lock.acquire(False) is not True:
            return result
    except BaseException:
        return result
    try:
        snapshot = dict(state)
    except BaseException:
        lock.release()
        return result
    else:
        lock.release()
    phase = snapshot.get("phase")
    invocation_started = snapshot.get("invocation_started_monotonic")
    phase_started = snapshot.get("phase_started_monotonic")
    if (
        snapshot.get("available") is not True
        or type(phase) is not str
        or phase not in _DIAGNOSTIC_PHASES
        or type(snapshot.get("transition_ordinal")) is not int
        or not 0 <= snapshot["transition_ordinal"] <= _PHASE_ORDINAL_MAX
        or type(invocation_started) is not float
        or type(phase_started) is not float
        or not math.isfinite(invocation_started)
        or not math.isfinite(phase_started)
        or phase_started < invocation_started
    ):
        return result
    try:
        now = _MONOTONIC()
    except BaseException:
        return result
    if type(now) is not float or not math.isfinite(now) or now < phase_started:
        return result
    invocation_elapsed = now - invocation_started
    phase_elapsed = now - phase_started
    if (
        type(invocation_elapsed) is not float
        or type(phase_elapsed) is not float
        or not math.isfinite(invocation_elapsed)
        or not math.isfinite(phase_elapsed)
        or invocation_elapsed < 0.0
        or phase_elapsed < 0.0
        or phase_elapsed > invocation_elapsed
    ):
        return result
    result.update(
        availability="OBSERVED",
        phase=snapshot["phase"],
        transition_ordinal=snapshot["transition_ordinal"],
        invocation_elapsed_ms=int(min(invocation_elapsed, _PHASE_ELAPSED_MS_MAX / 1000) * 1000),
        phase_elapsed_ms=int(min(phase_elapsed, _PHASE_ELAPSED_MS_MAX / 1000) * 1000),
    )
    return result


def _valid_phase_diagnostic(value: object) -> bool:
    if (
        type(value) is not dict
        or set(value)
        != {
            "schema",
            "availability",
            "phase",
            "transition_ordinal",
            "invocation_elapsed_ms",
            "phase_elapsed_ms",
        }
        or value.get("schema") != _PHASE_DIAGNOSTIC_SCHEMA
    ):
        return False
    if value.get("availability") == "OBSERVED":
        return (
            type(value.get("phase")) is str
            and value["phase"] in _DIAGNOSTIC_PHASES
            and type(value.get("transition_ordinal")) is int
            and 0 <= value["transition_ordinal"] <= _PHASE_ORDINAL_MAX
            and all(
                type(value.get(key)) is int and 0 <= value[key] <= _PHASE_ELAPSED_MS_MAX
                for key in ("invocation_elapsed_ms", "phase_elapsed_ms")
            )
            and value["phase_elapsed_ms"] <= value["invocation_elapsed_ms"]
        )
    return (
        value.get("availability") == "UNOBSERVED"
        and value.get("phase") == "UNOBSERVED"
        and value.get("transition_ordinal") is None
        and value.get("invocation_elapsed_ms") is None
        and value.get("phase_elapsed_ms") is None
    )


def _literal_source_codes(raw: bytes, function_names: frozenset[str]) -> frozenset[str]:
    """Extract only literal error enums from an already source-pinned module."""
    if type(raw) is not bytes or not 0 < len(raw) <= 64 * 1024 * 1024:
        return frozenset()
    try:
        tree = ast.parse(raw.decode("utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return frozenset()
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func.id if isinstance(node.func, ast.Name) else None
        if function not in function_names or len(node.args) < 2:
            continue
        value = node.args[1]
        if (
            isinstance(value, ast.Constant)
            and type(value.value) is str
            and _CODE.fullmatch(value.value)
        ):
            codes.add(value.value)
            if len(codes) > 512:
                return frozenset()
    return frozenset(codes)


def _exception_type_label(context: dict[str, object], error: BaseException) -> str:
    error_type = type(error)
    label = _EXCEPTION_TYPE_ENUM.get(error_type)
    if label is not None:
        return label
    custom_types = context.get("diagnostic_exception_types")
    if type(custom_types) is dict:
        return custom_types.get(error_type, "UNOBSERVED")
    return "UNOBSERVED"


def _register_exception_types(context: dict[str, object], module: types.ModuleType) -> None:
    custom_types = context.setdefault("diagnostic_exception_types", {})
    if type(custom_types) is not dict:
        return
    error_type = getattr(module, "RootEnvelopeError", None)
    if isinstance(error_type, type) and issubclass(error_type, RuntimeError):
        custom_types[error_type] = "RootEnvelopeError"


def _record_source_failure(
    context: dict[str, object], role: str, error: BaseException, code: object
) -> None:
    exception_type = _exception_type_label(context, error)
    allowlists = context.get("diagnostic_source_codes")
    role_codes = allowlists.get(role) if type(allowlists) is dict else None
    source_code = (
        code
        if exception_type != "UNOBSERVED"
        and type(code) is str
        and type(role_codes) is frozenset
        and code in role_codes
        else "UNOBSERVED"
    )
    phase = context.get("diagnostic_phase")
    if phase not in _DIAGNOSTIC_PHASES:
        phase = "source_custody_enter"
    context["safe_exception_diagnostic"] = {
        "phase": phase,
        "exception_type": exception_type,
        "source_code": source_code,
    }


def _diagnostic_payload(context: dict[str, object], error: BaseException) -> dict[str, str]:
    saved = context.get("safe_exception_diagnostic")
    current_type = _exception_type_label(context, error)
    if (
        type(saved) is dict
        and saved.get("phase") == context.get("diagnostic_phase")
        and saved.get("exception_type") == current_type
    ):
        return {
            "phase": saved["phase"],
            "exception_type": saved["exception_type"],
            "source_code": saved["source_code"],
        }
    phase = context.get("diagnostic_phase")
    return {
        "phase": phase if phase in _DIAGNOSTIC_PHASES else "source_custody_enter",
        "exception_type": current_type,
        "source_code": "UNOBSERVED",
    }


def _wrap_reason_function(
    module: types.ModuleType,
    attribute: str,
    role: str,
    context: dict[str, object],
    argument_name: str,
) -> None:
    original = getattr(module, attribute, None)
    if not callable(original):
        return

    def observed(*args, **kwargs):
        code = kwargs.get(argument_name)
        if code is None and len(args) > 1:
            code = args[1]
        try:
            return original(*args, **kwargs)
        except BaseException as error:
            _record_source_failure(context, role, error, code)
            raise

    setattr(module, attribute, observed)


def _diagnostic_need(context: dict[str, object], condition: bool, code: str) -> None:
    try:
        _need(condition, code)
    except BaseException as error:
        _record_source_failure(context, "r12", error, code)
        raise


def _source_codes_from_r2(raw: bytes) -> frozenset[str]:
    return _literal_source_codes(raw, frozenset({"need"}))


def _wrap_r2_need(module: types.ModuleType, context: dict[str, object]) -> None:
    original = module.need

    def observed(value, reason="root_public_contract"):
        try:
            result = original(value, reason)
        except BaseException as error:
            _record_source_failure(context, "r2", error, reason)
            raise
        if reason == "profiler_module_set":
            _set_diagnostic_phase(context, "profiler_cache_verify")
        if reason == "held_profiler_code_graph_changed" and context.get(
            "profiler_cache_verify_count"
        ) == context.get("profiler_cache_expected_count"):
            _set_diagnostic_phase(context, "profiler_cache_verified")
        return result

    module.need = observed


def _track_profiler_verifier(verifier, context: dict[str, object]):
    def observed(name, source_bytes, cache_bytes):
        _set_diagnostic_phase(context, "profiler_cache_verify")
        result = verifier(name, source_bytes, cache_bytes)
        context["profiler_cache_verify_count"] = context.get("profiler_cache_verify_count", 0) + 1
        return result

    return observed


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_key(path: str | Path) -> str:
    _need(isinstance(path, (str, Path)), "path_type")
    raw = os.fspath(path)
    _need(type(raw) is str and raw and "\x00" not in raw, "path_text")
    _need(ntpath.isabs(raw), "path_not_absolute")
    key = ntpath.normcase(ntpath.normpath(raw))
    drive, tail = ntpath.splitdrive(key)
    _need(bool(drive) and tail.startswith("\\"), "path_shape")
    return key


def _merge_path_hashes(*maps: dict[str | Path, str]) -> tuple[dict[str, str], int]:
    merged: dict[str, str] = {}
    aliases = 0
    for mapping in maps:
        _need(type(mapping) is dict, "pin_map_type")
        for path, digest in mapping.items():
            key = _path_key(path)
            _need(type(digest) is str and _HASH.fullmatch(digest) is not None, "pin_digest_shape")
            previous = merged.get(key)
            if previous is None:
                merged[key] = digest
            else:
                _need(previous == digest, "path_digest_conflict")
                aliases += 1
    return merged, aliases


def _read_fixed(path: str | Path, digest: str) -> bytes:
    _need(type(digest) is str and _HASH.fullmatch(digest) is not None, "fixed_pin_shape")
    raw = Path(path).read_bytes()
    _need(type(raw) is bytes and _sha(raw) == digest, "fixed_pin_mismatch")
    return raw


def _canonical_held(raw_held: dict[str | Path, bytes]) -> dict[str, bytes]:
    _need(type(raw_held) is dict, "held_map_type")
    held: dict[str, bytes] = {}
    for path, raw in raw_held.items():
        key = _path_key(path)
        _need(type(raw) is bytes, "held_bytes_type")
        previous = held.get(key)
        _need(previous is None or previous == raw, "held_path_bytes_conflict")
        held[key] = raw
    return held


def _held_bytes(held: dict[str, bytes], path: str | Path) -> bytes:
    key = _path_key(path)
    _need(key in held, "held_path_missing")
    return held[key]


def _load_declarations(raw: bytes, path: Path, name: str) -> types.ModuleType:
    _need(name not in sys.modules, "fixed_module_alias_already_loaded")
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module.__verified_source_sha256__ = _sha(raw)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def _review_candidate() -> dict[str, object]:
    return {
        "source_sha256": ROOT_SELF_SHA256,
        "test_sha256": ROOT_TEST_SHA256,
        "source_bundle_sha256": ROOT_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": ROOT_PACKET_PINS["source-index.json"],
        "source_pins_sha256": ROOT_PACKET_PINS["source-pins.json"],
        "checkpoint_sha256": ROOT_PACKET_PINS["checkpoint.json"],
        "r33_driver_sha256": DRIVER_SHA256,
        "r33_driver_test_sha256": DRIVER_TEST_SHA256,
        "r33_driver_source_bundle_sha256": DRIVER_PACKET_PINS["source-bundle.zip"],
        "r33_driver_review_json_sha256": DRIVER_REVIEW_PINS["review.json"],
        "r2_glue_sha256": R2_GLUE_SHA256,
        "cuv2_sha256": CUV2_SHA256,
        "driver_public_path_count": ACTIVE_DRIVER_PUBLIC_PATH_COUNT,
        "driver_software_path_count": 5,
        "driver_alias_count": ACTIVE_DRIVER_ALIAS_COUNT,
        "r2_inert_driver_pin_count": R2_INERT_DRIVER_PIN_COUNT,
    }


def _r2_inert_pin_count(module: types.ModuleType) -> int:
    """Derive the closed R19 source-map count required by the frozen R2 glue."""
    _need(
        module.ROOT_ENABLED is False
        and module.ROOT_REVIEWED_ACTIVATION is False
        and module.ROOT_DRIVER_REVIEW_READY is False
        and module.ROOT_DRIVER_SHA256 is None,
        "r2_inert_driver_defaults_changed",
    )
    pins, software, aliases = module._expected_pins()
    _need(
        type(pins) is dict and type(software) is dict and len(software) == 5 and aliases == 12,
        "r2_inert_driver_closure_shape",
    )
    return len(pins)


def _valid_pin_map(value: object, names: set[str]) -> bool:
    return (
        type(value) is dict
        and set(value) == names
        and all(
            type(digest) is str and _HASH.fullmatch(digest) is not None for digest in value.values()
        )
    )


def activation_ready() -> bool:
    """Readiness predicate used by production main after complete child binding."""
    return (
        ROOT_ACTUAL_ENABLED is True
        and ROOT_REVIEW_READY is True
        and ROOT_REVIEWED_ACTIVATION is True
        and type(ROOT_SELF_SHA256) is str
        and _HASH.fullmatch(ROOT_SELF_SHA256) is not None
        and type(ROOT_TEST_SHA256) is str
        and _HASH.fullmatch(ROOT_TEST_SHA256) is not None
        and _valid_pin_map(ROOT_PACKET_PINS, set(_PACKET_REQUIRED))
        and _valid_pin_map(ROOT_REVIEW_PINS, set(_REVIEW_REQUIRED))
        and ROOT_REVIEW_PINS.get("README.md") == ROOT_REVIEW_README_SHA256
        and type(DRIVER_SHA256) is str
        and _HASH.fullmatch(DRIVER_SHA256) is not None
        and type(DRIVER_TEST_SHA256) is str
        and _HASH.fullmatch(DRIVER_TEST_SHA256) is not None
        and _valid_pin_map(DRIVER_PACKET_PINS, set(_PACKET_REQUIRED))
        and _valid_pin_map(DRIVER_REVIEW_PINS, set(_REVIEW_REQUIRED))
        and DRIVER_REVIEW_PINS.get("README.md") is not None
        and type(INERT_DRIVER_PUBLIC_PATH_COUNT) is int
        and INERT_DRIVER_PUBLIC_PATH_COUNT >= 0
        and type(R2_INERT_DRIVER_PIN_COUNT) is int
        and R2_INERT_DRIVER_PIN_COUNT >= INERT_DRIVER_PUBLIC_PATH_COUNT
        and type(ACTIVE_DRIVER_PUBLIC_PATH_COUNT) is int
        and ACTIVE_DRIVER_PUBLIC_PATH_COUNT >= INERT_DRIVER_PUBLIC_PATH_COUNT
        and R2_INERT_DRIVER_PIN_COUNT <= ACTIVE_DRIVER_PUBLIC_PATH_COUNT
        and type(ACTIVE_DRIVER_ALIAS_COUNT) is int
        and ACTIVE_DRIVER_ALIAS_COUNT >= 0
        and _validated_parent_deadline() is not None
        and _path_key(DRIVER_ACTIVE_PATH) != _path_key(DRIVER)
    )


def bind_child_activation(
    payload: dict[str, object],
    *,
    artifact_reader=None,
) -> dict[str, object]:
    """Validate the full parent payload and bind only declared activation slots.

    ``artifact_reader`` is a narrow sourcefake test seam. Production calls this
    with no override, so every artifact is read from its fixed public path.
    The R16 composite validator receives only frozen R16 inputs; R17 is checked
    by its own successor validator.
    """
    global ROOT_SELF_SHA256, ROOT_TEST_SHA256, ROOT_PACKET_PINS, ROOT_REVIEW_PINS
    global ROOT_REVIEW_README_SHA256, ROOT_ACTUAL_ENABLED, ROOT_REVIEW_READY
    global ROOT_REVIEWED_ACTIVATION, DRIVER_SHA256, DRIVER_TEST_SHA256
    global DRIVER_PACKET_PINS, DRIVER_REVIEW_PINS, PARENT_DEADLINE_MONOTONIC
    global PARENT_DEADLINE_DOMAIN, INERT_DRIVER_PUBLIC_PATH_COUNT
    global ACTIVE_DRIVER_PUBLIC_PATH_COUNT, ACTIVE_DRIVER_ALIAS_COUNT
    global R2_INERT_DRIVER_PIN_COUNT
    global ROOT_CONTROL, ROOT_SCRATCH, ROOT_DRIVER_CONTROL, ROOT_DRIVER_SCRATCH
    global ROOT_OUTPUT, ROOT_PRECHECK_OUTPUT

    required = {
        "schema",
        "invoke",
        "driver",
        "counts",
        "fresh_paths",
        "parent_deadline_monotonic",
        "parent_deadline_domain",
    }
    _need(type(payload) is dict and set(payload) == required, "child_activation_payload_shape")
    _need(payload.get("schema") == _CHILD_ACTIVATION_SCHEMA, "child_activation_schema_invalid")
    invoke = payload.get("invoke")
    driver = payload.get("driver")
    _need(
        type(invoke) is dict
        and set(invoke)
        == {
            "path",
            "sha256",
            "test_path",
            "test_sha256",
            "packet_dir",
            "packet_pins",
            "review_dir",
            "review_pins",
            "review_readme_sha256",
        },
        "invoke_binding_shape_invalid",
    )
    _need(
        type(driver) is dict
        and set(driver)
        == {
            "path",
            "sha256",
            "test_path",
            "test_sha256",
            "packet_dir",
            "packet_pins",
            "review_dir",
            "review_pins",
            "review_readme_sha256",
            "active_path",
        },
        "driver_binding_shape_invalid",
    )
    _need(
        _path_key(Path(invoke["path"])) == _path_key(ROOT_SELF_PATH)
        and _path_key(Path(invoke["test_path"])) == _path_key(ROOT_TEST_PATH)
        and _path_key(Path(invoke["packet_dir"])) == _path_key(ROOT_PACKET)
        and _path_key(Path(invoke["review_dir"])) == _path_key(ROOT_REVIEW),
        "invoke_binding_path_invalid",
    )
    _need(
        _path_key(Path(driver["path"])) == _path_key(DRIVER)
        and _path_key(Path(driver["test_path"])) == _path_key(DRIVER_TEST)
        and _path_key(Path(driver["packet_dir"])) == _path_key(DRIVER_PACKET)
        and _path_key(Path(driver["review_dir"])) == _path_key(DRIVER_REVIEW)
        and _path_key(Path(driver["active_path"])) == _path_key(DRIVER_ACTIVE_PATH),
        "driver_binding_path_invalid",
    )
    counts = payload.get("counts")
    _need(
        type(counts) is dict
        and set(counts)
        == {"inert_public_paths", "active_public_paths", "software_paths", "path_aliases"},
        "child_counts_shape_invalid",
    )
    _need(
        all(type(value) is int and value >= 0 for value in counts.values())
        and counts["software_paths"] == 5
        and counts["active_public_paths"] >= counts["inert_public_paths"],
        "child_counts_invalid",
    )
    fresh_paths = payload.get("fresh_paths")
    expected_fresh = {
        "ROOT_CONTROL": str(ROOT_CONTROL),
        "ROOT_SCRATCH": str(ROOT_SCRATCH),
        "ROOT_DRIVER_CONTROL": str(ROOT_DRIVER_CONTROL),
        "ROOT_DRIVER_SCRATCH": str(ROOT_DRIVER_SCRATCH),
        "ROOT_OUTPUT": str(ROOT_OUTPUT),
        "ROOT_PRECHECK_OUTPUT": str(ROOT_PRECHECK_OUTPUT),
    }
    _need(type(fresh_paths) is dict and fresh_paths == expected_fresh, "child_fresh_paths_invalid")
    deadline = payload.get("parent_deadline_monotonic")
    domain = payload.get("parent_deadline_domain")
    now = time.monotonic()
    _need(
        type(deadline) is float
        and type(now) is float
        and math.isfinite(deadline)
        and math.isfinite(now)
        and 0.0 < deadline - now <= OUTER_WAIT_SECONDS
        and domain == PARENT_DEADLINE_CLOCK_DOMAIN,
        "child_deadline_invalid",
    )

    read = artifact_reader or (lambda path: Path(path).read_bytes())
    _need(callable(read), "artifact_reader_invalid")
    invoke_raw = read(ROOT_SELF_PATH)
    invoke_test_raw = read(ROOT_TEST_PATH)
    _need(
        type(invoke_raw) is bytes and _sha(invoke_raw) == invoke["sha256"],
        "invoke_source_hash_invalid",
    )
    _need(
        type(invoke_test_raw) is bytes and _sha(invoke_test_raw) == invoke["test_sha256"],
        "invoke_test_hash_invalid",
    )
    _need(
        _path_key(ROOT_SELF_PATH) == _path_key(Path(invoke["path"])), "invoke_source_path_invalid"
    )
    _need(
        _valid_pin_map(invoke["packet_pins"], set(_PACKET_REQUIRED)), "invoke_packet_pins_invalid"
    )
    _need(
        _valid_pin_map(invoke["review_pins"], set(_REVIEW_REQUIRED)), "invoke_review_pins_invalid"
    )
    _need(
        invoke["review_readme_sha256"] == invoke["review_pins"]["README.md"],
        "invoke_review_readme_pin_invalid",
    )
    driver_raw = read(DRIVER)
    driver_test_raw = read(DRIVER_TEST)
    _need(
        type(driver_raw) is bytes and _sha(driver_raw) == driver["sha256"],
        "driver_source_hash_invalid",
    )
    _need(
        type(driver_test_raw) is bytes and _sha(driver_test_raw) == driver["test_sha256"],
        "driver_test_hash_invalid",
    )
    _need(
        _valid_pin_map(driver["packet_pins"], set(_PACKET_REQUIRED)), "driver_packet_pins_invalid"
    )
    _need(
        _valid_pin_map(driver["review_pins"], set(_REVIEW_REQUIRED)), "driver_review_pins_invalid"
    )
    _need(
        driver["review_readme_sha256"] == driver["review_pins"]["README.md"],
        "driver_review_readme_pin_invalid",
    )

    helper_raw = read(ROOT_BINDING_HELPER)
    _need(
        type(helper_raw) is bytes
        and type(ROOT_BINDING_HELPER_SHA256) is str
        and _sha(helper_raw) == ROOT_BINDING_HELPER_SHA256,
        "r19_helper_hash_invalid",
    )
    helper = _load_declarations(
        helper_raw, ROOT_BINDING_HELPER, "_iteration41_optional16_r33_r19_child_binding"
    )
    r17_helper_raw = read(R17_BINDING_HELPER)
    _need(
        type(r17_helper_raw) is bytes and _sha(r17_helper_raw) == R17_BINDING_HELPER_SHA256,
        "r17_helper_hash_invalid",
    )
    r17_helper = _load_declarations(
        r17_helper_raw, R17_BINDING_HELPER, "_iteration41_optional16_r33_r17_frozen_binding"
    )
    r16_helper_raw = read(R16_BINDING_HELPER)
    _need(
        type(r16_helper_raw) is bytes and _sha(r16_helper_raw) == R16_BINDING_HELPER_SHA256,
        "r16_helper_hash_invalid",
    )
    r16_helper = r17_helper._load_r16_helper(r16_helper_raw)
    r18_helper_raw = read(R18_BINDING_HELPER)
    _need(
        type(r18_helper_raw) is bytes and _sha(r18_helper_raw) == R18_BINDING_HELPER_SHA256,
        "r18_helper_hash_invalid",
    )
    r18_helper = _load_declarations(
        r18_helper_raw, R18_BINDING_HELPER, "_iteration41_optional16_r33_r18_frozen_binding"
    )
    r16_source_names = set(r16_helper.SUCCESSOR_ROLE_PATHS.values()) | {
        r16_helper.SUCCESSOR_TEST_PATH
    }
    r17_source_names = set(r17_helper.R17_ROLE_PATHS.values()) | {r17_helper.R17_TEST_PATH}
    r18_source_names = set(r18_helper.R18_ROLE_PATHS.values()) | {r18_helper.R18_TEST_PATH}
    r19_source_names = set(helper.R19_ROLE_PATHS.values()) | {helper.R19_TEST_PATH}
    source_names = r16_source_names | r17_source_names | r18_source_names | r19_source_names
    source_files = {name: read(ROOT / name) for name in source_names}
    _need(
        driver_raw == source_files[helper.R19_ROLE_PATHS["driver"]], "driver_source_not_frozen_r19"
    )
    _need(driver_test_raw == source_files[helper.R19_TEST_PATH], "driver_test_not_frozen_r19")
    packet_files = {name: read(ROOT_PACKET / name) for name in _PACKET_REQUIRED}
    review_files = {name: read(ROOT_REVIEW / name) for name in _REVIEW_REQUIRED}
    r16_packet_files = {name: read(helper.R16_PACKET / name) for name in helper.R16_PACKET_PINS}
    r16_review_files = {name: read(helper.R16_REVIEW / name) for name in helper.R16_REVIEW_PINS}
    r17_packet_files = {name: read(helper.R17_PACKET / name) for name in helper.R17_PACKET_PINS}
    r17_review_files = {name: read(helper.R17_REVIEW / name) for name in helper.R17_REVIEW_PINS}
    r18_packet_files = {name: read(helper.R18_PACKET / name) for name in helper.R18_PACKET_PINS}
    r18_review_files = {name: read(helper.R18_REVIEW / name) for name in helper.R18_REVIEW_PINS}
    helper.validate_successor_artifacts(
        source_files,
        packet_files,
        review_files,
        packet_pins=invoke["packet_pins"],
        review_pins=invoke["review_pins"],
        r16_packet_files=r16_packet_files,
        r16_review_files=r16_review_files,
        r17_packet_files=r17_packet_files,
        r17_review_files=r17_review_files,
        r18_packet_files=r18_packet_files,
        r18_review_files=r18_review_files,
    )

    driver_module = _load_declarations(
        driver_raw,
        DRIVER,
        "_iteration41_optional16_r33_r19_child_driver_activation",
    )
    r2_inert_driver_pin_count = _r2_inert_pin_count(driver_module)
    driver_validation = _validate_driver_r2(
        driver_module,
        driver_binding=driver,
        expected_counts=counts,
        artifact_reader=read,
    )

    ROOT_SELF_SHA256 = invoke["sha256"]
    ROOT_TEST_SHA256 = invoke["test_sha256"]
    ROOT_PACKET_PINS = dict(invoke["packet_pins"])
    ROOT_REVIEW_PINS = dict(invoke["review_pins"])
    ROOT_REVIEW_README_SHA256 = invoke["review_readme_sha256"]
    DRIVER_SHA256 = driver["sha256"]
    DRIVER_TEST_SHA256 = driver["test_sha256"]
    DRIVER_PACKET_PINS = dict(driver["packet_pins"])
    DRIVER_REVIEW_PINS = dict(driver["review_pins"])
    PARENT_DEADLINE_MONOTONIC = deadline
    PARENT_DEADLINE_DOMAIN = domain
    INERT_DRIVER_PUBLIC_PATH_COUNT = counts["inert_public_paths"]
    ACTIVE_DRIVER_PUBLIC_PATH_COUNT = counts["active_public_paths"]
    ACTIVE_DRIVER_ALIAS_COUNT = counts["path_aliases"]
    R2_INERT_DRIVER_PIN_COUNT = r2_inert_driver_pin_count
    ROOT_ACTUAL_ENABLED = True
    ROOT_REVIEW_READY = True
    ROOT_REVIEWED_ACTIVATION = True
    ROOT_CONTROL = Path(fresh_paths["ROOT_CONTROL"])
    ROOT_SCRATCH = Path(fresh_paths["ROOT_SCRATCH"])
    ROOT_DRIVER_CONTROL = Path(fresh_paths["ROOT_DRIVER_CONTROL"])
    ROOT_DRIVER_SCRATCH = Path(fresh_paths["ROOT_DRIVER_SCRATCH"])
    ROOT_OUTPUT = Path(fresh_paths["ROOT_OUTPUT"])
    ROOT_PRECHECK_OUTPUT = Path(fresh_paths["ROOT_PRECHECK_OUTPUT"])
    _need(activation_ready(), "invoke_activation_readiness_failed")
    return {
        "schema": _CHILD_ACTIVATION_SCHEMA,
        "status": "COMPLETE_CHILD_BINDING_VALIDATED",
        "r16_composite_validated": True,
        "r17_composite_validated": True,
        "r18_composite_validated": True,
        "r19_driver_activation_validated": True,
        "driver_expected_public_pin_count": driver_validation["public_path_count"],
        "r2_inert_driver_pin_count": R2_INERT_DRIVER_PIN_COUNT,
        "driver_software_pin_count": driver_validation["software_path_count"],
        "driver_path_alias_count": driver_validation["same_digest_alias_count"],
        "driver_activation_ready": driver_validation["activation_ready"],
        "invoke_activation_ready": True,
        "driver_sha256": DRIVER_SHA256,
        "driver_test_sha256": DRIVER_TEST_SHA256,
        "driver_packet_pin_count": len(DRIVER_PACKET_PINS),
        "driver_review_pin_count": len(DRIVER_REVIEW_PINS),
        "activation_enabled": True,
    }


def _validate_root_review(held: dict[str, bytes]) -> dict[str, object]:
    """Validate R16, R17, and R19 on their separate aggregate contracts."""
    _need(ROOT_REVIEW_READY is True and ROOT_REVIEWED_ACTIVATION is True, "root_review_gate_closed")
    _need(
        set(ROOT_PACKET_PINS)
        == {
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa/qa-summary.json",
        },
        "root_packet_pins_shape",
    )
    _need(
        set(ROOT_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        },
        "root_review_pins_shape",
    )
    helper_raw = _held_bytes(held, ROOT_BINDING_HELPER)
    _need(_sha(helper_raw) == ROOT_BINDING_HELPER_SHA256, "aggregate_binding_helper_pin_mismatch")
    helper = _load_declarations(
        helper_raw,
        ROOT_BINDING_HELPER,
        "_iteration41_optional16_r33_r19_aggregate_invoke_binding",
    )
    r17_helper_raw = _held_bytes(held, R17_BINDING_HELPER)
    _need(_sha(r17_helper_raw) == R17_BINDING_HELPER_SHA256, "r17_helper_pin_mismatch")
    r17_helper = _load_declarations(
        r17_helper_raw, R17_BINDING_HELPER, "_iteration41_optional16_r33_r17_frozen_binding"
    )
    r16_helper_raw = _held_bytes(held, R16_BINDING_HELPER)
    _need(_sha(r16_helper_raw) == R16_BINDING_HELPER_SHA256, "r16_helper_pin_mismatch")
    r16_helper = r17_helper._load_r16_helper(r16_helper_raw)
    r18_helper_raw = _held_bytes(held, R18_BINDING_HELPER)
    _need(_sha(r18_helper_raw) == R18_BINDING_HELPER_SHA256, "r18_helper_pin_mismatch")
    r18_helper = _load_declarations(
        r18_helper_raw, R18_BINDING_HELPER, "_iteration41_optional16_r33_r18_frozen_binding"
    )
    source_names = (
        set(r16_helper.SUCCESSOR_ROLE_PATHS.values())
        | {r16_helper.SUCCESSOR_TEST_PATH}
        | set(r17_helper.R17_ROLE_PATHS.values())
        | {r17_helper.R17_TEST_PATH}
        | set(r18_helper.R18_ROLE_PATHS.values())
        | {r18_helper.R18_TEST_PATH}
        | set(helper.R19_ROLE_PATHS.values())
        | {helper.R19_TEST_PATH}
    )
    source_files = {name: _held_bytes(held, ROOT / name) for name in source_names}
    packet_files = {name: _held_bytes(held, ROOT_PACKET / name) for name in ROOT_PACKET_PINS}
    review_files = {name: _held_bytes(held, ROOT_REVIEW / name) for name in ROOT_REVIEW_PINS}
    r16_packet_files = {
        name: _held_bytes(held, helper.R16_PACKET / name) for name in helper.R16_PACKET_PINS
    }
    r16_review_files = {
        name: _held_bytes(held, helper.R16_REVIEW / name) for name in helper.R16_REVIEW_PINS
    }
    r17_packet_files = {
        name: _held_bytes(held, helper.R17_PACKET / name) for name in helper.R17_PACKET_PINS
    }
    r17_review_files = {
        name: _held_bytes(held, helper.R17_REVIEW / name) for name in helper.R17_REVIEW_PINS
    }
    r18_packet_files = {
        name: _held_bytes(held, helper.R18_PACKET / name) for name in helper.R18_PACKET_PINS
    }
    r18_review_files = {
        name: _held_bytes(held, helper.R18_REVIEW / name) for name in helper.R18_REVIEW_PINS
    }
    return helper.validate_successor_artifacts(
        source_files,
        packet_files,
        review_files,
        packet_pins=ROOT_PACKET_PINS,
        review_pins=ROOT_REVIEW_PINS,
        r16_packet_files=r16_packet_files,
        r16_review_files=r16_review_files,
        r17_packet_files=r17_packet_files,
        r17_review_files=r17_review_files,
        r18_packet_files=r18_packet_files,
        r18_review_files=r18_review_files,
    )


def _validate_driver_r2(
    module: types.ModuleType,
    *,
    driver_binding: dict[str, object],
    expected_counts: dict[str, int],
    artifact_reader=None,
) -> dict[str, object]:
    """Bind and validate the actual R19 driver activation contract.

    The only test seam is the byte reader. All activation and aggregate
    validators below are the unchanged production implementations.
    """
    _need(module.__name__ != "__main__", "driver_must_be_non_main")
    _need(
        module.ROOT_ENABLED is False and module.ROOT_REVIEWED_ACTIVATION is False,
        "driver_disk_activation_changed",
    )
    _need(
        module.ROOT_DRIVER_REVIEW_READY is False and module.ROOT_DRIVER_SHA256 is None,
        "driver_disk_review_changed",
    )
    _need(
        all(value is None for value in module.ROOT_DRIVER_REVIEW_PINS.values()),
        "driver_disk_review_pins_changed",
    )
    _need(
        all(value is None for value in module.ROOT_DRIVER_PACKET_PINS.values()),
        "driver_disk_packet_pins_changed",
    )
    _need(type(driver_binding) is dict, "driver_binding_invalid")
    _need(type(expected_counts) is dict, "driver_expected_counts_invalid")
    read = artifact_reader or (lambda path: Path(path).read_bytes())
    _need(callable(read), "driver_artifact_reader_invalid")
    active_path = Path(driver_binding["active_path"])
    source_raw = read(DRIVER)
    active_raw = read(active_path)
    _need(
        type(source_raw) is bytes
        and _sha(source_raw) == driver_binding["sha256"]
        and type(active_raw) is bytes
        and active_raw == source_raw,
        "driver_active_copy_mismatch",
    )
    test_raw = read(DRIVER_TEST)
    _need(
        type(test_raw) is bytes and _sha(test_raw) == driver_binding["test_sha256"],
        "driver_test_hash_invalid",
    )
    module.__file__ = str(active_path)
    module.ROOT_DRIVER_PATH = active_path
    module.DRIVER_PACKET = Path(driver_binding["packet_dir"])
    module.DRIVER_REVIEW = Path(driver_binding["review_dir"])
    module.ROOT_ENABLED = True
    module.ROOT_REVIEWED_ACTIVATION = True
    module.ROOT_DRIVER_REVIEW_READY = True
    module.ROOT_DRIVER_SHA256 = driver_binding["sha256"]
    module.DRIVER_TEST_SHA256 = driver_binding["test_sha256"]
    module.ROOT_DRIVER_PACKET_PINS = dict(driver_binding["packet_pins"])
    module.ROOT_DRIVER_REVIEW_PINS = dict(driver_binding["review_pins"])
    _need(module._activation_ready() is True, "driver_activation_readiness_failed")

    # This is the production map derivation. It reads only the pinned public
    # metadata and source indexes; no external source bytes are opened here.
    pins, software, aliases = module._expected_pins()
    public_raw = read(module.ROOT_PUBLIC_PINS)
    _need(
        type(public_raw) is bytes and _sha(public_raw) == module.ROOT_PUBLIC_PINS_SHA256,
        "driver_inert_public_pin_invalid",
    )
    try:
        public_doc = json.loads(public_raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        raise RootEnvelopeError("driver_inert_public_metadata_invalid") from None
    base_paths = public_doc.get("public_paths_sha256") if type(public_doc) is dict else None
    _need(type(base_paths) is dict, "driver_inert_public_map_invalid")
    observed_counts = {
        "inert_public_paths": len(base_paths),
        "active_public_paths": len(pins),
        "software_paths": len(software),
        "path_aliases": aliases,
    }
    _need(
        observed_counts == expected_counts
        and len(software) == 5
        and observed_counts["active_public_paths"] >= observed_counts["inert_public_paths"],
        "driver_r5_active_map_shape",
    )
    held: dict[str, bytes] = {}
    helper_raw = read(ROOT_BINDING_HELPER)
    r17_helper_raw = read(R17_BINDING_HELPER)
    r16_helper_raw = read(R16_BINDING_HELPER)
    _need(
        type(helper_raw) is bytes
        and _sha(helper_raw) == ROOT_BINDING_HELPER_SHA256
        and type(r17_helper_raw) is bytes
        and _sha(r17_helper_raw) == R17_BINDING_HELPER_SHA256
        and type(r16_helper_raw) is bytes
        and _sha(r16_helper_raw) == R16_BINDING_HELPER_SHA256,
        "driver_aggregate_helper_pin_invalid",
    )
    helper = _load_declarations(
        helper_raw, ROOT_BINDING_HELPER, "_iteration41_optional16_r33_r19_driver_validate"
    )
    r18_helper_raw = read(R18_BINDING_HELPER)
    r17_helper = _load_declarations(
        r17_helper_raw, R17_BINDING_HELPER, "_iteration41_optional16_r33_r17_driver_validate"
    )
    _need(
        type(r18_helper_raw) is bytes and _sha(r18_helper_raw) == R18_BINDING_HELPER_SHA256,
        "r18_aggregate_helper_pin_invalid",
    )
    r18_helper = _load_declarations(
        r18_helper_raw, R18_BINDING_HELPER, "_iteration41_optional16_r33_r18_driver_validate"
    )
    r16_helper = r17_helper._load_r16_helper(r16_helper_raw)
    source_names = (
        set(r16_helper.SUCCESSOR_ROLE_PATHS.values())
        | {r16_helper.SUCCESSOR_TEST_PATH}
        | set(r17_helper.R17_ROLE_PATHS.values())
        | {r17_helper.R17_TEST_PATH}
        | set(r18_helper.R18_ROLE_PATHS.values())
        | {r18_helper.R18_TEST_PATH}
        | set(helper.R19_ROLE_PATHS.values())
        | {helper.R19_TEST_PATH}
    )
    for name in source_names:
        path = ROOT / name
        raw = read(path)
        _need(type(raw) is bytes, "driver_aggregate_source_missing")
        held[_path_key(path)] = raw
    for folder, mapping in (
        (helper.R16_PACKET, helper.R16_PACKET_PINS),
        (helper.R16_REVIEW, helper.R16_REVIEW_PINS),
        (helper.R17_PACKET, helper.R17_PACKET_PINS),
        (helper.R17_REVIEW, helper.R17_REVIEW_PINS),
        (helper.R18_PACKET, helper.R18_PACKET_PINS),
        (helper.R18_REVIEW, helper.R18_REVIEW_PINS),
        (module.DRIVER_PACKET, module.ROOT_DRIVER_PACKET_PINS),
        (module.DRIVER_REVIEW, module.ROOT_DRIVER_REVIEW_PINS),
    ):
        for name, digest in mapping.items():
            path = folder / name
            raw = read(path)
            _need(type(raw) is bytes and _sha(raw) == digest, "driver_aggregate_input_pin_invalid")
            held[_path_key(path)] = raw
    held[_path_key(ROOT_BINDING_HELPER)] = helper_raw
    result = module._validate_driver_review(held)
    _need(
        result.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and result.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and result.get("strict_cases_passed") == 0
        and result.get("case_pass") is False
        and result.get("registry_admission") is False,
        "driver_r5_review_invalid",
    )
    _need(module._activation_ready() is True, "driver_activation_readiness_lost")
    return {
        "public_path_count": len(pins),
        "software_path_count": len(software),
        "same_digest_alias_count": aliases,
        "verdict": result["verdict"],
        "activation_ready": True,
    }


class _DeferredScope:
    """Calls postverify before the underlying custody scope can release."""

    def __init__(self, scope: object, context: dict[str, object], r2: types.ModuleType):
        self._scope = scope
        self._context = context
        self._r2 = r2
        self.enter_started = False
        self.entered = False
        self.released = False
        self.release_attempted = False
        self.native_release_started = False
        self.ready_for_result_release = False
        self.raw_held: dict[str | Path, bytes] | None = None
        self.held: dict[str, bytes] | None = None

    def __enter__(self):
        _set_diagnostic_phase(self._context, "source_custody_enter")
        self.enter_started = True
        private, cli, raw = self._scope.__enter__()
        self.entered = True
        _set_diagnostic_phase(self._context, "source_custody_entered")
        try:
            self.raw_held = raw
            self.held = _canonical_held(raw)
            expected = self._context["expected_pins"]
            for path, digest in expected.items():
                _diagnostic_need(
                    self._context,
                    _sha(_held_bytes(self.held, path)) == digest,
                    "complete_held_source_mismatch",
                )
            mode = self._context["mode"]
            if mode == "actual":
                self._context["root_review"] = _validate_root_review(self.held)
            private.create_private_directory = _wrap_private_create_directory(
                private.create_private_directory, self._context
            )
            self._context.update(private=private, cli=cli, raw_held=raw, held=self.held, scope=self)
            return private, cli, raw
        except BaseException as error:
            _record_source_custody_entered_failure(self._context, error)
            raise


    def __exit__(self, exc_type, exc, tb):
        self.release_attempted = True
        if exc_type is not None:
            return False
        _set_diagnostic_phase(self._context, "source_postverify_release")
        _diagnostic_need(
            self._context, self.entered and self.held is not None, "scope_exit_before_enter"
        )
        for path, digest in self._context["expected_pins"].items():
            _diagnostic_need(
                self._context,
                _sha(_held_bytes(self.held, path)) == digest,
                "postverify_source_mismatch",
            )
        self._context["source_postverified"] = True
        if self._context["mode"] == "actual":
            _diagnostic_need(
                self._context,
                self._context.get("outer_control_verified") is True,
                "outer_control_not_verified",
            )
            driver = self._context.get("active_driver")
            _diagnostic_need(
                self._context,
                type(driver) is types.ModuleType and not driver._KEEPALIVES,
                "driver_cleanup_not_clean",
            )
            # The fixed R2 helper constructs and validates its final bounded
            # projection after __exit__ returns.  Hold the external lease until
            # adapted_save has validated that projection.
            self.ready_for_result_release = True
            return False
        self.native_release_started = True
        result = self._scope.__exit__(None, None, None)
        self.released = True
        self._context["source_released"] = True
        _set_diagnostic_phase(self._context, "source_released")
        return result

    def release_after_result(self) -> None:
        _set_diagnostic_phase(self._context, "source_postverify_release")
        _diagnostic_need(
            self._context, self._context["mode"] == "actual", "result_release_wrong_mode"
        )
        _diagnostic_need(
            self._context,
            self.ready_for_result_release and not self.released,
            "result_release_not_ready",
        )
        self.native_release_started = True
        self._scope.__exit__(None, None, None)
        self.released = True
        self._context["source_released"] = True
        _set_diagnostic_phase(self._context, "source_released")


def _record_source_custody_entered_failure(
    context: dict[str, object], error: BaseException
) -> None:
    """Project only a closed static R21 envelope code for this exact phase."""
    if (
        type(error) is RootEnvelopeError
        and context.get("diagnostic_phase") == "source_custody_entered"
        and len(error.args) == 1
        and type(error.args[0]) is str
        and error.args[0] in _SOURCE_CUSTODY_ENTERED_ROOT_CODES
    ):
        context["safe_exception_diagnostic"] = {
            "phase": "source_custody_entered",
            "exception_type": "RootEnvelopeError",
            "source_code": error.args[0],
        }


class _ControlProxy:
    def __init__(self, control: object, context: dict[str, object]):
        self._control = control
        self._context = context

    def verify(self):
        result = self._control.verify()
        if self._context.get("control_written") is True:
            self._context["outer_control_verified"] = True
        return result

    def write_bytes(self, *args, **kwargs):
        result = self._control.write_bytes(*args, **kwargs)
        self._context["control_written"] = True
        return result

    def __getattr__(self, name):
        return getattr(self._control, name)


def _wrap_private_create_directory(original, context: dict[str, object]):
    def create(path):
        _need(context.get("mode") == "actual", "private_control_during_precheck")
        _need(_path_key(path) == _path_key(ROOT_CONTROL), "unexpected_outer_control_path")
        result = original(path)
        control = _ControlProxy(result, context)
        context["outer_control"] = control
        return control

    return create


def _active_driver_loaded(module: types.ModuleType, context: dict[str, object]) -> None:
    _set_diagnostic_phase(context, "reviewed_root_contract")
    context.setdefault("diagnostic_source_codes", {})["driver"] = _literal_source_codes(
        context["active_driver_raw"], frozenset({"_need"})
    )
    _register_exception_types(context, module)
    _wrap_reason_function(module, "_need", "driver", context, "code")
    module.DRIVER_REVIEW = DRIVER_REVIEW
    module.ROOT_DRIVER_PATH = _driver_active_path()
    _diagnostic_need(
        context,
        _path_key(module.__file__) == _path_key(module.ROOT_DRIVER_PATH),
        "active_driver_path_mismatch",
    )
    context["active_driver"] = module
    _set_diagnostic_phase(context, "source_contract_validation")
    _bind_r12_driver_namespaces(module)
    # Preserve the three frozen lineage/policy gates with diagnostic wrappers.
    # The aggregate source/review validator itself remains the selected source
    # function and is never replaced or wrapped in memory.
    for attribute in (
        "_validate_candidate_review",
        "_validate_r33_candidate_review",
        "_validate_r28_lineage",
    ):
        original_validator = getattr(module, attribute, None)
        if callable(original_validator):

            def observed_validator(*args, _validator=original_validator, **kwargs):
                _set_diagnostic_phase(context, "reviewed_root_contract")
                try:
                    return _validator(*args, **kwargs)
                except BaseException as error:
                    saved = context.get("safe_exception_diagnostic")
                    if not (
                        type(saved) is dict
                        and saved.get("phase") == "reviewed_root_contract"
                        and saved.get("exception_type") == _exception_type_label(context, error)
                    ):
                        _record_source_failure(context, "driver", error, None)
                    raise

            setattr(module, attribute, observed_validator)
    _need(
        callable(getattr(module, "_validate_driver_review", None)),
        "aggregate_review_validator_missing",
    )
    # R15 glue retains its historic R32 hook; bind that call site to the
    # aggregate-aware R16 validator without altering the validator itself.
    module._validate_r32_candidate_review = module._validate_driver_review
    fake_main = context.get("fake_active_main")
    if fake_main is not None:
        _need(context.get("source_fake_mode") is True, "fake_active_main_not_source_fake")
        driver_main = fake_main
    else:
        driver_main = getattr(module, "main", None)
    _need(callable(driver_main), "active_driver_main_missing")

    def observed_driver_main(*args, **kwargs):
        _set_diagnostic_phase(context, "r5_driver_main")
        result = driver_main(*args, **kwargs)
        _set_diagnostic_phase(context, "r5_driver_returned")
        return result

    module.main = observed_driver_main


def _bind_r12_driver_namespaces(module: types.ModuleType) -> None:
    _need(
        _path_key(Path(module.CONTROL)) == _path_key(PINNED_R5_DRIVER_CONTROL)
        and _path_key(Path(module.SCRATCH)) == _path_key(PINNED_R5_DRIVER_SCRATCH)
        and _path_key(Path(module.PROGRESS_PATH)) == _path_key(PINNED_R5_DRIVER_PROGRESS_PATH)
        and module.PROGRESS_NAME == "r33-r19-progress.frames",
        "driver_r5_namespace_source_mismatch",
    )
    _need(
        _path_key(ROOT_DRIVER_CONTROL) != _path_key(ROOT_DRIVER_SCRATCH),
        "r12_driver_namespace_collision",
    )
    _need(
        _path_key(ROOT_DRIVER_CONTROL)
        not in {
            _path_key(ROOT_CONTROL),
            _path_key(ROOT_SCRATCH),
            _path_key(ROOT_OUTPUT),
            _path_key(ROOT_PRECHECK_OUTPUT),
        }
        and _path_key(ROOT_DRIVER_SCRATCH)
        not in {
            _path_key(ROOT_CONTROL),
            _path_key(ROOT_SCRATCH),
            _path_key(ROOT_OUTPUT),
            _path_key(ROOT_PRECHECK_OUTPUT),
        },
        "r12_driver_namespace_collision",
    )
    module.CONTROL = ROOT_DRIVER_CONTROL
    module.SCRATCH = ROOT_DRIVER_SCRATCH
    module.PROGRESS_PATH = ROOT_DRIVER_CONTROL / module.PROGRESS_NAME
    _need(
        _path_key(module.PROGRESS_PATH.parent) == _path_key(ROOT_DRIVER_CONTROL)
        and _path_key(module.PROGRESS_PATH) != _path_key(PINNED_R5_DRIVER_PROGRESS_PATH),
        "r12_progress_namespace_mismatch",
    )


def _current_image_check(
    image: types.ModuleType,
    private: types.ModuleType,
    original=None,
    context: dict[str, object] | None = None,
) -> None:
    if context is not None:
        _set_diagnostic_phase(context, "current_image_check")
    if context is not None and context.get("source_fake_mode") is True:
        context["fake_image_check"](image, private)
    else:
        (original or image.current_image_check)(private)
    if context is not None:
        _set_diagnostic_phase(context, "current_image_checked")


def _extra_pins(mode: str) -> dict[Path, str]:
    _need(
        ROOT_SELF_SHA256 is not None and _HASH.fullmatch(ROOT_SELF_SHA256), "outer_self_hash_unset"
    )
    _need(
        type(ROOT_TEST_SHA256) is str and _HASH.fullmatch(ROOT_TEST_SHA256), "outer_test_hash_unset"
    )
    _need(type(ROOT_PACKET_PINS) is dict, "outer_packet_shape")
    _need(
        set(ROOT_PACKET_PINS)
        == {
            "source-bundle.zip",
            "source-index.json",
            "source-pins.json",
            "checkpoint.json",
            "README.md",
            "qa/qa-summary.json",
        },
        "outer_packet_names",
    )
    _need(
        all(
            type(digest) is str and _HASH.fullmatch(digest) for digest in ROOT_PACKET_PINS.values()
        ),
        "outer_packet_unset",
    )
    result = {
        Path(__file__): ROOT_SELF_SHA256,
        ROOT_TEST_PATH: ROOT_TEST_SHA256,
        ROOT_BINDING_HELPER: ROOT_BINDING_HELPER_SHA256,
    }
    result.update({ROOT_PACKET / name: digest for name, digest in ROOT_PACKET_PINS.items()})
    if mode == "actual":
        _need(
            ROOT_ACTUAL_ENABLED is True
            and ROOT_REVIEW_READY is True
            and ROOT_REVIEWED_ACTIVATION is True,
            "outer_activation_closed",
        )
        _need(type(ROOT_REVIEW_PINS) is dict, "outer_review_pin_shape")
        _need(
            set(ROOT_REVIEW_PINS)
            == {
                "review.json",
                "review-bundle.zip",
                "review-index.json",
                "review-checkpoint.json",
                "README.md",
            },
            "outer_review_pin_names",
        )
        _need(
            all(
                type(digest) is str and _HASH.fullmatch(digest)
                for digest in ROOT_REVIEW_PINS.values()
            ),
            "outer_review_pins_unset",
        )
        _need(
            ROOT_REVIEW_PINS["README.md"] == ROOT_REVIEW_README_SHA256,
            "outer_review_readme_not_bound",
        )
        result.update({ROOT_REVIEW / name: digest for name, digest in ROOT_REVIEW_PINS.items()})
    else:
        _need(
            ROOT_ACTUAL_ENABLED is False and ROOT_REVIEWED_ACTIVATION is False,
            "precheck_must_not_activate",
        )
    return result


_R2_ERROR_CLASS_ENUM = frozenset(set(_EXCEPTION_TYPE_ENUM.values()) | {"RootEnvelopeError"})
_R2_LOCK_TYPE = type(threading.Lock())
_R2_APPLICATION_DIAGNOSTIC_SCHEMA = "iteration41.optional16.r33.root-application-diagnostic.r12.v1"


def _r2_sink_facts(r2: types.ModuleType, sink: object) -> tuple[bool | None, bool | None]:
    if type(sink) is not getattr(r2, "BoundedSink", None):
        return None, None
    lock = getattr(sink, "lock", None)
    if type(lock) is not _R2_LOCK_TYPE:
        return None, None
    try:
        acquired = lock.acquire(False)
    except BaseException:
        return None, None
    if acquired is not True:
        return None, None
    try:
        overflow = getattr(sink, "overflow", None)
        overflow_fact = overflow if type(overflow) is bool else None
        value = sink.getvalue()
        nonempty_fact = value != "" if type(value) is str else None
        return overflow_fact, nonempty_fact
    except BaseException:
        return None, None
    finally:
        lock.release()


def _r2_application_diagnostic(r2: types.ModuleType) -> dict[str, object]:
    """Take a bounded, nonblocking snapshot of R2's retained application state."""
    result: dict[str, object] = {
        "schema": _R2_APPLICATION_DIAGNOSTIC_SCHEMA,
        "application_done_event_set": None,
        "application_thread_alive": None,
        "state_error_class": "UNOBSERVED",
        "stdout_overflow": None,
        "stderr_overflow": None,
        "stderr_nonempty": None,
        "application_elapsed_seconds": "UNOBSERVED",
    }
    keepalive = getattr(r2, "_KEEPALIVE", None)
    if type(keepalive) is not list or len(keepalive) != 1:
        return result
    retained = keepalive[0]
    if type(retained) is not dict:
        return result

    done = retained.get("done")
    if type(done) is threading.Event:
        try:
            observed_done = done.is_set()
            if type(observed_done) is bool:
                result["application_done_event_set"] = observed_done
        except BaseException:
            pass
    thread = retained.get("thread")
    if type(thread) is threading.Thread:
        try:
            observed_alive = thread.is_alive()
            if type(observed_alive) is bool:
                result["application_thread_alive"] = observed_alive
        except BaseException:
            pass

    if result["application_done_event_set"] is True:
        state = retained.get("state")
        if type(state) is dict and "error" in state:
            error_class = state["error"]
            if error_class is None:
                result["state_error_class"] = "NONE"
            elif type(error_class) is str and error_class in _R2_ERROR_CLASS_ENUM:
                result["state_error_class"] = error_class

    stdout_overflow, _stdout_nonempty = _r2_sink_facts(r2, retained.get("sink"))
    stderr_overflow, stderr_nonempty = _r2_sink_facts(r2, retained.get("stderr"))
    result["stdout_overflow"] = stdout_overflow
    result["stderr_overflow"] = stderr_overflow
    result["stderr_nonempty"] = stderr_nonempty
    return result


def _valid_r2_application_diagnostic(value: object) -> bool:
    return (
        type(value) is dict
        and set(value)
        == {
            "schema",
            "application_done_event_set",
            "application_thread_alive",
            "state_error_class",
            "stdout_overflow",
            "stderr_overflow",
            "stderr_nonempty",
            "application_elapsed_seconds",
        }
        and value.get("schema") == _R2_APPLICATION_DIAGNOSTIC_SCHEMA
        and all(
            value.get(key) is None or type(value.get(key)) is bool
            for key in (
                "application_done_event_set",
                "application_thread_alive",
                "stdout_overflow",
                "stderr_overflow",
                "stderr_nonempty",
            )
        )
        and value.get("state_error_class") in (_R2_ERROR_CLASS_ENUM | {"NONE", "UNOBSERVED"})
        and value.get("application_elapsed_seconds") == "UNOBSERVED"
    )


def _install_adaptation(r2: types.ModuleType, context: dict[str, object]) -> None:
    original_load = r2.load
    original_save = r2.save_new
    r2_codes = context.setdefault("diagnostic_source_codes", {})
    r2_codes["r2"] = _source_codes_from_r2(context["r2_raw"])
    r2_codes["r12"] = _literal_source_codes(context["r12_raw"], frozenset({"_need"}))
    _register_exception_types(context, r2)
    _wrap_r2_need(r2, context)
    _bind_r5_projection_schema(r2, context)

    def adapted_load(raw: bytes, path: Path, name: str):
        module = original_load(raw, path, name)
        key = _path_key(path)
        if key in {_path_key(DRIVER), _path_key(r2.ACTIVE_SOURCE)}:
            _need(_sha(raw) == DRIVER_SHA256, "driver_held_pin_changed")
            if name == _R2_ACTIVE_DRIVER_ALIAS:
                context["active_driver_raw"] = raw
                _active_driver_loaded(module, context)
            elif name == _R2_INERT_DRIVER_ALIAS:
                _register_exception_types(context, module)
                context.setdefault("diagnostic_source_codes", {})["driver"] = _literal_source_codes(
                    raw, frozenset({"_need"})
                )
                _wrap_reason_function(module, "_need", "driver", context, "code")
                original_expected_pins = module._expected_pins

                def observed_expected_pins(*args, **kwargs):
                    _set_diagnostic_phase(context, "public_map_assembly")
                    try:
                        return original_expected_pins(*args, **kwargs)
                    except BaseException as error:
                        saved = context.get("safe_exception_diagnostic")
                        if not (
                            type(saved) is dict
                            and saved.get("phase") == "public_map_assembly"
                            and saved.get("exception_type") == _exception_type_label(context, error)
                        ):
                            _record_source_failure(context, "driver", error, None)
                        raise

                module._expected_pins = observed_expected_pins
        elif key == _path_key(r2.CU):
            _need(raw == context["cu_raw"] and _sha(raw) == CUV2_SHA256, "cuv2_held_bytes_changed")
            source_fake_module_factory = context.get("source_fake_cu_module_factory")
            if context.get("source_fake_mode") is True and callable(source_fake_module_factory):
                module = source_fake_module_factory(name, path, raw, module)
                _need(
                    type(module) is types.ModuleType
                    and module.__name__ == name
                    and getattr(module, "__verified_source_sha256__", None) == CUV2_SHA256,
                    "source_fake_cuv2_module_invalid",
                )
                sys.modules[name] = module
            r2_codes["cuv2"] = _literal_source_codes(raw, frozenset({"check"}))
            _wrap_reason_function(module, "check", "cuv2", context, "code")
            original_held_public_sources = module.held_public_sources
            context["captured_cuv2_source_factory"] = original_held_public_sources

            def adapted_hold(pins: dict[str | Path, str], software: dict[str | Path, str]):
                _set_diagnostic_phase(context, "public_map_assembly")
                extra = _extra_pins(context["mode"])
                merged, aliases = _merge_path_hashes(pins, extra)
                normalized_software, software_aliases = _merge_path_hashes(software)
                context["expected_pins"] = merged
                context["expected_software"] = normalized_software
                context["full_alias_count"] = aliases + software_aliases
                fake_factory = context.get("source_fake_scope_factory")
                scope_factory = (
                    fake_factory
                    if context.get("source_fake_mode") is True and callable(fake_factory)
                    else original_held_public_sources
                )
                try:
                    raw_scope = scope_factory(merged, normalized_software)
                except BaseException as error:
                    _record_source_failure(context, "cuv2", error, None)
                    raise
                scope = _DeferredScope(raw_scope, context, r2)
                context["scope"] = scope
                return scope

            module.held_public_sources = adapted_hold
        elif key == _path_key(r2.IMAGE):
            r2_codes["image"] = _literal_source_codes(raw, frozenset({"need"}))
            _wrap_reason_function(module, "need", "image", context, "reason")
            _register_exception_types(context, module)
            context["image_module"] = module
            original_check = module.current_image_check
            module.current_image_check = lambda private: _current_image_check(
                module, private, original_check, context
            )
        elif key == _path_key(r2.PROFILER_PROOF):
            r2_codes["profiler"] = _literal_source_codes(raw, frozenset({"need"}))
            _wrap_reason_function(module, "need", "profiler", context, "reason")
            _register_exception_types(context, module)
            context["proof_module"] = module
            context["profiler_cache_verify_count"] = 0
            context["profiler_cache_expected_count"] = len(module.SOURCES)
            verifier = _track_profiler_verifier(module.verify_module_cache, context)
            if context.get("source_fake_mode") is True:
                # Keep the real proof module pinned; fake only the cache bytes.
                verifier = _track_profiler_verifier(context["fake_profiler_verifier"], context)
            module.verify_module_cache = verifier
        return module

    def adapted_save(path: Path, value: dict[str, object]) -> None:
        if type(value) is dict and value.get("status") == "ROOT_APPLICATION_UNCERTAIN":
            context["r2_application_diagnostic"] = _r2_application_diagnostic(r2)
            context["phase_diagnostic"] = _phase_diagnostic_snapshot(context)
        scope = context.get("scope")
        if (
            context.get("mode") == "actual"
            and type(value) is dict
            and value.get("status") == "ROOT_ACTUAL_OBSERVED_PENDING_REVIEW"
        ):
            _need(isinstance(scope, _DeferredScope), "clean_report_without_scope")
            _need(_clean_r2_report_before_release(value), "clean_report_contract_invalid")
            scope.release_after_result()
        original_save(path, value)
        context.setdefault("safe_reports", []).append(dict(value))

    r2.load = adapted_load
    r2.save_new = adapted_save


def _bind_r5_projection_schema(r2: types.ModuleType, context: dict[str, object]) -> None:
    """Bridge only the frozen parent parser's versioned schema literal.

    R2 is hash-checked and held as its original bytes. Its parser is otherwise
    retained byte-for-byte; this exact one-constant change teaches that parser
    to accept the R5 producer's R33 frame. The R33 frame itself is not relabeled
    or rewritten, and all of R2's field, status, lifecycle, and exit checks run
    unchanged.
    """
    function = getattr(r2, "main", None)
    code = getattr(function, "__code__", None)
    _need(
        type(function) is types.FunctionType
        and function.__globals__ is r2.__dict__
        and type(code) is types.CodeType
        and code.co_name == "main"
        and code.co_freevars == (),
        "r2_parent_parser_code_shape",
    )
    constants = code.co_consts
    matches = [
        index
        for index, value in enumerate(constants)
        if type(value) is str and value == _R2_PARENT_SCHEMA_V1
    ]
    _need(len(matches) == 1, "r2_parent_schema_literal_shape")
    index = matches[0]
    changed = list(constants)
    changed[index] = _R5_PARENT_SCHEMA_V1
    adapted = code.replace(co_consts=tuple(changed))
    _need(
        adapted.co_name == code.co_name
        and adapted.co_filename == code.co_filename
        and adapted.co_names == code.co_names
        and sum(
            1
            for position, value in enumerate(adapted.co_consts)
            if type(value) is str and value == _R5_PARENT_SCHEMA_V1
        )
        == 1
        and all(
            left == right
            for position, (left, right) in enumerate(zip(code.co_consts, adapted.co_consts))
            if position != index
        ),
        "r2_parent_schema_bridge_invalid",
    )
    function.__code__ = adapted
    context["r2_parent_schema_bridge"] = {
        "source_sha256": R2_GLUE_SHA256,
        "original_schema": _R2_PARENT_SCHEMA_V1,
        "accepted_schema": _R5_PARENT_SCHEMA_V1,
        "changed_constant_count": 1,
    }


def _rebind_r2(r2: types.ModuleType, mode: str) -> None:
    r2.SOURCE = DRIVER
    r2.SOURCE_SHA = DRIVER_SHA256
    r2.ACTIVE_SOURCE = _driver_active_path()
    r2.TEST = DRIVER_TEST
    r2.TEST_SHA = DRIVER_TEST_SHA256
    r2.PACKET = DRIVER_PACKET
    r2.PACKET_PINS = {name: DRIVER_PACKET_PINS[name] for name in _PACKET_REQUIRED}
    r2.REVIEW = DRIVER_REVIEW
    r2.ROOT_REVIEW_PINS = {name: DRIVER_REVIEW_PINS[name] for name in _R2_REVIEW_MAP_REQUIRED}
    r2.ROOT_REVIEW_README_SHA = DRIVER_REVIEW_PINS["README.md"]
    r2.ROOT_ACTUAL_ENABLED = True
    r2.ROOT_REVIEW_READY = True
    r2._ROOT_SELF_SHA256 = R2_GLUE_SHA256
    r2.CONTROL = ROOT_CONTROL
    r2.OUT = ROOT_PRECHECK_OUTPUT if mode == "precheck" else ROOT_OUTPUT
    r2.APPLICATION_WAIT_SECONDS = OUTER_WAIT_SECONDS
    r2.PARENT_DEADLINE_MONOTONIC = PARENT_DEADLINE_MONOTONIC
    r2.PARENT_DEADLINE_DOMAIN = PARENT_DEADLINE_DOMAIN
    r2.INERT_PIN_COUNT = R2_INERT_DRIVER_PIN_COUNT
    r2.ACTIVE_PIN_COUNT = ACTIVE_DRIVER_PUBLIC_PATH_COUNT
    r2.ACTIVE_ALIAS_COUNT = ACTIVE_DRIVER_ALIAS_COUNT


def _check_r12_fixed_inputs(mode: str) -> None:
    self_path = Path(__file__)
    _need(_path_key(self_path) == _path_key(ROOT_SELF_PATH), "outer_source_path_mismatch")
    _read_fixed(self_path, ROOT_SELF_SHA256)
    _read_fixed(
        ROOT_TEST_PATH,
        ROOT_TEST_SHA256,
    )
    for name, digest in ROOT_PACKET_PINS.items():
        _read_fixed(ROOT_PACKET / name, digest)
    _need(_path_key(R2_GLUE) != _path_key(DRIVER), "r2_driver_path_collision")
    _need(_path_key(ROOT_CONTROL) != _path_key(ROOT_SCRATCH), "root_namespace_collision")
    _need(
        _path_key(ROOT_CONTROL) not in {_path_key(ROOT_OUTPUT), _path_key(ROOT_PRECHECK_OUTPUT)},
        "root_namespace_collision",
    )
    _need(_path_key(ROOT_OUTPUT) != _path_key(ROOT_PRECHECK_OUTPUT), "root_output_collision")
    driver_control, driver_scratch, driver_active_path = _driver_namespace_paths()
    _need(_path_key(driver_active_path) != _path_key(DRIVER), "driver_active_path_alias")
    _read_fixed(driver_active_path, DRIVER_SHA256)
    namespace_keys = {
        _path_key(ROOT_CONTROL),
        _path_key(ROOT_SCRATCH),
        _path_key(ROOT_OUTPUT),
        _path_key(ROOT_PRECHECK_OUTPUT),
        _path_key(driver_control),
        _path_key(driver_scratch),
        _path_key(ROOT_SELF_PATH),
        _path_key(ROOT_PACKET),
        _path_key(ROOT_REVIEW),
    }
    _need(len(namespace_keys) == 9, "r12_namespace_collision")
    if mode == "actual":
        _need(
            not ROOT_CONTROL.exists()
            and not ROOT_SCRATCH.exists()
            and not ROOT_OUTPUT.exists()
            and not ROOT_PRECHECK_OUTPUT.exists(),
            "outer_actual_namespace_already_exists",
        )
        _need(
            not driver_control.exists() and not driver_scratch.exists(),
            "inner_driver_namespace_already_exists",
        )
        _validate_outer_review_slots()
    else:
        _need(not ROOT_PRECHECK_OUTPUT.exists(), "outer_precheck_namespace_already_exists")


def _validate_outer_review_slots() -> None:
    _need(
        ROOT_ACTUAL_ENABLED is True
        and ROOT_REVIEW_READY is True
        and ROOT_REVIEWED_ACTIVATION is True,
        "outer_activation_fields_closed",
    )
    _need(
        type(ROOT_REVIEW_PINS) is dict
        and set(ROOT_REVIEW_PINS)
        == {
            "review.json",
            "review-bundle.zip",
            "review-index.json",
            "review-checkpoint.json",
            "README.md",
        },
        "outer_review_slots_invalid",
    )
    _need(
        all(type(value) is str and _HASH.fullmatch(value) for value in ROOT_REVIEW_PINS.values()),
        "outer_review_slots_unset",
    )
    _need(
        ROOT_REVIEW_PINS["README.md"] == ROOT_REVIEW_README_SHA256,
        "outer_review_readme_slot_invalid",
    )


def _driver_namespace_paths() -> tuple[Path, Path, Path]:
    raw = _read_fixed(DRIVER, DRIVER_SHA256)
    name = "_iteration41_r27_r12_namespace_probe"
    module = types.ModuleType(name)
    module.__file__ = str(DRIVER)
    module.__package__ = ""
    module.__cached__ = None
    module.__loader__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, origin=str(DRIVER))
    exec(compile(raw, str(DRIVER), "exec", dont_inherit=True), module.__dict__)
    _need(module.__name__ != "__main__", "driver_namespace_probe_main")
    _need(
        _path_key(Path(module.CONTROL)) == _path_key(PINNED_R5_DRIVER_CONTROL),
        "driver_r5_control_pin_mismatch",
    )
    _need(
        _path_key(Path(module.SCRATCH)) == _path_key(PINNED_R5_DRIVER_SCRATCH),
        "driver_r5_scratch_pin_mismatch",
    )
    _need(_path_key(DRIVER_ACTIVE_PATH) != _path_key(DRIVER), "driver_active_path_alias")
    return ROOT_DRIVER_CONTROL, ROOT_DRIVER_SCRATCH, DRIVER_ACTIVE_PATH


def _driver_active_path() -> Path:
    return _driver_namespace_paths()[2]


def _r2_main(mode: str, context: dict[str, object], test_fake_active_main=None) -> int:
    if type(context.get("diagnostic_phase_lock")) is not _LOCK_TYPE:
        _initialize_phase_diagnostic(context)
    _set_diagnostic_phase(context, "r2_invocation")
    if mode == "actual":
        _need(_validated_parent_deadline() is not None, "parent_deadline_invalid")
    _check_r12_fixed_inputs(mode)
    r2_raw = _read_fixed(R2_GLUE, R2_GLUE_SHA256)
    cu_raw = _read_fixed(CUV2, CUV2_SHA256)
    r12_raw = _read_fixed(ROOT_SELF_PATH, ROOT_SELF_SHA256)
    _need(type(r2_raw) is bytes and type(cu_raw) is bytes, "r2_support_bytes_invalid")
    r2 = _load_declarations(r2_raw, R2_GLUE, _R2_ALIAS)
    _need(_path_key(r2.CU) == _path_key(CUV2) and r2.CU_SHA == CUV2_SHA256, "cuv2_binding_mismatch")
    context.update(mode=mode, r2=r2, r2_raw=r2_raw, cu_raw=cu_raw, r12_raw=r12_raw)
    _register_exception_types(context, sys.modules[__name__])
    _rebind_r2(r2, mode)
    _install_adaptation(r2, context)
    if test_fake_active_main is not None:
        context["fake_active_main"] = test_fake_active_main
        context["source_fake_mode"] = True
        _need(context.get("fake_system") is not None, "fake_system_missing")
        _need(callable(context.get("fake_image_check")), "fake_image_leaf_missing")
        _need(callable(context.get("fake_profiler_verifier")), "fake_profiler_leaf_missing")
        r2.sys = context["fake_system"]
    old_argv = r2.sys.argv
    old_wait = r2.APPLICATION_WAIT_SECONDS
    context["outer_stdout"] = r2.sys.stdout
    if context.get("source_fake_mode") is True:
        fake_wait = context.get("source_fake_wait_seconds")
        if fake_wait is not None:
            _need(
                type(fake_wait) is float and 0.0 < fake_wait <= OUTER_WAIT_SECONDS,
                "fake_wait_invalid",
            )
            r2.APPLICATION_WAIT_SECONDS = fake_wait
    r2.sys.argv = [str(R2_GLUE)] + (["--activation-precheck"] if mode == "precheck" else [])
    _set_diagnostic_phase(context, "r2_invocation")
    try:
        try:
            code = r2.main()
        except BaseException as error:
            context["adapter_exception"] = True
            context["safe_exception_diagnostic"] = _diagnostic_payload(context, error)
            return _uncertain_summary(context, "root_adapter_exception")
    finally:
        # The active module receives argv=[] from the fixed outer helper.
        r2.sys.argv = old_argv
        r2.APPLICATION_WAIT_SECONDS = old_wait
    context["root_exit_code"] = code
    context["r2_retained"] = r2._KEEPALIVE
    context["r2_module"] = r2
    scope = context.get("scope")
    if not isinstance(scope, _DeferredScope):
        return _uncertain_summary(context, "source_scope_unavailable")
    if scope.released and context.get("source_released") is True:
        if mode == "precheck":
            context["clean"] = True
            return 0
        safe_reports = context.get("safe_reports", [])
        report = safe_reports[-1] if type(safe_reports) is list and safe_reports else None
        if type(report) is dict and _clean_r2_report(report, scope):
            context["clean"] = True
            context["safe_report"] = report
            return code
    return _uncertain_summary(context, "root_invocation_or_postverify_uncertain")


def _clean_r2_report(report: dict[str, object], scope: _DeferredScope) -> bool:
    return scope.released and _clean_r2_report_before_release(report)


def _valid_progress_diagnostic(value: object) -> bool:
    if type(value) is not dict:
        return False
    required = {
        "schema",
        "availability",
        "reason_code",
        "capture_state",
        "phase_status",
        "phase_event_count",
        "last_phase",
        "active_phase",
        "matrix_status",
        "matrix_frame_count",
        "completed_case_count",
        "last_case_id",
        "active_stage",
        "last_elapsed_ms",
        "strict_cases_passed",
        "case_pass",
        "acceptance",
        "authority",
    }
    phase_names = {
        "candidate_module_load",
        "entry_preflight",
        "source_map",
        "root_template",
        "owner_source",
        "r9_source",
        "topology_selection",
        "site_presence",
        "distribution_inventory",
        "exact_closure",
        "diagnostic_policy",
        "network_guard",
        "installed_record_gate",
        "sdk_import",
        "sdk_guard",
        "payload_closure",
        "source_map_after_import",
        "gate_proof",
        "source_map_before_matrix",
        "matrix_source",
        "wire_source",
        "matrix_import_scope_enter",
        "pre_matrix_guard",
        "matrix_dispatch",
        "matrix_cleanup",
        "sdk_cleanup_guard",
        "manifest_close",
        "result_ready",
    }
    valid = (
        set(value) == required
        and value.get("schema") == "iteration41.optional16.r33.progress-diagnostic.r5.v1"
        and value.get("availability") in {"AVAILABLE", "UNAVAILABLE"}
        and (
            value.get("reason_code") is None
            or value.get("reason_code")
            in {
                "sidecar_header_invalid",
                "sidecar_limit_exceeded",
                "sidecar_readback_invalid",
                "sidecar_writer_failed",
                "sidecar_not_started",
                "sidecar_completion_missing",
                "phase_frame_invalid",
                "matrix_frame_invalid",
                "matrix_outside_matrix_run",
            }
        )
        and value.get("capture_state") in {"COMPLETE", "PREFIX", "UNAVAILABLE"}
        and value.get("phase_status")
        in {
            "NOT_STARTED",
            "IN_PROGRESS",
            "FAILED_DIAGNOSTIC",
            "PREFIX",
            "COMPLETE_DIAGNOSTIC",
            "UNAVAILABLE",
        }
        and (
            value.get("phase_event_count") is None
            or (
                type(value.get("phase_event_count")) is int
                and 0 <= value["phase_event_count"] <= 56
            )
        )
        and (value.get("last_phase") is None or value.get("last_phase") in phase_names)
        and (value.get("active_phase") is None or value.get("active_phase") in phase_names)
        and value.get("matrix_status")
        in {
            "NOT_STARTED",
            "IN_PROGRESS",
            "FAILED_DIAGNOSTIC",
            "COMPLETE_DIAGNOSTIC",
            "INCOMPLETE",
            "UNAVAILABLE",
        }
        and (
            value.get("matrix_frame_count") is None
            or (
                type(value.get("matrix_frame_count")) is int
                and 0 <= value["matrix_frame_count"] <= 640
            )
        )
        and (
            value.get("completed_case_count") is None
            or (
                type(value.get("completed_case_count")) is int
                and 0 <= value["completed_case_count"] <= 16
            )
        )
        and (
            value.get("last_case_id") is None
            or value.get("last_case_id") == "MATRIX"
            or value.get("last_case_id")
            in {
                "D-E0-R0-M0",
                "D-E0-R0-M1",
                "D-E0-R1-M0",
                "D-E0-R1-M1",
                "D-E1-R0-M0",
                "D-E1-R0-M1",
                "D-E1-R1-M0",
                "D-E1-R1-M1",
                "D-E2-R0-M0",
                "D-E2-R0-M1",
                "D-E2-R1-M0",
                "D-E2-R1-M1",
                "D-E3-R0-M0",
                "D-E3-R0-M1",
                "D-E3-R1-M0",
                "D-E3-R1-M1",
            }
        )
        and (
            value.get("active_stage") is None
            or value.get("active_stage")
            in {
                "matrix",
                "case",
                "zmq_context_create",
                "gateway_server_start",
                "zmq_context_term",
                "execution_facade_close",
                "execution_store_close",
                "risk_gate_close",
                "matrix_temp_cleanup",
            }
        )
        and (
            value.get("last_elapsed_ms") is None
            or (
                type(value.get("last_elapsed_ms")) is int and 0 <= value["last_elapsed_ms"] <= 60000
            )
        )
        and type(value.get("strict_cases_passed")) is int
        and value.get("strict_cases_passed") == 0
        and value.get("case_pass") is False
        and value.get("acceptance") == "NOT_ESTABLISHED"
        and value.get("authority") == "DIAGNOSTIC_ONLY"
    )
    if not valid:
        return False
    if value["availability"] == "UNAVAILABLE":
        return (
            value["reason_code"] is not None
            and value["capture_state"] == "UNAVAILABLE"
            and value["phase_status"] == "UNAVAILABLE"
            and value["phase_event_count"] is None
            and value["last_phase"] is None
            and value["active_phase"] is None
            and value["matrix_status"] == "UNAVAILABLE"
            and value["matrix_frame_count"] is None
            and value["completed_case_count"] is None
            and value["last_case_id"] is None
            and value["active_stage"] is None
            and value["last_elapsed_ms"] is None
        )
    return value["reason_code"] is None and value["capture_state"] in {"COMPLETE", "PREFIX"}


def _clean_r2_report_before_release(report: dict[str, object]) -> bool:
    observation = report.get("root_observation")
    progress_ok = (
        "progress_diagnostic" not in observation if type(observation) is dict else True
    ) or _valid_progress_diagnostic(observation.get("progress_diagnostic"))
    return (
        progress_ok
        and report.get("complete_custody_postverified") is True
        and report.get("complete_custody_retained_until_root_process_exit") is False
        and report.get("late_frame_parsed") is not True
        and report.get("status") == "ROOT_ACTUAL_OBSERVED_PENDING_REVIEW"
        and type(report.get("strict_cases_passed")) is int
        and report.get("strict_cases_passed") == 0
        and report.get("case_pass") is False
        and report.get("g1_accepted") is False
        and type(report.get("optional16_real_accepted")) is int
        and report.get("optional16_real_accepted") == 0
        and report.get("whole_command_hard_deadline") is False
        and report.get("profiler_source_and_cache_held") is True
        and report.get("profiler_cache_code_graph_matches_pinned_source") is True
        and report.get("held_path_keys_normalized") is True
        and report.get("normalization_no_ambient_resolution") is True
        and type(observation) is dict
        and type(observation.get("strict_cases_passed")) is int
        and observation.get("strict_cases_passed") == 0
        and observation.get("case_pass") is False
        and observation.get("registry_admission") is False
        and observation.get("provider_session_created") is False
        and observation.get("network_access_allowed") is False
        and observation.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and observation.get("status") in {"BLOCKED", "LOCAL_DIAGNOSTIC_ONLY"}
        and observation.get("cleanup") in {"CLEAN", "NOT_STARTED"}
    )


def _uncertain_summary(context: dict[str, object], reason: str) -> int:
    context["uncertain"] = True
    context["public_raw_saved"] = False
    context["late_frame_parsed"] = False
    if context not in _RETAINED:
        _RETAINED.append(context)
    scope = context.get("scope")
    if not isinstance(scope, _DeferredScope):
        custody_state = "NOT_ESTABLISHED"
    elif scope.released:
        custody_state = "RELEASED"
    elif scope.native_release_started:
        custody_state = "UNOBSERVED"
    elif scope.entered:
        custody_state = "HELD"
    elif scope.enter_started:
        custody_state = "UNOBSERVED"
    else:
        custody_state = "NOT_ESTABLISHED"
    summary = {
        "schema": "iteration41.optional16.r33.root-invoke-r12.observation.v1",
        "status": "ROOT_UNCERTAIN_RETAINED_NO_PARSE",
        "reason_code": reason,
        "source_scope_released": custody_state == "RELEASED",
        "complete_custody_postverified": context.get("source_postverified") is True,
        "source_custody_state": custody_state,
        "source_scope_references_retained_until_root_process_exit": True,
        "complete_custody_retained_until_root_process_exit": custody_state == "HELD",
        "late_frame_parsed": False,
        "public_raw_saved": False,
        "strict_cases_passed": 0,
        "case_pass": False,
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
    }
    application_diagnostic = context.get("r2_application_diagnostic")
    if _valid_r2_application_diagnostic(application_diagnostic):
        summary["r2_application_diagnostic"] = dict(application_diagnostic)
        if (
            application_diagnostic.get("application_done_event_set") is False
            and application_diagnostic.get("application_thread_alive") is True
        ):
            phase_diagnostic = context.get("phase_diagnostic")
            if not _valid_phase_diagnostic(phase_diagnostic):
                phase_diagnostic = _phase_diagnostic_snapshot(context)
            if _valid_phase_diagnostic(phase_diagnostic):
                summary["phase_diagnostic"] = dict(phase_diagnostic)
    diagnostic = context.get("safe_exception_diagnostic")
    if (
        type(diagnostic) is dict
        and set(diagnostic) == {"phase", "exception_type", "source_code"}
        and diagnostic.get("phase") in _DIAGNOSTIC_PHASES
        and diagnostic.get("exception_type")
        in set(_EXCEPTION_TYPE_ENUM.values()) | {"RootEnvelopeError", "UNOBSERVED"}
        and (
            diagnostic.get("source_code") == "UNOBSERVED"
            or (
                type(diagnostic.get("source_code")) is str
                and _CODE.fullmatch(diagnostic["source_code"]) is not None
            )
        )
    ):
        summary["exception_diagnostic"] = dict(diagnostic)
    print(json.dumps(summary, sort_keys=True), file=context.get("outer_stdout", sys.stdout))
    return 2


def _runtime_policy_ok() -> bool:
    return (
        sys.flags.isolated == 1
        and sys.flags.no_site == 1
        and sys.dont_write_bytecode is True
        and sys.flags.optimize == 0
        and sys.implementation.name == "cpython"
        and sys.version_info[:3] == (3, 11, 5)
    )


def _blocked_summary(reason: str) -> int:
    print(
        json.dumps(
            {
                "schema": "iteration41.optional16.r33.root-invoke-r12.observation.v1",
                "status": "BLOCKED",
                "reason_code": reason,
                "root_actual_enabled": False,
                "strict_cases_passed": 0,
                "case_pass": False,
                "acceptance": "NOT_ACCEPTED_OPTIONAL16",
            },
            sort_keys=True,
        )
    )
    return 2


def _precheck() -> int:
    context: dict[str, object] = {"mode": "precheck"}
    try:
        code = _r2_main("precheck", context)
    except BaseException:
        return _blocked_summary("physical_precheck_failed")
    if context.get("clean") is True:
        summary = {
            "schema": "iteration41.optional16.r33.root-invoke-r12.observation.v1",
            "status": "PHYSICAL_PRECHECK_CLEAN",
            "source_scope_released": True,
            "current_image_checked": True,
            "child_started": False,
            "private_controls_created": False,
            "strict_cases_passed": 0,
            "case_pass": False,
            "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        }
        print(json.dumps(summary, sort_keys=True))
        return 0
    return code


def _actual() -> int:
    context: dict[str, object] = {"mode": "actual"}
    try:
        code = _r2_main("actual", context)
    except BaseException:
        if not isinstance(context.get("scope"), _DeferredScope):
            return _blocked_summary("fixed_outer_preflight_failed")
        return _uncertain_summary(context, "root_outer_exception")
    if context.get("clean") is not True:
        return code
    report = context.get("safe_report")
    _need(type(report) is dict, "safe_report_missing")
    output = {
        "schema": "iteration41.optional16.r33.root-invoke-r12.observation.v1",
        "status": "CLEAN_DRIVER_RESULT",
        "root_exit_code": code,
        "driver_status": report.get("status"),
        "driver_reason": report.get("reason"),
        "driver_cleanup": report.get("cleanup"),
        "driver_public_path_count": ACTIVE_DRIVER_PUBLIC_PATH_COUNT,
        "driver_software_path_count": 5,
        "driver_alias_count": ACTIVE_DRIVER_ALIAS_COUNT,
        "complete_custody_postverified": True,
        "native_cleanup_completed_before_outer_release": True,
        "late_frame_parsed": False,
        "public_raw_saved": False,
        "strict_cases_passed": 0,
        "case_pass": False,
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
    }
    observation = report.get("root_observation")
    progress = observation.get("progress_diagnostic") if type(observation) is dict else None
    if _valid_progress_diagnostic(progress):
        output["progress_diagnostic"] = dict(progress)
    print(json.dumps(output, sort_keys=True))
    return code


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not _runtime_policy_ok():
        return _blocked_summary("pinned_interpreter_required")
    if args in ([], ["--physical-precheck"]):
        if ROOT_SELF_SHA256 is None or any(value is None for value in ROOT_PACKET_PINS.values()):
            return _blocked_summary("outer_source_pins_unset")
        if ROOT_ACTUAL_ENABLED is not False or ROOT_REVIEWED_ACTIVATION is not False:
            return _blocked_summary("precheck_activation_state_invalid")
        return _precheck()
    if args == ["--execute-r33-root-r5"]:
        if not activation_ready():
            return _blocked_summary("root_activation_not_filled_in_memory")
        return _actual()
    return _blocked_summary("arguments_rejected")


if __name__ == "__main__":
    raise SystemExit(main())
