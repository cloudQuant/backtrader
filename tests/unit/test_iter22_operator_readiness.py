"""Offline acceptance tests for the Iteration 22 operator readiness checker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "013_3_sa_midfreq_simnow"
MODULE_NAME = "iter22_operator_readiness_test_module"


def _load_module():
    existing = sys.modules.get(MODULE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(MODULE_NAME, EXAMPLE / "operator_readiness.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


readiness = _load_module()


@pytest.fixture(autouse=True)
def _remove_operator_credential_environment(monkeypatch):
    """Make CLI tests independent of an operator's ignored local credentials."""

    for name in readiness.RELEVANT_ENVIRONMENT_KEYS:
        monkeypatch.delenv(name, raising=False)


def _calendar(tmp_path: Path) -> tuple[Path, str]:
    payload = {
        "schema_version": "iter22.czce-trading-calendar.v1",
        "exchange": "CZCE",
        "source": "unit-fixture",
        "as_of_utc": "2026-09-20T00:00:00Z",
        "trading_days": ["20260921", "20260922", "20260923"],
    }
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _config(
    tmp_path: Path,
    *,
    calendar_path: Path | None = None,
    calendar_hash: str | None = None,
    research_status: str = "RESEARCH_NOT_ESTABLISHED",
    profile: str = "simnow_first_group1",
) -> Path:
    calendar_path = calendar_path or _calendar(tmp_path)[0]
    if calendar_hash is None:
        calendar_hash = hashlib.sha256(calendar_path.read_bytes()).hexdigest()
    payload = {
        "environment": profile,
        "profiles": {name: dict(value) for name, value in readiness.FROZEN_PROFILES.items()},
        "trading_calendar": {"artifact": str(calendar_path), "sha256": calendar_hash},
        "research": {"status": research_status},
    }
    path = tmp_path / "config.yaml"
    # JSON is a valid YAML subset and keeps the fixture compact and exact.
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _env(path: Path, *, include_approval: bool = True) -> tuple[str, str]:
    password = "fixture-password-must-not-escape"
    hmac_key = "fixture-hmac-key-must-not-escape-0123456789"
    lines = [
        "CTP_USER_ID=fixture-investor",
        f"CTP_PASSWORD={password}",
        "CTP_BROKER_ID=9999",
        "CTP_APP_ID=fixture-app",
        "CTP_AUTH_CODE=fixture-auth-code",
    ]
    if include_approval:
        lines.extend(
            [
                "ITER22_APPROVAL_KEY_ID=fixture-approval-key",
                f"ITER22_APPROVAL_HMAC_KEY={hmac_key}",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return password, hmac_key


def test_readiness_reports_missing_simnow_values_and_windows_g2_requirement(tmp_path):
    config_path = _config(tmp_path)
    report = readiness.build_readiness_report(
        config_path=config_path,
        env_path=tmp_path / "absent.env",
        process_environment={},
        platform_name="nt",
    )

    assert report["inspection"] == {
        "scope": "offline_local_configuration_only",
        "network_accessed": False,
        "ctp_writes_submitted": False,
        "credential_values_exposed": False,
    }
    assert report["simnow_static"]["calendar"]["ready"] is True
    assert report["simnow_static"]["credentials"]["missing"] == [
        "CTP_USER_ID",
        "CTP_PASSWORD",
        "CTP_APP_ID",
        "CTP_AUTH_CODE",
    ]
    assert "simnow_credentials_missing" in report["simnow_static"]["blockers"]
    assert report["simnow_natural_signal"]["research"] == {
        "status": "RESEARCH_NOT_ESTABLISHED",
        "admitted": False,
    }
    assert "research_not_admitted" in report["simnow_natural_signal"]["blockers"]
    assert report["simnow_natural_signal"]["windows_g2_evidence"] == {
        "required": True,
        "status": "REQUIRED_NOT_INSPECTED_OFFLINE",
    }
    assert "windows_g2_native_ctp_evidence_required" in report["simnow_natural_signal"]["blockers"]


def test_static_readiness_is_safe_but_never_certifies_natural_signal_or_production(
    tmp_path, capsys
):
    config_path = _config(tmp_path, research_status="RESEARCH_ADMITTED")
    env_path = tmp_path / "operator.env"
    password, hmac_key = _env(env_path)
    output_path = tmp_path / "nested" / "readiness.json"

    exit_code = readiness.main(
        [
            "--config",
            str(config_path),
            "--env-file",
            str(env_path),
            "--output",
            str(output_path),
            "--strict",
        ]
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))
    printed = capsys.readouterr().out

    assert exit_code == 0
    assert report["simnow_static"]["ready"] is True
    assert report["simnow_static"]["credentials"]["ready"] is True
    assert report["simnow_static"]["calendar"]["hash_matches"] is True
    assert report["simnow_natural_signal"]["ready"] is False
    assert report["simnow_natural_signal"]["verdict"] == "REQUIRES_CONTROLLED_RUNTIME_ADMISSION"
    assert (
        "signed_admission_receipt_not_inspected_offline"
        in report["simnow_natural_signal"]["blockers"]
    )
    assert report["production"] == {
        "ready": False,
        "supported_by_iteration22_runner": False,
        "verdict": "BLOCKED_ITER22_SIMNOW_ONLY",
        "blockers": [
            "production_requires_a_separate_ctp_profile",
            "production_requires_new_account_bound_admission",
            "production_requires_firm_specific_fronts_and_credentials",
        ],
    }
    serialized = json.dumps(report) + printed
    assert password not in serialized
    assert hmac_key not in serialized
    assert "fixture-investor" not in serialized
    assert "fixture-auth-code" not in serialized


@pytest.mark.parametrize(
    ("calendar_path_factory", "calendar_hash_factory", "expected_issue"),
    [
        (
            lambda tmp_path: tmp_path / "missing-calendar.json",
            lambda _path: "a" * 64,
            "calendar_artifact_unavailable",
        ),
        (
            lambda tmp_path: _calendar(tmp_path)[0],
            lambda _path: "",
            "calendar_hash_missing",
        ),
        (
            lambda tmp_path: _calendar(tmp_path)[0],
            lambda _path: "b" * 64,
            "calendar_hash_mismatch",
        ),
    ],
)
def test_calendar_report_distinguishes_artifact_hash_failures(
    tmp_path, calendar_path_factory, calendar_hash_factory, expected_issue
):
    calendar_path = calendar_path_factory(tmp_path)
    config_path = _config(
        tmp_path,
        calendar_path=calendar_path,
        calendar_hash=calendar_hash_factory(calendar_path),
    )

    report = readiness.build_readiness_report(
        config_path=config_path,
        env_path=tmp_path / "absent.env",
        process_environment={},
    )
    calendar = report["simnow_static"]["calendar"]

    assert calendar["ready"] is False
    assert expected_issue in calendar["issues"]


def test_profile_override_uses_runner_precedence_without_exposing_credential_values(tmp_path):
    config_path = _config(tmp_path, research_status="RESEARCH_ADMITTED")
    env_path = tmp_path / "aliases.env"
    env_path.write_text(
        "\n".join(
            [
                "SIMNOW_USER_ID=alias-investor",
                "SIMNOW_PASSWORD=alias-password-not-to-leak",
                "SIMNOW_APP_ID=alias-app",
                "SIMNOW_AUTH_CODE=alias-auth-not-to-leak",
                "ITER22_SIMNOW_PROFILE=simnow_second_7x24",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = readiness.build_readiness_report(
        config_path=config_path,
        env_path=env_path,
        process_environment={},
        platform_name="posix",
    )
    serialized = json.dumps(report)

    assert report["simnow_static"]["credentials"]["ready"] is True
    assert report["simnow_static"]["profile"]["name"] == "simnow_second_7x24"
    assert (
        "natural_signal_requires_actual_market_hours_profile"
        in report["simnow_natural_signal"]["blockers"]
    )
    assert "alias-password-not-to-leak" not in serialized
    assert "alias-auth-not-to-leak" not in serialized


def test_static_readiness_rejects_custom_profile_definitions_and_raw_fronts(tmp_path):
    config_path = _config(tmp_path, research_status="RESEARCH_ADMITTED")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["profiles"]["simnow_first_group1"]["td_front"] = "tcp://broker-front.invalid:1234"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    env_path = tmp_path / "operator.env"
    _env(env_path)

    report = readiness.build_readiness_report(
        config_path=config_path,
        env_path=env_path,
        process_environment={},
    )

    assert report["simnow_static"]["ready"] is False
    assert report["config"]["frozen_profile_contract"] == {
        "ready": False,
        "issues": ["frozen_profile_definitions_mismatch"],
    }
    assert "frozen_profile_definitions_mismatch" in report["simnow_static"]["blockers"]


def test_static_readiness_rejects_a_production_environment_name_without_serializing_it(tmp_path):
    config_path = _config(tmp_path, research_status="RESEARCH_ADMITTED")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["environment"] = "production-account-value-must-not-escape"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    env_path = tmp_path / "operator.env"
    _env(env_path)

    report = readiness.build_readiness_report(
        config_path=config_path,
        env_path=env_path,
        process_environment={},
    )
    serialized = json.dumps(report)

    assert report["simnow_static"]["ready"] is False
    assert "configured_environment_not_frozen_simnow_profile" in report["simnow_static"]["blockers"]
    assert "selected_profile_not_frozen" in report["simnow_static"]["blockers"]
    assert "production-account-value-must-not-escape" not in serialized


def test_exact_front_override_pair_is_accepted_without_serializing_endpoints(tmp_path):
    config_path = _config(tmp_path, research_status="RESEARCH_ADMITTED")
    env_path = tmp_path / "fronts.env"
    _env(env_path)
    with env_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "CTP_TD_FRONT=tcp://180.168.146.187:10201\n"
            "CTP_MD_FRONT=tcp://180.168.146.187:10211\n"
        )

    report = readiness.build_readiness_report(
        config_path=config_path,
        env_path=env_path,
        process_environment={},
    )
    front_overrides = report["simnow_static"]["front_overrides"]
    serialized = json.dumps(report)

    assert report["simnow_static"]["ready"] is True
    assert front_overrides["ready"] is True
    assert front_overrides["state"] == "MATCHES_SELECTED_FROZEN_PROFILE"
    assert "tcp://180.168.146.187:10201" not in serialized
    assert "tcp://180.168.146.187:10211" not in serialized


@pytest.mark.parametrize(
    ("environment_lines", "expected_issue"),
    [
        (("CTP_TD_FRONT=tcp://180.168.146.187:10201",), "front_override_pair_incomplete"),
        (
            (
                "SIMNOW_TD_FRONT=tcp://broker-front.invalid:1234",
                "SIMNOW_MD_FRONT=tcp://broker-front.invalid:5678",
            ),
            "front_override_does_not_match_selected_profile",
        ),
    ],
)
def test_front_override_must_be_a_complete_exact_selected_frozen_pair(
    tmp_path, environment_lines, expected_issue
):
    config_path = _config(tmp_path, research_status="RESEARCH_ADMITTED")
    env_path = tmp_path / "fronts.env"
    _env(env_path)
    with env_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(environment_lines) + "\n")

    report = readiness.build_readiness_report(
        config_path=config_path,
        env_path=env_path,
        process_environment={},
    )
    front_overrides = report["simnow_static"]["front_overrides"]

    assert report["simnow_static"]["ready"] is False
    assert front_overrides["issues"] == [expected_issue]
    assert expected_issue in report["simnow_static"]["blockers"]
