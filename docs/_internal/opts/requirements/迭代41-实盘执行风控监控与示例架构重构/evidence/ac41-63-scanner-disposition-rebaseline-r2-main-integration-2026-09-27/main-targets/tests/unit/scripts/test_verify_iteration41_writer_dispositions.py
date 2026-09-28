"""Contracts for the Iteration 41 static writer-disposition verifier."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "verify_iteration41_writer_dispositions.py"
CHECKLIST_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "_internal"
    / "opts"
    / "requirements"
    / "迭代41-实盘执行风控监控与示例架构重构"
    / "evidence"
    / "live-execution-writer-dispositions.json"
)


def _verifier_module():
    name = "iteration41_writer_dispositions_test_module"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_inventory(verifier, tmp_path: Path):
    source_root = tmp_path / "source"
    fixture_dir = source_root / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "writer.py").write_text(
        "import importlib\n"
        "api.submit_order({})\n"
        "importlib.import_module('unreviewed.module')\n",
        encoding="utf-8",
    )
    collector = verifier._load_inventory_collector()
    return collector.collect_inventory(source_root, ("fixture",))


def test_disposition_checklist_requires_a_complete_conservative_record(tmp_path: Path) -> None:
    verifier = _verifier_module()
    inventory = _fixture_inventory(verifier, tmp_path)

    checklist = verifier.build_review_required_checklist(inventory)
    result = verifier.validate_disposition_checklist(inventory, checklist)

    assert result["status"] == "PASS"
    assert result["discovered_candidate_count"] == 2
    assert result["review_required_count"] == 2
    assert checklist["status"] == verifier.CHECKLIST_STATUS
    assert checklist["closure_status"] == verifier.CHECKLIST_CLOSURE_STATUS
    assert (
        checklist["historical_ctp_candidate_scopes"] == inventory["historical_ctp_candidate_scopes"]
    )
    assert all(entry["owner"] for entry in checklist["entries"])
    assert all(entry["route"] == verifier.UNRESOLVED_LIVE_ROUTE for entry in checklist["entries"])
    assert all(entry["test_node"] for entry in checklist["entries"])
    assert all(entry["trace_evidence_disposition"] for entry in checklist["entries"])


def test_disposition_verifier_rejects_a_missing_candidate_or_required_field(tmp_path: Path) -> None:
    verifier = _verifier_module()
    inventory = _fixture_inventory(verifier, tmp_path)
    checklist = verifier.build_review_required_checklist(inventory)

    missing_candidate = deepcopy(checklist)
    missing_candidate["entries"].pop()
    missing_result = verifier.validate_disposition_checklist(inventory, missing_candidate)
    assert missing_result["status"] == "REJECTED"
    assert any(reason.startswith("candidate_disposition_missing:") for reason in missing_result["reason_codes"])

    missing_owner = deepcopy(checklist)
    del missing_owner["entries"][0]["owner"]
    owner_result = verifier.validate_disposition_checklist(inventory, missing_owner)
    assert owner_result["status"] == "REJECTED"
    assert any(reason.startswith("checklist_entry_missing_fields:") for reason in owner_result["reason_codes"])

    invalid_status = deepcopy(checklist)
    invalid_status["status"] = "PASS"
    invalid_status_result = verifier.validate_disposition_checklist(inventory, invalid_status)
    assert invalid_status_result["status"] == "REJECTED"
    assert "checklist_status_must_remain_review_required" in invalid_status_result["reason_codes"]

    static_trace_relabel = deepcopy(checklist)
    static_trace_relabel["entries"][0]["route"] = "REPLAY_ONLY_NO_EXTERNAL_WRITE"
    static_trace_relabel["entries"][0]["disposition"] = "NO_EXTERNAL_WRITE"
    static_trace_result = verifier.validate_disposition_checklist(inventory, static_trace_relabel)
    assert static_trace_result["status"] == "REJECTED"
    assert any(
        reason.startswith("static_trace_candidate_not_review_required:")
        for reason in static_trace_result["reason_codes"]
    )

    missing_scope_note = deepcopy(checklist)
    missing_scope_note["historical_ctp_candidate_scopes"] = [
        {"path": "examples/014_1_ctp_options_lowfreq"}
    ]
    scope_result = verifier.validate_disposition_checklist(inventory, missing_scope_note)
    assert scope_result["status"] == "REJECTED"
    assert "checklist_historical_scope_notes_mismatch" in scope_result["reason_codes"]


def test_disposition_verifier_rejects_an_available_live_candidate(tmp_path: Path) -> None:
    verifier = _verifier_module()
    inventory = _fixture_inventory(verifier, tmp_path)
    checklist = verifier.build_review_required_checklist(inventory)
    entry = checklist["entries"][0]
    entry["route"] = "LIVE_MANAGED_EXECUTION"
    entry["disposition"] = "NO_EXTERNAL_WRITE"
    entry["availability"] = "AVAILABLE"

    result = verifier.validate_disposition_checklist(inventory, checklist)

    assert result["status"] == "REJECTED"
    assert any(reason.startswith("live_candidate_marked_available:") for reason in result["reason_codes"])


def test_rebaseline_id_lists_reject_malformed_values_without_raising(tmp_path: Path) -> None:
    verifier = _verifier_module()
    inventory = _fixture_inventory(verifier, tmp_path)
    base_checklist = verifier.build_review_required_checklist(inventory)
    for missing_value in ("missing", None):
        checklist = deepcopy(base_checklist)
        checklist["historical_tombstones"] = []
        if missing_value == "missing":
            checklist.pop("baseline_preservation", None)
        else:
            checklist["baseline_preservation"] = None

        result = verifier.validate_disposition_checklist(inventory, checklist)

        assert result["status"] == "REJECTED"
        assert "checklist_baseline_preservation_invalid" in result["reason_codes"]

    cases = (
        (
            "baseline_candidate_ids_in_order",
            [{}] + [f"baseline-{index}" for index in range(388)],
            "checklist_baseline_389_ids_invalid",
        ),
        (
            "previous_445_candidate_ids_in_order",
            None,
            "checklist_previous_445_ids_invalid",
        ),
        (
            "previous_445_candidate_ids_in_order",
            [{}] + [f"previous-{index}" for index in range(444)],
            "checklist_previous_445_ids_invalid",
        ),
        (
            "removed_to_historical_tombstones",
            None,
            "checklist_tombstone_archive_ids_invalid",
        ),
        (
            "removed_to_historical_tombstones",
            [{}],
            "checklist_tombstone_archive_ids_invalid",
        ),
        (
            "new_g6_candidate_ids",
            None,
            "checklist_new_g6_candidate_ids_invalid",
        ),
        (
            "new_g6_candidate_ids",
            [{}] + [f"new-{index}" for index in range(20)],
            "checklist_new_g6_candidate_ids_invalid",
        ),
    )

    for field, invalid_value, expected_reason in cases:
        checklist = deepcopy(base_checklist)
        checklist["baseline_preservation"] = {
            "baseline_candidate_ids_in_order": [f"baseline-{index}" for index in range(389)],
            "baseline_disposition_payload_sha256": "0" * 64,
            "previous_445_candidate_ids_in_order": [f"previous-{index}" for index in range(445)],
            "previous_445_disposition_payload_sha256": "0" * 64,
            "removed_to_historical_tombstones": [],
            "new_g6_candidate_ids": [f"new-{index}" for index in range(21)],
        }
        checklist["baseline_preservation"][field] = invalid_value

        result = verifier.validate_disposition_checklist(inventory, checklist)

        assert result["status"] == "REJECTED"
        assert expected_reason in result["reason_codes"]


def test_checked_in_disposition_checklist_covers_current_inventory() -> None:
    verifier = _verifier_module()
    checklist = json.loads(CHECKLIST_PATH.read_text(encoding="utf-8"))
    collector = verifier._load_inventory_collector()
    inventory = collector.collect_inventory(REPOSITORY_ROOT)

    result = verifier.validate_disposition_checklist(inventory, checklist)

    assert result["status"] == "PASS", result["reason_codes"]
    expected_count = (
        inventory["counts"]["writer_candidates"]
        + inventory["counts"]["dynamic_execution_candidates"]
    )
    assert result["discovered_candidate_count"] == expected_count
    assert result["checklist_entry_count"] == expected_count
    assert result["review_required_count"] == expected_count
    assert result["historical_tombstone_count"] == 6
    assert result["evidence_boundary"].endswith("NOT_LIVE_ADMISSION")

    missing_preservation = deepcopy(checklist)
    del missing_preservation["baseline_preservation"]
    missing_result = verifier.validate_disposition_checklist(inventory, missing_preservation)
    assert missing_result["status"] == "REJECTED"
    assert "checklist_baseline_preservation_invalid" in missing_result["reason_codes"]

    missing_history = deepcopy(checklist)
    for field in ("baseline_preservation", "historical_tombstones", "tombstone_lineage"):
        missing_history.pop(field, None)
    missing_history_result = verifier.validate_disposition_checklist(inventory, missing_history)
    assert missing_history_result["status"] == "REJECTED"
    assert "checklist_baseline_preservation_invalid" in missing_history_result["reason_codes"]

    missing_lineage = deepcopy(checklist)
    del missing_lineage["tombstone_lineage"]
    lineage_result = verifier.validate_disposition_checklist(inventory, missing_lineage)
    assert lineage_result["status"] == "REJECTED"
    assert "checklist_tombstone_lineage_mismatch" in lineage_result["reason_codes"]


def test_expanded_dispositions_preserve_old_389_and_fence_new_candidates() -> None:
    verifier = _verifier_module()
    checklist = json.loads(CHECKLIST_PATH.read_text(encoding="utf-8"))
    collector = verifier._load_inventory_collector()
    inventory = collector.collect_inventory(REPOSITORY_ROOT)
    records = verifier.candidate_records(inventory)

    preservation = checklist["baseline_preservation"]
    old_ids = preservation["baseline_candidate_ids_in_order"]
    assert len(old_ids) == 389
    assert verifier._records_digest([{"candidate_id": value} for value in old_ids]) == (
        "e482c7b95050c4573e10d0ee46829470877936cdd9f87f228772f82cf0327f7e"
    )
    all_preserved = {
        entry["candidate_id"]: entry
        for entry in checklist["entries"] + checklist["historical_tombstones"]
    }
    old_entries = [all_preserved[candidate_id] for candidate_id in old_ids]
    old_payload = json.dumps(
        old_entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert hashlib.sha256(old_payload).hexdigest() == (
        "aec51e6b4e4c186fe959c86868a96bdfb8e14c5bbf1da539793ee48b89d54d27"
    )

    current_ids = {record["candidate_id"] for record in records}
    previous_ids = preservation["previous_445_candidate_ids_in_order"]
    assert len(previous_ids) == 445
    previous_id_set = set(previous_ids)
    tombstone_ids = {entry["candidate_id"] for entry in checklist["historical_tombstones"]}
    expected_tombstones = {
        "i41-writer-8eb4d6d3af6bfe6363a8",
        "i41-writer-78a383b74fdb54d3cd7d",
        "i41-writer-53c79013abdaf0c12bb1",
        "i41-writer-c365b35e32c5c8eb3c54",
        "i41-writer-d23e870f6f57d76a755e",
        "i41-writer-fbe05d71d70ed65a9838",
    }
    assert tombstone_ids == expected_tombstones
    assert previous_id_set - current_ids == tombstone_ids
    assert current_ids - previous_id_set == set(preservation["new_g6_candidate_ids"])
    assert len(current_ids) == 460
    assert len(checklist["entries"]) == 460
    assert len(checklist["historical_tombstones"]) == 6
    assert all(
        row["disposition"] == "REVIEW_REQUIRED"
        and row["availability"] == "NOT_AVAILABLE"
        and row["route"] == verifier.UNRESOLVED_LIVE_ROUTE
        for row in checklist["historical_tombstones"]
    )
    added_ids = [
        record["candidate_id"]
        for record in records
        if record["candidate_id"] not in previous_id_set
    ]
    assert set(added_ids) == set(preservation["new_g6_candidate_ids"])
    assert len(added_ids) == 21
    assert (
        hashlib.sha256(("".join(value + "\n" for value in sorted(added_ids))).encode()).hexdigest()
        == "e26be8d85edacdfaac78a77cc6f3b7ac109e6f9bf21c5906bc672b419fe24866"
    )
    added_entries = [
        entry for entry in checklist["entries"] if entry["candidate_id"] in set(added_ids)
    ]
    assert all(
        entry["disposition"] == "REVIEW_REQUIRED"
        and entry["availability"] == "NOT_AVAILABLE"
        and entry["route"] == verifier.UNRESOLVED_LIVE_ROUTE
        for entry in added_entries
    )
    assert checklist["source_inventory_counts"] == inventory["counts"]
    assert checklist["source_inventory_candidate_digest"] == verifier._records_digest(records)
    assert checklist["source_inventory_counts"] == {
        "writer_candidates": 363,
        "dynamic_execution_candidates": 97,
        "files_scanned": 355,
        "parse_errors": 0,
    }
    old_445_rows = [all_preserved[candidate_id] for candidate_id in previous_ids]
    old_445_payload = json.dumps(
        old_445_rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    assert hashlib.sha256(old_445_payload).hexdigest() == (
        "3528389a43ca3b8113d0cd1fa8564e0349e55d94cb9ee9bd254fb368cb35dd6c"
    )

    result = verifier.validate_disposition_checklist(inventory, checklist)
    assert result["status"] == "PASS", result["reason_codes"]
    assert result["review_required_count"] == 460
