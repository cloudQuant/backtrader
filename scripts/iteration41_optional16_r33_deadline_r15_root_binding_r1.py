"""Source-only binder for the combined Optional16 R33 deadline R15 packet.

This helper verifies the one published R15 source packet and aggregate
independent review, then exposes the exact four selected source roles. It does
not create activation state, private directories, processes, or native objects.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import sys
from typing import Any, Dict, Mapping, Tuple
import zipfile


ROOT = Path(r"D:\source_code\backtrader")
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
PACKET = EVIDENCE / "iteration41-optional16-r33-deadline-propagation-r15-source-fake-2026-10-07"
REVIEW = EVIDENCE / "iteration41-optional16-r33-deadline-propagation-r15-independent-review-r1-2026-10-07"

BINDING_SCHEMA = "iteration41.optional16.r33.deadline-r15.root-binding.v1"
QA_PROJECTION_SCHEMA = "iteration41.optional16.r33.deadline-r15.independent-qa-projection.v1"

SOURCE_BUNDLE_SHA256 = "ef4b95d618e503da9f99346a0bb44b2c54595ba87df8dcc8617782037402e044"
SOURCE_INDEX_SHA256 = "99b31e4759fffb22c7d64057e287f3b553611343e0b36712671abde57c1deab5"
SOURCE_PINS_SHA256 = "d6001eb1f00307b9b407bc784c993c77f357c95646ff2192ccf0f22f176d97ad"
SOURCE_CHECKPOINT_SHA256 = "d6867f7558706d39f59ae0c31e3dc342a4e20436d41c11e849909454f3c3aab0"
REVIEW_JSON_SHA256 = "db173e605489a9271260a758ad7864cba5ae722bb3537183c444e95eed3a93b2"
REVIEW_BUNDLE_SHA256 = "8e24bbda889b44fc7de7e8faee154ad201193b8517a9b7567567960a0a5b2f69"
REVIEW_INDEX_SHA256 = "b1b5591b71c6ea107d18f30318b9e6928ba574ae0aa735e5c5edb6062438b3b5"
REVIEW_CHECKPOINT_SHA256 = "dd1e1456593aa2706967283801a9dcb131ac5607fc5e604e9875b5423356a5e1"
REVIEW_README_SHA256 = "a6657a1355f1ed0bb4baa9496e19488859d53492ff548c74cb8d2680760ff5b7"
PRIOR_R2_OBSERVATION_PATH = "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r33-whole-call-r2-root-tool-observation-2026-10-06/observation.json"
PRIOR_R2_OBSERVATION_SHA256 = "d9b286e1c5191c582c69f612d2a460dc16ea11a56f9a66cc88f6f4ad73e257ab"
R12_R2_GLUE_BUNDLE_SHA256 = "045973cadfb5256faf7955c6c646bd2494009136e283516b16e2281e588981bb"
R12_R2_GLUE_INDEX_SHA256 = "3794e99e3a71606b8dd4bf6a5948d52bca302368c6bad45161450f88d913adbc"
R12_R2_GLUE_MEMBER_SHA256 = "c93a20753db03df0710b86262b3e4a95d9a49ac5c86fe6aad055acfc945f162e"

ROLE_PATHS = {
    "whole_call_supervisor": "scripts/iteration41_optional16_r33_whole_call_supervisor_r15.py",
    "invoke": "scripts/iteration41_optional16_r33_root_held_invoke_r15.py",
    "glue": "scripts/iteration41_optional16_r33_root_held_glue_r15.py",
    "driver": "scripts/iteration41_optional16_r33_root_driver_r15.py",
}
TEST_PATH = "tests/unit/scripts/test_iteration41_optional16_r33_deadline_r15.py"
SUCCESSOR_SCHEMA = "iteration41.optional16.r33.deadline-r15.aggregate-successor-source-index.v1"
SUCCESSOR_REVIEW_SCHEMA = "iteration41.optional16.r33.deadline-r15.aggregate-successor-independent-review.v1"
SUCCESSOR_ROLE_PATHS = {
    "whole_call_supervisor": "scripts/iteration41_optional16_r33_whole_call_supervisor_r16.py",
    "invoke": "scripts/iteration41_optional16_r33_root_held_invoke_r16.py",
    "glue": ROLE_PATHS["glue"],
    "driver": "scripts/iteration41_optional16_r33_root_driver_r16.py",
    "binding_helper": "scripts/iteration41_optional16_r33_deadline_r15_root_binding_r1.py",
}
SUCCESSOR_TEST_PATH = "tests/unit/scripts/test_iteration41_optional16_r33_deadline_r16_aggregate_source_fake.py"
ROOT_ACTUAL_ENABLED = False


class BindingError(RuntimeError):
    """The combined R15 source/review binding is incomplete or inconsistent."""


def _need(value: bool, reason: str) -> None:
    if not value:
        raise BindingError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs_no_duplicates(pairs: list[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        _need(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise BindingError("non_finite_json_value")


def _json(raw: bytes) -> Dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError("json_invalid") from exc
    _need(type(value) is dict, "json_object_required")
    return value


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
        "ascii"
    )


def _read_expected(folder: Path, name: str, digest: str) -> bytes:
    raw = (folder / name).read_bytes()
    _need(_sha(raw) == digest, "pinned_file_mismatch:" + name)
    return raw


def _safe_zip(raw: bytes) -> Dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            names = archive.namelist()
            _need(len(names) == len(set(names)), "duplicate_zip_member")
            result: Dict[str, bytes] = {}
            for name in names:
                _need(
                    name
                    and not name.startswith(("/", "\\"))
                    and "\\" not in name
                    and all(part not in ("", ".", "..") for part in name.split("/")),
                    "unsafe_zip_member_name",
                )
                _need(not name.endswith("/"), "zip_directory_member_rejected")
                result[name] = archive.read(name)
            return result
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise BindingError("zip_invalid") from exc


def _index_rows(rows: Any, key_name: str, exact_keys: set[str]) -> Dict[str, Dict[str, Any]]:
    _need(type(rows) is list, "index_rows_invalid")
    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        _need(type(row) is dict and set(row) == exact_keys, "index_row_shape_invalid")
        key = row.get(key_name)
        _need(type(key) is str and key not in result, "index_row_key_invalid")
        result[key] = row
    return result


def _verify_indexed_archive(
    archive_bytes: bytes,
    rows: Any,
    *,
    path_field: str,
    expected_files: Mapping[str, bytes] | None = None,
) -> Dict[str, bytes]:
    archive = _safe_zip(archive_bytes)
    if type(rows) is dict:
        normalized_rows = []
        for name, row in rows.items():
            _need(type(name) is str and type(row) is dict, "index_row_mapping_invalid")
            normalized_rows.append({path_field: name, **row})
        rows = normalized_rows
    indexed = _index_rows(rows, path_field, {path_field, "sha256", "size_bytes"})
    _need(set(archive) == set(indexed), "archive_index_member_set_mismatch")
    for name, body in archive.items():
        row = indexed[name]
        _need(type(row["sha256"]) is str and row["sha256"] == _sha(body), "archive_member_hash_mismatch")
        _need(type(row["size_bytes"]) is int and row["size_bytes"] == len(body), "archive_member_size_mismatch")
    if expected_files is not None:
        _need(set(expected_files).issubset(archive), "archive_missing_expected_file")
        for name, body in expected_files.items():
            _need(archive[name] == body, "archive_expected_file_mismatch")
    return archive


def _verify_prior_r2_observation() -> Dict[str, Any]:
    raw = _read_expected(ROOT, PRIOR_R2_OBSERVATION_PATH, PRIOR_R2_OBSERVATION_SHA256)
    document = _json(raw)
    parent = document.get("actual_parent_result")
    closure = document.get("source_closure")
    _need(
        document.get("schema") == "iteration41.optional16.r33.whole-call-r2.root-tool-observation.v1"
        and document.get("classification") == "ROOT_REPORTED_TOOL_OBSERVATION_NOT_INDEPENDENT_ACCOUNT_EVIDENCE"
        and type(parent) is dict
        and parent.get("status") == "ROOT_UNCERTAIN_RETAINED_NO_PARSE"
        and parent.get("reason_code") == "outer_call_deadline"
        and parent.get("root_exit_code") == 2
        and parent.get("whole_command_g1") is False
        and parent.get("raw_or_late_child_frame_parsed") is False
        and type(closure) is dict
        and closure.get("full_source_software_map_count") == 549
        and closure.get("source_postverification_completed") is False
        and closure.get("external_streams_released") is False,
        "prior_r2_observation_contract_invalid",
    )
    return {
        "path": PRIOR_R2_OBSERVATION_PATH,
        "sha256": PRIOR_R2_OBSERVATION_SHA256,
        "classification": document["classification"],
        "status": parent["status"],
        "reason_code": parent["reason_code"],
        "root_exit_code": parent["root_exit_code"],
        "whole_command_g1": parent["whole_command_g1"],
        "late_frame_parsed": parent["raw_or_late_child_frame_parsed"],
        "prior_full_source_software_map_count": closure["full_source_software_map_count"],
        "source_postverification_completed": closure["source_postverification_completed"],
        "external_streams_released": closure["external_streams_released"],
    }


def _verify_source_packet(packet: Path, root: Path) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, int]]:
    names = {
        "source-bundle.zip": SOURCE_BUNDLE_SHA256,
        "source-index.json": SOURCE_INDEX_SHA256,
        "source-pins.json": SOURCE_PINS_SHA256,
        "checkpoint.json": SOURCE_CHECKPOINT_SHA256,
    }
    raw_files = {name: _read_expected(packet, name, digest) for name, digest in names.items()}
    readme = (packet / "README.md").read_bytes()
    _need(_sha(readme) == "332191d9744303dad91e986c8a49d8d135f471bfbef6411e735e9b02fdb2a70f", "source_readme_pin_mismatch")
    indexed = _json(raw_files["source-index.json"])
    pins = _json(raw_files["source-pins.json"])
    checkpoint = _json(raw_files["checkpoint.json"])

    expected_index_keys = {
        "schema", "candidate_status", "source_bundle_sha256", "source_bundle_member_count",
        "members", "qa_summary_sha256", "strict_cases_passed", "optional16_real_accepted",
        "real_process_started", "root_map_created",
    }
    _need(set(indexed) == expected_index_keys, "source_index_schema_shape_invalid")
    _need(indexed.get("schema") == "iteration41.optional16.r33.deadline-r15.source-index.v1", "source_index_schema_invalid")
    _need(indexed.get("candidate_status") == "SOURCE_FAKE_ONLY_CLOSED", "source_candidate_status_invalid")
    _need(indexed.get("source_bundle_sha256") == SOURCE_BUNDLE_SHA256, "source_index_bundle_reference_invalid")
    _need(indexed.get("source_bundle_member_count") == 5, "source_index_member_count_invalid")
    _need(indexed.get("strict_cases_passed") == 0 and indexed.get("optional16_real_accepted") == 0, "source_acceptance_claim_invalid")
    _need(indexed.get("real_process_started") is False and indexed.get("root_map_created") is False, "source_execution_claim_invalid")

    member_rows = _index_rows(indexed.get("members"), "path", {"path", "sha256", "size_bytes"})
    expected_member_paths = set(ROLE_PATHS.values()) | {TEST_PATH}
    _need(set(member_rows) == expected_member_paths, "selected_r15_member_set_invalid")
    member_hashes: Dict[str, str] = {}
    member_sizes: Dict[str, int] = {}
    for relative, row in member_rows.items():
        digest = row["sha256"]
        size = row["size_bytes"]
        _need(type(digest) is str and len(digest) == 64, "source_member_hash_invalid")
        _need(type(size) is int and size > 0, "source_member_size_invalid")
        member_hashes[relative] = digest
        member_sizes[relative] = size
        current = (root / relative).read_bytes()
        _need(len(current) == size and _sha(current) == digest, "workspace_member_pin_mismatch")

    bundle = _verify_indexed_archive(
        raw_files["source-bundle.zip"],
        [
            {"path": name, "sha256": row["sha256"], "size_bytes": row["size_bytes"]}
            for name, row in member_rows.items()
        ],
        path_field="path",
    )
    _need(set(bundle) == expected_member_paths, "source_bundle_member_set_invalid")
    pins_expected = {
        "schema": "iteration41.optional16.r33.deadline-r15.source-pins.v1",
        "source_bundle_sha256": SOURCE_BUNDLE_SHA256,
        "pins": member_hashes,
        "qa_summary_sha256": indexed["qa_summary_sha256"],
    }
    _need(pins == pins_expected, "source_pins_contract_invalid")
    _need(type(indexed["qa_summary_sha256"]) is str and len(indexed["qa_summary_sha256"]) == 64, "declared_qa_hash_invalid")

    frozen = {
        "scripts/iteration41_optional16_r33_whole_call_supervisor_r2.py": "0ea972a9eee9f4d0135caa78a11200b15f6f63504dbb015a6078ebb51e7f7668",
        "scripts/iteration41_optional16_r33_root_held_invoke_r12.py": "234ab113fce0792a05437154cbd0a47e2a17f5f4d7771151e6d9a50e01195a9b",
        "scripts/iteration41_optional16_r33_root_driver_r5.py": "e7d573fbebe282fe33e3043fbae95b4b44414fa708b9c2c8a8dcb9fde82ddc70",
    }
    expected_checkpoint = {
        "schema": "iteration41.optional16.r33.deadline-r15.source-fake-checkpoint.v1",
        "status": "SOURCE_FAKE_ONLY_CLOSED",
        "source_bundle_sha256": SOURCE_BUNDLE_SHA256,
        "source_index_sha256": SOURCE_INDEX_SHA256,
        "source_pins_sha256": SOURCE_PINS_SHA256,
        "qa_summary_sha256": indexed["qa_summary_sha256"],
        "qa": {"passed": 13, "failed": 0, "skipped": 0, "real_process_started": False, "root_map_created": False},
        "frozen_sources_unchanged": frozen,
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
        "g1_accepted": False,
    }
    _need(checkpoint == expected_checkpoint, "source_checkpoint_contract_invalid")
    return indexed, member_hashes, member_sizes


def _verify_review(review_dir: Path, packet_dir: Path, indexed: Dict[str, Any], member_hashes: Dict[str, str], member_sizes: Dict[str, int]) -> Tuple[Dict[str, Any], Dict[str, str], bytes, str]:
    pin_values = {
        "review.json": REVIEW_JSON_SHA256,
        "review-bundle.zip": REVIEW_BUNDLE_SHA256,
        "review-index.json": REVIEW_INDEX_SHA256,
        "review-checkpoint.json": REVIEW_CHECKPOINT_SHA256,
        "README.md": REVIEW_README_SHA256,
    }
    files = {name: _read_expected(review_dir, name, digest) for name, digest in pin_values.items()}
    review = _json(files["review.json"])
    review_index = _json(files["review-index.json"])
    checkpoint = _json(files["review-checkpoint.json"])
    _need(review.get("schema") == "iteration41.optional16.r33.deadline-propagation-r15.independent-review.v1", "aggregate_review_schema_invalid")
    _need(review.get("review_id") == "iteration41-optional16-r33-deadline-propagation-r15-independent-review-r1-2026-10-07", "aggregate_review_id_invalid")
    decision = review.get("decision")
    _need(type(decision) is dict, "aggregate_decision_missing")
    _need(
        decision.get("source_fake_review") == "GO_SOURCE_FAKE_ONLY"
        and decision.get("actual_g1") == "NO_GO"
        and decision.get("g1_accepted") is False
        and decision.get("strict_cases_passed") == 0
        and decision.get("optional16_real_accepted") == 0
        and decision.get("optional16_total") == 16
        and decision.get("actual_r15_invoked") is False
        and decision.get("actual_process_started") is False
        and decision.get("root_map_created") is False,
        "aggregate_decision_scope_invalid",
    )

    package = review.get("source_package")
    _need(type(package) is dict, "aggregate_source_package_missing")
    _need(
        package.get("source_bundle_sha256") == SOURCE_BUNDLE_SHA256
        and package.get("source_index_sha256") == SOURCE_INDEX_SHA256
        and package.get("source_pins_sha256") == SOURCE_PINS_SHA256
        and package.get("checkpoint_sha256") == SOURCE_CHECKPOINT_SHA256
        and package.get("declared_member_count") == 5
        and package.get("qa_summary_blob_present") is False,
        "aggregate_source_package_binding_invalid",
    )
    _need(package.get("directory") == "evidence/" + packet_dir.name, "aggregate_source_package_path_invalid")

    expected_selection = {
        "whole_call_supervisor": "R15 payload fixes root_held_invoke_r15.py by fixed path and source hash.",
        "invoke_glue": "R15 invoke fixes R2_GLUE to scripts/iteration41_optional16_r33_root_held_glue_r15.py and DRIVER to scripts/iteration41_optional16_r33_root_driver_r15.py; activation pins are unset on disk.",
        "glue_driver": "R15 glue fixes SOURCE to the R15 root driver and requires held bytes to equal its designated active copy before exec.",
        "legacy_name_note": "The R15 root-driver has a legacy R2_GLUE constant for the old R3 glue as a held lineage input. It is not the application glue selected by the R15 invoke module; no old-source shadow was executed here.",
    }
    _need(review.get("source_selection") == expected_selection, "aggregate_role_selection_invalid")
    deadline = review.get("deadline_flow")
    _need(type(deadline) is dict and set(deadline) == {"parent", "bootstrap", "invoke", "glue", "driver"}, "deadline_flow_shape_invalid")
    for step, source in (
        ("parent", ROLE_PATHS["whole_call_supervisor"]),
        ("bootstrap", ROLE_PATHS["whole_call_supervisor"]),
        ("invoke", ROLE_PATHS["invoke"]),
        ("glue", ROLE_PATHS["glue"]),
        ("driver", ROLE_PATHS["driver"]),
    ):
        _need(type(deadline[step]) is dict and deadline[step].get("source") == source, "deadline_flow_source_invalid:" + step)

    test_report = review.get("test_report")
    _need(
        type(test_report) is dict
        and test_report.get("passed") == 13
        and test_report.get("failed") == 0
        and test_report.get("skipped") == 0,
        "independent_qa_summary_invalid",
    )
    predecessor = review.get("predecessor_collision")
    _need(
        type(predecessor) is dict
        and predecessor.get("old_r2_sha256") == "0ea972a9eee9f4d0135caa78a11200b15f6f63504dbb015a6078ebb51e7f7668"
        and predecessor.get("old_r12_sha256") == "234ab113fce0792a05437154cbd0a47e2a17f5f4d7771151e6d9a50e01195a9b"
        and predecessor.get("old_r5_sha256") == "e7d573fbebe282fe33e3043fbae95b4b44414fa708b9c2c8a8dcb9fde82ddc70"
        and predecessor.get("public_r3_glue_member_sha256") == R12_R2_GLUE_MEMBER_SHA256
        and predecessor.get("root_native_observation_used") is False,
        "predecessor_lineage_invalid",
    )

    _need(review_index.get("schema") == "iteration41.optional16.r33.deadline-propagation-r15.independent-review-index.v1", "review_index_schema_invalid")
    _need(review_index.get("review_id") == review.get("review_id"), "review_index_id_mismatch")
    _need(review_index.get("review_json") == {"path": "review.json", "sha256": REVIEW_JSON_SHA256, "size_bytes": len(files["review.json"])}, "review_index_json_reference_invalid")
    _need(review_index.get("review_bundle") == {"path": "review-bundle.zip", "sha256": REVIEW_BUNDLE_SHA256, "size_bytes": len(files["review-bundle.zip"])}, "review_index_bundle_reference_invalid")
    _need(review_index.get("source_bindings") == review.get("source_bindings"), "review_source_bindings_mismatch")
    _need(review_index.get("evidence_bindings") == review.get("evidence_bindings"), "review_evidence_bindings_mismatch")
    _need(review_index.get("status") == "GO_SOURCE_FAKE_ONLY / NO_GO_AS_ACTUAL_G1", "review_index_status_invalid")
    _need(review_index.get("strict_cases_passed") == 0 and review_index.get("optional16_real_accepted") == 0 and review_index.get("actual_r15_invoked") is False, "review_index_acceptance_invalid")

    binding_rows = _index_rows(review_index.get("source_bindings"), "path", {"path", "sha256", "size_bytes", "set"})
    for role, relative in ROLE_PATHS.items():
        row = binding_rows.get(relative)
        _need(
            row == {"path": relative, "sha256": member_hashes[relative], "size_bytes": member_sizes[relative], "set": "r15-source-bundle"},
            "review_role_binding_invalid:" + role,
        )
    test_row = binding_rows.get(TEST_PATH)
    _need(test_row == {"path": TEST_PATH, "sha256": member_hashes[TEST_PATH], "size_bytes": member_sizes[TEST_PATH], "set": "r15-source-bundle"}, "review_test_binding_invalid")
    _need(len(binding_rows) == 9 and len(review_index.get("evidence_bindings", [])) == 11, "review_binding_counts_invalid")

    indexed_review_members = review_index.get("bundle_members")
    outer_members = _verify_indexed_archive(
        files["review-bundle.zip"], indexed_review_members, path_field="bundle_path"
    )
    expected_review_inputs = {
        "inputs/r15/source-bundle.zip": _read_expected(packet_dir, "source-bundle.zip", SOURCE_BUNDLE_SHA256),
        "inputs/r15/source-index.json": _read_expected(packet_dir, "source-index.json", SOURCE_INDEX_SHA256),
        "inputs/r15/source-pins.json": _read_expected(packet_dir, "source-pins.json", SOURCE_PINS_SHA256),
        "inputs/r15/checkpoint.json": _read_expected(packet_dir, "checkpoint.json", SOURCE_CHECKPOINT_SHA256),
        "inputs/r15/README.md": (packet_dir / "README.md").read_bytes(),
        "inputs/frozen/iteration41_optional16_r33_whole_call_supervisor_r2.py": (ROOT / "scripts/iteration41_optional16_r33_whole_call_supervisor_r2.py").read_bytes(),
        "inputs/frozen/iteration41_optional16_r33_root_held_invoke_r12.py": (ROOT / "scripts/iteration41_optional16_r33_root_held_invoke_r12.py").read_bytes(),
        "inputs/frozen/iteration41_optional16_r33_root_driver_r5.py": (ROOT / "scripts/iteration41_optional16_r33_root_driver_r5.py").read_bytes(),
    }
    for archive_path, expected in expected_review_inputs.items():
        _need(outer_members.get(archive_path) == expected, "review_bundle_source_input_mismatch:" + archive_path)
    _need(_sha(outer_members["inputs/r12-r2-public-glue-export/source-bundle.zip"]) == R12_R2_GLUE_BUNDLE_SHA256, "r3_glue_export_bundle_hash_invalid")
    _need(_sha(outer_members["inputs/r12-r2-public-glue-export/source-index.json"]) == R12_R2_GLUE_INDEX_SHA256, "r3_glue_export_index_hash_invalid")
    glue_index = _json(outer_members["inputs/r12-r2-public-glue-export/source-index.json"])
    glue_bundle = _verify_indexed_archive(
        outer_members["inputs/r12-r2-public-glue-export/source-bundle.zip"],
        glue_index.get("members"),
        path_field="path",
    )
    _need(set(glue_bundle) == {"source/root-held-glue-r3.py"}, "r3_glue_export_member_set_invalid")
    _need(_sha(glue_bundle["source/root-held-glue-r3.py"]) == R12_R2_GLUE_MEMBER_SHA256, "r3_glue_export_member_hash_invalid")

    expected_checkpoint_hashes = {
        "README.md": REVIEW_README_SHA256,
        "review-bundle.zip": REVIEW_BUNDLE_SHA256,
        "review-index.json": REVIEW_INDEX_SHA256,
        "review.json": REVIEW_JSON_SHA256,
    }
    _need(checkpoint.get("schema") == "iteration41.optional16.r33.deadline-propagation-r15.independent-review-checkpoint.v1", "review_checkpoint_schema_invalid")
    _need(checkpoint.get("review_id") == review.get("review_id"), "review_checkpoint_id_mismatch")
    _need(checkpoint.get("status") == "GO_SOURCE_FAKE_ONLY / NO_GO_AS_ACTUAL_G1", "review_checkpoint_status_invalid")
    _need(checkpoint.get("hashes") == expected_checkpoint_hashes, "review_checkpoint_hash_binding_invalid")
    inputs = checkpoint.get("inputs")
    _need(
        type(inputs) is dict
        and inputs.get("r15_source_bundle_sha256") == SOURCE_BUNDLE_SHA256
        and inputs.get("r15_source_index_sha256") == SOURCE_INDEX_SHA256
        and inputs.get("r15_source_pins_sha256") == SOURCE_PINS_SHA256
        and inputs.get("r15_source_checkpoint_sha256") == SOURCE_CHECKPOINT_SHA256
        and inputs.get("r15_test_sha256") == member_hashes[TEST_PATH]
        and inputs.get("r12_r2_glue_export_sha256") == R12_R2_GLUE_BUNDLE_SHA256
        and inputs.get("r12_r2_glue_member_sha256") == R12_R2_GLUE_MEMBER_SHA256,
        "review_checkpoint_input_binding_invalid",
    )

    qa_projection = _canonical(
        {
            "schema": QA_PROJECTION_SCHEMA,
            "source_review_id": review["review_id"],
            "source_review_json_sha256": REVIEW_JSON_SHA256,
            "source_review_bundle_sha256": REVIEW_BUNDLE_SHA256,
            "source_test_path": TEST_PATH,
            "source_test_sha256": member_hashes[TEST_PATH],
            "independent_test_report": {"passed": 13, "failed": 0, "skipped": 0},
            "author_qa_summary_blob_available": False,
            "strict_cases_passed": 0,
            "case_pass": False,
        }
    )
    qa_projection_sha = _sha(qa_projection)
    _need(qa_projection_sha != indexed["qa_summary_sha256"], "qa_projection_reused_author_digest")
    return review, pin_values, qa_projection, qa_projection_sha


@dataclass(frozen=True)
class R15Binding:
    """Validated aggregate R15 source/review mapping; never an activation token."""

    source_index: Mapping[str, Any]
    review: Mapping[str, Any]
    role_paths: Mapping[str, str]
    member_hashes: Mapping[str, str]
    member_sizes: Mapping[str, int]
    packet_pins: Mapping[str, str]
    review_pins: Mapping[str, str]
    qa_projection: bytes
    qa_projection_sha256: str

    def require_role(self, role: str, path: str, digest: str) -> None:
        expected = ROLE_PATHS.get(role)
        _need(expected is not None and path == expected, "aggregate_role_path_mismatch")
        _need(digest == self.member_hashes[expected], "aggregate_role_hash_mismatch")

    def report(self) -> Dict[str, Any]:
        selected = {
            role: {
                "path": path,
                "sha256": self.member_hashes[path],
                "size_bytes": self.member_sizes[path],
            }
            for role, path in self.role_paths.items()
        }
        successor_packet = EVIDENCE / "iteration41-optional16-r33-deadline-r15-successor-source-candidate-2026-10-07"
        successor_review = EVIDENCE / "iteration41-optional16-r33-deadline-r15-successor-independent-review-2026-10-07"
        successor_sources = {
            role: {
                "path": path,
                "sha256": _sha((ROOT / path).read_bytes()),
                "size_bytes": (ROOT / path).stat().st_size,
            }
            for role, path in SUCCESSOR_ROLE_PATHS.items()
        }
        successor_test_raw = (ROOT / SUCCESSOR_TEST_PATH).read_bytes()
        return {
            "schema": BINDING_SCHEMA,
            "status": "SOURCE_BINDING_ONLY",
            "activation_enabled": False,
            "selected_successor_count": len(selected),
            "shared_test_count": 1,
            "selected_successors": selected,
            "successor_preparation": {
                "status": "R16_SOURCE_CANDIDATE_ONLY",
                "activation_enabled": False,
                "packet_directory": "evidence/iteration41-optional16-r33-deadline-r15-successor-source-candidate-2026-10-07",
                "review_directory": "evidence/iteration41-optional16-r33-deadline-r15-successor-independent-review-2026-10-07",
                "selected_roles": {
                    **successor_sources,
                    "shared_test": {
                        "path": SUCCESSOR_TEST_PATH,
                        "sha256": _sha(successor_test_raw),
                        "size_bytes": len(successor_test_raw),
                    },
                },
                "independent_successor_review_present": (successor_review / "review.json").is_file(),
                "author_qa_summary_blob_reconstructed": False,
                "source_bundle_created": (successor_packet / "source-bundle.zip").is_file(),
            },
            "shared_test": {
                "path": TEST_PATH,
                "sha256": self.member_hashes[TEST_PATH],
                "size_bytes": self.member_sizes[TEST_PATH],
            },
            "source_index_member_count": len(self.member_hashes),
            "independent_review_source_binding_count": len(self.review["source_bindings"]),
            "independent_review_evidence_binding_count": len(self.review["evidence_bindings"]),
            "independent_qa_projection": {
                "schema": QA_PROJECTION_SCHEMA,
                "sha256": self.qa_projection_sha256,
                "source_review_json_sha256": REVIEW_JSON_SHA256,
                "written": False,
                "author_qa_summary_blob_available": False,
            },
            "driver_closure_counts": {
                "computed_from_physical_map": False,
                "reason": "R16 must run its pinned _expected_pins() over the 379-row public source index and validate the resulting held closure before reporting counts.",
                "r15_predecessor_declarations_only": {
                    "inert_public_paths": 495,
                    "active_public_paths": 505,
                    "software_paths": 5,
                    "path_aliases": 16,
                },
                "r16_public_base_map": {
                    "path": "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iter41-zmq-r6-map-r3-20261007/source/p/r25-public-path-pins.json",
                    "sha256": "5264b763bac6aac5d70fcbaa4e7cea423544ce90cd367e5e34da55c1680b9899",
                    "declared_public_path_rows": 379,
                },
                "r15_unbound_d_temp_placeholder": "D:/temp/iteration41-optional16-r33-root-public-pins-r15.json",
                "r16_computed_values": None,
            },
            "prior_r2_actual_observation": _verify_prior_r2_observation(),
            "deadline_budget_seconds": {
                "whole_call": 100,
                "whole_cleanup": 5,
                "application_wait_max": 100,
                "glue_capture_reserve": 5,
                "driver_invocation": 60,
                "driver_cleanup": 5,
                "parent_capture_reserve": 5,
                "driver_entry_minimum": 70,
            },
            "strict_cases_passed": 0,
            "optional16_real_accepted": 0,
            "actual_r15_invoked": False,
            "root_map_created": False,
        }


def _r15_evidence_files() -> Dict[str, bytes]:
    """Read only the fixed public R15 packet/review members already hash-bound above."""
    rows = {
        "inputs/r15/source-bundle.zip": (PACKET / "source-bundle.zip", SOURCE_BUNDLE_SHA256),
        "inputs/r15/source-index.json": (PACKET / "source-index.json", SOURCE_INDEX_SHA256),
        "inputs/r15/source-pins.json": (PACKET / "source-pins.json", SOURCE_PINS_SHA256),
        "inputs/r15/checkpoint.json": (PACKET / "checkpoint.json", SOURCE_CHECKPOINT_SHA256),
        "inputs/r15/README.md": (PACKET / "README.md", "332191d9744303dad91e986c8a49d8d135f471bfbef6411e735e9b02fdb2a70f"),
        "inputs/r15-review/review.json": (REVIEW / "review.json", REVIEW_JSON_SHA256),
        "inputs/r15-review/review-bundle.zip": (REVIEW / "review-bundle.zip", REVIEW_BUNDLE_SHA256),
        "inputs/r15-review/review-index.json": (REVIEW / "review-index.json", REVIEW_INDEX_SHA256),
        "inputs/r15-review/review-checkpoint.json": (REVIEW / "review-checkpoint.json", REVIEW_CHECKPOINT_SHA256),
        "inputs/r15-review/README.md": (REVIEW / "README.md", REVIEW_README_SHA256),
        "inputs/prior-r2-observation/observation.json": (
            ROOT / PRIOR_R2_OBSERVATION_PATH,
            PRIOR_R2_OBSERVATION_SHA256,
        ),
    }
    return {name: _read_expected(path.parent, path.name, digest) for name, (path, digest) in rows.items()}


def _member_rows(source_files: Mapping[str, bytes]) -> list[Dict[str, Any]]:
    return [
        {"path": name, "sha256": _sha(body), "size_bytes": len(body)}
        for name, body in sorted(source_files.items())
    ]


def _successor_source_binding(binding: R15Binding, source_files: Mapping[str, bytes]) -> Dict[str, Any]:
    new_roles = {
        role: {"path": path, "sha256": _sha(source_files[path]), "size_bytes": len(source_files[path])}
        for role, path in SUCCESSOR_ROLE_PATHS.items()
    }
    old_roles = {
        role: {
            "path": path,
            "sha256": binding.member_hashes[path],
            "size_bytes": binding.member_sizes[path],
        }
        for role, path in ROLE_PATHS.items()
    }
    return {
        "source_bundle_sha256": SOURCE_BUNDLE_SHA256,
        "source_index_sha256": SOURCE_INDEX_SHA256,
        "source_pins_sha256": SOURCE_PINS_SHA256,
        "source_checkpoint_sha256": SOURCE_CHECKPOINT_SHA256,
        "source_review_json_sha256": REVIEW_JSON_SHA256,
        "source_review_bundle_sha256": REVIEW_BUNDLE_SHA256,
        "source_review_index_sha256": REVIEW_INDEX_SHA256,
        "source_review_checkpoint_sha256": REVIEW_CHECKPOINT_SHA256,
        "prior_r2_actual_observation": _verify_prior_r2_observation(),
        "r15_roles": old_roles,
        "successor_roles": new_roles,
        "r15_test": {"path": TEST_PATH, "sha256": binding.member_hashes[TEST_PATH]},
        "successor_test": {
            "path": SUCCESSOR_TEST_PATH,
            "sha256": _sha(source_files[SUCCESSOR_TEST_PATH]),
            "size_bytes": len(source_files[SUCCESSOR_TEST_PATH]),
        },
    }


def validate_successor_artifacts(
    source_files: Mapping[str, bytes],
    packet_files: Mapping[str, bytes],
    review_files: Mapping[str, bytes],
    *,
    packet_pins: Mapping[str, str],
    review_pins: Mapping[str, str],
) -> Dict[str, Any]:
    """Validate one combined successor packet/review against R15 and exact roles.

    This consumes bytes already held by the caller. It never turns the review
    into an activation token; caller gates and the outer Root-owned source map
    remain mandatory.
    """
    binding = load_binding()
    required_sources = set(SUCCESSOR_ROLE_PATHS.values()) | {SUCCESSOR_TEST_PATH}
    _need(type(source_files) is dict and set(source_files) == required_sources, "successor_source_role_set_invalid")
    _need(all(type(body) is bytes and body for body in source_files.values()), "successor_source_bytes_invalid")
    required_packet = {
        "source-bundle.zip", "source-index.json", "source-pins.json", "checkpoint.json",
        "README.md", "qa/qa-summary.json",
    }
    required_review = {
        "review.json", "review-bundle.zip", "review-index.json", "review-checkpoint.json", "README.md",
    }
    _need(type(packet_files) is dict and set(packet_files) == required_packet, "successor_packet_member_set_invalid")
    _need(type(review_files) is dict and set(review_files) == required_review, "successor_review_member_set_invalid")
    _need(type(packet_pins) is dict and set(packet_pins) == required_packet, "successor_packet_pin_set_invalid")
    _need(type(review_pins) is dict and set(review_pins) == required_review, "successor_review_pin_set_invalid")
    for name, raw in packet_files.items():
        _need(type(raw) is bytes and _sha(raw) == packet_pins[name], "successor_packet_hash_mismatch:" + name)
    for name, raw in review_files.items():
        _need(type(raw) is bytes and _sha(raw) == review_pins[name], "successor_review_hash_mismatch:" + name)

    qa_projection = binding.qa_projection
    _need(packet_files["qa/qa-summary.json"] == qa_projection, "successor_qa_projection_invalid")
    source_bundle = _safe_zip(packet_files["source-bundle.zip"])
    _need(set(source_bundle) == required_sources, "successor_source_bundle_members_invalid")
    for path, body in source_files.items():
        _need(source_bundle[path] == body, "successor_source_bundle_bytes_mismatch:" + path)

    source_index = _json(packet_files["source-index.json"])
    source_pins = _json(packet_files["source-pins.json"])
    source_checkpoint = _json(packet_files["checkpoint.json"])
    expected_rows = _member_rows(source_files)
    r15_binding = _successor_source_binding(binding, source_files)
    _need(
        source_index == {
            "schema": SUCCESSOR_SCHEMA,
            "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
            "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
            "source_bundle_member_count": len(required_sources),
            "members": expected_rows,
            "r15_binding": r15_binding,
            "qa_projection_sha256": _sha(qa_projection),
            "qa_projection_schema": QA_PROJECTION_SCHEMA,
            "strict_cases_passed": 0,
            "optional16_real_accepted": 0,
            "actual_process_started": False,
            "root_map_created": False,
        },
        "successor_source_index_invalid",
    )
    expected_hashes = {path: _sha(body) for path, body in source_files.items()}
    _need(
        source_pins == {
            "schema": "iteration41.optional16.r33.deadline-r15.aggregate-successor-source-pins.v1",
            "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
            "source_index_sha256": _sha(packet_files["source-index.json"]),
            "member_sha256": expected_hashes,
            "r15_review_json_sha256": REVIEW_JSON_SHA256,
            "prior_r2_actual_observation": _verify_prior_r2_observation(),
            "qa_projection_sha256": _sha(qa_projection),
            "strict_cases_passed": 0,
            "optional16_real_accepted": 0,
        },
        "successor_source_pins_invalid",
    )
    _need(
        source_checkpoint == {
            "schema": "iteration41.optional16.r33.deadline-r15.aggregate-successor-source-checkpoint.v1",
            "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
            "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
            "source_index_sha256": _sha(packet_files["source-index.json"]),
            "source_pins_sha256": _sha(packet_files["source-pins.json"]),
            "r15_review_json_sha256": REVIEW_JSON_SHA256,
            "qa_projection_sha256": _sha(qa_projection),
            "strict_cases_passed": 0,
            "case_pass": False,
            "registry_admission": False,
            "optional16_real_accepted": 0,
            "actual_process_started": False,
            "g1_accepted": False,
        },
        "successor_source_checkpoint_invalid",
    )

    review = _json(review_files["review.json"])
    review_index = _json(review_files["review-index.json"])
    review_checkpoint = _json(review_files["review-checkpoint.json"])
    candidate = {
        "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
        "source_index_sha256": _sha(packet_files["source-index.json"]),
        "source_pins_sha256": _sha(packet_files["source-pins.json"]),
        "checkpoint_sha256": _sha(packet_files["checkpoint.json"]),
        "r15_transform": r15_binding,
        "r15_review_json_sha256": REVIEW_JSON_SHA256,
        "r15_review_bundle_sha256": REVIEW_BUNDLE_SHA256,
        "qa_projection_sha256": _sha(qa_projection),
        "r15_roles": r15_binding["r15_roles"],
        "successor_roles": r15_binding["successor_roles"],
        "r15_test": r15_binding["r15_test"],
        "successor_test": r15_binding["successor_test"],
    }
    expected_source_bindings = [
        {"path": path, "sha256": binding.member_hashes[path], "size_bytes": binding.member_sizes[path], "set": "r15-transform-input"}
        for path in sorted(ROLE_PATHS.values())
    ] + [
        {"path": TEST_PATH, "sha256": binding.member_hashes[TEST_PATH], "size_bytes": binding.member_sizes[TEST_PATH], "set": "r15-transform-input"}
    ] + [
        {"path": path, "sha256": _sha(source_files[path]), "size_bytes": len(source_files[path]), "set": "r16-successor-source-bundle"}
        for path in sorted(SUCCESSOR_ROLE_PATHS.values())
    ] + [
        {"path": SUCCESSOR_TEST_PATH, "sha256": _sha(source_files[SUCCESSOR_TEST_PATH]), "size_bytes": len(source_files[SUCCESSOR_TEST_PATH]), "set": "r16-successor-source-bundle"}
    ]
    expected_source_bindings.sort(key=lambda row: (row["set"], row["path"]))
    report = review.get("independent_test_report") if type(review) is dict else None
    _need(
        type(review) is dict
        and set(review) == {
            "schema", "verdict", "acceptance", "strict_cases_passed", "case_pass", "registry_admission",
            "candidate", "source_bindings", "source_fake_checks", "independent_test_report", "limitations",
        }
        and review.get("schema") == SUCCESSOR_REVIEW_SCHEMA
        and review.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review.get("acceptance") == "NOT_ACCEPTED_OPTIONAL16"
        and type(review.get("strict_cases_passed")) is int
        and review.get("strict_cases_passed") == 0
        and review.get("case_pass") is False
        and review.get("registry_admission") is False
        and review.get("candidate") == candidate
        and review.get("source_bindings") == expected_source_bindings
        and type(review.get("limitations")) is list
        and type(report) is dict
        and set(report) == {"source_test_sha256", "passed", "failed", "skipped"}
        and report.get("source_test_sha256") == candidate["successor_test"]["sha256"]
        and type(report.get("passed")) is int and report.get("passed") > 0
        and report.get("failed") == 0 and report.get("skipped") == 0,
        "successor_review_semantics_invalid",
    )
    checks = review.get("source_fake_checks")
    _need(
        checks == {
            "combined_r15_packet_and_review_verified": True,
            "exact_four_r15_roles_and_shared_test_bound": True,
            "successor_bundle_and_shared_test_bound": True,
            "qa_projection_is_generated_and_not_author_blob": True,
            "no_actual_process_or_root_map_claimed": True,
            "deadline_100_plus_5_contract_preserved": True,
        },
        "successor_review_checks_invalid",
    )
    _need(
        type(review_index) is dict
        and set(review_index) == {
            "schema", "verdict", "status", "review_json_sha256", "review_bundle_sha256",
            "source_bundle_sha256", "source_index_sha256", "source_pins_sha256", "source_bindings",
            "independent_test_report", "strict_cases_passed", "optional16_real_accepted",
            "actual_process_started", "root_map_created", "bundle_members",
        }
        and review_index.get("schema") == "iteration41.optional16.r33.deadline-r15.aggregate-successor-review-index.v1",
        "successor_review_index_schema_invalid",
    )
    _need(
        review_index.get("verdict") == "GO_SOURCE_FAKE_ONLY"
        and review_index.get("status") == "GO_SOURCE_FAKE_ONLY / NO_GO_AS_ACTUAL_G1"
        and review_index.get("review_json_sha256") == _sha(review_files["review.json"])
        and review_index.get("review_bundle_sha256") == _sha(review_files["review-bundle.zip"])
        and review_index.get("source_bundle_sha256") == _sha(packet_files["source-bundle.zip"])
        and review_index.get("source_index_sha256") == _sha(packet_files["source-index.json"])
        and review_index.get("source_pins_sha256") == _sha(packet_files["source-pins.json"])
        and review_index.get("source_bindings") == expected_source_bindings
        and review_index.get("source_bindings") == review.get("source_bindings")
        and review_index.get("independent_test_report") == report
        and review_index.get("strict_cases_passed") == 0
        and review_index.get("optional16_real_accepted") == 0
        and review_index.get("actual_process_started") is False
        and review_index.get("root_map_created") is False,
        "successor_review_index_invalid",
    )
    _need(type(review_index.get("bundle_members")) is list, "successor_review_bundle_index_invalid")
    evidence_files = _r15_evidence_files()
    review_bundle_expected = {
        "review.json": review_files["review.json"],
        "README.md": review_files["README.md"],
        "qa/qa-summary.json": qa_projection,
        "inputs/r16/source-bundle.zip": packet_files["source-bundle.zip"],
        "inputs/r16/source-index.json": packet_files["source-index.json"],
        "inputs/r16/source-pins.json": packet_files["source-pins.json"],
        "inputs/r16/checkpoint.json": packet_files["checkpoint.json"],
        "inputs/r16/README.md": packet_files["README.md"],
        "inputs/r16/qa/qa-summary.json": qa_projection,
        **evidence_files,
    }
    zipped_review = _verify_indexed_archive(
        review_files["review-bundle.zip"], review_index["bundle_members"], path_field="bundle_path"
    )
    _need(zipped_review == review_bundle_expected, "successor_review_bundle_members_or_bytes_invalid")
    expected_review_checkpoint = {
        "schema": "iteration41.optional16.r33.deadline-r15.aggregate-successor-review-checkpoint.v1",
        "verdict": "GO_SOURCE_FAKE_ONLY",
        "acceptance": "NOT_ACCEPTED_OPTIONAL16",
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
        "review_json_sha256": _sha(review_files["review.json"]),
        "review_bundle_sha256": _sha(review_files["review-bundle.zip"]),
        "review_index_sha256": _sha(review_files["review-index.json"]),
        "source_bundle_sha256": _sha(packet_files["source-bundle.zip"]),
        "source_index_sha256": _sha(packet_files["source-index.json"]),
        "source_pins_sha256": _sha(packet_files["source-pins.json"]),
        "r15_review_json_sha256": REVIEW_JSON_SHA256,
        "test_sha256": candidate["successor_test"]["sha256"],
        "independent_test_report": report,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "root_map_created": False,
        "g1_accepted": False,
    }
    _need(review_checkpoint == expected_review_checkpoint, "successor_review_checkpoint_invalid")
    return review


def build_successor_source_packet(output: Path) -> Dict[str, Any]:
    """Build the additive source-fake packet; it never creates an independent review."""
    binding = load_binding()
    source_paths = set(SUCCESSOR_ROLE_PATHS.values()) | {SUCCESSOR_TEST_PATH}
    source_files = {name: (ROOT / name).read_bytes() for name in source_paths}
    _need(all(type(raw) is bytes and raw for raw in source_files.values()), "successor_source_file_empty")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, body in sorted(source_files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 7, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body)
    source_bundle = zip_buffer.getvalue()
    rows = _member_rows(source_files)
    r15_binding = _successor_source_binding(binding, source_files)
    source_index = {
        "schema": SUCCESSOR_SCHEMA,
        "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "source_bundle_sha256": _sha(source_bundle),
        "source_bundle_member_count": len(source_files),
        "members": rows,
        "r15_binding": r15_binding,
        "qa_projection_sha256": binding.qa_projection_sha256,
        "qa_projection_schema": QA_PROJECTION_SCHEMA,
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "root_map_created": False,
    }
    source_index_raw = _canonical(source_index)
    member_hashes = {name: _sha(body) for name, body in source_files.items()}
    source_pins = {
        "schema": "iteration41.optional16.r33.deadline-r15.aggregate-successor-source-pins.v1",
        "source_bundle_sha256": _sha(source_bundle),
        "source_index_sha256": _sha(source_index_raw),
        "member_sha256": member_hashes,
        "r15_review_json_sha256": REVIEW_JSON_SHA256,
        "prior_r2_actual_observation": _verify_prior_r2_observation(),
        "qa_projection_sha256": binding.qa_projection_sha256,
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
    }
    source_pins_raw = _canonical(source_pins)
    source_checkpoint = {
        "schema": "iteration41.optional16.r33.deadline-r15.aggregate-successor-source-checkpoint.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "source_bundle_sha256": _sha(source_bundle),
        "source_index_sha256": _sha(source_index_raw),
        "source_pins_sha256": _sha(source_pins_raw),
        "r15_review_json_sha256": REVIEW_JSON_SHA256,
        "qa_projection_sha256": binding.qa_projection_sha256,
        "strict_cases_passed": 0,
        "case_pass": False,
        "registry_admission": False,
        "optional16_real_accepted": 0,
        "actual_process_started": False,
        "g1_accepted": False,
    }
    files = {
        "source-bundle.zip": source_bundle,
        "source-index.json": source_index_raw,
        "source-pins.json": source_pins_raw,
        "checkpoint.json": _canonical(source_checkpoint),
        "README.md": (
            "# R15 aggregate successor source candidate\n\n"
            "Status: READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW. This packet binds the four selected R15 roles and their shared test as transform inputs, then binds the additive R16 whole-call, invoke, driver, reused R15 glue, binding helper, and source-fake test. `qa/qa-summary.json` is a generated projection of the pinned R15 independent review; the author's missing QA summary blob is not reconstructed. No actual process, root map, provider, SDK, native call, or acceptance claim is included. Closure counts remain uncomputed until Root validates the physical source map.\n"
        ).encode("utf-8"),
        "qa/qa-summary.json": binding.qa_projection,
    }
    _need(isinstance(output, Path) and not output.exists(), "successor_packet_output_already_exists")
    output.mkdir(parents=True, exist_ok=False)
    for name, body in files.items():
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
    return {
        "schema": "iteration41.optional16.r33.deadline-r15.aggregate-successor-packet-builder.v1",
        "status": "READY_FOR_INDEPENDENT_SOURCE_FAKE_REVIEW",
        "packet_directory": str(output),
        "packet_sha256": {name: _sha(body) for name, body in files.items()},
        "source_member_count": len(source_files),
        "selected_successor_role_count": len(SUCCESSOR_ROLE_PATHS),
        "shared_test_count": 1,
        "strict_cases_passed": 0,
        "optional16_real_accepted": 0,
        "independent_successor_review_present": False,
        "author_qa_summary_blob_available": False,
        "source_map_counts_computed": False,
    }


def load_binding(
    packet: Path = PACKET,
    review_dir: Path = REVIEW,
    root: Path = ROOT,
) -> R15Binding:
    """Validate published public R15 bytes and the exact four selected roles."""
    indexed, member_hashes, member_sizes = _verify_source_packet(packet, root)
    review, review_pins, qa_projection, qa_projection_sha = _verify_review(
        review_dir, packet, indexed, member_hashes, member_sizes
    )
    packet_pins = {
        "source-bundle.zip": SOURCE_BUNDLE_SHA256,
        "source-index.json": SOURCE_INDEX_SHA256,
        "source-pins.json": SOURCE_PINS_SHA256,
        "checkpoint.json": SOURCE_CHECKPOINT_SHA256,
    }
    return R15Binding(
        source_index=indexed,
        review=review,
        role_paths=dict(ROLE_PATHS),
        member_hashes=member_hashes,
        member_sizes=member_sizes,
        packet_pins=packet_pins,
        review_pins=review_pins,
        qa_projection=qa_projection,
        qa_projection_sha256=qa_projection_sha,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--build-successor-source-packet"]:
        output = EVIDENCE / "iteration41-optional16-r33-deadline-r15-successor-source-candidate-2026-10-07"
        try:
            report = build_successor_source_packet(output)
        except (BindingError, OSError, KeyError, TypeError, ValueError) as exc:
            report = {
                "schema": "iteration41.optional16.r33.deadline-r15.aggregate-successor-packet-builder.v1",
                "status": "BLOCKED",
                "reason": str(exc) if type(exc) is BindingError else "packet_build_failed",
                "strict_cases_passed": 0,
                "optional16_real_accepted": 0,
                "source_map_counts_computed": False,
            }
            print(json.dumps(report, sort_keys=True))
            return 2
        print(json.dumps(report, sort_keys=True))
        return 0
    if args != ["--source-check"]:
        print(
            json.dumps(
                {
                    "schema": BINDING_SCHEMA,
                    "status": "PREPARED_UNSET",
                    "activation_enabled": False,
                    "actual_r15_invoked": False,
                    "strict_cases_passed": 0,
                },
                sort_keys=True,
            )
        )
        return 2
    try:
        report = load_binding().report()
    except (BindingError, OSError, KeyError, TypeError, ValueError):
        print(
            json.dumps(
                {
                    "schema": BINDING_SCHEMA,
                    "status": "BLOCKED_SOURCE_BINDING",
                    "activation_enabled": False,
                    "actual_r15_invoked": False,
                    "strict_cases_passed": 0,
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
