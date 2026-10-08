"""Closed R17 binding for the complete Optional16 R33 child activation."""

from __future__ import annotations

import hashlib
import importlib.machinery
import io
import json
from pathlib import Path
import sys
import types
from typing import Any, Dict, Mapping
import zipfile


ROOT = Path(r"D:\source_code\backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
R16_PACKET = EVIDENCE / "iteration41-optional16-r33-deadline-r15-successor-source-candidate-2026-10-07"
R16_REVIEW = EVIDENCE / "iteration41-optional16-r33-deadline-r15-successor-independent-review-2026-10-07"
R16_HELPER_PATH = ROOT / "scripts/iteration41_optional16_r33_deadline_r15_root_binding_r1.py"
R16_HELPER_SHA256 = "5b30bb4a1516fcc632362a8be9073b4dfbdaafe8476b8d73c5b300ca05433a75"
R16_PACKET_PINS = {
    "source-bundle.zip": "b68d48374b2fe88d21a633a24f4da58e932c441189f0c86465a241487aa60184",
    "source-index.json": "423074c1f0123cde9612e74bf5dec34ecdb000bd2bc90b41346def853ee56066",
    "source-pins.json": "b1a80e804f44e19adc0cbef555ee50c81a920853de6b6fe75e2bfea249e5d3a0",
    "checkpoint.json": "20ec128fb84436de65b1446c59df7727cf67e300c5667f02dff34e4e399aa1e1",
    "README.md": "7277e16543e7afdbf344d4228baa5510c62815a8d146ae009fd645712a9dc713",
    "qa/qa-summary.json": "247c17c2a55ed4be129d6655ed81fa0889595844bc2ad296cd0f77b6e678f513",
}
R16_REVIEW_PINS = {
    "review.json": "ad9ac104f313e4dddd0b975426697d2e290da972cd2c6ce6e2db7407f4b71d02",
    "review-bundle.zip": "bd0d9d319ebe8471a281a9670966a8aab11846f3698d54e57cec50e8c30021ca",
    "review-index.json": "820d87fca9d37ff97014375957aba052a5120de9e0375c365c8f533faf4661a4",
    "review-checkpoint.json": "8658685567370080ffd847415adbbd0c0672692f21e905ea87794303f1c6b0aa",
    "README.md": "2ec949a02051a7d934df7c903f2123931397a489c61170b33c07f29b1e713afb",
}
R17_PACKET = EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r17-source-candidate-2026-10-07"
R17_REVIEW = EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r17-independent-review-2026-10-07"
R17_SCHEMA = "iteration41.optional16.r33.deadline-r17.source-index.v1"
R17_REVIEW_SCHEMA = "iteration41.optional16.r33.deadline-r17.aggregate-successor-independent-review.v1"
R17_QA_SCHEMA = "iteration41.optional16.r33.deadline-r17.generated-qa-projection.v1"
R17_ROLE_PATHS = {
    "whole_call_supervisor": "scripts/iteration41_optional16_r33_whole_call_supervisor_r17.py",
    "invoke": "scripts/iteration41_optional16_r33_root_held_invoke_r17.py",
    "binding_helper": "scripts/iteration41_optional16_r33_deadline_r17_binding.py",
}
R17_TEST_PATH = "tests/unit/scripts/test_iteration41_optional16_r33_activation_r17_source_fake.py"
R17_ACTIVATION_SCHEMA = "iteration41.optional16.r33.whole-call.r17-child-activation.v1"
_PACKET_NAMES = frozenset({"source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json", "README.md", "qa/qa-summary.json"})
_REVIEW_NAMES = frozenset({"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json", "README.md"})


class BindingError(RuntimeError):
    """A pinned R16 or R17 source/review contract failed closed."""


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise BindingError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def _json(raw: bytes) -> Dict[str, Any]:
    def pairs(rows: list[tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in rows:
            _need(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError("json_invalid") from exc
    _need(type(value) is dict, "json_object_required")
    return value


def _safe_zip(raw: bytes) -> Dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            names = archive.namelist()
            _need(len(names) == len(set(names)), "duplicate_zip_member")
            files: Dict[str, bytes] = {}
            for name in names:
                _need(name and not name.startswith(("/", "\\")) and "\\" not in name, "unsafe_zip_path")
                _need(all(part not in ("", ".", "..") for part in name.split("/")), "unsafe_zip_path")
                _need(not name.endswith("/"), "zip_directory_rejected")
                files[name] = archive.read(name)
            return files
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise BindingError("zip_invalid") from exc


def _indexed_zip(raw: bytes, rows: Any) -> Dict[str, bytes]:
    archive = _safe_zip(raw)
    _need(type(rows) is list, "zip_index_rows_invalid")
    indexed: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        _need(type(row) is dict and set(row) == {"path", "sha256", "size_bytes"}, "zip_index_row_invalid")
        path = row["path"]
        _need(type(path) is str and path not in indexed, "zip_index_path_invalid")
        indexed[path] = row
    _need(set(indexed) == set(archive), "zip_index_member_set_mismatch")
    for path, body in archive.items():
        _need(indexed[path]["sha256"] == _sha(body) and indexed[path]["size_bytes"] == len(body), "zip_index_member_mismatch")
    return archive


def _read_pin(folder: Path, name: str, digest: str) -> bytes:
    raw = (folder / name).read_bytes()
    _need(_sha(raw) == digest, "pinned_file_mismatch:" + name)
    return raw


def _load_r16_helper(raw: bytes | None = None) -> Any:
    if raw is None:
        raw = R16_HELPER_PATH.read_bytes()
    _need(_sha(raw) == R16_HELPER_SHA256, "r16_helper_hash_mismatch")
    name = "_iteration41_optional16_r33_r16_frozen_binding_" + _sha(raw)[:12]
    prior = sys.modules.get(name)
    if prior is not None:
        return prior
    spec = importlib.machinery.ModuleSpec(name, loader=None, origin=str(R16_HELPER_PATH))
    module = types.ModuleType(name)
    module.__file__ = str(R16_HELPER_PATH)
    module.__package__ = ""
    module.__spec__ = spec
    sys.modules[name] = module
    exec(compile(raw, str(R16_HELPER_PATH), "exec", dont_inherit=True), module.__dict__)
    return module


def validate_r16_composite(
    source_files: Dict[str, bytes],
    packet_files: Dict[str, bytes],
    review_files: Dict[str, bytes],
) -> Dict[str, Any]:
    """Call the unchanged R16 aggregate validator on its own held inputs."""
    helper_raw = source_files.get(R16_HELPER_PATH.relative_to(ROOT).as_posix())
    _need(type(helper_raw) is bytes, "r16_helper_source_missing")
    helper = _load_r16_helper(helper_raw)
    binding = helper.load_binding()
    source_paths = set(helper.SUCCESSOR_ROLE_PATHS.values()) | {helper.SUCCESSOR_TEST_PATH}
    _need(set(source_files) == source_paths, "r16_source_member_set_invalid")
    _need(set(packet_files) == set(R16_PACKET_PINS), "r16_packet_member_set_invalid")
    _need(set(review_files) == set(R16_REVIEW_PINS), "r16_review_member_set_invalid")
    for name, digest in R16_PACKET_PINS.items():
        _need(_sha(packet_files[name]) == digest, "r16_packet_pin_mismatch:" + name)
    for name, digest in R16_REVIEW_PINS.items():
        _need(_sha(review_files[name]) == digest, "r16_review_pin_mismatch:" + name)
    validation = helper.validate_successor_artifacts(
        source_files,
        packet_files,
        review_files,
        packet_pins=dict(R16_PACKET_PINS),
        review_pins=dict(R16_REVIEW_PINS),
    )
    _need(validation.get("verdict") == "GO_SOURCE_FAKE_ONLY", "r16_composite_verdict_invalid")
    _need(validation.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16", "r16_composite_acceptance_invalid")
    return {"binding": binding, "helper": helper, "source_files": source_files, "packet_files": packet_files, "review_files": review_files, "validation": validation}


def load_r16_composite() -> Dict[str, Any]:
    """Run the unchanged R16 aggregate validator on its own exact inputs."""
    helper = _load_r16_helper()
    source_paths = set(helper.SUCCESSOR_ROLE_PATHS.values()) | {helper.SUCCESSOR_TEST_PATH}
    source_files = {path: (ROOT / path).read_bytes() for path in source_paths}
    packet_files = {name: _read_pin(R16_PACKET, name, digest) for name, digest in R16_PACKET_PINS.items()}
    review_files = {name: _read_pin(R16_REVIEW, name, digest) for name, digest in R16_REVIEW_PINS.items()}
    return validate_r16_composite(source_files, packet_files, review_files)


def _member_rows(source_files: Mapping[str, bytes], predecessor_paths: set[str]) -> list[Dict[str, Any]]:
    rows = []
    for path in sorted(source_files):
        body = source_files[path]
        rows.append({"path": path, "sha256": _sha(body), "size_bytes": len(body), "source_set": "r16-frozen-composite" if path in predecessor_paths else "r17-successor"})
    return rows


def _r16_record(composite: Mapping[str, Any]) -> Dict[str, Any]:
    binding = composite["binding"]
    return {
        "source_bundle_sha256": R16_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R16_PACKET_PINS["source-index.json"],
        "source_pins_sha256": R16_PACKET_PINS["source-pins.json"],
        "checkpoint_sha256": R16_PACKET_PINS["checkpoint.json"],
        "review_json_sha256": R16_REVIEW_PINS["review.json"],
        "review_bundle_sha256": R16_REVIEW_PINS["review-bundle.zip"],
        "review_index_sha256": R16_REVIEW_PINS["review-index.json"],
        "review_checkpoint_sha256": R16_REVIEW_PINS["review-checkpoint.json"],
        "review_readme_sha256": R16_REVIEW_PINS["README.md"],
        "selected_roles": dict(composite["helper"].SUCCESSOR_ROLE_PATHS),
        "test": {
            "path": composite["helper"].SUCCESSOR_TEST_PATH,
            "sha256": _sha(composite["source_files"][composite["helper"].SUCCESSOR_TEST_PATH]),
        },
        "source_fake_verdict": composite["validation"]["verdict"],
        "acceptance": composite["validation"]["acceptance"],
    }


def _r17_sources(composite: Mapping[str, Any], root: Path = ROOT) -> Dict[str, bytes]:
    r16 = dict(composite["source_files"])
    r17_paths = set(R17_ROLE_PATHS.values()) | {R17_TEST_PATH}
    r17 = {path: (root / path).read_bytes() for path in r17_paths}
    _need(set(r16).isdisjoint(r17), "r17_r16_source_path_collision")
    return {**r16, **r17}


def _qa_projection(source_files: Mapping[str, bytes], r16_record: Mapping[str, Any]) -> bytes:
    return _canonical({
        "schema": R17_QA_SCHEMA,
        "classification": "GENERATED_SOURCE_REVIEW_PROJECTION_NOT_AUTHOR_QA",
        "r16_composite": dict(r16_record),
        "r17_test_sha256": _sha(source_files[R17_TEST_PATH]),
        "author_qa_summary_blob_available": False,
        "actual_process_started": False,
        "root_map_created": False,
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
    })


def _expected_packet(source_files: Mapping[str, bytes], r16_record: Mapping[str, Any], qa: bytes, bundle: bytes, predecessor_paths: set[str]) -> Dict[str, bytes]:
    members = _member_rows(source_files, predecessor_paths)
    index = {
        "schema": R17_SCHEMA,
        "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "source_bundle_sha256": _sha(bundle),
        "source_bundle_member_count": len(source_files),
        "members": members,
        "r16_composite": dict(r16_record),
        "qa_projection_sha256": _sha(qa),
        "qa_projection_schema": R17_QA_SCHEMA,
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "root_map_created": False,
    }
    pins = {
        "schema": "iteration41.optional16.r33.deadline-r17.source-pins.v1",
        "source_bundle_sha256": _sha(bundle),
        "source_index_sha256": _sha(_canonical(index)),
        "member_sha256": {path: _sha(body) for path, body in source_files.items()},
        "r16_packet_review": dict(r16_record),
        "qa_projection_sha256": _sha(qa),
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
    }
    checkpoint = {
        "schema": "iteration41.optional16.r33.deadline-r17.source-checkpoint.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "source_bundle_sha256": _sha(bundle),
        "source_index_sha256": _sha(_canonical(index)),
        "source_pins_sha256": _sha(_canonical(pins)),
        "r16_review_json_sha256": R16_REVIEW_PINS["review.json"],
        "qa_projection_sha256": _sha(qa),
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "g1_accepted": False,
    }
    readme = (
        "# Optional16 R33 R17 activation binding source candidate\n\n"
        "This is sourcefake-only. It adds a closed whole-to-invoke payload that binds the frozen R16 driver, test, packet, and independent review before child activation. The frozen R16 aggregate validator is called only on R16 inputs. No native/provider process or root map was used.\n"
    ).encode("utf-8")
    return {
        "source-bundle.zip": bundle,
        "source-index.json": _canonical(index),
        "source-pins.json": _canonical(pins),
        "checkpoint.json": _canonical(checkpoint),
        "README.md": readme,
        "qa/qa-summary.json": qa,
    }


def build_source_packet(output: Path = R17_PACKET) -> Dict[str, Any]:
    _need(not output.exists(), "r17_packet_output_already_exists")
    composite = load_r16_composite()
    source_files = _r17_sources(composite)
    r16_record = _r16_record(composite)
    qa = _qa_projection(source_files, r16_record)
    bundle_io = io.BytesIO()
    with zipfile.ZipFile(bundle_io, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source_files):
            archive.writestr(path, source_files[path])
    files = _expected_packet(source_files, r16_record, qa, bundle_io.getvalue(), set(composite["source_files"]))
    output.mkdir(parents=True, exist_ok=False)
    for name, body in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(body)
    return {
        "schema": "iteration41.optional16.r33.deadline-r17.packet-builder.v1",
        "status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "packet_path": str(output),
        "source_bundle_sha256": _sha(files["source-bundle.zip"]),
        "source_index_sha256": _sha(files["source-index.json"]),
        "source_pins_sha256": _sha(files["source-pins.json"]),
        "checkpoint_sha256": _sha(files["checkpoint.json"]),
        "readme_sha256": _sha(files["README.md"]),
        "qa_projection_sha256": _sha(qa),
        "source_member_count": len(source_files),
        "r16_composite_verdict": composite["validation"]["verdict"],
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "root_map_created": False,
    }


def _packet_pins_valid(packet_pins: Mapping[str, str]) -> bool:
    return type(packet_pins) is dict and set(packet_pins) == _PACKET_NAMES and all(type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value) for value in packet_pins.values())


def _review_pins_valid(review_pins: Mapping[str, str]) -> bool:
    return type(review_pins) is dict and set(review_pins) == _REVIEW_NAMES and all(type(value) is str and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value) for value in review_pins.values())


def validate_successor_artifacts(
    source_files: Dict[str, bytes],
    packet_files: Dict[str, bytes],
    review_files: Dict[str, bytes],
    *,
    packet_pins: Dict[str, str],
    review_pins: Dict[str, str],
    r16_packet_files: Dict[str, bytes],
    r16_review_files: Dict[str, bytes],
) -> Dict[str, Any]:
    """Validate R17 packet/review and unchanged R16 composite independently."""
    r16_helper = _load_r16_helper()
    r16_paths = set(r16_helper.SUCCESSOR_ROLE_PATHS.values()) | {r16_helper.SUCCESSOR_TEST_PATH}
    r17_paths = set(R17_ROLE_PATHS.values()) | {R17_TEST_PATH}
    _need(type(source_files) is dict and set(source_files) == r16_paths | r17_paths, "r17_source_set_invalid")
    r16_sources = {path: source_files[path] for path in r16_paths}
    r17_sources = {path: source_files[path] for path in r17_paths}
    composite = validate_r16_composite(r16_sources, r16_packet_files, r16_review_files)
    _need(type(packet_files) is dict and set(packet_files) == _PACKET_NAMES, "r17_packet_member_set_invalid")
    _need(type(review_files) is dict and set(review_files) == _REVIEW_NAMES, "r17_review_member_set_invalid")
    _need(_packet_pins_valid(packet_pins) and _review_pins_valid(review_pins), "r17_pin_shape_invalid")
    for name, body in packet_files.items():
        _need(type(body) is bytes and _sha(body) == packet_pins[name], "r17_packet_pin_mismatch:" + name)
    for name, body in review_files.items():
        _need(type(body) is bytes and _sha(body) == review_pins[name], "r17_review_pin_mismatch:" + name)
    r16_record = _r16_record(composite)
    qa = _qa_projection(source_files, r16_record)
    _need(packet_files["qa/qa-summary.json"] == qa, "r17_qa_projection_mismatch")
    bundle = _safe_zip(packet_files["source-bundle.zip"])
    _need(bundle == source_files, "r17_bundle_source_mismatch")
    expected_packet = _expected_packet(source_files, r16_record, qa, packet_files["source-bundle.zip"], r16_paths)
    _need(packet_files == expected_packet, "r17_packet_semantics_invalid")
    candidate = {
        "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
        "source_index_sha256": _sha(packet_files["source-index.json"]),
        "source_pins_sha256": _sha(packet_files["source-pins.json"]),
        "checkpoint_sha256": _sha(packet_files["checkpoint.json"]),
        "r16_composite": r16_record,
        "qa_projection_sha256": _sha(qa),
    }
    source_bindings = [
        {"path": path, "sha256": _sha(body), "size_bytes": len(body), "source_set": "r16-frozen-composite" if path in r16_paths else "r17-successor"}
        for path, body in sorted(source_files.items())
    ]
    review = _json(review_files["review.json"])
    report = review.get("independent_test_report")
    expected_checks = {
        "unchanged_r16_composite_validator_passed": True,
        "complete_driver_activation_payload_bound": True,
        "whole_child_propagates_all_driver_pins": True,
        "invoke_activation_readiness_passed": True,
        "no_native_provider_or_actual_run": True,
        "100_plus_5_deadline_contract_preserved": True,
    }
    _need(
        type(review) is dict
        and set(review) == {"schema", "verdict", "acceptance", "strict_cases_passed", "case_pass", "registry_admission", "candidate", "source_bindings", "source_fake_checks", "independent_test_report", "limitations"}
        and review.get("schema") == R17_REVIEW_SCHEMA
        and review.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and review.get("strict_cases_passed") == 0
        and review.get("case_pass") is False
        and review.get("registry_admission") is False
        and review.get("candidate") == candidate
        and review.get("source_bindings") == source_bindings
        and review.get("source_fake_checks") == expected_checks
        and type(review.get("limitations")) is list
        and type(report) is dict
        and set(report) == {"source_test_sha256", "passed", "failed", "skipped"}
        and report.get("source_test_sha256") == _sha(source_files[R17_TEST_PATH])
        and type(report.get("passed")) is int and report["passed"] > 0
        and report.get("failed") == 0 and report.get("skipped") == 0,
        "r17_review_semantics_invalid",
    )
    review_index = _json(review_files["review-index.json"])
    review_checkpoint = _json(review_files["review-checkpoint.json"])
    _need(
        type(review_index) is dict
        and review_index.get("schema") == "iteration41.optional16.r33.deadline-r17.aggregate-review-index.v1"
        and review_index.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review_index.get("review_json_sha256") == _sha(review_files["review.json"])
        and review_index.get("review_bundle_sha256") == _sha(review_files["review-bundle.zip"])
        and review_index.get("source_bundle_sha256") == _sha(packet_files["source-bundle.zip"])
        and review_index.get("source_index_sha256") == _sha(packet_files["source-index.json"])
        and review_index.get("source_pins_sha256") == _sha(packet_files["source-pins.json"])
        and review_index.get("source_bindings") == source_bindings
        and review_index.get("independent_test_report") == report
        and review_index.get("strict_cases_passed") == 0
        and review_index.get("optional16_real_accepted") == 0
        and review_index.get("actual_process_started") is False
        and review_index.get("root_map_created") is False,
        "r17_review_index_invalid",
    )
    expected_review_bundle = {
        "review.json": review_files["review.json"],
        "README.md": review_files["README.md"],
        "qa/qa-summary.json": qa,
        **{f"inputs/r17/{name}": body for name, body in packet_files.items()},
        **{f"inputs/r16/packet/{name}": body for name, body in r16_packet_files.items()},
        **{f"inputs/r16/review/{name}": body for name, body in r16_review_files.items()},
    }
    reviewed_bundle = _indexed_zip(review_files["review-bundle.zip"], review_index.get("bundle_members"))
    _need(reviewed_bundle == expected_review_bundle, "r17_review_bundle_bytes_invalid")
    expected_checkpoint = {
        "schema": "iteration41.optional16.r33.deadline-r17.aggregate-review-checkpoint.v1",
        "verdict": "GO_SOURCE_FAKE_ONLY",
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "review_json_sha256": _sha(review_files["review.json"]),
        "review_bundle_sha256": _sha(review_files["review-bundle.zip"]),
        "review_index_sha256": _sha(review_files["review-index.json"]),
        "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
        "source_index_sha256": _sha(packet_files["source-index.json"]),
        "source_pins_sha256": _sha(packet_files["source-pins.json"]),
        "r16_review_json_sha256": R16_REVIEW_PINS["review.json"],
        "independent_test_report": report,
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "root_map_created": False,
    }
    _need(review_checkpoint == expected_checkpoint, "r17_review_checkpoint_invalid")
    return {
        "schema": R17_REVIEW_SCHEMA,
        "verdict": "GO_SOURCE_FAKE_ONLY",
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "candidate": candidate,
        "source_bindings": source_bindings,
        "independent_test_report": report,
        "r16_composite_verdict": composite["validation"]["verdict"],
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
    }


def _read_directory(folder: Path, names: set[str]) -> Dict[str, bytes]:
    return {name: (folder / name).read_bytes() for name in names}


def validate_paths(packet: Path = R17_PACKET, review: Path = R17_REVIEW) -> Dict[str, Any]:
    composite = load_r16_composite()
    sources = _r17_sources(composite)
    packet_files = _read_directory(packet, set(_PACKET_NAMES))
    review_files = _read_directory(review, set(_REVIEW_NAMES))
    packet_pins = {name: _sha(body) for name, body in packet_files.items()}
    review_pins = {name: _sha(body) for name, body in review_files.items()}
    return validate_successor_artifacts(sources, packet_files, review_files, packet_pins=packet_pins, review_pins=review_pins, r16_packet_files=composite["packet_files"], r16_review_files=composite["review_files"])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args == ["--source-check"]:
            result = load_r16_composite()
            print(json.dumps({"schema": "iteration41.optional16.r33.deadline-r17.binding.v1", "status": "R16_COMPOSITE_VERIFIED_R17_SOURCE_ONLY", "r16_verdict": result["validation"]["verdict"], "r16_source_member_count": len(result["source_files"]), "r17_packet_present": R17_PACKET.exists(), "r17_review_present": R17_REVIEW.exists(), "strict_cases_passed": 0, "optional16_real_accepted": 0}, sort_keys=True))
            return 0
        if args == ["--build-source-packet"]:
            print(json.dumps(build_source_packet(), sort_keys=True))
            return 0
        print(json.dumps({"schema": "iteration41.optional16.r33.deadline-r17.binding.v1", "status": "PREPARED_UNSET", "activation_enabled": False, "strict_cases_passed": 0}, sort_keys=True))
        return 2
    except (BindingError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"schema": "iteration41.optional16.r33.deadline-r17.binding.v1", "status": "BLOCKED", "reason": str(exc) if type(exc) is BindingError else "binding_failed", "strict_cases_passed": 0, "optional16_real_accepted": 0}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
