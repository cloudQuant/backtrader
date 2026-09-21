#!/usr/bin/env python
"""Offline, secret-safe readiness inspection for the Iteration 22 CTP pilot.

This utility deliberately does *not* import a CTP SDK, construct a Store, open
a socket, or submit a CTP request.  It is an operator aid for checking the
local prerequisites before running the existing Iteration 22 runner.  In
particular, it must not be treated as an admission decision: G1/G2/G3 evidence
and a signed admission receipt are verified only at the runner's controlled
network boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import yaml


HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.yaml"
DEFAULT_ENV_FILE = HERE / ".env"
SCHEMA_VERSION = "iter22.operator-readiness.v1"
CALENDAR_SCHEMA_VERSION = "iter22.czce-trading-calendar.v1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
FROZEN_PROFILES = {
    "simnow_first_group1": {
        "kind": "simnow",
        "market_alignment": "actual_market_hours",
        "td_front": "tcp://180.168.146.187:10201",
        "md_front": "tcp://180.168.146.187:10211",
    },
    "simnow_first_group2": {
        "kind": "simnow",
        "market_alignment": "actual_market_hours",
        "td_front": "tcp://180.168.146.187:10202",
        "md_front": "tcp://180.168.146.187:10212",
    },
    "simnow_second_7x24": {
        "kind": "simnow",
        "market_alignment": "engineering_only",
        "td_front": "tcp://180.168.146.187:10130",
        "md_front": "tcp://180.168.146.187:10131",
    },
}

# Keep this list aligned with ``run.credentials``.  The report uses only the
# canonical names; it never serializes an environment value or an alias value.
SIMNOW_CREDENTIAL_ALIASES = {
    "CTP_USER_ID": ("CTP_USER_ID", "SIMNOW_USER_ID", "simnow_user_id"),
    "CTP_PASSWORD": ("CTP_PASSWORD", "SIMNOW_PASSWORD", "simnow_password"),
    "CTP_BROKER_ID": ("CTP_BROKER_ID", "SIMNOW_BROKER_ID", "simnow_broker_id"),
    "CTP_APP_ID": ("CTP_APP_ID", "SIMNOW_APP_ID", "simnow_app_id"),
    "CTP_AUTH_CODE": ("CTP_AUTH_CODE", "SIMNOW_AUTH_CODE", "simnow_auth_code"),
}
FRONT_OVERRIDE_ALIASES = {
    "td": ("CTP_TD_FRONT", "SIMNOW_TD_FRONT", "simnow_td_front"),
    "md": ("CTP_MD_FRONT", "SIMNOW_MD_FRONT", "simnow_md_front"),
}
APPROVAL_KEYS = ("ITER22_APPROVAL_KEY_ID", "ITER22_APPROVAL_HMAC_KEY")
RELEVANT_ENVIRONMENT_KEYS = (
    frozenset(name for aliases in SIMNOW_CREDENTIAL_ALIASES.values() for name in aliases)
    | frozenset(name for aliases in FRONT_OVERRIDE_ALIASES.values() for name in aliases)
    | frozenset(APPROVAL_KEYS)
    | frozenset({"ITER22_SIMNOW_PROFILE"})
)
PLACEHOLDER_VALUES = frozenset(
    {
        "change-me",
        "change_me",
        "changeme",
        "example",
        "replace-me",
        "replace_me",
        "todo",
        "none",
        "null",
    }
)
RESEARCH_STATUSES = frozenset(
    {"RESEARCH_NOT_ESTABLISHED", "RESEARCH_ADMITTED", "RESEARCH_REJECTED"}
)


def _safe_issue(code: str) -> str:
    """Return a fixed diagnostic code, never an exception/secret payload."""

    return code


def _is_configured(value: object) -> bool:
    """Return whether a local setting is nonempty and not an obvious placeholder."""

    normalized = str(value or "").strip()
    if not normalized:
        return False
    lower = normalized.lower()
    if lower in PLACEHOLDER_VALUES or lower.startswith("your_"):
        return False
    return not (
        (normalized.startswith("<") and normalized.endswith(">"))
        or (normalized.startswith("${") and normalized.endswith("}"))
    )


def _resolve_config_path(value: Path | str) -> Path:
    """Mirror the Iteration 22 runner's relative-config lookup behavior."""

    path = Path(value)
    if not path.is_absolute():
        example_candidate = HERE / path
        path = example_candidate if example_candidate.exists() else path.resolve()
    return path.resolve()


def _read_dotenv(path: Path) -> Tuple[Dict[str, str], bool]:
    """Read simple dotenv assignments without evaluating shell syntax.

    Values are kept only in this function's return mapping and are never put
    into the readiness report or copied into ``os.environ``.
    """

    if not path.is_file():
        return {}, False
    values: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        # The caller reports the file as present but simply obtains no usable
        # values.  Do not expose an exception whose message could contain a
        # sensitive filename or content.
        return {}, True
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values, True


def _effective_environment(
    dotenv_values: Mapping[str, str], process_environment: Mapping[str, str]
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return runner-compatible values plus their non-sensitive origins."""

    values = dict(dotenv_values)
    origins = dict.fromkeys(dotenv_values, "dotenv")
    # ``run._load_env_file`` does not replace any pre-existing process value,
    # including an intentionally blank value.  Preserve that precise
    # precedence without mutating process state.
    for key, value in process_environment.items():
        if key in values or key in RELEVANT_ENVIRONMENT_KEYS:
            values[str(key)] = str(value)
            origins[str(key)] = "process"
    return values, origins


def _configured_alias(
    names: Sequence[str], values: Mapping[str, str], origins: Mapping[str, str]
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Find the first configured alias, returning no setting value."""

    for name in names:
        if _is_configured(values.get(name)):
            return True, name, origins.get(name)
    return False, None, None


def _credential_readiness(values: Mapping[str, str], origins: Mapping[str, str]) -> Dict[str, Any]:
    """Summarize SimNow credential presence without emitting their contents."""

    configured = []
    missing = []
    aliases = {}
    sources = {}
    for canonical, names in SIMNOW_CREDENTIAL_ALIASES.items():
        present, alias, source = _configured_alias(names, values, origins)
        # The established runner defaults an omitted broker id to SimNow's
        # broker identifier.  It is non-secret and does not make another
        # credential optional.
        if canonical == "CTP_BROKER_ID" and not present:
            present, alias, source = True, "runner_default", "runner_default"
        if present:
            configured.append(canonical)
            aliases[canonical] = alias
            sources[canonical] = source
        else:
            missing.append(canonical)
    return {
        "ready": not missing,
        "configured": configured,
        "missing": missing,
        "sources": sources,
        "aliases_used": aliases,
    }


def _approval_readiness(values: Mapping[str, str], origins: Mapping[str, str]) -> Dict[str, Any]:
    """Summarize the local approval trust root without exposing it."""

    configured = []
    missing = []
    invalid = []
    sources = {}
    for name in APPROVAL_KEYS:
        value = values.get(name)
        if not _is_configured(value):
            missing.append(name)
            continue
        if name == "ITER22_APPROVAL_HMAC_KEY" and len(str(value).encode("utf-8")) < 32:
            invalid.append(name)
            continue
        configured.append(name)
        sources[name] = origins.get(name)
    return {
        "ready": not missing and not invalid,
        "configured": configured,
        "missing": missing,
        "invalid": invalid,
        "sources": sources,
    }


def _sha256_file(path: Path) -> str:
    """Hash an artifact in bounded chunks without retaining its contents."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _calendar_readiness(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Check the local, hash-bound calendar contract without querying an exchange."""

    calendar = config.get("trading_calendar")
    if not isinstance(calendar, Mapping):
        return {
            "ready": False,
            "artifact_configured": False,
            "hash_configured": False,
            "artifact_exists": False,
            "hash_matches": None,
            "contract_valid": None,
            "coverage": "NOT_EVALUATED_OFFLINE",
            "issues": [_safe_issue("calendar_configuration_missing")],
        }

    artifact_name = str(calendar.get("artifact") or "").strip()
    expected_hash = str(calendar.get("sha256") or "").strip().lower()
    result: Dict[str, Any] = {
        "ready": False,
        "artifact_configured": bool(artifact_name),
        "hash_configured": bool(HEX64.fullmatch(expected_hash)),
        "artifact_exists": False,
        "hash_matches": None,
        "contract_valid": None,
        "coverage": "NOT_EVALUATED_OFFLINE",
        "issues": [],
    }
    if artifact_name:
        artifact = Path(artifact_name)
        if not artifact.is_absolute():
            # This intentionally matches ``run._load_trading_calendar``:
            # relative artifact paths are rooted at the example, not the
            # caller's current directory or a custom config's parent.
            artifact = HERE / artifact
        artifact = artifact.resolve()
        result["artifact_exists"] = artifact.is_file()
    else:
        result["issues"].append(_safe_issue("calendar_artifact_missing"))
        artifact = None
    if not expected_hash:
        result["issues"].append(_safe_issue("calendar_hash_missing"))
    elif not HEX64.fullmatch(expected_hash):
        result["issues"].append(_safe_issue("calendar_hash_invalid"))
    if artifact is None or not artifact.is_file():
        if artifact is not None:
            result["issues"].append(_safe_issue("calendar_artifact_unavailable"))
        return result
    if not HEX64.fullmatch(expected_hash):
        return result
    try:
        actual_hash = _sha256_file(artifact)
    except OSError:
        result["issues"].append(_safe_issue("calendar_artifact_unreadable"))
        return result
    result["hash_matches"] = actual_hash == expected_hash
    if not result["hash_matches"]:
        result["issues"].append(_safe_issue("calendar_hash_mismatch"))
        return result
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        result["issues"].append(_safe_issue("calendar_artifact_invalid_json"))
        return result
    contract_issues = _calendar_contract_issues(payload)
    result["contract_valid"] = not contract_issues
    result["issues"].extend(contract_issues)
    result["ready"] = not result["issues"]
    return result


def _calendar_contract_issues(payload: object) -> list[str]:
    """Return only fixed codes for the runner's calendar artifact contract."""

    if not isinstance(payload, Mapping):
        return [_safe_issue("calendar_artifact_contract_invalid")]
    if (
        payload.get("schema_version") != CALENDAR_SCHEMA_VERSION
        or str(payload.get("exchange") or "").upper() not in {"CZCE", "ZCE"}
        or not str(payload.get("source") or "").strip()
        or not str(payload.get("as_of_utc") or "").strip()
        or not isinstance(payload.get("trading_days"), list)
    ):
        return [_safe_issue("calendar_artifact_contract_invalid")]
    days = []
    for raw_day in payload["trading_days"]:
        text = str(raw_day).replace("-", "")
        try:
            days.append(datetime.strptime(text, "%Y%m%d").date())
        except ValueError:
            return [_safe_issue("calendar_trading_days_invalid")]
    if days != sorted(set(days)):
        return [_safe_issue("calendar_trading_days_not_unique_ordered")]
    return []


def _load_config(path: Path) -> Tuple[Optional[Dict[str, Any]], list[str]]:
    """Load a mapping safely, returning generic issue codes on all failures."""

    if not path.is_file():
        return None, [_safe_issue("config_missing")]
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None, [_safe_issue("config_unreadable_or_invalid")]
    if not isinstance(raw, dict):
        return None, [_safe_issue("config_root_not_mapping")]
    return dict(raw), []


def _frozen_profile_contract(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Verify the no-SDK frozen SimNow profile contract used by the runner.

    A raw broker/production endpoint must never make this checker say that the
    Iteration 22 SimNow configuration is statically ready.  The comparison is
    deliberately exact and serializes only fixed diagnostic codes, never the
    received profile values.
    """

    if not isinstance(config, Mapping):
        return {"ready": False, "issues": [_safe_issue("frozen_profiles_not_evaluated")]}
    profiles = config.get("profiles")
    if not isinstance(profiles, Mapping):
        return {"ready": False, "issues": [_safe_issue("frozen_profiles_missing")]}
    issues = []
    if set(profiles) != set(FROZEN_PROFILES):
        issues.append(_safe_issue("frozen_profile_names_mismatch"))
    elif any(
        not isinstance(profiles.get(name), Mapping) or dict(profiles[name]) != expected
        for name, expected in FROZEN_PROFILES.items()
    ):
        issues.append(_safe_issue("frozen_profile_definitions_mismatch"))
    configured_environment = str(config.get("environment") or "").strip()
    if configured_environment not in FROZEN_PROFILES:
        issues.append(_safe_issue("configured_environment_not_frozen_simnow_profile"))
    return {"ready": not issues, "issues": issues}


def _profile_readiness(
    config: Optional[Mapping[str, Any]], values: Mapping[str, str], origins: Mapping[str, str]
) -> Dict[str, Any]:
    """Resolve the selected frozen SimNow profile without reaching the SDK."""

    result: Dict[str, Any] = {
        "ready": False,
        "name": None,
        "selection_source": None,
        "kind": None,
        "market_alignment": None,
        "front_pair_configured": False,
        "issues": [],
    }
    if not isinstance(config, Mapping):
        result["issues"].append(_safe_issue("profile_not_evaluated_without_config"))
        return result
    profiles = config.get("profiles")
    if not isinstance(profiles, Mapping):
        result["issues"].append(_safe_issue("profiles_missing"))
        return result
    configured_name = str(config.get("environment") or "").strip()
    override = values.get("ITER22_SIMNOW_PROFILE")
    # Match ``run.effective_profile_config`` precisely: any nonempty override
    # selects a profile, including a placeholder that will then be rejected.
    selected_name = (
        str(override).strip() if override is not None and str(override) != "" else configured_name
    )
    # An environment override is untrusted input.  Only serialize one of the
    # fixed profile names, never an arbitrary value supplied to the process.
    result["name"] = selected_name if selected_name in FROZEN_PROFILES else None
    result["selection_source"] = (
        origins.get("ITER22_SIMNOW_PROFILE")
        if override is not None and str(override) != ""
        else "config"
    )
    if not selected_name:
        result["issues"].append(_safe_issue("selected_profile_missing"))
        return result
    if selected_name not in FROZEN_PROFILES:
        result["issues"].append(_safe_issue("selected_profile_not_frozen"))
        return result
    profile = profiles.get(selected_name)
    if not isinstance(profile, Mapping):
        result["issues"].append(_safe_issue("selected_profile_unknown"))
        return result
    kind = str(profile.get("kind") or "").strip()
    alignment = str(profile.get("market_alignment") or "").strip()
    td_front = str(profile.get("td_front") or "").strip()
    md_front = str(profile.get("md_front") or "").strip()
    result.update(
        kind=kind if kind == "simnow" else None,
        market_alignment=(
            alignment if alignment in {"actual_market_hours", "engineering_only"} else None
        ),
        front_pair_configured=bool(td_front and md_front),
    )
    if kind != "simnow":
        result["issues"].append(_safe_issue("selected_profile_not_simnow"))
    if bool(td_front) != bool(md_front):
        result["issues"].append(_safe_issue("profile_front_pair_incomplete"))
    elif not td_front:
        result["issues"].append(_safe_issue("profile_front_pair_missing"))
    if alignment not in {"actual_market_hours", "engineering_only"}:
        result["issues"].append(_safe_issue("profile_market_alignment_invalid"))
    result["ready"] = not result["issues"]
    return result


def _runner_front_override(
    names: Sequence[str], values: Mapping[str, str], origins: Mapping[str, str]
) -> Tuple[str, Optional[str], Optional[str]]:
    """Mirror the runner's ``a or b or c`` front override precedence safely."""

    for name in names:
        value = values.get(name)
        if value:
            return str(value).strip(), name, origins.get(name)
    return "", None, None


def _front_override_readiness(
    profile: Mapping[str, Any],
    frozen_contract: Mapping[str, Any],
    values: Mapping[str, str],
    origins: Mapping[str, str],
) -> Dict[str, Any]:
    """Check optional TD/MD overrides against the exact frozen selected pair."""

    td_value, td_alias, td_source = _runner_front_override(
        FRONT_OVERRIDE_ALIASES["td"], values, origins
    )
    md_value, md_alias, md_source = _runner_front_override(
        FRONT_OVERRIDE_ALIASES["md"], values, origins
    )
    result: Dict[str, Any] = {
        "ready": False,
        "configured": bool(td_value or md_value),
        "td_alias": td_alias,
        "td_source": td_source,
        "md_alias": md_alias,
        "md_source": md_source,
        "state": "NOT_CONFIGURED" if not td_value and not md_value else "INVALID",
        "issues": [],
    }
    if not td_value and not md_value:
        result["ready"] = True
        return result
    if bool(td_value) != bool(md_value):
        result["issues"].append(_safe_issue("front_override_pair_incomplete"))
        return result
    selected_name = profile.get("name")
    expected = FROZEN_PROFILES.get(str(selected_name or ""))
    if not frozen_contract.get("ready") or expected is None:
        result["issues"].append(_safe_issue("front_override_not_evaluated_without_frozen_profile"))
        return result
    if td_value != expected["td_front"] or md_value != expected["md_front"]:
        result["issues"].append(_safe_issue("front_override_does_not_match_selected_profile"))
        return result
    result.update(ready=True, state="MATCHES_SELECTED_FROZEN_PROFILE")
    return result


def _merge_blockers(*collections: Iterable[str]) -> list[str]:
    """Return ordered, de-duplicated fixed readiness codes."""

    result = []
    for collection in collections:
        for item in collection:
            if item not in result:
                result.append(item)
    return result


def build_readiness_report(
    *,
    config_path: Path | str = DEFAULT_CONFIG,
    env_path: Path | str = DEFAULT_ENV_FILE,
    process_environment: Optional[Mapping[str, str]] = None,
    platform_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a local-only readiness report without opening a network connection.

    ``process_environment`` and ``platform_name`` make the function directly
    testable while the CLI defaults to the host process and operating system.
    Neither input's values are included in the returned mapping.
    """

    resolved_config = _resolve_config_path(config_path)
    resolved_env = Path(env_path).resolve()
    dotenv_values, env_file_present = _read_dotenv(resolved_env)
    effective_values, origins = _effective_environment(
        dotenv_values, os.environ if process_environment is None else process_environment
    )
    config, config_issues = _load_config(resolved_config)
    frozen_profile_contract = _frozen_profile_contract(config)
    profile = _profile_readiness(config, effective_values, origins)
    front_overrides = _front_override_readiness(
        profile, frozen_profile_contract, effective_values, origins
    )
    credentials = _credential_readiness(effective_values, origins)
    calendar = _calendar_readiness(config or {})
    raw_research_status = (
        str((config or {}).get("research", {}).get("status") or "")
        if isinstance((config or {}).get("research"), Mapping)
        else ""
    )
    research_status = (
        raw_research_status if raw_research_status in RESEARCH_STATUSES else "MISSING_OR_INVALID"
    )
    approval = _approval_readiness(effective_values, origins)

    static_blockers = _merge_blockers(
        config_issues,
        frozen_profile_contract["issues"],
        profile["issues"],
        front_overrides["issues"],
        ["simnow_credentials_missing"] if not credentials["ready"] else [],
        calendar["issues"],
    )
    static_ready = not static_blockers
    host_is_windows = (platform_name or os.name).lower() in {"nt", "windows", "win32"}

    natural_blockers = list(static_blockers)
    if profile.get("market_alignment") != "actual_market_hours":
        natural_blockers.append("natural_signal_requires_actual_market_hours_profile")
    if research_status != "RESEARCH_ADMITTED":
        natural_blockers.append("research_not_admitted")
    if not approval["ready"]:
        natural_blockers.append("approval_trust_root_missing_or_invalid")
    natural_blockers.extend(
        [
            "signed_admission_receipt_not_inspected_offline",
            "g1_g2_g3_runtime_evidence_not_inspected_offline",
        ]
    )
    if host_is_windows:
        natural_blockers.append("windows_g2_native_ctp_evidence_required")
    natural_blockers = _merge_blockers(natural_blockers)

    return {
        "schema_version": SCHEMA_VERSION,
        "inspection": {
            "scope": "offline_local_configuration_only",
            "network_accessed": False,
            "ctp_writes_submitted": False,
            "credential_values_exposed": False,
        },
        "config": {
            "loaded": config is not None,
            "issues": config_issues,
            "frozen_profile_contract": frozen_profile_contract,
        },
        "environment_file": {
            "present": env_file_present,
            "values_exposed": False,
        },
        "simnow_static": {
            "ready": static_ready,
            "profile": profile,
            "front_overrides": front_overrides,
            "credentials": credentials,
            "calendar": calendar,
            "blockers": static_blockers,
        },
        "simnow_natural_signal": {
            # A local static inspection cannot certify a signed receipt,
            # account binding, live G1/G2/G3 evidence, or an actual session.
            "ready": False,
            "verdict": "REQUIRES_CONTROLLED_RUNTIME_ADMISSION",
            "research": {
                "status": research_status,
                "admitted": research_status == "RESEARCH_ADMITTED",
            },
            "approval_trust_root": approval,
            "admission_receipt": {
                "required": True,
                "status": "NOT_INSPECTED_OFFLINE",
            },
            "runtime_gates": {
                "required": ["G1", "G2", "G3"],
                "status": "NOT_INSPECTED_OFFLINE",
            },
            "windows_g2_evidence": {
                "required": host_is_windows,
                "status": (
                    "REQUIRED_NOT_INSPECTED_OFFLINE"
                    if host_is_windows
                    else "NOT_REQUIRED_FOR_CURRENT_HOST"
                ),
            },
            "blockers": natural_blockers,
        },
        "production": {
            "ready": False,
            "supported_by_iteration22_runner": False,
            "verdict": "BLOCKED_ITER22_SIMNOW_ONLY",
            "blockers": [
                "production_requires_a_separate_ctp_profile",
                "production_requires_new_account_bound_admission",
                "production_requires_firm_specific_fronts_and_credentials",
            ],
        },
        "strict": {
            "scope": "simnow_static_only",
            "would_pass": static_ready,
        },
    }


def _write_json(path: Path, report: Mapping[str, Any]) -> None:
    """Atomically write the safe report only when the operator asks for it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI without importing any CTP-facing code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--output", type=Path, help="optional safe JSON report destination")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return nonzero unless offline SimNow static readiness passes; never certifies trading",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the inspection, print only redacted readiness metadata, and exit."""

    args = build_parser().parse_args(argv)
    report = build_readiness_report(config_path=args.config, env_path=args.env_file)
    if args.output is not None:
        _write_json(Path(args.output).resolve(), report)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return 0 if not args.strict or report["strict"]["would_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
