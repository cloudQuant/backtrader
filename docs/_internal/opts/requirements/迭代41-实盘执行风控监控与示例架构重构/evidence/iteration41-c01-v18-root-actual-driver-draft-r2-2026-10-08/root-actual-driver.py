"""Root-owned V18 activation driver draft. Never run before final review/readback."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.machinery
import io
import json
import ntpath
from pathlib import Path
import re
import sys
import types
from typing import Any


ROOT = Path("D:/source_code/backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
PACKET_ID = "iteration41-c01-v18-root-actual-driver-draft-r2-2026-10-08"
PACKET_DIR = Path(__file__).absolute().parent
PINS_PATH = PACKET_DIR / "pins.json"
V18_PACKET_ID = "iteration41-c01-v18-root-entry-activation-r2-20261008"
V18_PACKET_DIR = EVIDENCE / V18_PACKET_ID
V18_PINS_COPY = "reference/v18-activation/pins.json"
V18_SCHEMA_COPY = "reference/v18-activation/public-result-schema.json"
V18_README_COPY = "reference/v18-activation/README.md"
V18_PINS_SHA256 = "fdb94c5416f0fe7949326bcd67af14d9e588d21c7dbf4c07f70efdc872d5c103"

WRAPPER_RELATIVE = "scripts/run_simnow_c01_native_td_read_v18_root_activation_r1.py"
WRAPPER_SHA256 = "a77627312d0823284ebe8d673392668abf31e8fd6fc2a91892d4a215be004075"
ENTRY_RELATIVE = "backtrader_runtime/certification_simnow_c01_root_entry_v18.py"
ENTRY_SHA256 = "ea7221fdc5d156670376f64ae5302306e42a34af82411650ccec94336949ab30"
CUV2_PATH = Path(r"D:\temp\iteration41-root-public-custody-v2.py")
CUV2_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
PYTHON_EXE_SHA256 = "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
PYTHON_DLL_SHA256 = "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"
R1_DIAGNOSTIC_PACKET_ID = "iteration41-c01-v18-root-actual-driver-parent-diagnostic-r1-2026-10-08"
R1_DIAGNOSTIC_SHA256 = "72eeecb119273c497be8130bb89c60ff74fea076af9c3254bff47a140a622434"
R1_DIAGNOSTIC_COPY = "reference/r1-parent-diagnostic/observation.json"

MAX_PINNED_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES = 512 * 1024
MAX_STDOUT_BYTES = 32 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_REASON = re.compile(r"[a-z0-9_:-]{1,96}\Z")

ACTIVATION = None
KEEPALIVE: list[Any] = []

_PUBLIC_RESULT_KEYS = frozenset(
    {
        "case_id",
        "certification",
        "mode",
        "profile",
        "reason",
        "write_policy",
        "writes",
        "receipt_type",
        "receipt_verified",
        "source_closure_verified",
        "root_postverify_verified",
        "request_count",
        "query_callback_count",
        "snapshot_count",
        "write_invocation_count",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    }
)
_CLEANUP_KEYS = (
    "outer_job_empty",
    "stdout_eof",
    "stderr_eof",
    "stderr_empty",
    "job_handles_closed",
    "reader_threads_joined",
    "cleanup_verified",
)


class DriverBlocked(RuntimeError):
    """Fixed safe category used for every public driver failure."""

    def __init__(self, code: str):
        if type(code) is not str or not _SAFE_REASON.fullmatch(code):
            code = "root_driver_blocked"
        self.code = code
        super().__init__(code)


def need(condition: object, code: str) -> None:
    if not condition:
        raise DriverBlocked(code)


def require_unoptimized_runtime() -> None:
    """Keep optimization from stripping any production gate."""

    if sys.flags.optimize != 0:
        raise DriverBlocked("optimized_python_not_supported")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def path_key(path: str | Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(path)))


def exact(path: str | Path, expected_sha256: str, maximum: int = MAX_PINNED_BYTES) -> bytes:
    """Read bounded public bytes and verify stable identity and SHA-256."""

    path = Path(path)
    need(path.name.lower() not in {".env", "config.yaml", "secrets.yaml"}, "private_input_denied")
    before = path.lstat()
    need(not path.is_symlink(), "source_link_denied")
    need(not (getattr(before, "st_file_attributes", 0) & 0x400), "source_reparse_denied")
    need(path.is_file() and 0 < before.st_size <= maximum, "source_size_invalid")
    with path.open("rb") as stream:
        raw = stream.read(before.st_size + 1)
    after = path.stat()
    need(len(raw) == before.st_size, "source_size_changed")
    need(
        (before.st_ino, before.st_size, before.st_mtime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns),
        "source_identity_changed",
    )
    need(sha(raw) == expected_sha256, "source_pin_mismatch")
    return raw


def _strict_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError("non_finite_json_number")


def parse_ascii_json(raw: bytes) -> Any:
    return json.loads(
        raw.decode("ascii", "strict"),
        object_pairs_hook=_strict_pairs,
        parse_constant=_reject_constant,
    )


def _source_rows(pins: dict) -> dict[str, dict]:
    rows = pins.get("source_payload_files")
    need(type(rows) is list and len(rows) == 29, "source_payload_count")
    result = {}
    for row in rows:
        need(type(row) is dict and set(row) == {"path", "bytes", "sha256"}, "source_row_shape")
        relative = row["path"]
        need(type(relative) is str and relative not in result, "source_path_duplicate")
        relative_path = Path(relative)
        need(not relative_path.is_absolute() and ".." not in relative_path.parts, "source_path_invalid")
        need(type(row["bytes"]) is int and row["bytes"] > 0, "source_byte_count_invalid")
        need(type(row["sha256"]) is str and _SHA256.fullmatch(row["sha256"]), "source_hash_invalid")
        result[relative] = row
    return result


def _packet_file_map(pins: dict) -> dict[str, dict]:
    rows = pins.get("packet_files")
    need(type(rows) is list, "packet_file_list_invalid")
    result = {}
    for row in rows:
        need(type(row) is dict and set(row) == {"path", "bytes", "sha256"}, "packet_file_shape")
        relative = row["path"]
        need(type(relative) is str and relative not in result, "packet_file_duplicate")
        relative_path = Path(relative)
        need(not relative_path.is_absolute() and ".." not in relative_path.parts, "packet_file_path_invalid")
        need(type(row["bytes"]) is int and row["bytes"] > 0, "packet_file_byte_count_invalid")
        need(type(row["sha256"]) is str and _SHA256.fullmatch(row["sha256"]), "packet_file_hash_invalid")
        result[relative] = row
    return result


def verify_packet_and_sources(expected_packet_pins_sha256: str) -> tuple[dict, bytes, bytes]:
    """Verify packet, frozen V18 closure, and all physical source bytes."""

    need(_SHA256.fullmatch(expected_packet_pins_sha256), "packet_pin_argument_invalid")
    pins_raw = exact(PINS_PATH, expected_packet_pins_sha256, 256 * 1024)
    pins = parse_ascii_json(pins_raw)
    need(type(pins) is dict, "packet_pins_invalid")
    need(pins.get("schema") == "iteration41.simnow.v18.root_actual_driver.pins.r2", "packet_schema")
    need(pins.get("status") == "ROOT_ACTUAL_DRIVER_DRAFT_NOT_EXECUTED_PENDING_REVIEW", "packet_status")
    need(pins.get("driver_revision") == "R2", "driver_revision")
    need(pins.get("packet_id") == PACKET_ID, "packet_id")
    need(pins.get("official_c01_pass_count") == 0, "official_pass_count")
    need(pins.get("v18_activation_packet_id") == V18_PACKET_ID, "v18_packet_id")
    need(pins.get("v18_activation_packet_pins_sha256") == V18_PINS_SHA256, "v18_packet_pin")
    need(pins.get("wrapper_sha256") == WRAPPER_SHA256, "wrapper_pin")
    need(pins.get("entry_sha256") == ENTRY_SHA256, "entry_pin")
    need(pins.get("cuv2_sha256") == CUV2_SHA256, "cuv2_pin")
    need(pins.get("r1_parent_diagnostic_packet_id") == R1_DIAGNOSTIC_PACKET_ID, "r1_diagnostic_packet_id")
    need(pins.get("r1_parent_diagnostic_sha256") == R1_DIAGNOSTIC_SHA256, "r1_diagnostic_pin")
    need(pins.get("public_source_file_count") == 29, "packet_public_source_count")
    need(pins.get("software_pin_count") == 2, "packet_software_pin_count")
    need(pins.get("held_file_count") == 31, "packet_held_file_count")

    diagnostic_copy = exact(PACKET_DIR / R1_DIAGNOSTIC_COPY, R1_DIAGNOSTIC_SHA256, 16 * 1024)
    diagnostic_physical = exact(
        EVIDENCE / R1_DIAGNOSTIC_PACKET_ID / "observation.json",
        R1_DIAGNOSTIC_SHA256,
        16 * 1024,
    )
    need(diagnostic_copy == diagnostic_physical, "r1_diagnostic_copy_mismatch")
    diagnostic = parse_ascii_json(diagnostic_copy)
    need(diagnostic.get("profile_status") == "BLOCKED", "r1_diagnostic_status")
    need(diagnostic.get("fixed_reason") == "held_source_map_keys", "r1_diagnostic_reason")
    need(diagnostic.get("wrapper_invoked") is False, "r1_diagnostic_wrapper_started")
    need(diagnostic.get("source_expected_count") == 29, "r1_diagnostic_source_count")
    need(diagnostic.get("software_expected_count") == 2, "r1_diagnostic_software_count")
    need(diagnostic.get("actual_held_count") == 31, "r1_diagnostic_held_count")
    need(diagnostic.get("recovery_full_map_exact") is True, "r1_diagnostic_recovery_map")
    need(diagnostic.get("recovery_all_held_hashes_verified") is True, "r1_diagnostic_recovery_hashes")
    need(diagnostic.get("original_cuv2_postverify_completed") is True, "r1_diagnostic_postverify")
    need(diagnostic.get("retained_count_after_release") == 0, "r1_diagnostic_retention")
    need(diagnostic.get("official_c01_pass_count") == 0, "r1_diagnostic_official_pass_count")

    v18_pins_raw = exact(PACKET_DIR / V18_PINS_COPY, V18_PINS_SHA256, 256 * 1024)
    current_v18_pins_raw = exact(V18_PACKET_DIR / "pins.json", V18_PINS_SHA256, 256 * 1024)
    need(v18_pins_raw == current_v18_pins_raw, "v18_pins_copy_mismatch")
    v18_pins = parse_ascii_json(v18_pins_raw)
    need(v18_pins.get("packet") == V18_PACKET_ID, "v18_packet_identity")
    need(v18_pins.get("evidence_level") == "PUBLIC_SOURCE_FAKE_ONLY_NOT_REAL_ACCOUNT_ACCEPTANCE", "v18_evidence_level")
    activation_map = v18_pins.get("activation_source_map")
    need(type(activation_map) is dict and len(activation_map) == 29, "v18_source_map_shape")
    need(activation_map.get(WRAPPER_RELATIVE) == WRAPPER_SHA256, "v18_wrapper_map_pin")
    need(activation_map.get(ENTRY_RELATIVE) == ENTRY_SHA256, "v18_entry_map_pin")

    rows = _source_rows(pins)
    need(set(rows) == set(activation_map), "source_map_rows_mismatch")
    for relative, expected in rows.items():
        copied = exact(PACKET_DIR / "source" / relative, expected["sha256"])
        need(len(copied) == expected["bytes"], "source_copy_size")
        physical = exact(ROOT / relative, expected["sha256"])
        need(len(physical) == expected["bytes"], "physical_source_size")
        need(expected["sha256"] == activation_map[relative], "source_map_hash_mismatch")

    packet_files = _packet_file_map(pins)
    for relative, expected in packet_files.items():
        raw = exact(PACKET_DIR / relative, expected["sha256"], 2 * 1024 * 1024)
        need(len(raw) == expected["bytes"], "packet_file_size")
    expected_paths = set(packet_files) | {"pins.json"} | {"source/" + rel for rel in rows}
    actual_paths = {
        path.relative_to(PACKET_DIR).as_posix()
        for path in PACKET_DIR.rglob("*")
        if path.is_file()
    }
    need(actual_paths == expected_paths, "packet_contents_mismatch")
    driver_row = packet_files.get("root-actual-driver.py")
    need(type(driver_row) is dict, "driver_self_pin_missing")
    driver_raw = exact(PACKET_DIR / "root-actual-driver.py", driver_row["sha256"], 128 * 1024)
    need(len(driver_raw) == driver_row["bytes"], "driver_self_size")
    need(Path(__file__).resolve(strict=True) == (PACKET_DIR / "root-actual-driver.py").resolve(strict=True), "driver_file_binding")

    software_pins = pins.get("software_pins")
    need(
        software_pins
        == {
            "C:/anaconda3/python.exe": PYTHON_EXE_SHA256,
            "C:/anaconda3/python311.dll": PYTHON_DLL_SHA256,
        },
        "software_pins_invalid",
    )
    return pins, pins_raw, driver_raw


def _public_evidence_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    resolved_root = EVIDENCE.resolve(strict=True)
    resolved = path.resolve(strict=True)
    need(resolved.is_relative_to(resolved_root), "evidence_path_outside_public_root")
    need(path.name.lower() not in {".env", "config.yaml", "secrets.yaml"}, "private_evidence_denied")
    return path


def verify_review_readback(
    readback_raw: bytes,
    review_raw: bytes,
    *,
    expected_readback_sha256: str,
    expected_review_sha256: str,
    expected_packet_pins_sha256: str,
    driver_sha256: str,
) -> tuple[dict, dict]:
    """Require final independent review and Root readback before loading CUv2."""

    need(_SHA256.fullmatch(expected_readback_sha256), "readback_pin_invalid")
    need(_SHA256.fullmatch(expected_review_sha256), "review_pin_invalid")
    need(sha(readback_raw) == expected_readback_sha256, "readback_hash_mismatch")
    need(sha(review_raw) == expected_review_sha256, "review_hash_mismatch")
    readback = parse_ascii_json(readback_raw)
    review = parse_ascii_json(review_raw)
    need(type(readback) is dict and type(review) is dict, "review_object_invalid")
    need(readback.get("schema") == "iteration41.simnow.v18.root_driver.pre_activation_readback.r2", "readback_schema")
    need(readback.get("driver_revision") == "R2", "readback_driver_revision")
    need(readback.get("status") == "PUBLIC_SOURCE_AND_INDEPENDENT_REVIEW_MATCH", "readback_status")
    need(readback.get("driver_sha256") == driver_sha256, "readback_driver_pin")
    need(readback.get("driver_packet_pins_sha256") == expected_packet_pins_sha256, "readback_packet_pin")
    need(readback.get("independent_review_sha256") == expected_review_sha256, "readback_review_pin")
    need(readback.get("v18_activation_packet_pins_sha256") == V18_PINS_SHA256, "readback_v18_pin")
    need(readback.get("wrapper_sha256") == WRAPPER_SHA256, "readback_wrapper_pin")
    need(readback.get("entry_sha256") == ENTRY_SHA256, "readback_entry_pin")
    need(readback.get("cuv2_sha256") == CUV2_SHA256, "readback_cuv2_pin")
    need(readback.get("r1_parent_diagnostic_sha256") == R1_DIAGNOSTIC_SHA256, "readback_r1_diagnostic_pin")
    need(readback.get("public_source_file_count") == 29, "readback_source_count")
    need(readback.get("public_source_files_verified") == 29, "readback_source_verified")
    need(readback.get("software_pin_count") == 2, "readback_software_count")
    need(readback.get("software_pins_verified") == 2, "readback_software_verified")
    need(readback.get("held_file_count") == 31, "readback_held_count")
    need(readback.get("held_files_verified") == 31, "readback_held_verified")
    need(readback.get("driver_executed") is False, "readback_driver_executed")
    need(readback.get("private_inputs_read") is False, "readback_private_inputs")
    need(readback.get("actual_root_provider_native_acceptance") == "NOT_RUN", "readback_actual_status")
    need(readback.get("official_c01_pass_count") == 0, "readback_official_pass_count")

    need(review.get("schema") == "iteration41.simnow.v18.root_driver.independent_review.r2", "review_schema")
    need(review.get("driver_revision") == "R2", "review_driver_revision")
    need(review.get("status") == "FINAL_INDEPENDENT_SOURCE_FAKE_REVIEW", "review_status")
    need(review.get("verdict") == "GO_SOURCE_FAKE_ONLY", "review_verdict")
    candidate = review.get("candidate")
    need(type(candidate) is dict, "review_candidate")
    need(candidate.get("driver_sha256") == driver_sha256, "review_driver_pin")
    need(candidate.get("driver_packet_pins_sha256") == expected_packet_pins_sha256, "review_packet_pin")
    need(candidate.get("v18_activation_packet_pins_sha256") == V18_PINS_SHA256, "review_v18_pin")
    need(candidate.get("wrapper_sha256") == WRAPPER_SHA256, "review_wrapper_pin")
    need(candidate.get("entry_sha256") == ENTRY_SHA256, "review_entry_pin")
    need(candidate.get("cuv2_sha256") == CUV2_SHA256, "review_cuv2_pin")
    need(candidate.get("r1_parent_diagnostic_sha256") == R1_DIAGNOSTIC_SHA256, "review_r1_diagnostic_pin")
    need(candidate.get("public_source_file_count") == 29, "review_source_count")
    need(candidate.get("software_pin_count") == 2, "review_software_count")
    need(candidate.get("held_file_count") == 31, "review_held_count")
    need(review.get("official_c01_pass_count") == 0, "review_official_pass_count")
    need(review.get("actual_root_provider_native_acceptance") == "NOT_RUN", "review_actual_status")
    need(review.get("driver_executed") is False, "review_driver_executed")
    need(review.get("private_inputs_read") is False, "review_private_inputs")
    return readback, review


def validate_public_result(value: object, exit_code: int) -> dict:
    """Accept only the exact finite 22-field V18 wrapper projection."""

    need(type(value) is dict and set(value) == _PUBLIC_RESULT_KEYS, "public_result_shape")
    need(value.get("case_id") == "C01", "public_case_id")
    need(value.get("certification") in {"PASS", "BLOCKED"}, "public_certification")
    need(value.get("mode") == "C01_NATIVE_TD_READ_V18", "public_mode")
    need(value.get("profile") == "C01_NATIVE_TD_READ_V18", "public_profile")
    reason = value.get("reason")
    need(type(reason) is str and _SAFE_REASON.fullmatch(reason), "public_reason")
    need(value.get("write_policy") == "NO_WRITE", "public_write_policy")
    need(type(value.get("writes")) is int and value["writes"] == 0, "public_writes")
    receipt_type = value.get("receipt_type")
    need(receipt_type is None or receipt_type == "C01RootCaseResultReceipt", "public_receipt_type")
    for key in (
        "receipt_verified",
        "source_closure_verified",
        "root_postverify_verified",
        "outer_job_empty",
        "stdout_eof",
        "stderr_eof",
        "stderr_empty",
        "job_handles_closed",
        "reader_threads_joined",
        "cleanup_verified",
    ):
        need(type(value.get(key)) is bool, "public_boolean_shape")
    for key in ("request_count", "query_callback_count", "snapshot_count", "write_invocation_count"):
        need(type(value.get(key)) is int and value[key] >= 0, "public_count_shape")
    need(value["write_invocation_count"] == 0, "public_write_invocation_count")
    need(exit_code in {0, 2}, "wrapper_exit_code")
    if value["certification"] == "PASS":
        need(exit_code == 0, "pass_exit_code")
        need(reason == "root_case_receipt_verified", "pass_reason")
        need(receipt_type == "C01RootCaseResultReceipt", "pass_receipt_type")
        need(value["receipt_verified"] is True, "pass_receipt_unverified")
        need(value["source_closure_verified"] is True, "pass_source_closure")
        need(value["root_postverify_verified"] is True, "pass_root_postverify")
        need(value["request_count"] == 8, "pass_request_count")
        need(6 <= value["query_callback_count"] <= 8, "pass_callback_count")
        need(value["snapshot_count"] == 2, "pass_snapshot_count")
        need(value["write_invocation_count"] == 0, "pass_write_count")
        need(all(value[key] is True for key in _CLEANUP_KEYS), "pass_cleanup_incomplete")
        need(value["writes"] == 0, "pass_write_policy")
    else:
        need(exit_code == 2, "blocked_exit_code")
        need(value["receipt_type"] is None, "blocked_receipt_type")
        need(value["receipt_verified"] is False, "blocked_receipt_verified")
        need(value["source_closure_verified"] is False, "blocked_source_closure")
        need(value["root_postverify_verified"] is False, "blocked_root_postverify")
        need(value["request_count"] == 0, "blocked_request_count")
        need(value["query_callback_count"] == 0, "blocked_callback_count")
        need(value["snapshot_count"] == 0, "blocked_snapshot_count")
    return dict(value)


def parse_public_result(raw: bytes, exit_code: int, stderr: bytes = b"") -> dict:
    need(type(raw) is bytes and 0 < len(raw) <= MAX_STDOUT_BYTES, "wrapper_output_size")
    need(type(stderr) is bytes and stderr == b"", "wrapper_stderr_not_empty")
    body = raw[:-2] if raw.endswith(b"\r\n") else raw[:-1] if raw.endswith(b"\n") else None
    need(body is not None and body and b"\n" not in body and b"\r" not in body, "wrapper_output_lines")
    value = parse_ascii_json(body)
    canonical = json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("ascii")
    need(canonical == body, "wrapper_output_not_canonical")
    return validate_public_result(value, exit_code)


def _load_module(raw: bytes, path: str | Path, module_name: str) -> types.ModuleType:
    module = types.ModuleType(module_name)
    module.__file__ = str(path)
    module.__package__ = "scripts"
    module.__spec__ = importlib.machinery.ModuleSpec(module_name, loader=None, origin=str(path))
    need(module_name not in sys.modules, "module_name_already_loaded")
    sys.modules[module_name] = module
    try:
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _expected_absolute_pins(source_map: dict[str, str], root: Path) -> dict[str, str]:
    result = {}
    for relative, digest in source_map.items():
        need(type(relative) is str and not Path(relative).is_absolute(), "source_path_invalid")
        need(type(digest) is str and _SHA256.fullmatch(digest), "source_hash_invalid")
        result[str(root / relative)] = digest
    return result


def _normalized_expected_group(pins: dict[str, str], *, code: str) -> dict[str, tuple[str, str]]:
    need(type(pins) is dict, code)
    result = {}
    for path, digest in pins.items():
        need(type(path) is str and ntpath.isabs(path), code)
        need(type(digest) is str and _SHA256.fullmatch(digest), code)
        normalized = path_key(path)
        need(normalized not in result, "held_pin_path_duplicate")
        result[normalized] = (path, digest)
    return result


def _expected_full_held_map(
    public_pins: dict[str, str], software_pins: dict[str, str]
) -> tuple[dict[str, tuple[str, str]], int, int]:
    """Normalize the complete CUv2 public-source and software pin union."""

    public = _normalized_expected_group(public_pins, code="public_pin_map_invalid")
    software = _normalized_expected_group(software_pins, code="software_pin_map_invalid")
    need(set(public).isdisjoint(software), "public_software_pin_overlap")
    return {**public, **software}, len(public), len(software)


def _normalize_held_map(held: object) -> dict[str, bytes]:
    need(type(held) is dict, "held_source_map_type")
    normalized = {}
    for path, raw in held.items():
        need(type(path) is str and ntpath.isabs(path), "held_source_path_invalid")
        key = path_key(path)
        need(key not in normalized, "held_source_path_duplicate")
        normalized[key] = raw
    return normalized


def verify_held_source_map(
    held: object, expected: dict[str, tuple[str, str]]
) -> dict[str, bytes]:
    normalized = _normalize_held_map(held)
    need(set(normalized) == set(expected), "held_source_map_keys")
    copied = {}
    for key, (_path, digest) in expected.items():
        raw = normalized.get(key)
        need(type(raw) is bytes and sha(raw) == digest, "held_source_hash")
        copied[key] = raw
    return copied


class HeldSourceLease:
    """Own the CUv2 scope and delay public output until postverify and close."""

    def __init__(
        self,
        manager,
        private_module,
        cli_module,
        held,
        expected,
        root,
        cuv2_raw,
        public_source_count,
        software_pin_count,
    ):
        self.manager = manager
        self.private_module = private_module
        self.cli_module = cli_module
        self.held = held
        self.expected = expected
        self.root = root
        self.cuv2_raw = cuv2_raw
        self.entered = True
        self.closed = False
        self.exit_started = False
        self.postverify_complete = False
        self.public_source_count = public_source_count
        self.software_pin_count = software_pin_count
        self.references = []

    def verify_held(self) -> bool:
        try:
            verify_held_source_map(self.held, self.expected)
            return True
        except BaseException:
            return False

    def postverify_and_close(self, *, cuv2_path: Path, cuv2_sha256: str) -> bool:
        if self.closed or self.exit_started or not self.entered or not self.verify_held():
            return False
        try:
            held_map = verify_held_source_map(self.held, self.expected)
            for key, (path, digest) in self.expected.items():
                current = exact(Path(path), digest)
                if current != held_map[key]:
                    return False
            self.exit_started = True
            self.manager.__exit__(None, None, None)
            self.closed = True
            if not self.verify_held():
                return False
            held_map = verify_held_source_map(self.held, self.expected)
            for key, (path, digest) in self.expected.items():
                current = exact(Path(path), digest)
                if current != held_map[key]:
                    return False
            if exact(cuv2_path, cuv2_sha256, 2 * 1024 * 1024) != self.cuv2_raw:
                return False
            self.postverify_complete = True
            return True
        except BaseException:
            return False

    def keepalive(self, activation_module=None) -> tuple:
        return (
            self,
            self.manager,
            self.private_module,
            self.cli_module,
            self.held,
            self.expected,
            self.cuv2_raw,
            activation_module,
        ) + tuple(self.references)


def _retain_uncertain(lease: HeldSourceLease, activation_module=None) -> None:
    refs = lease.keepalive(activation_module)
    if not any(item is refs for item in KEEPALIVE):
        KEEPALIVE.append(refs)
    if activation_module is not None:
        retained = getattr(activation_module, "_ROOT_RETAINED_UNRESOLVED_JOB_REFS", None)
        if type(retained) is list and retained:
            if not any(item is retained for item in KEEPALIVE):
                KEEPALIVE.append(retained)


def _all_cleanup_true(projection: dict) -> bool:
    return all(projection.get(key) is True for key in _CLEANUP_KEYS)


def _blocked_projection(reason: str) -> dict:
    safe = reason if type(reason) is str and _SAFE_REASON.fullmatch(reason) else "root_driver_blocked"
    return {
        "case_id": "C01",
        "certification": "BLOCKED",
        "mode": "C01_NATIVE_TD_READ_V18",
        "profile": "C01_NATIVE_TD_READ_V18",
        "reason": safe,
        "write_policy": "NO_WRITE",
        "writes": 0,
        "receipt_type": None,
        "receipt_verified": False,
        "source_closure_verified": False,
        "root_postverify_verified": False,
        "request_count": 0,
        "query_callback_count": 0,
        "snapshot_count": 0,
        "write_invocation_count": 0,
        "outer_job_empty": False,
        "stdout_eof": False,
        "stderr_eof": False,
        "stderr_empty": False,
        "job_handles_closed": False,
        "reader_threads_joined": False,
        "cleanup_verified": False,
    }


def _driver_result(
    projection: dict,
    *,
    outer_postverify: bool,
    outer_closed: bool,
    public_source_count: int = 29,
    software_pin_count: int = 2,
) -> dict:
    if projection.get("certification") == "PASS" and not (
        outer_postverify is True and outer_closed is True
    ):
        projection = _blocked_projection("outer_cuv2_postverify_failed")
    return {
        "schema": "iteration41.simnow.v18.root_actual_driver.public_result.r2",
        "classification": "ROOT_PROFILE_RESULT_NOT_OFFICIAL_C01_ACCEPTANCE",
        "profile_result": dict(projection),
        "independent_review_verified": True,
        "root_readback_verified": True,
        "outer_cuv2_postverify_verified": bool(outer_postverify),
        "outer_cuv2_scope_closed": bool(outer_closed),
        "public_source_file_count": public_source_count,
        "software_pin_count": software_pin_count,
        "held_file_count": public_source_count + software_pin_count,
        "writes": 0,
        "official_c01_pass_count": 0,
        "formal_c01_pass": False,
        "private_capture_read_by_driver": False,
        "opaque_receipt_seen_by_driver": False,
        "late_private_capture_read": False,
    }


def invoke_fixed_wrapper_main(
    wrapper_raw: bytes,
    *,
    wrapper_path: str | Path,
    expected_wrapper_sha256: str,
    module_name: str,
    on_module=None,
    on_start=None,
) -> tuple[dict, types.ModuleType]:
    """Call only the frozen wrapper's fixed activation argv; capture its stdout."""

    need(sha(wrapper_raw) == expected_wrapper_sha256, "wrapper_held_pin")
    module = _load_module(wrapper_raw, wrapper_path, module_name)
    started = False
    try:
        retained = getattr(module, "_ROOT_RETAINED_UNRESOLVED_JOB_REFS", None)
        need(retained is None or type(retained) is list, "wrapper_retention_shape")
        need(not retained, "wrapper_preexisting_uncertain_job_refs")
        if on_module is not None:
            on_module(module)
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            "--activate-c01-v18-td-read",
            "--expected-wrapper-sha256",
            expected_wrapper_sha256,
        ]
        main = getattr(module, "main", None)
        need(callable(main), "wrapper_main_unavailable")
        exit_code = None
        with redirect_stdout(stdout), redirect_stderr(stderr):
            if on_start is not None:
                on_start()
            started = True
            exit_code = main(argv)
        current_retained = getattr(module, "_ROOT_RETAINED_UNRESOLVED_JOB_REFS", None)
        if type(current_retained) is list and current_retained:
            KEEPALIVE.append(module)
            KEEPALIVE.append(current_retained)
            raise DriverBlocked("wrapper_same_call_unresolved_job_refs")
        try:
            stdout_raw = stdout.getvalue().encode("ascii", "strict")
            stderr_raw = stderr.getvalue().encode("ascii", "strict")
        except Exception:
            raise DriverBlocked("wrapper_output_encoding") from None
        projection = parse_public_result(stdout_raw, exit_code, stderr_raw)
        return projection, module
    except BaseException:
        if not started:
            sys.modules.pop(module_name, None)
        raise


def activate_with_held_sources(
    cuv2,
    cuv2_raw: bytes,
    *,
    source_map: dict[str, str],
    software_pins: dict[str, str],
    wrapper_relative: str,
    wrapper_sha256: str,
    root: Path,
    cuv2_path: Path,
    cuv2_sha256: str = CUV2_SHA256,
) -> tuple[dict, HeldSourceLease, types.ModuleType | None]:
    """Run wrapper from exact held bytes and close CUv2 before any PASS is returned."""

    public_pins = _expected_absolute_pins(source_map, root)
    expected, public_source_count, software_pin_count = _expected_full_held_map(
        public_pins, software_pins
    )
    manager = cuv2.held_public_sources(public_pins, software_pins)
    entered = False
    values = None
    lease = None
    activation = None
    wrapper_started = False
    try:
        values = manager.__enter__()
        entered = True
        need(type(values) is tuple and len(values) == 3, "cuv2_context_shape")
        private_module, cli_module, held = values
        lease = HeldSourceLease(
            manager,
            private_module,
            cli_module,
            held,
            expected,
            root,
            cuv2_raw,
            public_source_count,
            software_pin_count,
        )
        held_map = verify_held_source_map(held, expected)
        wrapper_path = root / wrapper_relative
        wrapper_raw = held_map.get(path_key(str(wrapper_path)))
        need(type(wrapper_raw) is bytes, "wrapper_not_held")

        def remember_module(module):
            nonlocal activation
            activation = module
            lease.references.append(module)

        def mark_wrapper_started():
            nonlocal wrapper_started
            wrapper_started = True

        projection, activation = invoke_fixed_wrapper_main(
            wrapper_raw,
            wrapper_path=wrapper_path,
            expected_wrapper_sha256=wrapper_sha256,
            module_name="_iteration41_simnow_c01_v18_root_activation_wrapper",
            on_module=remember_module,
            on_start=mark_wrapper_started,
        )
        if not _all_cleanup_true(projection):
            _retain_uncertain(lease, activation)
            return (
                _driver_result(
                    projection,
                    outer_postverify=False,
                    outer_closed=False,
                    public_source_count=public_source_count,
                    software_pin_count=software_pin_count,
                ),
                lease,
                activation,
            )
        if not lease.postverify_and_close(cuv2_path=cuv2_path, cuv2_sha256=cuv2_sha256):
            _retain_uncertain(lease, activation)
            blocked = _blocked_projection("outer_cuv2_postverify_failed")
            return (
                _driver_result(
                    blocked,
                    outer_postverify=False,
                    outer_closed=lease.closed,
                    public_source_count=public_source_count,
                    software_pin_count=software_pin_count,
                ),
                lease,
                activation,
            )
        return (
            _driver_result(
                projection,
                outer_postverify=lease.postverify_complete,
                outer_closed=lease.closed,
                public_source_count=public_source_count,
                software_pin_count=software_pin_count,
            ),
            lease,
            activation,
        )
    except BaseException:
        if lease is not None:
            if not wrapper_started and not lease.closed and not lease.exit_started and lease.verify_held():
                if not lease.postverify_and_close(cuv2_path=cuv2_path, cuv2_sha256=cuv2_sha256):
                    _retain_uncertain(lease, activation)
            else:
                _retain_uncertain(lease, activation)
        elif entered:
            KEEPALIVE.append((manager, cuv2, cuv2_raw, expected, values))
        # A context whose __enter__ did not return is never manually exited.
        raise


def _load_cuv2() -> tuple[types.ModuleType, bytes]:
    raw = exact(CUV2_PATH, CUV2_SHA256, 2 * 1024 * 1024)
    module = _load_module(raw, CUV2_PATH, "_iteration41_root_public_custody_v2")
    need(callable(getattr(module, "held_public_sources", None)), "cuv2_api_unavailable")
    return module, raw


def _parse_args(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate-c01-v18-td-read", action="store_true", required=True)
    parser.add_argument("--expected-wrapper-sha256", required=True)
    parser.add_argument("--root-readback", required=True)
    parser.add_argument("--expected-root-readback-sha256", required=True)
    parser.add_argument("--independent-review", required=True)
    parser.add_argument("--expected-independent-review-sha256", required=True)
    parser.add_argument("--expected-packet-pins-sha256", required=True)
    args = parser.parse_args(argv)
    for value in (
        args.expected_wrapper_sha256,
        args.expected_root_readback_sha256,
        args.expected_independent_review_sha256,
        args.expected_packet_pins_sha256,
    ):
        if not _SHA256.fullmatch(value):
            parser.error("expected SHA-256 values must be 64 lowercase hexadecimal characters")
    if args.expected_wrapper_sha256 != WRAPPER_SHA256:
        parser.error("wrapper pin does not match the frozen V18 activation API")
    return args


def _fixed_runtime_matches() -> bool:
    return bool(
        tuple(sys.version_info[:3]) == (3, 11, 5)
        and sys.flags.isolated
        and sys.flags.no_site
        and sys.dont_write_bytecode
        and path_key(sys.executable) == path_key("C:/anaconda3/python.exe")
    )


def run_root_activation(argv: list[str] | None = None) -> dict:
    global ACTIVATION

    require_unoptimized_runtime()
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    need(_fixed_runtime_matches(), "fixed_runtime_required")
    need(PACKET_DIR.resolve(strict=True) == (EVIDENCE / PACKET_ID).resolve(strict=True), "driver_packet_path")
    pins, _pins_raw, driver_raw = verify_packet_and_sources(args.expected_packet_pins_sha256)
    driver_sha256 = sha(driver_raw)
    readback_path = _public_evidence_path(args.root_readback)
    review_path = _public_evidence_path(args.independent_review)
    readback_raw = exact(readback_path, args.expected_root_readback_sha256, MAX_EVIDENCE_BYTES)
    review_raw = exact(review_path, args.expected_independent_review_sha256, MAX_EVIDENCE_BYTES)
    verify_review_readback(
        readback_raw,
        review_raw,
        expected_readback_sha256=args.expected_root_readback_sha256,
        expected_review_sha256=args.expected_independent_review_sha256,
        expected_packet_pins_sha256=args.expected_packet_pins_sha256,
        driver_sha256=driver_sha256,
    )
    runtime_pins = pins["software_pins"]
    exact(Path(sys.executable), runtime_pins["C:/anaconda3/python.exe"])
    exact(Path("C:/anaconda3/python311.dll"), runtime_pins["C:/anaconda3/python311.dll"])
    cuv2, cuv2_raw = _load_cuv2()
    v18_pins = parse_ascii_json(exact(PACKET_DIR / V18_PINS_COPY, V18_PINS_SHA256, 256 * 1024))
    source_map = v18_pins["activation_source_map"]
    ACTIVATION = None
    try:
        result, lease, activation = activate_with_held_sources(
            cuv2,
            cuv2_raw,
            source_map=source_map,
            software_pins=runtime_pins,
            wrapper_relative=WRAPPER_RELATIVE,
            wrapper_sha256=WRAPPER_SHA256,
            root=ROOT,
            cuv2_path=CUV2_PATH,
            cuv2_sha256=CUV2_SHA256,
        )
        ACTIVATION = activation
        return result
    except DriverBlocked as error:
        return _driver_result(_blocked_projection(error.code), outer_postverify=False, outer_closed=False)
    except Exception:
        return _driver_result(_blocked_projection("root_driver_blocked"), outer_postverify=False, outer_closed=False)


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_root_activation(argv)
    except DriverBlocked as error:
        result = _driver_result(_blocked_projection(error.code), outer_postverify=False, outer_closed=False)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    except SystemExit:
        raise
    except Exception:
        result = _driver_result(_blocked_projection("root_driver_blocked"), outer_postverify=False, outer_closed=False)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    else:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    return 0 if result["profile_result"]["certification"] == "PASS" and result["outer_cuv2_postverify_verified"] else 2


if __name__ == "__main__":
    try:
        require_unoptimized_runtime()
    except DriverBlocked as error:
        raise SystemExit(error.code)
    raise SystemExit(main())
