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
PACKET_ID = "iteration41-c01-v18-root-actual-driver-draft-r4b-2026-10-08"
PACKET_DIR = Path(__file__).absolute().parent
PINS_PATH = PACKET_DIR / "pins.json"
SOURCE_REFERENCE_PACKET_ID = "iteration41-c01-v18-root-actual-driver-draft-r4-2026-10-08"
SOURCE_REFERENCE_PINS_COPY = "reference/r4-source-packet/pins.json"
SOURCE_REFERENCE_PINS_SHA256 = "b6e3f096d9419d21f5ba4a911b55a076009d58535b0de70fd86d9e8658d175c5"
SOURCE_REFERENCE_DIR = EVIDENCE / SOURCE_REFERENCE_PACKET_ID
V18_PACKET_ID = "iteration41-c01-v18-root-entry-isolated-import-r5-20261008"
V18_PACKET_DIR = EVIDENCE / V18_PACKET_ID
V18_R4_PACKET_ID = "iteration41-c01-v18-root-entry-isolated-import-r4-20261008"
V18_R4_PACKET_DIR = EVIDENCE / V18_R4_PACKET_ID
V18_R4_PINS_COPY = "reference/v18-activation-r4/pins.json"
V18_R4_WRAPPER_COPY = "reference/v18-activation-r4/public-source/root_activation_wrapper_r2.py"
V18_R4_TEST_COPY = "reference/v18-activation-r4/tests/test_root_activation_wrapper_r2_source_fake.py"
V18_R4_PINS_SHA256 = "2528ee847adcb7ffa18b130053ae1772954689197c883d9b2c310a413dfba1e8"
V18_R4_WRAPPER_SHA256 = "b2506ceb764ddb3a5ec6fedb743b3e5835feeefc1308e3c4dd1e444cf7812486"
V18_R4_TEST_SHA256 = "0ea25be6a0cdf29820e3b374c4267491fb6ba5a63213ebd74440f70a3c3f5ac9"
V18_R4_MANIFEST_SHA256 = "c1475f636dd21dd8b303b3921dad0d6f1912c8bf48180afe194c99075aa464a8"
V18_PINS_COPY = "reference/v18-activation-r5/pins.json"
V18_README_COPY = "reference/v18-activation-r5/README.md"
V18_SOURCE_MAP_DELTA_COPY = "reference/v18-activation-r5/source-map-delta.json"
V18_WRAPPER_COPY = "reference/v18-activation-r5/public-source/root_activation_wrapper_r2.py"
V18_TEST_COPY = "reference/v18-activation-r5/tests/test_root_activation_wrapper_r2_source_fake.py"
V18_REVIEW_COPY = "reference/v18-activation-r5/independent-review.md"
V18_PINS_SHA256 = "3c1fdd78d0eaf6103478a534a51809948839daa9096a226a57d16f784890691d"
V18_SOURCE_MAP_DELTA_SHA256 = "a774d28c4d18af8f25a04e7ba822a0ef51a903428a536801c10429dfcf53a70b"
V18_SOURCE_MAP_CHECK_SHA256 = "828df6686478abeeefeab097e49ac91257fc04d9e3330fee1d4e74f2b7efe394"
V18_TEST_RELATIVE = "tests/unit/runtime/test_simnow_c01_native_td_read_v18_root_activation_r2_source_fake.py"
V18_TEST_SHA256 = "ae44a08668aac9ffda8c0939d9417de8fdcb7ae698c914def1dac2bd9fd092fb"
V18_REVIEW_SHA256 = "c94642b61a07e22497658c9e0818451c45a00be17b8fee79bce52f40c037ebca"

WRAPPER_RELATIVE = "scripts/run_simnow_c01_native_td_read_v18_root_activation_r2.py"
WRAPPER_SHA256 = "ce221c68a92bfce4ef0f273347f09c3260f127b6b68f985b16505ef7a1cda4bb"
ENTRY_RELATIVE = "backtrader_runtime/certification_simnow_c01_root_entry_v18.py"
ENTRY_SHA256 = "ea7221fdc5d156670376f64ae5302306e42a34af82411650ccec94336949ab30"
CUV2_PATH = Path(r"D:\temp\iteration41-root-public-custody-v2.py")
CUV2_SHA256 = "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246"
PYTHON_EXE_SHA256 = "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642"
PYTHON_DLL_SHA256 = "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00"
R2_DIAGNOSTIC_PACKET_ID = "iteration41-c01-v18-root-actual-driver-parent-diagnostic-r2-2026-10-08"
R2_DIAGNOSTIC_SHA256 = "3ebf3f8c71b5dab3d5f83cfe5af6a7fc28defcf3b94e36123dc8f37e264441e3"
R2_DIAGNOSTIC_COPY = "reference/r2-parent-diagnostic/observation.json"

MAX_PINNED_BYTES = 16 * 1024 * 1024
MAX_EVIDENCE_BYTES = 512 * 1024
MAX_STDOUT_BYTES = 32 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_REASON = re.compile(r"[a-z0-9_:-]{1,96}\Z")

ACTIVATION = None
KEEPALIVE: list[Any] = []
_FORMAL_ACTIVATION_AUTHORITY = object()

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
    need(type(rows) is list and len(rows) == 31, "source_payload_count")
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
    need(pins.get("schema") == "iteration41.simnow.v18.root_actual_driver.pins.r4b", "packet_schema")
    need(pins.get("status") == "ROOT_ACTUAL_DRIVER_DRAFT_NOT_EXECUTED_PENDING_REVIEW", "packet_status")
    need(pins.get("driver_revision") == "R4B", "driver_revision")
    need(pins.get("packet_id") == PACKET_ID, "packet_id")
    need(pins.get("source_reference_packet_id") == SOURCE_REFERENCE_PACKET_ID, "source_reference_packet_id")
    need(pins.get("source_reference_pins_sha256") == SOURCE_REFERENCE_PINS_SHA256, "source_reference_pins_sha256")
    _exact_count(pins, "official_c01_pass_count", 0, "official_pass_count")
    need(pins.get("v18_activation_packet_id") == V18_PACKET_ID, "v18_packet_id")
    need(pins.get("v18_activation_packet_pins_sha256") == V18_PINS_SHA256, "v18_packet_pin")
    need(pins.get("wrapper_sha256") == WRAPPER_SHA256, "wrapper_pin")
    need(pins.get("entry_sha256") == ENTRY_SHA256, "entry_pin")
    need(pins.get("cuv2_sha256") == CUV2_SHA256, "cuv2_pin")
    need(pins.get("r2_parent_diagnostic_packet_id") == R2_DIAGNOSTIC_PACKET_ID, "r2_diagnostic_packet_id")
    need(pins.get("r2_parent_diagnostic_sha256") == R2_DIAGNOSTIC_SHA256, "r2_diagnostic_pin")
    need(pins.get("v18_source_map_delta_sha256") == V18_SOURCE_MAP_DELTA_SHA256, "v18_delta_pin")
    need(pins.get("v18_wrapper_test_sha256") == V18_TEST_SHA256, "v18_test_pin")
    need(pins.get("v18_wrapper_independent_review_sha256") == V18_REVIEW_SHA256, "v18_review_pin")
    _exact_count(pins, "public_source_file_count", 31, "packet_public_source_count")
    _exact_count(pins, "software_pin_count", 2, "packet_software_pin_count")
    _exact_count(pins, "planned_held_file_count", 33, "packet_planned_held_file_count")

    diagnostic_copy = exact(PACKET_DIR / R2_DIAGNOSTIC_COPY, R2_DIAGNOSTIC_SHA256, 16 * 1024)
    diagnostic_physical = exact(
        EVIDENCE / R2_DIAGNOSTIC_PACKET_ID / "observation.json",
        R2_DIAGNOSTIC_SHA256,
        16 * 1024,
    )
    need(diagnostic_copy == diagnostic_physical, "r2_diagnostic_copy_mismatch")
    diagnostic = parse_ascii_json(diagnostic_copy)
    diagnostic_result = diagnostic.get("result")
    diagnostic_projection = diagnostic_result.get("profile_result") if type(diagnostic_result) is dict else None
    need(diagnostic.get("wrapper_invoked") is True, "r2_diagnostic_wrapper_started")
    need(type(diagnostic_projection) is dict, "r2_diagnostic_projection")
    need(diagnostic_projection.get("certification") == "BLOCKED", "r2_diagnostic_status")
    need(diagnostic_projection.get("reason") == "root_entry_blocked", "r2_diagnostic_reason")
    _exact_count(diagnostic_result, "public_source_file_count", 29, "r2_diagnostic_source_count")
    _exact_count(diagnostic_result, "software_pin_count", 2, "r2_diagnostic_software_count")
    _exact_count(diagnostic_result, "held_file_count", 31, "r2_diagnostic_held_count")
    need(diagnostic_result.get("outer_cuv2_postverify_verified") is True, "r2_diagnostic_postverify")
    need(diagnostic_result.get("outer_cuv2_scope_closed") is True, "r2_diagnostic_scope_closed")
    need(diagnostic.get("retained_reference_count") == 0, "r2_diagnostic_retention")
    need(diagnostic.get("provider_stage") == "UNOBSERVED", "r2_diagnostic_provider_stage")
    need(diagnostic.get("native_stage") == "UNOBSERVED", "r2_diagnostic_native_stage")
    _exact_count(diagnostic_result, "official_c01_pass_count", 0, "r2_diagnostic_official_pass_count")

    v18_pins_raw = exact(PACKET_DIR / V18_PINS_COPY, V18_PINS_SHA256, 256 * 1024)
    current_v18_pins_raw = exact(V18_PACKET_DIR / "pins.json", V18_PINS_SHA256, 256 * 1024)
    need(v18_pins_raw == current_v18_pins_raw, "v18_pins_copy_mismatch")
    v18_pins = parse_ascii_json(v18_pins_raw)
    need(v18_pins.get("schema") == "simnow.c01.v18.root_activation.public_held_source_map.v1", "v18_packet_schema")
    need(v18_pins.get("public_source_rows") == 31, "v18_public_source_count")
    need(v18_pins.get("software_rows") == 2, "v18_software_count")
    need(v18_pins.get("held_rows_total") == 33, "v18_held_count")
    need(v18_pins.get("software_pins") == pins.get("software_pins"), "v18_software_pin_copy")
    activation_map = v18_pins.get("public_source_pins")
    need(type(activation_map) is dict and len(activation_map) == 31, "v18_source_map_shape")
    need(activation_map.get(WRAPPER_RELATIVE) == WRAPPER_SHA256, "v18_wrapper_map_pin")
    need(activation_map.get(ENTRY_RELATIVE) == ENTRY_SHA256, "v18_entry_map_pin")

    r4_pins_raw = exact(PACKET_DIR / V18_R4_PINS_COPY, V18_R4_PINS_SHA256, 256 * 1024)
    r4_pins_physical = exact(V18_R4_PACKET_DIR / "pins.json", V18_R4_PINS_SHA256, 256 * 1024)
    need(r4_pins_raw == r4_pins_physical, "v18_r4_pins_copy_mismatch")
    r4_wrapper_copy = exact(PACKET_DIR / V18_R4_WRAPPER_COPY, V18_R4_WRAPPER_SHA256)
    r4_test_copy = exact(PACKET_DIR / V18_R4_TEST_COPY, V18_R4_TEST_SHA256)
    need(bool(r4_wrapper_copy) and bool(r4_test_copy), "v18_r4_historical_payload_missing")
    r4_pins = parse_ascii_json(r4_pins_raw)
    r4_map = r4_pins.get("public_source_pins")
    need(type(r4_map) is dict and len(r4_map) == 31, "v18_r4_source_map_shape")
    successor_map = dict(r4_map)
    successor_map[WRAPPER_RELATIVE] = WRAPPER_SHA256
    need(successor_map == activation_map, "v18_r5_map_delta_not_exact")
    need(r4_pins.get("software_pins") == v18_pins.get("software_pins"), "v18_r5_software_changed")

    delta_copy = exact(PACKET_DIR / V18_SOURCE_MAP_DELTA_COPY, V18_SOURCE_MAP_DELTA_SHA256, 32 * 1024)
    delta_physical = exact(V18_PACKET_DIR / "source-map-delta.json", V18_SOURCE_MAP_DELTA_SHA256, 32 * 1024)
    need(delta_copy == delta_physical, "v18_delta_copy_mismatch")
    delta = parse_ascii_json(delta_copy)
    need(delta.get("schema") == "simnow.c01.v18.root_activation.generated_method_identity.r5", "v18_delta_schema")
    need(delta.get("packet") == V18_PACKET_ID, "v18_delta_packet")
    inherited = delta.get("inherits")
    inherited_r4 = inherited.get("r4_packet") if type(inherited) is dict else None
    need(type(inherited_r4) is dict, "v18_r5_r4_inheritance_shape")
    need(inherited_r4.get("pins_sha256") == V18_R4_PINS_SHA256, "v18_r5_r4_pins_pin")
    need(inherited_r4.get("manifest_sha256") == V18_R4_MANIFEST_SHA256, "v18_r5_r4_manifest_pin")
    need(inherited_r4.get("frozen_r4_wrapper_sha256") == V18_R4_WRAPPER_SHA256, "v18_r5_r4_wrapper_pin")
    need(inherited_r4.get("frozen_r4_test_sha256") == V18_R4_TEST_SHA256, "v18_r5_r4_test_pin")
    need(inherited.get("r3_packet") == "../iteration41-c01-v18-root-entry-activation-r3-clean-source-20261008", "v18_r5_r3_parent")
    need(inherited.get("r2_packet") == "../iteration41-c01-v18-root-entry-activation-r2-20261008", "v18_r5_r2_parent")
    wrapper_successor = delta.get("wrapper_successor")
    need(type(wrapper_successor) is dict, "v18_wrapper_successor_shape")
    need(wrapper_successor.get("sha256") == WRAPPER_SHA256, "v18_wrapper_successor_pin")
    need(wrapper_successor.get("workspace_path") == WRAPPER_RELATIVE, "v18_wrapper_successor_path")
    need(wrapper_successor.get("r4_parent_wrapper_sha256") == V18_R4_WRAPPER_SHA256, "v18_wrapper_r4_parent_pin")
    need(wrapper_successor.get("root_entry_v18_sha256_unchanged") == ENTRY_SHA256, "v18_entry_unchanged_pin")
    need(wrapper_successor.get("bytes") == 112913, "v18_wrapper_byte_count")
    held_map = delta.get("held_map")
    need(type(held_map) is dict, "v18_r5_held_map_shape")
    need(held_map.get("public_rows") == 31, "v18_r5_public_rows")
    need(held_map.get("software_rows") == 2, "v18_r5_software_rows")
    need(held_map.get("held_rows_total") == 33, "v18_r5_held_rows")
    need(held_map.get("pins_sha256") == V18_PINS_SHA256, "v18_r5_pins_binding")
    need(held_map.get("entry_literal_rows_unchanged") == 27, "v18_r5_entry_literal_rows")
    need(held_map.get("fixed_wrapper_dependency_delta_rows") == 2, "v18_r5_fixed_delta_rows")
    need(held_map.get("entry_self_row") == 1 and held_map.get("wrapper_self_row") == 1, "v18_r5_self_rows")
    unchanged = delta.get("unchanged_source_pins")
    need(type(unchanged) is dict, "v18_r5_unchanged_sources_shape")
    need(unchanged.get("added_common_case_engine_sha256") == "f8dcbac821ea75ce1d6f49aaeb78f7a42626f5c24ecfca4a855831b66ed7aec1", "v18_case_engine_pin")
    need(unchanged.get("added_common_completion_invariants_sha256") == "58ae3c8c59bccfbe17680f313fd30b9abbcd0a14e7f8ed7e51bc520985f4506e", "v18_completion_invariants_pin")
    test_metadata = delta.get("test")
    need(type(test_metadata) is dict, "v18_r5_test_shape")
    need(test_metadata.get("workspace_path") == V18_TEST_RELATIVE, "v18_r5_test_path")
    need(test_metadata.get("bytes") == 20698, "v18_r5_test_byte_count")
    need(test_metadata.get("sha256") == V18_TEST_SHA256, "v18_r5_test_pin")
    need(test_metadata.get("test_cases") == 8, "v18_r5_test_case_count")
    need(test_metadata.get("new_generated_constructor_case") == "DescriptiveCasePlan.__init__ replaced at the fake custody lease boundary using identical globals and original co_filename; expected common_module_code_identity_changed", "v18_r5_generated_constructor_case")
    source_map_check_path = "reference/v18-activation-r5/qa/source-map-check.txt"
    source_map_check = exact(PACKET_DIR / source_map_check_path, V18_SOURCE_MAP_CHECK_SHA256, 4 * 1024)
    source_map_check_physical = exact(
        V18_PACKET_DIR / "qa/source-map-check.txt", V18_SOURCE_MAP_CHECK_SHA256, 4 * 1024
    )
    need(source_map_check == source_map_check_physical, "v18_source_map_check_copy_mismatch")
    source_map_check_text = source_map_check.decode("ascii", "strict")
    need("public_rows=31" in source_map_check_text, "v18_source_map_check_rows")
    need("source_matches=31" in source_map_check_text, "v18_source_map_check_matches")
    need("mismatches=0" in source_map_check_text, "v18_source_map_check_mismatches")
    wrapper_copy = exact(PACKET_DIR / V18_WRAPPER_COPY, WRAPPER_SHA256)
    need(wrapper_copy == exact(ROOT / WRAPPER_RELATIVE, WRAPPER_SHA256), "v18_wrapper_copy_mismatch")
    test_copy = exact(PACKET_DIR / V18_TEST_COPY, V18_TEST_SHA256)
    need(test_copy == exact(ROOT / V18_TEST_RELATIVE, V18_TEST_SHA256), "v18_test_copy_mismatch")
    review_copy = exact(PACKET_DIR / V18_REVIEW_COPY, V18_REVIEW_SHA256, 8 * 1024)
    review_physical = exact(
        EVIDENCE / "iteration41-c01-v18-root-entry-isolated-import-independent-review-r5-20261008.md",
        V18_REVIEW_SHA256,
        8 * 1024,
    )
    need(review_copy == review_physical, "v18_review_copy_mismatch")
    review_text = review_copy.decode("utf-8", "strict")
    for marker in (
        "**SOURCE_FAKE_ONLY_REVIEW: PASS**",
        WRAPPER_SHA256,
        V18_TEST_SHA256,
        V18_PINS_SHA256,
        V18_SOURCE_MAP_DELTA_SHA256,
        "**50 passed, 0 failed**",
    ):
        need(marker in review_text, "v18_review_content_mismatch")

    source_reference_copy = exact(
        PACKET_DIR / SOURCE_REFERENCE_PINS_COPY,
        SOURCE_REFERENCE_PINS_SHA256,
        256 * 1024,
    )
    source_reference_physical = exact(
        SOURCE_REFERENCE_DIR / "pins.json",
        SOURCE_REFERENCE_PINS_SHA256,
        256 * 1024,
    )
    need(source_reference_copy == source_reference_physical, "source_reference_copy_mismatch")
    source_reference_pins = parse_ascii_json(source_reference_copy)
    need(type(source_reference_pins) is dict, "source_reference_pins_invalid")
    need(source_reference_pins.get("packet_id") == SOURCE_REFERENCE_PACKET_ID, "source_reference_packet_id_invalid")
    need(source_reference_pins.get("schema") == "iteration41.simnow.v18.root_actual_driver.pins.r4", "source_reference_schema")
    need(source_reference_pins.get("driver_revision") == "R4", "source_reference_revision")
    _exact_count(source_reference_pins, "public_source_file_count", 31, "source_reference_public_count")
    _exact_count(source_reference_pins, "software_pin_count", 2, "source_reference_software_count")
    _exact_count(source_reference_pins, "planned_held_file_count", 33, "source_reference_planned_count")
    _exact_count(source_reference_pins, "official_c01_pass_count", 0, "source_reference_official_count")
    rows = _source_rows(pins)
    need(rows == _source_rows(source_reference_pins), "source_reference_payload_rows_mismatch")
    need(set(rows) == set(activation_map), "source_map_rows_mismatch")
    for relative, expected in rows.items():
        copied = exact(SOURCE_REFERENCE_DIR / "source" / relative, expected["sha256"])
        need(len(copied) == expected["bytes"], "source_copy_size")
        physical = exact(ROOT / relative, expected["sha256"])
        need(len(physical) == expected["bytes"], "physical_source_size")
        need(expected["sha256"] == activation_map[relative], "source_map_hash_mismatch")

    packet_files = _packet_file_map(pins)
    for relative, expected in packet_files.items():
        raw = exact(PACKET_DIR / relative, expected["sha256"], 2 * 1024 * 1024)
        need(len(raw) == expected["bytes"], "packet_file_size")
    expected_paths = set(packet_files) | {"pins.json"}
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


def _exact_count(value: dict, key: str, expected: int, code: str) -> None:
    actual = value.get(key)
    need(type(actual) is int and actual == expected, code)


def verify_independent_review(
    review_raw: bytes,
    *,
    expected_review_sha256: str,
    expected_packet_pins_sha256: str,
    driver_sha256: str,
) -> dict:
    """Verify the independent source/fake review without claiming a CUv2 hold."""

    need(_SHA256.fullmatch(expected_review_sha256), "review_pin_invalid")
    need(sha(review_raw) == expected_review_sha256, "review_hash_mismatch")
    review = parse_ascii_json(review_raw)
    need(type(review) is dict, "review_object_invalid")
    need(review.get("schema") == "iteration41.simnow.v18.root_driver.independent_review.r4b", "review_schema")
    need(review.get("driver_revision") == "R4B", "review_driver_revision")
    need(review.get("status") == "FINAL_INDEPENDENT_SOURCE_FAKE_REVIEW", "review_status")
    need(review.get("verdict") == "GO_SOURCE_FAKE_ONLY", "review_verdict")
    candidate = review.get("candidate")
    need(type(candidate) is dict, "review_candidate")
    need(candidate.get("driver_sha256") == driver_sha256, "review_driver_pin")
    need(candidate.get("driver_packet_pins_sha256") == expected_packet_pins_sha256, "review_packet_pin")
    need(candidate.get("source_reference_packet_id") == SOURCE_REFERENCE_PACKET_ID, "review_source_reference_id")
    need(candidate.get("source_reference_pins_sha256") == SOURCE_REFERENCE_PINS_SHA256, "review_source_reference_pins")
    need(candidate.get("v18_activation_packet_pins_sha256") == V18_PINS_SHA256, "review_v18_pin")
    need(candidate.get("wrapper_sha256") == WRAPPER_SHA256, "review_wrapper_pin")
    need(candidate.get("entry_sha256") == ENTRY_SHA256, "review_entry_pin")
    need(candidate.get("cuv2_sha256") == CUV2_SHA256, "review_cuv2_pin")
    need(candidate.get("r2_parent_diagnostic_sha256") == R2_DIAGNOSTIC_SHA256, "review_r2_diagnostic_pin")
    need(candidate.get("v18_source_map_delta_sha256") == V18_SOURCE_MAP_DELTA_SHA256, "review_v18_delta_pin")
    need(candidate.get("v18_wrapper_independent_review_sha256") == V18_REVIEW_SHA256, "review_v18_wrapper_review_pin")
    _exact_count(candidate, "public_source_file_count", 31, "review_source_count")
    _exact_count(candidate, "software_pin_count", 2, "review_software_count")
    _exact_count(candidate, "planned_held_file_count", 33, "review_planned_held_count")
    _exact_count(candidate, "physical_pins_verified", 33, "review_physical_pins_verified")
    _exact_count(review, "official_c01_pass_count", 0, "review_official_pass_count")
    need(review.get("actual_root_provider_native_acceptance") == "NOT_RUN", "review_actual_status")
    need(review.get("driver_executed") is False, "review_driver_executed")
    need(review.get("private_inputs_read") is False, "review_private_inputs")
    return review


def verify_root_readback(
    readback_raw: bytes,
    *,
    expected_readback_sha256: str,
    expected_review_sha256: str,
    expected_packet_pins_sha256: str,
    driver_sha256: str,
) -> dict:
    """Verify Root's physical source/software pin readback before any CUv2 entry."""

    need(_SHA256.fullmatch(expected_readback_sha256), "readback_pin_invalid")
    need(_SHA256.fullmatch(expected_review_sha256), "review_pin_invalid")
    need(sha(readback_raw) == expected_readback_sha256, "readback_hash_mismatch")
    readback = parse_ascii_json(readback_raw)
    need(type(readback) is dict, "readback_object_invalid")
    need(readback.get("schema") == "iteration41.simnow.v18.root_driver.pre_activation_readback.r4b", "readback_schema")
    need(readback.get("driver_revision") == "R4B", "readback_driver_revision")
    need(readback.get("status") == "PUBLIC_SOURCE_AND_INDEPENDENT_REVIEW_MATCH", "readback_status")
    need(readback.get("driver_sha256") == driver_sha256, "readback_driver_pin")
    need(readback.get("driver_packet_pins_sha256") == expected_packet_pins_sha256, "readback_packet_pin")
    need(readback.get("source_reference_packet_id") == SOURCE_REFERENCE_PACKET_ID, "readback_source_reference_id")
    need(readback.get("source_reference_pins_sha256") == SOURCE_REFERENCE_PINS_SHA256, "readback_source_reference_pins")
    need(readback.get("independent_review_sha256") == expected_review_sha256, "readback_review_pin")
    need(readback.get("v18_activation_packet_pins_sha256") == V18_PINS_SHA256, "readback_v18_pin")
    need(readback.get("wrapper_sha256") == WRAPPER_SHA256, "readback_wrapper_pin")
    need(readback.get("entry_sha256") == ENTRY_SHA256, "readback_entry_pin")
    need(readback.get("cuv2_sha256") == CUV2_SHA256, "readback_cuv2_pin")
    need(readback.get("r2_parent_diagnostic_sha256") == R2_DIAGNOSTIC_SHA256, "readback_r2_diagnostic_pin")
    need(readback.get("v18_source_map_delta_sha256") == V18_SOURCE_MAP_DELTA_SHA256, "readback_v18_delta_pin")
    need(readback.get("v18_wrapper_independent_review_sha256") == V18_REVIEW_SHA256, "readback_v18_review_pin")
    _exact_count(readback, "public_source_file_count", 31, "readback_source_count")
    _exact_count(readback, "public_source_files_verified", 31, "readback_source_verified")
    _exact_count(readback, "software_pin_count", 2, "readback_software_count")
    _exact_count(readback, "software_pins_verified", 2, "readback_software_verified")
    _exact_count(readback, "planned_held_file_count", 33, "readback_planned_held_count")
    _exact_count(readback, "physical_pins_verified", 33, "readback_physical_pins_verified")
    _exact_count(readback, "official_c01_pass_count", 0, "readback_official_pass_count")
    need(readback.get("held_scope_entered") is False, "readback_scope_entered")
    need(readback.get("held_source_map_verified") is False, "readback_source_map_held")
    need(readback.get("driver_executed") is False, "readback_driver_executed")
    need(readback.get("private_inputs_read") is False, "readback_private_inputs")
    need(readback.get("actual_root_provider_native_acceptance") == "NOT_RUN", "readback_actual_status")
    return readback


def verify_review_readback(
    readback_raw: bytes,
    review_raw: bytes,
    *,
    expected_readback_sha256: str,
    expected_review_sha256: str,
    expected_packet_pins_sha256: str,
    driver_sha256: str,
) -> tuple[dict, dict]:
    """Compatibility helper for tests; each gate has an independent verifier."""

    review = verify_independent_review(
        review_raw,
        expected_review_sha256=expected_review_sha256,
        expected_packet_pins_sha256=expected_packet_pins_sha256,
        driver_sha256=driver_sha256,
    )
    readback = verify_root_readback(
        readback_raw,
        expected_readback_sha256=expected_readback_sha256,
        expected_review_sha256=expected_review_sha256,
        expected_packet_pins_sha256=expected_packet_pins_sha256,
        driver_sha256=driver_sha256,
    )
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


def _new_result_state() -> dict[str, Any]:
    return {
        "independent_review_verified": False,
        "root_readback_verified": False,
        "cuv2_scope_entered": False,
        "held_source_map_verified": False,
        "observed_public_source_count": 0,
        "observed_software_pin_count": 0,
        "observed_held_file_count": 0,
        "wrapper_call_count": 0,
        "wrapper_projection_verified": False,
        "outer_cuv2_postverify_verified": False,
        "outer_cuv2_scope_closed": False,
    }


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
    result_state: dict | None = None,
    formal_authority=None,
    lease: HeldSourceLease | None = None,
    activation=None,
) -> dict:
    state = result_state if type(result_state) is dict else _new_result_state()
    if projection.get("certification") == "PASS" and not (
        outer_postverify is True and outer_closed is True
    ):
        projection = _blocked_projection("outer_cuv2_postverify_failed")
    if type(projection) is not dict:
        projection = _blocked_projection("root_driver_blocked")
    intended_public_count = 31
    intended_software_count = 2
    held_map_verified = state.get("held_source_map_verified") is True
    observed_public_count = state.get("observed_public_source_count", 0) if held_map_verified else 0
    observed_software_count = state.get("observed_software_pin_count", 0) if held_map_verified else 0
    observed_held_count = state.get("observed_held_file_count", 0) if held_map_verified else 0
    need_observed_count = (
        type(observed_public_count) is int
        and type(observed_software_count) is int
        and type(observed_held_count) is int
    )
    if not need_observed_count:
        observed_public_count = observed_software_count = observed_held_count = 0
        held_map_verified = False
    formal_pass = _formal_root_pass(
        projection,
        state=state,
        outer_postverify=outer_postverify,
        outer_closed=outer_closed,
        formal_authority=formal_authority,
        lease=lease,
        activation=activation,
    )
    if (
        formal_authority is _FORMAL_ACTIVATION_AUTHORITY
        and projection.get("certification") == "PASS"
        and not formal_pass
    ):
        projection = _blocked_projection("formal_root_acceptance_incomplete")
    state["outer_cuv2_postverify_verified"] = outer_postverify is True
    state["outer_cuv2_scope_closed"] = outer_closed is True
    return {
        "schema": "iteration41.simnow.v18.root_actual_driver.public_result.r4b",
        "classification": (
            "ROOT_RECEIPT_AUTHORIZED_C01_PASS"
            if formal_pass
            else "ROOT_PROFILE_RESULT_NOT_OFFICIAL_C01_ACCEPTANCE"
        ),
        "profile_result": dict(projection),
        "independent_review_verified": state.get("independent_review_verified") is True,
        "root_readback_verified": state.get("root_readback_verified") is True,
        "intended_public_source_count": intended_public_count,
        "intended_software_pin_count": intended_software_count,
        "intended_held_file_count": intended_public_count + intended_software_count,
        "cuv2_scope_entered": state.get("cuv2_scope_entered") is True,
        "held_source_map_verified": held_map_verified,
        "observed_public_source_count": observed_public_count,
        "observed_software_pin_count": observed_software_count,
        "observed_held_file_count": observed_held_count,
        "wrapper_call_count": state.get("wrapper_call_count", 0),
        "wrapper_projection_verified": state.get("wrapper_projection_verified") is True,
        "outer_cuv2_postverify_verified": outer_postverify is True,
        "outer_cuv2_scope_closed": outer_closed is True,
        "writes": 0,
        "official_c01_pass_count": 1 if formal_pass else 0,
        "formal_c01_pass": formal_pass,
        "private_capture_read_by_driver": False,
        "opaque_receipt_seen_by_driver": False,
        "late_private_capture_read": False,
    }


def _formal_root_pass(
    projection: dict,
    *,
    state: dict,
    outer_postverify: bool,
    outer_closed: bool,
    formal_authority,
    lease: HeldSourceLease | None,
    activation,
) -> bool:
    """Accept formal C01 only on the gated single actual Root wrapper path."""

    if formal_authority is not _FORMAL_ACTIVATION_AUTHORITY:
        return False
    if type(projection) is not dict or projection.get("certification") != "PASS":
        return False
    expected_projection = (
        projection.get("case_id") == "C01"
        and projection.get("mode") == "C01_NATIVE_TD_READ_V18"
        and projection.get("profile") == "C01_NATIVE_TD_READ_V18"
        and projection.get("reason") == "root_case_receipt_verified"
        and projection.get("write_policy") == "NO_WRITE"
        and type(projection.get("writes")) is int
        and projection.get("writes") == 0
        and projection.get("receipt_type") == "C01RootCaseResultReceipt"
        and projection.get("receipt_verified") is True
        and projection.get("source_closure_verified") is True
        and projection.get("root_postverify_verified") is True
        and type(projection.get("request_count")) is int
        and projection.get("request_count") == 8
        and type(projection.get("query_callback_count")) is int
        and 6 <= projection.get("query_callback_count") <= 8
        and type(projection.get("snapshot_count")) is int
        and projection.get("snapshot_count") == 2
        and type(projection.get("write_invocation_count")) is int
        and projection.get("write_invocation_count") == 0
        and _all_cleanup_true(projection)
    )
    if not expected_projection:
        return False
    if not (
        state.get("independent_review_verified") is True
        and state.get("root_readback_verified") is True
        and state.get("cuv2_scope_entered") is True
        and state.get("held_source_map_verified") is True
        and state.get("observed_public_source_count") == 31
        and type(state.get("observed_public_source_count")) is int
        and state.get("observed_software_pin_count") == 2
        and type(state.get("observed_software_pin_count")) is int
        and state.get("observed_held_file_count") == 33
        and type(state.get("observed_held_file_count")) is int
        and state.get("wrapper_call_count") == 1
        and type(state.get("wrapper_call_count")) is int
        and state.get("wrapper_projection_verified") is True
        and outer_postverify is True
        and outer_closed is True
        and lease is not None
        and lease.entered is True
        and lease.closed is True
        and lease.postverify_complete is True
        and lease.verify_held() is True
        and lease.public_source_count == 31
        and lease.software_pin_count == 2
        and not KEEPALIVE
    ):
        return False
    if activation is None:
        return False
    retained = getattr(activation, "_ROOT_RETAINED_UNRESOLVED_JOB_REFS", None)
    return retained is None or (type(retained) is list and not retained)


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
    result_state: dict | None = None,
    formal_authority=None,
) -> tuple[dict, HeldSourceLease, types.ModuleType | None]:
    """Run wrapper from exact held bytes and close CUv2 before any PASS is returned."""

    state = result_state if type(result_state) is dict else _new_result_state()
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
        state["cuv2_scope_entered"] = True
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
        state["held_source_map_verified"] = True
        state["observed_public_source_count"] = public_source_count
        state["observed_software_pin_count"] = software_pin_count
        state["observed_held_file_count"] = len(held_map)
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
            state["wrapper_call_count"] += 1

        projection, activation = invoke_fixed_wrapper_main(
            wrapper_raw,
            wrapper_path=wrapper_path,
            expected_wrapper_sha256=wrapper_sha256,
            module_name="_iteration41_simnow_c01_v18_root_activation_wrapper",
            on_module=remember_module,
            on_start=mark_wrapper_started,
        )
        state["wrapper_projection_verified"] = True
        if not _all_cleanup_true(projection):
            _retain_uncertain(lease, activation)
            return (
                _driver_result(
                    projection,
                    outer_postverify=False,
                    outer_closed=False,
                    result_state=state,
                    formal_authority=formal_authority,
                    lease=lease,
                    activation=activation,
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
                    result_state=state,
                    formal_authority=formal_authority,
                    lease=lease,
                    activation=activation,
                ),
                lease,
                activation,
            )
        return (
            _driver_result(
                projection,
                outer_postverify=lease.postverify_complete,
                outer_closed=lease.closed,
                result_state=state,
                formal_authority=formal_authority,
                lease=lease,
                activation=activation,
            ),
            lease,
            activation,
        )
    except BaseException:
        if lease is not None:
            if not wrapper_started and not lease.closed and not lease.exit_started and lease.verify_held():
                if lease.postverify_and_close(cuv2_path=cuv2_path, cuv2_sha256=cuv2_sha256):
                    state["outer_cuv2_postverify_verified"] = True
                    state["outer_cuv2_scope_closed"] = True
                else:
                    state["outer_cuv2_scope_closed"] = lease.closed is True
                    _retain_uncertain(lease, activation)
            else:
                state["outer_cuv2_scope_closed"] = lease.closed is True
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

    state = _new_result_state()
    try:
        require_unoptimized_runtime()
        args = _parse_args(list(sys.argv[1:] if argv is None else argv))
        need(_fixed_runtime_matches(), "fixed_runtime_required")
        need(PACKET_DIR.resolve(strict=True) == (EVIDENCE / PACKET_ID).resolve(strict=True), "driver_packet_path")
        pins, _pins_raw, driver_raw = verify_packet_and_sources(args.expected_packet_pins_sha256)
        driver_sha256 = sha(driver_raw)

        review_path = _public_evidence_path(args.independent_review)
        review_raw = exact(review_path, args.expected_independent_review_sha256, MAX_EVIDENCE_BYTES)
        verify_independent_review(
            review_raw,
            expected_review_sha256=args.expected_independent_review_sha256,
            expected_packet_pins_sha256=args.expected_packet_pins_sha256,
            driver_sha256=driver_sha256,
        )
        state["independent_review_verified"] = True

        readback_path = _public_evidence_path(args.root_readback)
        readback_raw = exact(readback_path, args.expected_root_readback_sha256, MAX_EVIDENCE_BYTES)
        verify_root_readback(
            readback_raw,
            expected_readback_sha256=args.expected_root_readback_sha256,
            expected_review_sha256=args.expected_independent_review_sha256,
            expected_packet_pins_sha256=args.expected_packet_pins_sha256,
            driver_sha256=driver_sha256,
        )
        state["root_readback_verified"] = True

        runtime_pins = pins["software_pins"]
        exact(Path(sys.executable), runtime_pins["C:/anaconda3/python.exe"])
        exact(Path("C:/anaconda3/python311.dll"), runtime_pins["C:/anaconda3/python311.dll"])
        need(not KEEPALIVE, "preexisting_uncertain_driver_refs")
        cuv2, cuv2_raw = _load_cuv2()
        v18_pins = parse_ascii_json(exact(PACKET_DIR / V18_PINS_COPY, V18_PINS_SHA256, 256 * 1024))
        source_map = v18_pins["public_source_pins"]
        ACTIVATION = None
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
            result_state=state,
            formal_authority=_FORMAL_ACTIVATION_AUTHORITY,
        )
        ACTIVATION = activation
        return result
    except DriverBlocked as error:
        return _driver_result(
            _blocked_projection(error.code),
            outer_postverify=state.get("outer_cuv2_postverify_verified") is True,
            outer_closed=state.get("outer_cuv2_scope_closed") is True,
            result_state=state,
        )
    except Exception:
        return _driver_result(
            _blocked_projection("root_driver_blocked"),
            outer_postverify=state.get("outer_cuv2_postverify_verified") is True,
            outer_closed=state.get("outer_cuv2_scope_closed") is True,
            result_state=state,
        )


def main(argv: list[str] | None = None) -> int:
    try:
        result = run_root_activation(argv)
    except DriverBlocked as error:
        result = _driver_result(
            _blocked_projection(error.code), outer_postverify=False, outer_closed=False
        )
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    except SystemExit:
        raise
    except Exception:
        result = _driver_result(
            _blocked_projection("root_driver_blocked"), outer_postverify=False, outer_closed=False
        )
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    else:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
    return 0 if result.get("formal_c01_pass") is True else 2


if __name__ == "__main__":
    try:
        require_unoptimized_runtime()
    except DriverBlocked as error:
        raise SystemExit(error.code)
    raise SystemExit(main())
