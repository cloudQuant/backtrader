from __future__ import annotations

import copy
import importlib.util
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest


CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = CANDIDATE_ROOT / "scripts" / "generate_iteration42_tracker.py"
SPEC = importlib.util.spec_from_file_location("iteration42_public_tracker_candidate", GENERATOR)
assert SPEC is not None and SPEC.loader is not None
tracker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tracker)

REPO_ROOT = Path(os.environ.get("ITERATION42_REPO_ROOT", str(CANDIDATE_ROOT))).resolve()
SEED_PATH = CANDIDATE_ROOT / tracker.SEED_RELATIVE


def read_seed():
    seed, _raw = tracker.load_seed_bytes(SEED_PATH.read_bytes())
    return seed


def test_fixed_eight_rows_and_public_reference_hashes():
    seed = read_seed()
    refs = tracker.verify_public_references(REPO_ROOT, seed)
    assert seed["schema"] == "iteration42-public-status-v2"
    assert seed["source_policy"] == "FIXED_HASH_PINNED_PUBLIC_RECORDS_ONLY"
    assert seed["formal_account_pass_delta"] == 0
    assert tuple(row["id"] for row in seed["examples"]) == tracker.EXAMPLE_IDS
    assert tuple(refs) == tracker.REFERENCE_IDS
    assert len(seed["examples"]) == 8
    for ref_id, ref in refs.items():
        assert ref["path"] == tracker.REFERENCE_PATHS[ref_id]
        assert len(ref["sha256"]) == 64
        assert ref["locator"]
        assert ref["claim_scope"]


def test_tracker_output_preserves_fixed_hash_policy():
    seed_bytes = SEED_PATH.read_bytes()
    result = tracker.build_tracker(REPO_ROOT, seed_bytes=seed_bytes)
    assert result["source_policy"] == "FIXED_HASH_PINNED_PUBLIC_RECORDS_ONLY"
    assert result["formal_account_pass_delta"] == 0


def test_012_research_and_approval_boundaries_cannot_be_promoted():
    for field, value in (("research_status", "PASS"), ("approval_status", "APPROVED")):
        seed = copy.deepcopy(read_seed())
        seed["examples"][0]["admission_bounds"][field] = value
        with pytest.raises(tracker.TrackerInputError, match="fixed 012"):
            tracker.validate_seed(seed)


def test_current_blocked_rows_keep_latest_result_separate_from_history():
    seed = read_seed()
    rows = {row["id"]: row for row in seed["examples"]}
    assert rows["012_1_midfreq_cross_exchange"]["historical_best"]["status"] == "MECHANICAL_DEMO_SMOKE_PASS"
    assert rows["012_1_midfreq_cross_exchange"]["latest_known_attempt"]["status"] == "MECHANICAL_DEMO_SMOKE_PASS"
    assert rows["013_3_sa_midfreq_simnow"]["latest_known_attempt"]["status"] == "FAIL"
    assert rows["014_1_ctp_options_lowfreq"]["latest_known_attempt"]["status"] == "BLOCKED"
    assert rows["014_2_ctp_options_midfreq"]["latest_known_attempt"]["status"] == "BLOCKED"
    for row_id in ("013_3_sa_midfreq_simnow", "014_1_ctp_options_lowfreq", "014_2_ctp_options_midfreq"):
        assert rows[row_id]["current_capability"]["status"] in {"BLOCKED", "UNACCEPTED_FAIL"}


def test_012_source_binding_repair_keeps_qualification_and_live_unaccepted():
    seed = read_seed()
    rows = {row["id"]: row for row in seed["examples"]}
    for row_id in ("012_1_midfreq_cross_exchange", "012_2_event_driven_cross_exchange"):
        row = rows[row_id]
        assert row["historical_best"]["status"] == "MECHANICAL_DEMO_SMOKE_PASS"
        assert row["latest_known_attempt"]["status"] == "MECHANICAL_DEMO_SMOKE_PASS"
        cap = row["current_capability"]
        assert cap["status"] == "SOURCE_BINDING_REPAIRED_QUALIFICATION_NOT_ACCEPTED"
        assert "qualification-v3.json" in cap["summary"]
        assert "no live 012 invocation was reverified" in cap["summary"].lower()
        assert {"i43_manifest_qa", "i43_binding_review"}.issubset(cap["reference_ids"])
        assert row["admission_bounds"]["research_status"] == "RESEARCH_REJECTED"
        assert row["admission_bounds"]["approval_status"] == "NOT_APPROVED"
    assert seed["formal_account_pass_delta"] == 0


def test_post43_source_only_evidence_is_fixed_hash_pinned():
    seed = read_seed()
    refs = {ref["id"]: ref for ref in seed["source_references"]}
    assert refs["i43_manifest_qa"]["sha256"] == "ee40ecafcbc9d42dbdcdc571298358af201114c6e0e4a3d4b7d7ebe24d464875"
    assert refs["i43_binding_review"]["sha256"] == "eaf19d1a9760e834836f1532844c6b18fd5440a6bc0893cc66bc215d56cd1121"


def test_public_reference_hash_mismatch_is_rejected():
    seed = copy.deepcopy(read_seed())
    seed["source_references"][0]["sha256"] = "0" * 64
    tracker.validate_seed(seed)
    with pytest.raises(tracker.TrackerInputError, match="hash mismatch"):
        tracker.verify_public_references(REPO_ROOT, seed)


def test_unapproved_public_path_is_rejected():
    seed = copy.deepcopy(read_seed())
    seed["source_references"][0]["path"] = "docs/other.json"
    with pytest.raises(tracker.TrackerInputError, match="fixed public path allowlist"):
        tracker.validate_seed(seed)


def test_unknown_schema_is_rejected():
    seed = copy.deepcopy(read_seed())
    seed["schema"] = "iteration42-public-status-v999"
    with pytest.raises(tracker.TrackerInputError, match="unknown public status schema"):
        tracker.validate_seed(seed)


def test_reparse_point_in_public_path_is_rejected():
    target = REPO_ROOT / "docs"
    real_lstat = os.lstat

    def fake_lstat(path):
        if Path(path) == target:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o755,
                st_file_attributes=tracker.REPARSE_ATTRIBUTE,
            )
        return real_lstat(path)

    with mock.patch.object(tracker.os, "lstat", side_effect=fake_lstat), \
            pytest.raises(tracker.TrackerInputError, match="reparse point"):
        tracker._checked_public_file(REPO_ROOT, tracker.REFERENCE_PATHS["audit_md"])


def test_reparse_point_in_current_example_directory_is_rejected():
    target = REPO_ROOT / "examples"
    real_lstat = os.lstat

    def fake_lstat(path):
        if Path(path) == target:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o755,
                st_file_attributes=tracker.REPARSE_ATTRIBUTE,
            )
        return real_lstat(path)

    with mock.patch.object(tracker.os, "lstat", side_effect=fake_lstat), \
            pytest.raises(tracker.TrackerInputError, match="reparse point"):
        tracker._checked_public_directory(REPO_ROOT, tracker.CURRENT_PATHS[tracker.EXAMPLE_IDS[0]])


@pytest.mark.parametrize("row_id", [
    "012_1_midfreq_cross_exchange",
    "012_2_event_driven_cross_exchange",
])
def test_latest_blocked_stays_separate_from_historical_best(row_id):
    seed = copy.deepcopy(read_seed())
    row = next(item for item in seed["examples"] if item["id"] == row_id)
    assert row["historical_best"]["status"] == "MECHANICAL_DEMO_SMOKE_PASS"
    row["latest_known_attempt"]["status"] = "BLOCKED"
    row["latest_known_attempt"]["run_id"] = None
    expected_capability = row["current_capability"]["status"]
    payload = tracker._build_payload(seed, "a" * 64)
    projected = next(item for item in payload["examples"] if item["id"] == row_id)
    assert projected["historical_best"]["status"] == "MECHANICAL_DEMO_SMOKE_PASS"
    assert projected["latest_known_attempt"]["status"] == "BLOCKED"
    assert projected["current_capability"]["status"] == expected_capability


def test_json_and_markdown_are_deterministic():
    seed_bytes = SEED_PATH.read_bytes()
    first = tracker.build_tracker(REPO_ROOT, seed_bytes=seed_bytes)
    second = tracker.build_tracker(REPO_ROOT, seed_bytes=seed_bytes)
    assert tracker.render_json(first) == tracker.render_json(second)
    assert tracker.render_markdown(first) == tracker.render_markdown(second)
    assert b"generated_utc" not in tracker.render_json(first)


def test_tracker_does_not_glob_or_scan_path_mtime():
    with mock.patch.object(Path, "glob", side_effect=AssertionError("glob is forbidden")), \
            mock.patch.object(Path, "stat", side_effect=AssertionError("mtime scan is forbidden")):
        result = tracker.build_tracker(REPO_ROOT, seed_bytes=SEED_PATH.read_bytes())
    assert len(result["examples"]) == 8
