"""Offline scope binding checks; synthetic CTP fields never reach a provider."""

from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path
import socket

import pytest

from backtrader_runtime import config as runtime_config
from backtrader_runtime.ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
from backtrader_runtime.inventory import (
    ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION,
    ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
)
from backtrader_runtime.registry import RuntimeRegistry, validate_runtime_config


scope_module = importlib.import_module(
    "examples.007_ctp.live_certification.simnow_penetration.managed_case_scope"
)
entry_module = importlib.import_module(
    "examples.007_ctp.live_certification.simnow_penetration.managed_case_entry"
)


def _synthetic_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    broker_id: str = "9999",
    user_id: str = "offline-test-account",
    password: str = "offline-test-password",
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    registration = replace(ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION, runtime_dir=tmp_path)
    registry = RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=(
            CtpSimNowConfigReadOnlyBinding(runtime_id=ITERATION41_007_CTP_PRIVATE_RUNTIME_ID),
        ),
        registry_id="backtrader.iteration41.offline-certification-scope-test",
    )
    (tmp_path / "config.yaml").write_text(
        "\n".join(
            (
                "config_schema_version: 4",
                "strategy:",
                "  id: example.007_ctp.simnow_penetration",
                "runtime:",
                "  mode: simulation",
                "  preset: sandbox",
                "parameters: {}",
                "secrets_ref: config_yaml",
                "ctp:",
                "  front_pairs:",
                "    - md_front: tcp://127.0.0.1:21001",
                "      td_front: tcp://127.0.0.1:22001",
                "  instrument_id: rb2701",
                "  exchange_id: SHFE",
                "  hedge_flag: '1'",
                f"  broker_id: '{broker_id}'",
                f"  user_id: {user_id}",
                f"  password: {password}",
                "  app_id: offline_test_app",
                "  auth_code: offline_test_auth",
                "",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_config, "_require_private_config_security", lambda *_args, **_kwargs: None
    )
    effective = validate_runtime_config(tmp_path, registry)
    return effective, registry


def test_candidate_binds_case_and_both_config_digests_without_provider_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(
        socket, "socket", lambda *_args, **_kwargs: pytest.fail("network was attempted")
    )
    case_file = entry_module._expected_script("T01")

    scope = scope_module._bind_case_scope(
        effective, registry, "T01", case_file, expected_runtime_dir=tmp_path
    )

    assert scope.case_id == "T01"
    assert scope.scenario_id == "TRADE-OPEN-01"
    assert scope.runtime_id == ITERATION41_007_CTP_PRIVATE_RUNTIME_ID
    assert scope.account_identity_scheme == scope_module.ACCOUNT_IDENTITY_SCHEME
    assert len(scope.account_identity_sha256) == 64
    assert scope.suite_config_digest == effective.config_digest
    assert scope.suite_effective_digest == effective.effective_digest
    assert len(scope.case_config_digest) == 64
    assert len(scope.strategy_plan_digest) == 64
    assert len(scope.runner_digest) == 64
    assert "offline-test-account" not in repr(scope)
    assert "offline-test-password" not in repr(scope)
    assert "password" not in repr(scope)
    assert capsys.readouterr() == ("", "")


def test_all_33_strategy_plans_bind_to_their_case_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scenarios = entry_module._load_code_owned_scenarios()

    scopes = [
        scope_module._bind_case_scope(
            effective,
            registry,
            case_id,
            entry_module._expected_script(case_id),
            expected_runtime_dir=tmp_path,
        )
        for case_id in scenarios
    ]

    assert len(scopes) == 33
    assert {scope.case_id for scope in scopes} == set(scenarios)
    assert len({scope.strategy_plan_digest for scope in scopes}) == 33
    assert len({scope.runner_digest for scope in scopes}) == 33


def test_public_binding_does_not_accept_a_cloned_runtime_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    with pytest.raises(scope_module.CertificationCaseScopeError) as error:
        scope_module.bind_case_scope(
            effective, registry, "T01", entry_module._expected_script("T01")
        )
    assert error.value.reason == "sealed_ctp_runtime_required"


@pytest.mark.parametrize(
    ("case_id", "case_file", "reason"),
    (
        ("INVALID", "T01", "certification_case_id_invalid"),
        ("T01", "T01", "certification_case_path_invalid"),
    ),
)
def test_candidate_rejects_invalid_case_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    case_file: str,
    reason: str,
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    with pytest.raises(scope_module.CertificationCaseScopeError) as error:
        scope_module._bind_case_scope(
            effective, registry, case_id, case_file, expected_runtime_dir=tmp_path
        )
    assert error.value.reason == reason


def test_candidate_rejects_forged_effective_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    forged = replace(effective, effective_digest="0" * 64)
    with pytest.raises(scope_module.CertificationCaseScopeError) as error:
        scope_module._bind_case_scope(
            forged,
            registry,
            "T01",
            entry_module._expected_script("T01"),
            expected_runtime_dir=tmp_path,
        )
    assert error.value.reason == "sealed_ctp_runtime_required"


def test_decision_scope_binds_case_runtime_and_static_strategy_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    case_file = entry_module._expected_script("T01")
    scope = scope_module._bind_case_scope(
        effective, registry, "T01", case_file, expected_runtime_dir=tmp_path
    )
    plan = scope_module.load_descriptive_case_plan(case_file.parent / "T01_strategy.py")

    decision_scope = scope_module.decision_scope_from_case_scope(scope, plan)
    decision_scope.validate(plan)
    assert decision_scope.case_id == "T01"
    assert decision_scope.scenario_id == "TRADE-OPEN-01"
    assert decision_scope.plan_source_sha256 == scope.strategy_plan_digest
    assert decision_scope.account_identity_sha256 == scope.account_identity_sha256
    assert len(decision_scope.scope_sha256) == 64
    assert decision_scope.scope_sha256 != scope.suite_effective_digest


def test_decision_scope_rejects_stale_plan_and_replaced_case_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    case_file = entry_module._expected_script("T01")
    scope = scope_module._bind_case_scope(
        effective, registry, "T01", case_file, expected_runtime_dir=tmp_path
    )
    plan = scope_module.load_descriptive_case_plan(case_file.parent / "T01_strategy.py")
    replaced_scope = replace(scope, case_config_digest="1" * 64)
    with pytest.raises(scope_module.CertificationCaseScopeError) as replaced_error:
        scope_module.decision_scope_from_case_scope(replaced_scope, plan)
    assert replaced_error.value.reason == "certification_decision_scope_invalid"
    with pytest.raises(scope_module.CertificationCaseScopeError) as error:
        scope_module.decision_scope_from_case_scope(scope, replace(plan, source_sha256="0" * 64))
    assert error.value.reason == "certification_decision_scope_invalid"


def test_account_identity_is_canonical_and_bound_into_decision_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_effective, first_registry = _synthetic_runtime(
        tmp_path / "account-one", monkeypatch, user_id="offline-account-one"
    )
    second_effective, second_registry = _synthetic_runtime(
        tmp_path / "account-two", monkeypatch, user_id="offline-account-two"
    )
    same_account_effective, same_account_registry = _synthetic_runtime(
        tmp_path / "same-account-different-password",
        monkeypatch,
        user_id="offline-account-one",
        password="rotated-synthetic-password",
    )
    case_file = entry_module._expected_script("T01")
    first_scope = scope_module._bind_case_scope(
        first_effective,
        first_registry,
        "T01",
        case_file,
        expected_runtime_dir=tmp_path / "account-one",
    )
    second_scope = scope_module._bind_case_scope(
        second_effective,
        second_registry,
        "T01",
        case_file,
        expected_runtime_dir=tmp_path / "account-two",
    )
    same_account_scope = scope_module._bind_case_scope(
        same_account_effective,
        same_account_registry,
        "T01",
        case_file,
        expected_runtime_dir=tmp_path / "same-account-different-password",
    )
    plan = scope_module.load_descriptive_case_plan(case_file.parent / "T01_strategy.py")

    first_decision = scope_module.decision_scope_from_case_scope(first_scope, plan)
    second_decision = scope_module.decision_scope_from_case_scope(second_scope, plan)
    same_account_decision = scope_module.decision_scope_from_case_scope(same_account_scope, plan)

    assert first_scope.account_identity_sha256 != second_scope.account_identity_sha256
    assert first_scope.account_identity_sha256 == same_account_scope.account_identity_sha256
    assert first_decision.account_identity_sha256 == first_scope.account_identity_sha256
    assert second_decision.account_identity_sha256 == second_scope.account_identity_sha256
    assert first_decision.scope_sha256 != second_decision.scope_sha256
    assert first_decision.scope_sha256 == same_account_decision.scope_sha256


def test_account_identity_encoding_preserves_component_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    left_effective, left_registry = _synthetic_runtime(
        tmp_path / "left", monkeypatch, broker_id="ab", user_id="c"
    )
    right_effective, right_registry = _synthetic_runtime(
        tmp_path / "right", monkeypatch, broker_id="a", user_id="bc"
    )
    case_file = entry_module._expected_script("T01")
    left_scope = scope_module._bind_case_scope(
        left_effective,
        left_registry,
        "T01",
        case_file,
        expected_runtime_dir=tmp_path / "left",
    )
    right_scope = scope_module._bind_case_scope(
        right_effective,
        right_registry,
        "T01",
        case_file,
        expected_runtime_dir=tmp_path / "right",
    )

    assert left_scope.account_identity_sha256 != right_scope.account_identity_sha256


@pytest.mark.parametrize(
    "changes",
    (
        {"account_identity_sha256": ""},
        {"account_identity_sha256": "0" * 64},
        {"account_identity_scheme": "unknown.scheme"},
    ),
)
def test_decision_scope_rejects_empty_or_forged_account_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changes: dict[str, str],
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    case_file = entry_module._expected_script("T01")
    scope = scope_module._bind_case_scope(
        effective, registry, "T01", case_file, expected_runtime_dir=tmp_path
    )
    plan = scope_module.load_descriptive_case_plan(case_file.parent / "T01_strategy.py")
    forged_scope = replace(scope, **changes)

    with pytest.raises(scope_module.CertificationCaseScopeError) as error:
        scope_module.decision_scope_from_case_scope(forged_scope, plan)

    assert error.value.reason == "certification_decision_scope_invalid"
    assert "offline-test-account" not in str(error.value)
    assert "offline-test-password" not in str(error.value)
