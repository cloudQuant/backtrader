"""Offline invocation identity contracts for the staged 007 SimNow cases."""

from __future__ import annotations

import hashlib
import importlib
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import socket

import pytest

from backtrader_runtime import config as runtime_config
from backtrader_runtime.ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontEndpointEvidence,
    CtpFrontPairEvidence,
    CtpFrontPairSelection,
    CtpFrontProbeSample,
)
from backtrader_runtime.ctp_simnow_managed_md_bridge import ManagedCtpMdLeaseSnapshot
from backtrader_runtime.ctp_simnow_managed_operator import (
    CtpSimNowManagedScopeSelection,
    ctp_simnow_front_pair_set_sha256,
)
from backtrader_runtime.ctp_simulation_execution import CtpSimulationExecutionRegistration
from backtrader_runtime.inventory import (
    ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION,
    ITERATION41_007_CTP_PRIVATE_RUNTIME_ID,
)
from backtrader_runtime.registry import RuntimeRegistry, validate_runtime_config
from backtrader_runtime.ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding


invocation_module = importlib.import_module(
    "examples.007_ctp.live_certification.simnow_penetration.managed_case_invocation"
)
case_scope_module = importlib.import_module(
    "examples.007_ctp.live_certification.simnow_penetration.managed_case_scope"
)


def _synthetic_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_id: str = "offline-case-account",
    md_front: str = "tcp://127.0.0.1:21001",
    td_front: str = "tcp://127.0.0.1:22001",
    second_pair: tuple[str, str] | None = None,
    additional_pairs: tuple[tuple[str, str], ...] = (),
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    registration = replace(
        ITERATION41_007_CTP_PRIVATE_READONLY_REGISTRATION, runtime_dir=tmp_path
    )
    registry = RuntimeRegistry(
        (registration,),
        ctp_simnow_readonly_bindings=(
            CtpSimNowConfigReadOnlyBinding(runtime_id=ITERATION41_007_CTP_PRIVATE_RUNTIME_ID),
        ),
        registry_id="backtrader.iteration41.offline-case-invocation-test",
    )
    config_lines = [
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
        f"    - md_front: {md_front}",
        f"      td_front: {td_front}",
    ]
    additional_config_pairs = (() if second_pair is None else (second_pair,)) + additional_pairs
    for pair_md_front, pair_td_front in additional_config_pairs:
        config_lines.extend(
            (f"    - md_front: {pair_md_front}", f"      td_front: {pair_td_front}")
        )
    config_lines.extend(
        (
            "  instrument_id: rb2701",
            "  exchange_id: SHFE",
            "  hedge_flag: '1'",
            "  broker_id: '9999'",
            f"  user_id: {user_id}",
            "  password: offline-case-test-password",
            "  app_id: offline-case-test-app",
            "  auth_code: offline-case-test-auth",
            "",
        )
    )
    (tmp_path / "config.yaml").write_text(
        "\n".join(config_lines),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        runtime_config, "_require_private_config_security", lambda *_args, **_kwargs: None
    )
    effective = validate_runtime_config(tmp_path, registry)
    return effective, registry


def _issued_case_scope(
    effective, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    scenario = case_scope_module.managed_case_entry._load_code_owned_scenarios()["T01"]
    case_dir = tmp_path / "synthetic-cases" / "T01"
    case_dir.mkdir(parents=True)
    case_file = case_dir / "run.py"
    case_file.write_text("# synthetic blocked wrapper\n", encoding="utf-8")
    (case_dir / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: example.007_ctp.simnow_penetration.T01\n"
        "runtime:\n"
        "  mode: simulation\n"
        "  preset: sandbox\n"
        "parameters:\n"
        "  scenario: T01\n",
        encoding="utf-8",
    )
    (case_dir / "T01_strategy.py").write_text(
        'CASE_ID = "T01"\n'
        'CASE_NAME = "Synthetic offline T01"\n'
        "CASE_PLAN = {\n"
        '    "scenario_id": "TRADE-OPEN-01",\n'
        '    "actions": ["Synthetic offline action."],\n'
        '    "evidence": ["Synthetic offline evidence."],\n'
        '    "evidence_mode": "REAL",\n'
        '    "status": "PLANNED",\n'
        "}\n",
        encoding="utf-8",
    )
    entry = case_scope_module.managed_case_entry
    monkeypatch.setattr(entry, "_expected_script", lambda _case_id: case_file)
    monkeypatch.setattr(
        entry,
        "_is_exact_direct_case_path",
        lambda case_id, supplied: case_id == "T01" and Path(supplied) == case_file,
    )
    case_config_digest = entry._validated_case_config_digest(case_file, "T01")
    strategy_plan = case_scope_module.load_descriptive_case_plan(
        case_dir / "T01_strategy.py",
        expected_case_id="T01",
        expected_scenario_id=scenario.scenario_id,
    )
    scope = case_scope_module.CertificationCaseScope(
        case_id="T01",
        scenario_id=scenario.scenario_id,
        runtime_id=effective.registration.runtime_id,
        account_identity_scheme=case_scope_module.ACCOUNT_IDENTITY_SCHEME,
        account_identity_sha256=case_scope_module._account_identity_sha256(effective),
        suite_config_digest=effective.config_digest,
        suite_effective_digest=effective.effective_digest,
        case_config_digest=case_config_digest,
        strategy_plan_digest=strategy_plan.source_sha256,
        runner_digest=hashlib.sha256(case_file.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        case_scope_module, "_is_issued_scope", lambda candidate: candidate is scope
    )
    return scope, case_dir


def _selection(
    effective,
    *,
    account_fingerprint_sha256: str | None = None,
    md_front: str | None = None,
    td_front: str | None = None,
    config_digest: str | None = None,
    instrument_id: str | None = None,
    selected_index: int = 0,
):
    private = effective.config.ctp
    pairs = private.front_pairs
    pair_set_digest = ctp_simnow_front_pair_set_sha256(pairs)
    fingerprint = hashlib.sha256(
        f"{private.broker_id}:{private.user_id}".encode("utf-8")
    ).hexdigest()[:16]
    account_digest = hashlib.sha256(("acct_" + fingerprint).encode("ascii")).hexdigest()
    pair_evidence = []
    for index, configured_pair in enumerate(pairs):
        pair = CtpConfiguredFrontPair(
            configured_pair["md_front"], configured_pair["td_front"]
        )
        score = float(index + 1)
        sample = CtpFrontProbeSample(True, score, None, 0.1, score - 0.1)
        md_evidence = CtpFrontEndpointEvidence(pair.md_front, (sample, sample, sample))
        td_evidence = CtpFrontEndpointEvidence(pair.td_front, (sample, sample, sample))
        pair_evidence.append(
            CtpFrontPairEvidence(index, pair, md_evidence, td_evidence, True, score)
        )
    selected_evidence = pair_evidence[selected_index]
    selected_pair_value = selected_evidence.pair
    selected_md = md_front or selected_pair_value.md_front
    selected_td = td_front or selected_pair_value.td_front
    selected_pair = CtpFrontPairSelection(
        CtpConfiguredFrontPair(selected_md, selected_td),
        selected_index,
        selected_evidence.latency_score_ms,
        tuple(pair_evidence),
        3.0,
        3,
    )
    registration = CtpSimulationExecutionRegistration(
        runtime_registration=effective.registration,
        environment="simnow",
        sdk_profile="config_front_pair",
        td_front=selected_td,
        md_front=selected_md,
        account_fingerprint_sha256=account_fingerprint_sha256 or account_digest,
        allowed_secrets_ref="config_yaml",
        instrument_id=instrument_id or private.instrument_id,
        exchange_id=private.exchange_id,
        hedge_flag=private.hedge_flag,
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=2,
        max_gross_position=4,
        min_price=Decimal("1"),
        max_price=Decimal("100"),
        price_tick=Decimal("1"),
        approval_key_id="offline-test-key",
        front_pair_set_sha256=pair_set_digest,
        config_digest=config_digest or effective.config.config_digest,
        effective_digest=effective.effective_digest,
        profile_digest=None if effective.profile is None else effective.profile.digest,
        profile_approval_receipt_digest=(
            None if effective.profile is None else "b" * 64
        ),
    )
    return CtpSimNowManagedScopeSelection(
        execution_registration=registration,
        front_pair_selection=selected_pair,
        front_pair_set_sha256=pair_set_digest,
        config_digest=config_digest or effective.config.config_digest,
        effective_digest=effective.effective_digest,
        profile_digest=None if effective.profile is None else effective.profile.digest,
    )


def test_invocation_binds_exact_selected_scope_and_redacts_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    selection = _selection(effective)
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: pytest.fail("network used"))

    binding = invocation_module.bind_case_invocation(
        scope,
        selection,
        "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
        effective,
        registry,
    )
    invocation_module.validate_case_invocation(
        binding, scope, selection, effective, registry
    )

    assert binding.case_id == "T01"
    assert binding.config_digest == effective.config_digest
    assert binding.effective_digest == effective.effective_digest
    assert binding.pair_set_sha256 == selection.front_pair_set_sha256
    assert binding.registration_digest == selection.execution_registration.digest
    assert binding.instrument_id == "rb2701"
    assert binding.exchange_id == "SHFE"
    assert binding.strategy_plan_digest == scope.strategy_plan_digest
    assert binding.runner_digest == scope.runner_digest
    assert binding.lease_generation is None
    rendered = repr(binding) + repr(binding.as_redacted_dict())
    assert "offline-case-test-password" not in rendered
    assert "offline-case-account" not in rendered
    assert "tcp://127.0.0.1" not in rendered


def test_invocation_rejects_forged_pair_and_config_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    forged_pair = _selection(
        effective,
        md_front="tcp://127.0.0.1:29991",
        td_front="tcp://127.0.0.1:29992",
    )
    forged_config = _selection(effective, config_digest="f" * 64)

    with pytest.raises(invocation_module.ManagedCaseInvocationError) as pair_error:
        invocation_module.bind_case_invocation(
            scope,
            forged_pair,
            "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
            effective,
            registry,
        )
    assert pair_error.value.reason == "invocation_selection_invalid"

    with pytest.raises(invocation_module.ManagedCaseInvocationError) as config_error:
        invocation_module.bind_case_invocation(
            scope,
            forged_config,
            "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
            effective,
            registry,
        )
    assert config_error.value.reason == "invocation_config_scope_mismatch"


def test_invocation_rejects_account_mismatch_and_current_account_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    forged_account = _selection(effective, account_fingerprint_sha256="a" * 64)
    with pytest.raises(invocation_module.ManagedCaseInvocationError) as error:
        invocation_module.bind_case_invocation(
            scope,
            forged_account,
            "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
            effective,
            registry,
        )
    assert error.value.reason == "invocation_account_scope_mismatch"

    selection = _selection(effective)
    (tmp_path / "config.yaml").write_text(
        (tmp_path / "config.yaml").read_text(encoding="utf-8").replace(
            "user_id: offline-case-account", "user_id: rotated-offline-account"
        ),
        encoding="utf-8",
    )
    current = validate_runtime_config(tmp_path, registry)
    with pytest.raises(invocation_module.ManagedCaseInvocationError) as drift_error:
        invocation_module.bind_case_invocation(
            scope,
            selection,
            "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
            current,
            registry,
        )
    assert drift_error.value.reason == "invocation_account_scope_mismatch"


def test_invocation_rejects_contract_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    forged_contract = _selection(effective, instrument_id="zn2701")
    with pytest.raises(invocation_module.ManagedCaseInvocationError) as contract_error:
        invocation_module.bind_case_invocation(
            scope,
            forged_contract,
            "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
            effective,
            registry,
        )
    assert contract_error.value.reason == "invocation_contract_scope_mismatch"


def test_invocation_rejects_caller_supplied_lease_claims_without_owner_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    selection = _selection(effective)
    account = selection.execution_registration.account_fingerprint_sha256
    caller_claim = ManagedCtpMdLeaseSnapshot(account, 9, True)

    with pytest.raises(invocation_module.ManagedCaseInvocationError) as bind_error:
        invocation_module.bind_case_invocation(
            scope,
            selection,
            "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
            effective,
            registry,
            lease_snapshot=caller_claim,
        )
    assert bind_error.value.reason == "invocation_lease_verifier_unavailable"

    binding = invocation_module.bind_case_invocation(
        scope,
        selection,
        "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
        effective,
        registry,
    )
    assert binding.lease_generation is None
    with pytest.raises(invocation_module.ManagedCaseInvocationError) as validate_error:
        invocation_module.validate_case_invocation(
            binding,
            scope,
            selection,
            effective,
            registry,
            lease_snapshot=caller_claim,
        )
    assert validate_error.value.reason == "invocation_lease_verifier_unavailable"


def test_invocation_rejects_replaced_selection_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    selection = _selection(effective)
    binding = invocation_module.bind_case_invocation(
        scope,
        selection,
        "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
        effective,
        registry,
    )

    with pytest.raises(invocation_module.ManagedCaseInvocationError) as error:
        invocation_module.validate_case_invocation(
            binding,
            scope,
            _selection(effective),
            effective,
            registry,
        )
    assert error.value.reason == "invocation_binding_invalid"


@pytest.mark.parametrize(
    "sample",
    (
        CtpFrontProbeSample(True, 1.0, "fabricated_failure", 0.4, 0.6),
        CtpFrontProbeSample(True, 1.0, None, 0.4, 0.7),
        CtpFrontProbeSample(False, 1.0, None, 0.4, 0.6),
    ),
)
def test_invocation_rejects_inconsistent_tcp_sample_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sample: CtpFrontProbeSample,
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    selection = _selection(effective)
    front_selection = selection.front_pair_selection
    first_pair = front_selection.evidence[0]
    bad_md = replace(first_pair.md, samples=(sample, *first_pair.md.samples[1:]))
    bad_pair = replace(first_pair, md=bad_md)
    forged = replace(
        selection,
        front_pair_selection=replace(
            front_selection,
            evidence=(bad_pair, *front_selection.evidence[1:]),
        ),
    )
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: pytest.fail("network used"))

    with pytest.raises(invocation_module.ManagedCaseInvocationError) as error:
        invocation_module.bind_case_invocation(
            scope,
            forged,
            "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
            effective,
            registry,
        )
    assert error.value.reason == "invocation_selection_invalid"


def test_invocation_accepts_consistent_failed_tcp_sample_in_ranking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    selection = _selection(effective)
    front_selection = selection.front_pair_selection
    first_pair = front_selection.evidence[0]
    valid_failure = CtpFrontProbeSample(False, None, "ConnectionError")
    md = replace(first_pair.md, samples=(valid_failure, *first_pair.md.samples[1:]))
    mixed_pair = replace(first_pair, md=md)
    mixed = replace(
        selection,
        front_pair_selection=replace(
            front_selection,
            evidence=(mixed_pair, *front_selection.evidence[1:]),
        ),
    )
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: pytest.fail("network used"))

    binding = invocation_module.bind_case_invocation(
        scope,
        mixed,
        "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
        effective,
        registry,
    )
    assert binding.md_front == first_pair.pair.md_front


@pytest.mark.parametrize("pair_count", (1, 8))
def test_invocation_preserves_deterministic_one_to_eight_pair_ranking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pair_count: int
) -> None:
    additional_pairs = tuple(
        (
            f"tcp://127.0.0.1:{21000 + index}",
            f"tcp://127.0.0.1:{22000 + index}",
        )
        for index in range(2, pair_count + 1)
    )
    effective, registry = _synthetic_runtime(
        tmp_path, monkeypatch, additional_pairs=additional_pairs
    )
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    selection = _selection(effective)
    monkeypatch.setattr(socket, "socket", lambda *_args, **_kwargs: pytest.fail("network used"))

    binding = invocation_module.bind_case_invocation(
        scope,
        selection,
        "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
        effective,
        registry,
    )
    assert len(selection.front_pair_selection.evidence) == pair_count
    assert selection.front_pair_selection.config_index == 0
    assert binding.md_front == selection.front_pair_selection.pair.md_front
    assert binding.td_front == selection.front_pair_selection.pair.td_front


def test_invocation_rejects_forged_faster_evidence_and_candidate_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effective, registry = _synthetic_runtime(
        tmp_path,
        monkeypatch,
        second_pair=("tcp://127.0.0.1:21002", "tcp://127.0.0.1:22002"),
    )
    scope, _case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    selection = _selection(effective)
    front_selection = selection.front_pair_selection
    second = front_selection.evidence[1]
    fast_sample = CtpFrontProbeSample(True, 0.25, None, 0.1, 0.15)
    faster_second = replace(
        second,
        md=replace(second.md, samples=(fast_sample, fast_sample, fast_sample)),
        td=replace(second.td, samples=(fast_sample, fast_sample, fast_sample)),
        latency_score_ms=0.25,
    )
    forged_faster = replace(
        selection,
        front_pair_selection=replace(
            front_selection, evidence=(front_selection.evidence[0], faster_second)
        ),
    )
    wrong_candidate = replace(
        second,
        pair=CtpConfiguredFrontPair("tcp://127.0.0.1:29991", "tcp://127.0.0.1:22002"),
    )
    forged_candidates = replace(
        selection,
        front_pair_selection=replace(
            front_selection, evidence=(front_selection.evidence[0], wrong_candidate)
        ),
    )

    for forged in (forged_faster, forged_candidates):
        with pytest.raises(invocation_module.ManagedCaseInvocationError) as error:
            invocation_module.bind_case_invocation(
                scope,
                forged,
                "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
                effective,
                registry,
            )
        assert error.value.reason == "invocation_selection_invalid"


@pytest.mark.parametrize("changed_file", ("run.py", "config.yaml", "T01_strategy.py"))
def test_invocation_rejects_case_file_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_file: str,
) -> None:
    effective, registry = _synthetic_runtime(tmp_path, monkeypatch)
    scope, case_dir = _issued_case_scope(effective, monkeypatch, tmp_path)
    selection = _selection(effective)
    binding = invocation_module.bind_case_invocation(
        scope,
        selection,
        "3f0d1cb2-5b5a-4e10-8d9e-c3c910c08c17",
        effective,
        registry,
    )
    changed_path = case_dir / changed_file
    changed_path.write_text(
        changed_path.read_text(encoding="utf-8") + "\n# changed after scope binding\n",
        encoding="utf-8",
    )

    with pytest.raises(invocation_module.ManagedCaseInvocationError) as error:
        invocation_module.validate_case_invocation(
            binding, scope, selection, effective, registry
        )
    assert error.value.reason == "invocation_case_files_changed"
