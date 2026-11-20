"""Regression tests for the tracked build-artifact CI guard."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ci import check_tracked_build_artifacts as guard  # noqa: E402


def test_only_the_three_iteration51_evidence_paths_are_exempt():
    evidence_prefix = (
        "docs/_internal/opts/requirements/"
        "迭代51-因子流批一体与Alpha003-SimNow实盘示例/"
        "evidence/capacity87-corrected-rss-20261027/build/"
    )
    evidence_paths = {
        evidence_prefix + "completion.json",
        evidence_prefix + "launch.json",
        evidence_prefix + "result.json",
    }

    assert len(evidence_paths) == 3
    assert evidence_paths == guard._ALLOWED_EVIDENCE_PATHS
    assert guard.find_tracked_build_artifacts(evidence_paths) == []


def test_similar_evidence_paths_remain_rejected():
    allowed = next(
        path for path in guard._ALLOWED_EVIDENCE_PATHS if path.endswith("/build/result.json")
    )
    near_matches = [
        allowed.replace("capacity87-corrected-rss-20261027", "capacity87-corrected-rss-20261028"),
        allowed.replace("result.json", "result-copy.json"),
        allowed.replace("/build/", "/dist/"),
    ]

    assert guard.find_tracked_build_artifacts(near_matches) == near_matches


def test_nested_build_dist_and_egg_info_paths_remain_rejected():
    paths = [
        "package/src/build/generated.py",
        "docs/fixtures/dist/backtrader.whl",
        "vendor/example.egg-info/PKG-INFO",
    ]

    assert guard.find_tracked_build_artifacts(paths) == paths


def test_unrelated_evidence_json_is_not_rejected():
    paths = ["docs/evidence/capacity87/result.json", "tests/fixtures/build_result.json"]

    assert guard.find_tracked_build_artifacts(paths) == []


def test_guard_preserves_nonzero_failure_for_any_remaining_match(monkeypatch, capsys):
    violation = "package/dist/backtrader.whl"
    monkeypatch.setattr(guard, "read_tracked_paths", lambda: [violation])

    assert guard.main() == 1
    assert capsys.readouterr().out == (
        "Tracked build artifacts are not allowed:\n" + violation + "\n"
    )
