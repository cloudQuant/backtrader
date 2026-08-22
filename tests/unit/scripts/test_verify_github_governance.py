"""Tests for the offline GitHub-governance verifier.

Fixtures are sanitized in-memory dictionaries. They never contact GitHub.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ci.verify_github_governance import (  # noqa: E402
    check_codeowners_api_errors,
    check_ruleset_coverage,
    load_manifests,
    main,
    parse_codeowners,
    validate_codeowners,
)


def _manifests() -> dict:
    return load_manifests(_REPO_ROOT / ".github" / "governance" / "rulesets")


def _api_rulesets() -> list[dict]:
    """Build an API-shaped response from each tracked manifest."""
    rulesets: list[dict] = []
    for manifest in _manifests().values():
        rulesets.append(
            {
                "name": manifest["name"],
                "target": manifest["target"],
                "enforcement": manifest["enforcement"],
                "conditions": manifest["conditions"],
                "rules": manifest["rules"],
            }
        )
    return rulesets


# ---------------------------------------------------------------------------
# CODEOWNERS parsing and validation
# ---------------------------------------------------------------------------


def test_parse_codeowners_skips_comments_and_blanks():
    content = "# a comment\n\n   \n/backtrader/cerebro.py   @cloudQuant\n"
    entries = parse_codeowners(content)
    assert entries == [("/backtrader/cerebro.py", ["@cloudQuant"])]


def test_parse_codeowners_extracts_multiple_owners_and_inline_comment():
    content = "/scripts/ @octocat @org/team # inline comment\n"
    entries = parse_codeowners(content)
    assert entries == [("/scripts/", ["@octocat", "@org/team"])]


def test_validate_codeowners_rejects_placeholder():
    findings = validate_codeowners([("/backtrader/cerebro.py", ["@TODO"])])
    assert findings
    assert any("placeholder" in finding.lower() for finding in findings)


def test_validate_codeowners_accepts_user_and_team():
    entries = [
        ("/backtrader/cerebro.py", ["@cloudQuant"]),
        ("/scripts/", ["@cloudQuant/core-maintainers"]),
    ]
    assert validate_codeowners(entries) == []


def test_validate_codeowners_rejects_non_owner_token():
    findings = validate_codeowners([("/backtrader/cerebro.py", ["docs@example.com"])])
    assert findings


def test_codeowners_api_errors_accepts_empty_response():
    assert check_codeowners_api_errors({"errors": []}) == []


def test_codeowners_api_errors_reports_api_payload():
    findings = check_codeowners_api_errors({"errors": [{"kind": "invalid_owner"}]})
    assert findings
    assert "invalid_owner" in findings[0]


def test_codeowners_api_errors_reports_not_found_response():
    findings = check_codeowners_api_errors({"message": "Not Found"})
    assert findings
    assert "Not Found" in findings[0]


# ---------------------------------------------------------------------------
# Ruleset coverage
# ---------------------------------------------------------------------------


def test_ruleset_coverage_passes_when_all_branches_match_manifests():
    assert check_ruleset_coverage(_api_rulesets(), _manifests()) == []


def test_ruleset_coverage_reports_missing_branch():
    api = [ruleset for ruleset in _api_rulesets() if ruleset["name"] != "master-ruleset"]
    findings = check_ruleset_coverage(api, _manifests())
    assert any("master" in finding for finding in findings)


def test_ruleset_coverage_reports_wrong_enforcement():
    api = _api_rulesets()
    for ruleset in api:
        if ruleset["name"] == "development-ruleset":
            ruleset["enforcement"] = "active"
    findings = check_ruleset_coverage(api, _manifests())
    assert any("development" in finding and "enforcement" in finding for finding in findings)


def test_ruleset_coverage_reports_missing_required_check():
    api = _api_rulesets()
    for ruleset in api:
        if ruleset["name"] == "dev-ruleset":
            checks = next(
                rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks"
            )
            checks["parameters"]["required_status_checks"] = [{"context": "Lint"}]
    findings = check_ruleset_coverage(api, _manifests())
    assert any("missing required status checks" in finding for finding in findings)


def test_ruleset_coverage_reports_pull_request_parameter_drift():
    api = _api_rulesets()
    for ruleset in api:
        if ruleset["name"] == "master-ruleset":
            rule = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")
            rule["parameters"]["require_code_owner_review"] = False
    findings = check_ruleset_coverage(api, _manifests())
    assert any("require_code_owner_review" in finding for finding in findings)


def test_manifests_are_valid_json_and_cover_three_branches():
    manifests = _manifests()
    assert set(manifests) == {"dev", "development", "master"}
    for branch, manifest in manifests.items():
        json.dumps(manifest)
        assert manifest["branch"] == branch
        assert manifest["enforcement"] == "evaluate"


# ---------------------------------------------------------------------------
# Command-line proof requirements
# ---------------------------------------------------------------------------


def test_main_requires_remote_proofs_by_default():
    assert main([]) == 1


def test_main_allows_explicit_local_only_check():
    assert main(["--local-only"]) == 0
