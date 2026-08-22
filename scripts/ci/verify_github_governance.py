"""Verify GitHub governance configuration against the tracked manifests.

The verifier deliberately has no GitHub client and no credential handling. A
maintainer exports sanitized read-only API responses with ``gh api`` and passes
their paths here. Local-only syntax checks are available for development, but
they are never evidence that a Ruleset or CODEOWNERS is live on GitHub.

Exit code: 0 = consistent, 1 = a missing proof or configuration difference.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_REPO_ROOT = Path(__file__).resolve().parents[2]

_LONG_BRANCHES = ("dev", "development", "master")
_REQUIRED_RULE_TYPES = {"deletion", "non_fast_forward", "pull_request", "required_status_checks"}

# Owner tokens that must never appear in CODEOWNERS (D2 forbids placeholders).
_PLACEHOLDER_OWNERS = {"todo", "placeholder", "owner", "xxx", "example", "someone", "me"}

_OWNER_RE = re.compile(r"^@[\w-]+(?:/[\w-]+)?$")


def parse_codeowners(content: str) -> List[Tuple[str, List[str]]]:
    """Parse a CODEOWNERS file into ``(pattern, [owners])`` pairs."""
    entries: List[Tuple[str, List[str]]] = []
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " #" in line:
            line = line.split(" #", 1)[0].strip()
        parts = line.split()
        if len(parts) >= 2:
            entries.append((parts[0], parts[1:]))
    return entries


def validate_codeowners(entries: List[Tuple[str, List[str]]]) -> List[str]:
    """Return syntax/placeholder findings for parsed CODEOWNERS entries."""
    findings: List[str] = []
    for pattern, owners in entries:
        for owner in owners:
            name = owner.lstrip("@").split("/", 1)[0].lower()
            if name in _PLACEHOLDER_OWNERS:
                findings.append(f"{pattern}: placeholder owner {owner!r} is not allowed")
            elif not _OWNER_RE.match(owner):
                findings.append(
                    f"{pattern}: invalid owner {owner!r} (expected @username or @org/team)"
                )
    return findings


def _branch_for_ruleset(ruleset: Dict[str, Any]) -> Optional[str]:
    include = ruleset.get("conditions", {}).get("ref_name", {}).get("include", [])
    for ref in include:
        if isinstance(ref, str) and ref.startswith("refs/heads/"):
            return ref[len("refs/heads/") :]
    return None


def _rules_by_type(ruleset: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        rule["type"]: rule
        for rule in ruleset.get("rules", [])
        if isinstance(rule, dict) and isinstance(rule.get("type"), str)
    }


def _status_check_contexts(ruleset: Dict[str, Any]) -> List[str]:
    rule = _rules_by_type(ruleset).get("required_status_checks")
    if rule is None:
        return []
    checks = rule.get("parameters", {}).get("required_status_checks", [])
    return [check.get("context", "") for check in checks if isinstance(check, dict)]


def _check_pull_request_rule(
    branch: str, expected: Dict[str, Any], actual: Dict[str, Any]
) -> List[str]:
    """Compare explicitly tracked pull-request parameters."""
    findings: List[str] = []
    expected_rule = _rules_by_type(expected).get("pull_request", {})
    actual_rule = _rules_by_type(actual).get("pull_request", {})
    expected_parameters = expected_rule.get("parameters", {})
    actual_parameters = actual_rule.get("parameters", {})
    for key, expected_value in expected_parameters.items():
        actual_value = actual_parameters.get(key)
        if actual_value != expected_value:
            findings.append(
                f"{branch}: pull_request.{key} is {actual_value!r}, expected {expected_value!r}"
            )
    return findings


def check_ruleset_coverage(
    api_rulesets: List[Dict[str, Any]],
    manifests: Dict[str, Dict[str, Any]],
    expected_enforcement: Optional[str] = None,
) -> List[str]:
    """Compare a Rulesets API response against all long-lived branch manifests."""
    findings: List[str] = []
    by_branch: Dict[str, List[Dict[str, Any]]] = {}
    for ruleset in api_rulesets:
        branch = _branch_for_ruleset(ruleset)
        if branch is not None:
            by_branch.setdefault(branch, []).append(ruleset)

    for branch in _LONG_BRANCHES:
        expected = manifests.get(branch)
        if expected is None:
            findings.append(f"{branch}: missing manifest under .github/governance/rulesets/")
            continue

        matches = by_branch.get(branch, [])
        if not matches:
            findings.append(f"{branch}: no ruleset covers refs/heads/{branch}")
            continue
        if len(matches) != 1:
            findings.append(
                f"{branch}: expected exactly one matching ruleset, found {len(matches)}"
            )
            continue

        actual = matches[0]
        if actual.get("name") != expected.get("name"):
            findings.append(
                f"{branch}: ruleset name is {actual.get('name')!r}, expected {expected.get('name')!r}"
            )
        if actual.get("target") != expected.get("target"):
            findings.append(
                f"{branch}: ruleset target is {actual.get('target')!r}, expected {expected.get('target')!r}"
            )
        if actual.get("conditions") != expected.get("conditions"):
            findings.append(f"{branch}: ruleset conditions differ from the manifest")

        wanted_enforcement = expected_enforcement or expected.get("enforcement")
        if actual.get("enforcement") != wanted_enforcement:
            findings.append(
                f"{branch}: ruleset enforcement is {actual.get('enforcement')!r}, "
                f"expected {wanted_enforcement!r}"
            )

        expected_rules = _rules_by_type(expected)
        actual_rules = _rules_by_type(actual)
        missing_types = _REQUIRED_RULE_TYPES - set(actual_rules)
        if missing_types:
            findings.append(f"{branch}: missing required rule types {sorted(missing_types)}")
        unexpected_types = set(actual_rules) - set(expected_rules)
        if unexpected_types:
            findings.append(f"{branch}: unexpected rule types {sorted(unexpected_types)}")

        expected_contexts = set(_status_check_contexts(expected))
        actual_contexts = set(_status_check_contexts(actual))
        missing_contexts = expected_contexts - actual_contexts
        extra_contexts = actual_contexts - expected_contexts
        if missing_contexts:
            findings.append(f"{branch}: missing required status checks {sorted(missing_contexts)}")
        if extra_contexts:
            findings.append(f"{branch}: unexpected required status checks {sorted(extra_contexts)}")

        findings.extend(_check_pull_request_rule(branch, expected, actual))

    return findings


def check_codeowners_api_errors(response: Any) -> List[str]:
    """Normalize GitHub's codeowners/errors response into findings."""
    if isinstance(response, dict):
        errors = response.get("errors")
        if errors is None:
            message = response.get("message", "response has no 'errors' field")
            return [f"codeowners/errors API response is not valid: {message}"]
    elif isinstance(response, list):
        errors = response
    else:
        return ["codeowners/errors API response must be an object or array"]

    if not isinstance(errors, list):
        return ["codeowners/errors API response contains a non-list 'errors' field"]
    return [
        f"CODEOWNERS API error: {json.dumps(error, ensure_ascii=False, sort_keys=True)}"
        for error in errors
    ]


def load_manifests(directory: Path) -> Dict[str, Dict[str, Any]]:
    """Load all ``*.json`` manifests keyed by their ``branch`` field."""
    manifests: Dict[str, Dict[str, Any]] = {}
    if not directory.is_dir():
        return manifests
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        branch = data.get("branch")
        if isinstance(branch, str):
            manifests[branch] = data
    return manifests


def _load_json(path: Path, label: str) -> Tuple[Optional[Any], Optional[str]]:
    if not path.is_file():
        return None, f"{label} file not found: {path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as error:
        return None, f"{label} file is not valid JSON: {error}"


def _ruleset_list(response: Any) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    if isinstance(response, list) and all(isinstance(item, dict) for item in response):
        return response, None
    if isinstance(response, dict) and isinstance(response.get("rulesets"), list):
        rulesets = response["rulesets"]
        if all(isinstance(item, dict) for item in rulesets):
            return rulesets, None
    return None, "Rulesets API response must be a JSON array of objects"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify GitHub governance config against the in-repo manifests."
    )
    parser.add_argument(
        "--rulesets-json",
        type=Path,
        help="Sanitized JSON from `gh api repos/OWNER/REPO/rulesets`.",
    )
    parser.add_argument(
        "--codeowners-errors-json",
        type=Path,
        help="Sanitized JSON from `gh api repos/OWNER/REPO/codeowners/errors`.",
    )
    parser.add_argument(
        "--expected-enforcement",
        choices=("active", "disabled", "evaluate"),
        help="Override the manifest enforcement for a time-bounded rollout check.",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Only validate tracked manifests and local CODEOWNERS syntax; not deployment evidence.",
    )
    parser.add_argument(
        "--codeowners",
        type=Path,
        default=_REPO_ROOT / ".github" / "CODEOWNERS",
        help="Path to the CODEOWNERS file (default: repository file).",
    )
    parser.add_argument(
        "--manifests-dir",
        type=Path,
        default=_REPO_ROOT / ".github" / "governance" / "rulesets",
        help="Directory containing dev/development/master manifest JSON files.",
    )
    args = parser.parse_args(argv)

    findings: List[str] = []
    try:
        manifests = load_manifests(args.manifests_dir)
    except (OSError, json.JSONDecodeError) as error:
        manifests = {}
        findings.append(f"unable to load ruleset manifests: {error}")
    if set(manifests) != set(_LONG_BRANCHES):
        findings.append(
            "ruleset manifests must cover exactly dev, development, master; "
            f"found {sorted(manifests)}"
        )

    if args.codeowners.is_file():
        content = args.codeowners.read_text(encoding="utf-8")
        findings.extend(validate_codeowners(parse_codeowners(content)))
    else:
        findings.append(f"CODEOWNERS not found at {args.codeowners}")

    if args.rulesets_json is None:
        if not args.local_only:
            findings.append("missing --rulesets-json; local syntax is not live Ruleset evidence")
    else:
        response, error = _load_json(args.rulesets_json, "Rulesets API response")
        if error is not None:
            findings.append(error)
        else:
            rulesets, error = _ruleset_list(response)
            if error is not None:
                findings.append(error)
            else:
                findings.extend(
                    check_ruleset_coverage(rulesets, manifests, args.expected_enforcement)
                )

    if args.codeowners_errors_json is None:
        if not args.local_only:
            findings.append(
                "missing --codeowners-errors-json; local syntax is not GitHub CODEOWNERS evidence"
            )
    else:
        response, error = _load_json(args.codeowners_errors_json, "CODEOWNERS API response")
        if error is not None:
            findings.append(error)
        else:
            findings.extend(check_codeowners_api_errors(response))

    if findings:
        for finding in findings:
            print(f"[FAIL] {finding}")
        return 1

    if args.local_only:
        print(
            "[OK] local governance manifests and CODEOWNERS syntax are valid (remote proof skipped)"
        )
    else:
        print("[OK] GitHub governance config matches manifests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
