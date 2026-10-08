"""Closed aggregate binding for the R18 Optional16 R33 activation successor."""

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
R16_HELPER_PATH = ROOT / "scripts/iteration41_optional16_r33_deadline_r15_root_binding_r1.py"
R16_HELPER_SHA256 = "5b30bb4a1516fcc632362a8be9073b4dfbdaafe8476b8d73c5b300ca05433a75"
R17_HELPER_PATH = ROOT / "scripts/iteration41_optional16_r33_deadline_r17_binding.py"
R17_HELPER_SHA256 = "f4526bd40433fb74fe0c3d360c863d07e5613924a9bba243611026c058b442bd"

R16_PACKET = EVIDENCE / "iteration41-optional16-r33-deadline-r15-successor-source-candidate-2026-10-07"
R16_PACKET_PINS = {
    "source-bundle.zip": "b68d48374b2fe88d21a633a24f4da58e932c441189f0c86465a241487aa60184",
    "source-index.json": "423074c1f0123cde9612e74bf5dec34ecdb000bd2bc90b41346def853ee56066",
    "source-pins.json": "b1a80e804f44e19adc0cbef555ee50c81a920853de6b6fe75e2bfea249e5d3a0",
    "checkpoint.json": "20ec128fb84436de65b1446c59df7727cf67e300c5667f02dff34e4e399aa1e1",
    "README.md": "7277e16543e7afdbf344d4228baa5510c62815a8d146ae009fd645712a9dc713",
    "qa/qa-summary.json": "247c17c2a55ed4be129d6655ed81fa0889595844bc2ad296cd0f77b6e678f513",
}
R16_REVIEW = EVIDENCE / "iteration41-optional16-r33-deadline-r15-successor-independent-review-2026-10-07"
R16_REVIEW_PINS = {
    "review.json": "ad9ac104f313e4dddd0b975426697d2e290da972cd2c6ce6e2db7407f4b71d02",
    "review-bundle.zip": "bd0d9d319ebe8471a281a9670966a8aab11846f3698d54e57cec50e8c30021ca",
    "review-index.json": "820d87fca9d37ff97014375957aba052a5120de9e0375c365c8f533faf4661a4",
    "review-checkpoint.json": "8658685567370080ffd847415adbbd0c0672692f21e905ea87794303f1c6b0aa",
    "README.md": "2ec949a02051a7d934df7c903f2123931397a489c61170b33c07f29b1e713afb",
}
R17_PACKET = EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r17-source-candidate-2026-10-07"
R17_PACKET_PINS = {
    "source-bundle.zip": "54719e0ff6137eb19f1d114fa921dd51acad7bbb12217ec81d433b43e39ae61f",
    "source-index.json": "57ff1f5d4480f455444d5b1c827a3d9d4876fe2bb5b3d4492e52d040f171a903",
    "source-pins.json": "f7c1ee066a537b79e0cadd35527dd9614eeb860ff3be276245608b1346634b18",
    "checkpoint.json": "53e1cfe0b42650aa768a1b84812bf4eaa3d65992722839fbdd760ccdf092d6c1",
    "README.md": "7458c71d822ac2bc2f9e1d95c907e533ece5cf3d5b9ca6262f9fe242f462ec05",
    "qa/qa-summary.json": "c9c13a0867c6445c46eed19e59d89959ce58a3ef0c4677296adf4846991f9ceb",
}
R17_REVIEW = EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r17-independent-review-2026-10-07"
R17_REVIEW_PINS = {
    "review.json": "0731c95d7dcf5447a33aad952a466fa5bfcceed09287ede4a44a38ae0202b4f5",
    "review-bundle.zip": "0c81b9f5534650586bc00ba46c29ad4d5c141d6c0933e3e72e313d5bacfccda8",
    "review-index.json": "7f75adc01c0867da93062137fbd8cc54e25c22caebd00f5a5ddcc018bb14a0e4",
    "review-checkpoint.json": "d361d19c2cd2f3b918bc49feced6bf0b402fe1b71fe3c4093732b10107466c69",
    "README.md": "defe2616d4cfa044c7545e91bba04193d360ed591e72b9ebd05a561c54116e5e",
}

R18_PACKET = EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r18-source-candidate-2026-10-07"
R18_REVIEW = EVIDENCE / "iteration41-optional16-r33-whole-root-activation-r18-independent-review-2026-10-07"
R18_SCHEMA = "iteration41.optional16.r33.deadline-r18.source-index.v1"
R18_REVIEW_SCHEMA = "iteration41.optional16.r33.deadline-r18.aggregate-successor-independent-review.v1"
R18_QA_SCHEMA = "iteration41.optional16.r33.deadline-r18.generated-qa-projection.v1"
R18_ROLE_PATHS = {
    "binding_helper": "scripts/iteration41_optional16_r33_deadline_r18_binding.py",
    "driver": "scripts/iteration41_optional16_r33_root_driver_r18.py",
    "invoke": "scripts/iteration41_optional16_r33_root_held_invoke_r18.py",
    "whole_call_supervisor": "scripts/iteration41_optional16_r33_whole_call_supervisor_r18.py",
}
R18_TEST_PATH = "tests/unit/scripts/test_iteration41_optional16_r33_activation_r18_source_fake.py"
R18_ACTIVATION_SCHEMA = "iteration41.optional16.r33.whole-call.r18-child-activation.v1"
PACKET_NAMES = frozenset({"source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json", "README.md", "qa/qa-summary.json"})
REVIEW_NAMES = frozenset({"review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json", "README.md"})


class BindingError(RuntimeError):
    """A frozen predecessor or R18 aggregate binding failed closed."""


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
            result: Dict[str, bytes] = {}
            for name in names:
                _need(name and not name.startswith(("/", "\\")) and "\\" not in name, "unsafe_zip_path")
                _need(all(part not in ("", ".", "..") for part in name.split("/")), "unsafe_zip_path")
                _need(not name.endswith("/"), "zip_directory_rejected")
                result[name] = archive.read(name)
            return result
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise BindingError("zip_invalid") from exc


def _indexed_zip(raw: bytes, rows: Any) -> Dict[str, bytes]:
    contents = _safe_zip(raw)
    _need(type(rows) is list, "zip_index_rows_invalid")
    indexed: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        _need(type(row) is dict and set(row) == {"path", "sha256", "size_bytes"}, "zip_index_row_invalid")
        _need(type(row["path"]) is str and row["path"] not in indexed, "zip_index_path_invalid")
        indexed[row["path"]] = row
    _need(set(indexed) == set(contents), "zip_index_member_set_mismatch")
    for path, body in contents.items():
        _need(indexed[path]["sha256"] == _sha(body) and indexed[path]["size_bytes"] == len(body), "zip_index_member_mismatch")
    return contents


def _read_pin(folder: Path, name: str, digest: str) -> bytes:
    raw = (folder / name).read_bytes()
    _need(_sha(raw) == digest, "pinned_file_mismatch:" + name)
    return raw


def _load_declared(raw: bytes, path: Path, name: str) -> Any:
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.machinery.ModuleSpec(name, loader=None, origin=str(path))
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__spec__ = spec
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def _r16_paths(r16_helper: Any) -> set[str]:
    return set(r16_helper.SUCCESSOR_ROLE_PATHS.values()) | {r16_helper.SUCCESSOR_TEST_PATH}


def _r17_paths(r17_helper: Any) -> set[str]:
    return set(r17_helper.R17_ROLE_PATHS.values()) | {r17_helper.R17_TEST_PATH}


def _r18_paths() -> set[str]:
    return set(R18_ROLE_PATHS.values()) | {R18_TEST_PATH}


def _load_r17_helper(source_files: Mapping[str, bytes]) -> Any:
    raw = source_files.get(R17_HELPER_PATH.relative_to(ROOT).as_posix())
    _need(type(raw) is bytes and _sha(raw) == R17_HELPER_SHA256, "r17_helper_source_mismatch")
    return _load_declared(raw, R17_HELPER_PATH, "_iteration41_optional16_r33_r17_frozen_binding")


def _load_r16_inputs(source_files: Mapping[str, bytes], packet_files: Dict[str, bytes], review_files: Dict[str, bytes]) -> Dict[str, Any]:
    r17_helper = _load_r17_helper(source_files)
    r16_helper_raw = source_files.get(R16_HELPER_PATH.relative_to(ROOT).as_posix())
    _need(type(r16_helper_raw) is bytes and _sha(r16_helper_raw) == R16_HELPER_SHA256, "r16_helper_source_mismatch")
    r16_helper = _load_declared(r16_helper_raw, R16_HELPER_PATH, "_iteration41_optional16_r33_r16_frozen_binding")
    r16_source_paths = _r16_paths(r16_helper)
    _need(set(packet_files) == set(R16_PACKET_PINS), "r16_packet_shape_invalid")
    _need(set(review_files) == set(R16_REVIEW_PINS), "r16_review_shape_invalid")
    for name, digest in R16_PACKET_PINS.items():
        _need(_sha(packet_files[name]) == digest, "r16_packet_pin_mismatch:" + name)
    for name, digest in R16_REVIEW_PINS.items():
        _need(_sha(review_files[name]) == digest, "r16_review_pin_mismatch:" + name)
    validation = r17_helper.validate_r16_composite(
        {path: source_files[path] for path in r16_source_paths}, packet_files, review_files
    )
    _need(validation.get("validation", {}).get("verdict") == "GO_SOURCE_FAKE_ONLY", "r16_verdict_invalid")
    return {"helper": r17_helper, "r16_helper": r16_helper, "source_paths": r16_source_paths, "validation": validation}


def _load_predecessors(
    source_files: Dict[str, bytes],
    r16_packet_files: Dict[str, bytes],
    r16_review_files: Dict[str, bytes],
    r17_packet_files: Dict[str, bytes],
    r17_review_files: Dict[str, bytes],
) -> Dict[str, Any]:
    _need(type(source_files) is dict, "source_map_invalid")
    predecessor = _load_r16_inputs(source_files, r16_packet_files, r16_review_files)
    r17_helper = predecessor["helper"]
    r17_source_paths = _r17_paths(r17_helper)
    _need(set(r17_packet_files) == set(R17_PACKET_PINS), "r17_packet_shape_invalid")
    _need(set(r17_review_files) == set(R17_REVIEW_PINS), "r17_review_shape_invalid")
    for name, digest in R17_PACKET_PINS.items():
        _need(_sha(r17_packet_files[name]) == digest, "r17_packet_pin_mismatch:" + name)
    for name, digest in R17_REVIEW_PINS.items():
        _need(_sha(r17_review_files[name]) == digest, "r17_review_pin_mismatch:" + name)
    r16_r17_paths = predecessor["source_paths"] | r17_source_paths
    r16_r17_sources = {path: source_files[path] for path in r16_r17_paths}
    r17_validation = r17_helper.validate_successor_artifacts(
        r16_r17_sources,
        r17_packet_files,
        r17_review_files,
        packet_pins=dict(R17_PACKET_PINS),
        review_pins=dict(R17_REVIEW_PINS),
        r16_packet_files=r16_packet_files,
        r16_review_files=r16_review_files,
    )
    _need(
        r17_validation.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and r17_validation.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16",
        "r17_composite_verdict_invalid",
    )
    r16_result = predecessor["validation"]
    r16_record = r17_helper._r16_record(r16_result)
    r17_record = {
        "source_bundle_sha256": R17_PACKET_PINS["source-bundle.zip"],
        "source_index_sha256": R17_PACKET_PINS["source-index.json"],
        "source_pins_sha256": R17_PACKET_PINS["source-pins.json"],
        "checkpoint_sha256": R17_PACKET_PINS["checkpoint.json"],
        "review_json_sha256": R17_REVIEW_PINS["review.json"],
        "review_bundle_sha256": R17_REVIEW_PINS["review-bundle.zip"],
        "review_index_sha256": R17_REVIEW_PINS["review-index.json"],
        "review_checkpoint_sha256": R17_REVIEW_PINS["review-checkpoint.json"],
        "review_readme_sha256": R17_REVIEW_PINS["README.md"],
        "candidate": r17_validation["candidate"],
        "source_fake_verdict": r17_validation["verdict"],
        "acceptance": r17_validation["acceptance"],
        "independent_test_report": r17_validation["independent_test_report"],
    }
    return {
        **predecessor,
        "r17_source_paths": r17_source_paths,
        "r16_r17_paths": r16_r17_paths,
        "r16_record": r16_record,
        "r17_record": r17_record,
        "r17_validation": r17_validation,
        "r16_packet_files": r16_packet_files,
        "r16_review_files": r16_review_files,
        "r17_packet_files": r17_packet_files,
        "r17_review_files": r17_review_files,
    }


def _source_rows(source_files: Mapping[str, bytes], predecessor: Mapping[str, Any]) -> list[Dict[str, Any]]:
    r16_paths = predecessor["source_paths"]
    r17_paths = predecessor["r17_source_paths"]
    rows = []
    for path in sorted(source_files):
        body = source_files[path]
        source_set = "r16-frozen-composite" if path in r16_paths else "r17-frozen-composite" if path in r17_paths else "r18-successor"
        rows.append({"path": path, "sha256": _sha(body), "size_bytes": len(body), "source_set": source_set})
    return rows


def _r18_record(predecessor: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "r16_composite": dict(predecessor["r16_record"]),
        "r17_composite": dict(predecessor["r17_record"]),
        "r16_source_fake_verdict": predecessor["validation"]["validation"]["verdict"],
        "r17_source_fake_verdict": predecessor["r17_validation"]["verdict"],
        "r17_acceptance": predecessor["r17_validation"]["acceptance"],
    }


def _qa_projection(source_files: Mapping[str, bytes], record: Mapping[str, Any]) -> bytes:
    return _canonical({
        "schema": R18_QA_SCHEMA,
        "classification": "GENERATED_SOURCE_REVIEW_PROJECTION_NOT_AUTHOR_QA",
        "predecessor_composites": dict(record),
        "r18_test_sha256": _sha(source_files[R18_TEST_PATH]),
        "author_qa_summary_blob_available": False,
        "actual_process_started": False,
        "root_map_created": False,
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
    })


def _expected_packet(
    source_files: Mapping[str, bytes],
    record: Mapping[str, Any],
    qa: bytes,
    bundle: bytes,
    predecessor: Mapping[str, Any],
) -> Dict[str, bytes]:
    members = _source_rows(source_files, predecessor)
    index = {
        "schema": R18_SCHEMA,
        "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "source_bundle_sha256": _sha(bundle),
        "source_bundle_member_count": len(source_files),
        "members": members,
        "predecessor_composites": dict(record),
        "qa_projection_sha256": _sha(qa),
        "qa_projection_schema": R18_QA_SCHEMA,
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "root_map_created": False,
    }
    pins = {
        "schema": "iteration41.optional16.r33.deadline-r18.source-pins.v1",
        "source_bundle_sha256": _sha(bundle),
        "source_index_sha256": _sha(_canonical(index)),
        "member_sha256": {path: _sha(body) for path, body in source_files.items()},
        "predecessor_composites": dict(record),
        "qa_projection_sha256": _sha(qa),
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
    }
    checkpoint = {
        "schema": "iteration41.optional16.r33.deadline-r18.source-checkpoint.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "source_bundle_sha256": _sha(bundle),
        "source_index_sha256": _sha(_canonical(index)),
        "source_pins_sha256": _sha(_canonical(pins)),
        "r16_review_json_sha256": R16_REVIEW_PINS["review.json"],
        "r17_review_json_sha256": R17_REVIEW_PINS["review.json"],
        "qa_projection_sha256": _sha(qa),
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "g1_accepted": False,
    }
    readme = (
        "# Optional16 R33 R18 activation source candidate\n\n"
        "This sourcefake-only successor binds the frozen R16 aggregate, the independently reviewed R17 aggregate, and the R18 driver activation repair. The R33 review retains its four-file pin map and separately pinned README. The R18 driver map validates the four R33 files and the separate README hash. No native/provider process or actual run was used.\n"
    ).encode("utf-8")
    return {
        "source-bundle.zip": bundle,
        "source-index.json": _canonical(index),
        "source-pins.json": _canonical(pins),
        "checkpoint.json": _canonical(checkpoint),
        "README.md": readme,
        "qa/qa-summary.json": qa,
    }


def _source_files_from_disk(predecessor: Mapping[str, Any], root: Path = ROOT) -> Dict[str, bytes]:
    paths = predecessor["r16_r17_paths"] | _r18_paths()
    return {path: (root / path).read_bytes() for path in paths}


def build_source_packet(output: Path = R18_PACKET) -> Dict[str, Any]:
    _need(not output.exists(), "r18_packet_output_already_exists")
    r17_module_raw = R17_HELPER_PATH.read_bytes()
    _need(_sha(r17_module_raw) == R17_HELPER_SHA256, "r17_helper_hash_mismatch")
    r17_helper = _load_declared(r17_module_raw, R17_HELPER_PATH, "_iteration41_optional16_r33_r17_frozen_binding")
    r16_helper = r17_helper._load_r16_helper()
    r16_paths = _r16_paths(r16_helper)
    r17_paths = _r17_paths(r17_helper)
    r16_sources = {path: (ROOT / path).read_bytes() for path in r16_paths}
    r17_paths_all = r16_paths | r17_paths
    combined_r16_r17_sources = {path: (ROOT / path).read_bytes() for path in r17_paths_all}
    r16_packet_files = {name: _read_pin(R16_PACKET, name, digest) for name, digest in R16_PACKET_PINS.items()}
    r16_review_files = {name: _read_pin(R16_REVIEW, name, digest) for name, digest in R16_REVIEW_PINS.items()}
    r17_packet_files = {name: _read_pin(R17_PACKET, name, digest) for name, digest in R17_PACKET_PINS.items()}
    r17_review_files = {name: _read_pin(R17_REVIEW, name, digest) for name, digest in R17_REVIEW_PINS.items()}
    predecessor = _load_predecessors(
        combined_r16_r17_sources,
        r16_packet_files,
        r16_review_files,
        r17_packet_files,
        r17_review_files,
    )
    source_files = {**combined_r16_r17_sources, **{path: (ROOT / path).read_bytes() for path in _r18_paths()}}
    record = _r18_record(predecessor)
    qa = _qa_projection(source_files, record)
    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source_files):
            archive.writestr(path, source_files[path])
    files = _expected_packet(source_files, record, qa, archive_bytes.getvalue(), predecessor)
    output.mkdir(parents=True, exist_ok=False)
    for name, body in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(body)
    return {
        "schema": "iteration41.optional16.r33.deadline-r18.packet-builder.v1",
        "status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "packet_path": str(output),
        "source_bundle_sha256": _sha(files["source-bundle.zip"]),
        "source_index_sha256": _sha(files["source-index.json"]),
        "source_pins_sha256": _sha(files["source-pins.json"]),
        "checkpoint_sha256": _sha(files["checkpoint.json"]),
        "readme_sha256": _sha(files["README.md"]),
        "qa_projection_sha256": _sha(qa),
        "source_member_count": len(source_files),
        "r16_verdict": predecessor["validation"]["validation"]["verdict"],
        "r17_verdict": predecessor["r17_validation"]["verdict"],
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "root_map_created": False,
    }


def _hash_map_valid(value: Mapping[str, str], names: frozenset[str]) -> bool:
    return type(value) is dict and set(value) == set(names) and all(
        type(digest) is str and len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest)
        for digest in value.values()
    )


def _review_bundle_files(
    review_files: Mapping[str, bytes],
    qa: bytes,
    packet_files: Mapping[str, bytes],
    predecessor: Mapping[str, Any],
) -> Dict[str, bytes]:
    return {
        "review.json": review_files["review.json"],
        "README.md": review_files["README.md"],
        "qa/qa-summary.json": qa,
        **{f"inputs/r18/{name}": body for name, body in packet_files.items()},
        **{f"inputs/r17/packet/{name}": body for name, body in predecessor["r17_packet_files"].items()},
        **{f"inputs/r17/review/{name}": body for name, body in predecessor["r17_review_files"].items()},
        **{f"inputs/r16/packet/{name}": body for name, body in predecessor["r16_packet_files"].items()},
        **{f"inputs/r16/review/{name}": body for name, body in predecessor["r16_review_files"].items()},
    }


def validate_successor_artifacts(
    source_files: Dict[str, bytes],
    packet_files: Dict[str, bytes],
    review_files: Dict[str, bytes],
    *,
    packet_pins: Dict[str, str],
    review_pins: Dict[str, str],
    r16_packet_files: Dict[str, bytes],
    r16_review_files: Dict[str, bytes],
    r17_packet_files: Dict[str, bytes],
    r17_review_files: Dict[str, bytes],
) -> Dict[str, Any]:
    """Validate R16, R17, then R18 on three distinct aggregate contracts."""
    r17_helper = _load_r17_helper(source_files)
    r16_helper = r17_helper._load_r16_helper(source_files[R16_HELPER_PATH.relative_to(ROOT).as_posix()])
    r16_paths = _r16_paths(r16_helper)
    r17_paths = _r17_paths(r17_helper)
    r18_paths = _r18_paths()
    _need(type(source_files) is dict and set(source_files) == r16_paths | r17_paths | r18_paths, "r18_source_member_set_invalid")
    _need(all(type(body) is bytes for body in source_files.values()), "r18_source_bytes_invalid")
    _need(type(packet_files) is dict and set(packet_files) == PACKET_NAMES, "r18_packet_member_set_invalid")
    _need(type(review_files) is dict and set(review_files) == REVIEW_NAMES, "r18_review_member_set_invalid")
    _need(_hash_map_valid(packet_pins, PACKET_NAMES) and _hash_map_valid(review_pins, REVIEW_NAMES), "r18_pin_map_shape_invalid")
    for name, body in packet_files.items():
        _need(type(body) is bytes and _sha(body) == packet_pins[name], "r18_packet_pin_mismatch:" + name)
    for name, body in review_files.items():
        _need(type(body) is bytes and _sha(body) == review_pins[name], "r18_review_pin_mismatch:" + name)

    predecessor = _load_predecessors(
        {path: source_files[path] for path in r16_paths | r17_paths},
        r16_packet_files,
        r16_review_files,
        r17_packet_files,
        r17_review_files,
    )
    record = _r18_record(predecessor)
    qa = _qa_projection(source_files, record)
    _need(packet_files["qa/qa-summary.json"] == qa, "r18_qa_projection_mismatch")
    bundle = _safe_zip(packet_files["source-bundle.zip"])
    _need(bundle == source_files, "r18_bundle_source_mismatch")
    expected_packet = _expected_packet(source_files, record, qa, packet_files["source-bundle.zip"], predecessor)
    _need(packet_files == expected_packet, "r18_packet_semantics_invalid")

    candidate = {
        "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
        "source_index_sha256": _sha(packet_files["source-index.json"]),
        "source_pins_sha256": _sha(packet_files["source-pins.json"]),
        "checkpoint_sha256": _sha(packet_files["checkpoint.json"]),
        "predecessor_composites": record,
        "qa_projection_sha256": _sha(qa),
    }
    source_bindings = _source_rows(source_files, predecessor)
    report = _json(review_files["review.json"]).get("independent_test_report")
    checks = {
        "unchanged_r16_composite_validator_passed": True,
        "independently_reviewed_r17_composite_validator_passed": True,
        "r33_four_pin_map_and_separate_readme_preserved": True,
        "r18_driver_expected_pins_and_review_validator_passed": True,
        "complete_child_driver_payload_and_readiness_passed": True,
        "no_native_provider_or_actual_run": True,
        "100_plus_5_deadline_contract_preserved": True,
    }
    review = _json(review_files["review.json"])
    _need(
        set(review) == {"schema", "verdict", "acceptance", "strict_cases_passed", "case_pass", "registry_admission", "candidate", "source_bindings", "source_fake_checks", "independent_test_report", "limitations"}
        and review.get("schema") == R18_REVIEW_SCHEMA
        and review.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and review.get("strict_cases_passed") == 0
        and review.get("case_pass") is False
        and review.get("registry_admission") is False
        and review.get("candidate") == candidate
        and review.get("source_bindings") == source_bindings
        and review.get("source_fake_checks") == checks
        and type(review.get("limitations")) is list
        and type(report) is dict
        and set(report) == {"source_test_sha256", "passed", "failed", "skipped"}
        and report.get("source_test_sha256") == _sha(source_files[R18_TEST_PATH])
        and type(report.get("passed")) is int and report["passed"] > 0
        and report.get("failed") == 0 and report.get("skipped") == 0,
        "r18_review_semantics_invalid",
    )
    review_index = _json(review_files["review-index.json"])
    review_bundle_files = _review_bundle_files(review_files, qa, packet_files, predecessor)
    review_bundle = _indexed_zip(review_files["review-bundle.zip"], review_index.get("bundle_members"))
    _need(review_bundle == review_bundle_files, "r18_review_bundle_bytes_invalid")
    _need(
        set(review_index) == {"schema", "verdict", "status", "review_json_sha256", "review_bundle_sha256", "source_bundle_sha256", "source_index_sha256", "source_pins_sha256", "source_bindings", "independent_test_report", "strict_cases_passed", "optional16_real_accepted", "actual_process_started", "root_map_created", "bundle_members"}
        and review_index.get("schema") == "iteration41.optional16.r33.deadline-r18.aggregate-review-index.v1"
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
        "r18_review_index_invalid",
    )
    expected_checkpoint = {
        "schema": "iteration41.optional16.r33.deadline-r18.aggregate-review-checkpoint.v1",
        "verdict": "GO_SOURCE_FAKE_ONLY",
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "review_json_sha256": _sha(review_files["review.json"]),
        "review_bundle_sha256": _sha(review_files["review-bundle.zip"]),
        "review_index_sha256": _sha(review_files["review-index.json"]),
        "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
        "source_index_sha256": _sha(packet_files["source-index.json"]),
        "source_pins_sha256": _sha(packet_files["source-pins.json"]),
        "r16_review_json_sha256": R16_REVIEW_PINS["review.json"],
        "r17_review_json_sha256": R17_REVIEW_PINS["review.json"],
        "independent_test_report": report,
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "root_map_created": False,
    }
    _need(_json(review_files["review-checkpoint.json"]) == expected_checkpoint, "r18_review_checkpoint_invalid")
    return {
        "schema": R18_REVIEW_SCHEMA,
        "verdict": "GO_SOURCE_FAKE_ONLY",
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "candidate": candidate,
        "source_bindings": source_bindings,
        "independent_test_report": report,
        "r16_composite_verdict": predecessor["validation"]["validation"]["verdict"],
        "r17_composite_verdict": predecessor["r17_validation"]["verdict"],
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
    }


def _read_names(folder: Path, names: set[str] | frozenset[str]) -> Dict[str, bytes]:
    return {name: (folder / name).read_bytes() for name in names}


def validate_paths(packet: Path = R18_PACKET, review: Path = R18_REVIEW) -> Dict[str, Any]:
    r17_module_raw = R17_HELPER_PATH.read_bytes()
    _need(_sha(r17_module_raw) == R17_HELPER_SHA256, "r17_helper_hash_mismatch")
    r17_helper = _load_declared(r17_module_raw, R17_HELPER_PATH, "_iteration41_optional16_r33_r17_frozen_binding")
    r16_helper = r17_helper._load_r16_helper()
    r16_paths = _r16_paths(r16_helper)
    r17_paths = _r17_paths(r17_helper)
    source_files = {path: (ROOT / path).read_bytes() for path in r16_paths | r17_paths | _r18_paths()}
    r16_packet_files = _read_names(R16_PACKET, R16_PACKET_PINS)
    r16_review_files = _read_names(R16_REVIEW, R16_REVIEW_PINS)
    r17_packet_files = _read_names(R17_PACKET, R17_PACKET_PINS)
    r17_review_files = _read_names(R17_REVIEW, R17_REVIEW_PINS)
    packet_files = _read_names(packet, PACKET_NAMES)
    review_files = _read_names(review, REVIEW_NAMES)
    packet_pins = {name: _sha(body) for name, body in packet_files.items()}
    review_pins = {name: _sha(body) for name, body in review_files.items()}
    return validate_successor_artifacts(
        source_files,
        packet_files,
        review_files,
        packet_pins=packet_pins,
        review_pins=review_pins,
        r16_packet_files=r16_packet_files,
        r16_review_files=r16_review_files,
        r17_packet_files=r17_packet_files,
        r17_review_files=r17_review_files,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if args == ["--source-check"]:
            raw = R17_HELPER_PATH.read_bytes()
            _need(_sha(raw) == R17_HELPER_SHA256, "r17_helper_hash_mismatch")
            print(json.dumps({"schema": "iteration41.optional16.r33.deadline-r18.binding.v1", "status": "R16_R17_COMPOSITES_VERIFIED_R18_SOURCE_ONLY", "r17_helper_sha256": R17_HELPER_SHA256, "r18_packet_present": R18_PACKET.exists(), "r18_review_present": R18_REVIEW.exists(), "strict_cases_passed": 0, "optional16_real_accepted": 0}, sort_keys=True))
            return 0
        if args == ["--build-source-packet"]:
            print(json.dumps(build_source_packet(), sort_keys=True))
            return 0
        print(json.dumps({"schema": "iteration41.optional16.r33.deadline-r18.binding.v1", "status": "PREPARED_UNSET", "activation_enabled": False, "strict_cases_passed": 0}, sort_keys=True))
        return 2
    except (BindingError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"schema": "iteration41.optional16.r33.deadline-r18.binding.v1", "status": "BLOCKED", "reason": str(exc) if type(exc) is BindingError else "binding_failed", "strict_cases_passed": 0, "optional16_real_accepted": 0}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
