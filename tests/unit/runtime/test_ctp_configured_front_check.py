"""Fake-only tests for the explicit, credential-free CTP front check."""

from __future__ import annotations

import builtins
import importlib
import io
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backtrader_runtime import cli
from backtrader_runtime import ctp_configured_front_check as front_check
from backtrader_runtime.ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontEndpointEvidence,
    CtpFrontPairEvidence,
    CtpFrontPairProbeError,
    CtpFrontPairSelection,
    CtpFrontProbeSample,
)
from backtrader_runtime.ctp_simnow_operator import CtpSimNowConfigReadOnlyBinding
from backtrader_runtime.errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from backtrader_runtime.inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)


MD_ONE = "tcp://private-md-one.invalid:10130"
TD_ONE = "tcp://private-td-one.invalid:10131"
MD_TWO = "tcp://private-md-two.invalid:10132"
TD_TWO = "tcp://private-td-two.invalid:10133"
ACCOUNT_MARKER = "account-value-must-not-leak"
SECRET_MARKER = "secret-value-must-not-leak"


class _Registration:
    runtime_id = ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
    runtime_dir = ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    profiles: tuple[()] = ()


class _Registry:
    def __init__(self, registration: _Registration, binding: object) -> None:
        self.registration = registration
        self.binding = binding

    def require_runtime_dir(self, _path: object) -> _Registration:
        return self.registration

    def require_ctp_simnow_readonly_binding(self, _runtime_id: str) -> object:
        return self.binding


def _fixture():
    registration = _Registration()
    binding = CtpSimNowConfigReadOnlyBinding(runtime_id=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)
    registry = _Registry(registration, binding)
    front_pairs = (
        {"td_front": TD_ONE, "md_front": MD_ONE},
        {"td_front": TD_TWO, "md_front": MD_TWO},
    )
    private = SimpleNamespace(
        instrument_id="IF2612",
        exchange_id="CFFEX",
        hedge_flag="1",
        broker_id=ACCOUNT_MARKER,
        user_id=ACCOUNT_MARKER,
        password=SECRET_MARKER,
    )
    effective = SimpleNamespace(
        config=SimpleNamespace(strategy_dir=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR),
        registration=registration,
        profile=object(),
        mode="simulation",
        preset="sandbox",
    )
    return registry, binding, registration, effective, private, front_pairs


def _pair_evidence(
    index: int,
    *,
    td_front: str,
    md_front: str,
    md_connections: int,
    td_connections: int,
) -> CtpFrontPairEvidence:
    md_samples = tuple(
        CtpFrontProbeSample(
            connected=sample_index < md_connections,
            latency_ms=1.0 if sample_index < md_connections else None,
        )
        for sample_index in range(3)
    )
    td_samples = tuple(
        CtpFrontProbeSample(
            connected=sample_index < td_connections,
            latency_ms=1.0 if sample_index < td_connections else None,
        )
        for sample_index in range(3)
    )
    reachable = md_connections >= 2 and td_connections >= 2
    pair = CtpConfiguredFrontPair(md_front=md_front, td_front=td_front)
    return CtpFrontPairEvidence(
        config_index=index,
        pair=pair,
        md=CtpFrontEndpointEvidence(md_front, md_samples),
        td=CtpFrontEndpointEvidence(td_front, td_samples),
        reachable=reachable,
        latency_score_ms=1.0 if reachable else None,
    )


def _selection(index: int = 1) -> CtpFrontPairSelection:
    pairs = (
        _pair_evidence(0, td_front=TD_ONE, md_front=MD_ONE, md_connections=0, td_connections=1),
        _pair_evidence(1, td_front=TD_TWO, md_front=MD_TWO, md_connections=3, td_connections=3),
    )
    pair = pairs[index].pair
    return CtpFrontPairSelection(
        pair=pair,
        config_index=index,
        latency_score_ms=1.0,
        evidence=pairs,
        timeout_seconds=3.0,
        repeated_samples=3,
    )


def test_majority_connected_pair_projects_reachable_without_exposing_fronts(monkeypatch):
    registry, _binding, _registration, effective, _private, _pairs = (
        _install_fake_profile_gates(monkeypatch)
    )
    candidate = _pair_evidence(
        1, td_front=TD_TWO, md_front=MD_TWO, md_connections=2, td_connections=3
    )
    rejected = _pair_evidence(
        0, td_front=TD_ONE, md_front=MD_ONE, md_connections=1, td_connections=3
    )
    selection = replace(_selection(1), evidence=(rejected, candidate))
    monkeypatch.setattr(front_check, "select_ctp_front_pair", lambda *_a, **_k: selection)

    result = front_check.check_configured_ctp_fronts(effective, registry)
    public = result.as_public_dict()

    assert result.selected_config_index == 1
    assert public["pairs"][0]["status"] == "partial"
    assert public["pairs"][1]["status"] == "reachable"
    assert public["pairs"][1]["md_connected_count"] == 2
    assert "private-md" not in json.dumps(public)


def _install_fake_profile_gates(monkeypatch):
    registry, binding, registration, effective, private, front_pairs = _fixture()
    monkeypatch.setattr(
        front_check,
        "require_ctp_sandbox_profile_runtime",
        lambda _effective, _registry: effective.profile,
    )
    monkeypatch.setattr(
        CtpSimNowConfigReadOnlyBinding,
        "_sealed_private_config",
        lambda _self, _effective, _registry: (private, registration, front_pairs),
    )
    return registry, binding, registration, effective, private, front_pairs


def test_probe_uses_only_sealed_pairs_and_emits_value_free_counts(monkeypatch):
    registry, _binding, _registration, effective, _private, pairs = _install_fake_profile_gates(
        monkeypatch
    )
    monkeypatch.setenv("CTP_SIMNOW_SET", "set2_7x24")
    monkeypatch.setenv("CTP_FRONT_PAIR_INDEX", "0")
    monkeypatch.setenv("CTP_FRONT_PAIR_SET", "set1")
    monkeypatch.setenv("CTP_FRONT_PAIR_TIME", "2099-01-01T00:00:00Z")
    calls: list[object] = []

    def select(front_pairs: object, **kwargs: object) -> CtpFrontPairSelection:
        calls.append((front_pairs, kwargs))
        assert front_pairs == pairs
        assert kwargs == {
            "timeout_seconds": 3.0,
            "max_pairs": 8,
            "repeated_samples": 3,
        }
        return _selection(1)

    monkeypatch.setattr(front_check, "select_ctp_front_pair", select)

    def reject_if_used(*_args: object, **_kwargs: object) -> None:
        pytest.fail("front check must not resolve credentials")

    from backtrader_runtime import credential_resolver

    monkeypatch.setattr(credential_resolver, "resolve_runtime_credentials", reject_if_used)
    original_import = importlib.import_module

    def guarded_import(name: str, *args: object, **kwargs: object):
        if name.startswith("bt_api_"):
            pytest.fail("front check must not import an SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", guarded_import)
    from backtrader_runtime import ctp_i10_attempt_latch

    monkeypatch.setattr(
        ctp_i10_attempt_latch.PersistentI10OneShotAttemptLatch,
        "__init__",
        lambda *_args, **_kwargs: pytest.fail("front check must not touch the I10 latch"),
    )
    imported_capabilities: list[str] = []
    original_builtin_import = builtins.__import__

    def guarded_builtin_import(name: str, *args: object, **kwargs: object):
        if name.startswith("bt_api_"):
            imported_capabilities.append(name)
            pytest.fail("front check must not import provider SDK modules")
        return original_builtin_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_builtin_import)

    result = front_check.check_configured_ctp_fronts(effective, registry)
    public = result.as_public_dict()
    rendered = json.dumps(public, sort_keys=True)

    assert result.succeeded is True
    assert result.selected_config_index == 1
    assert [pair["config_index"] for pair in public["pairs"]] == [0, 1]
    assert public["pairs"][0] == {
        "config_index": 0,
        "md_connected_count": 0,
        "md_sample_count": 3,
        "status": "partial",
        "td_connected_count": 1,
        "td_sample_count": 3,
    }
    assert public["pairs"][1]["status"] == "reachable"
    assert public["credential_resolver_invoked"] is False
    assert public["sdk_imported"] is False
    assert public["authentication_attempted"] is False
    assert public["provider_login_started"] is False
    assert public["trading_writes"] == public["settlement_writes"] == 0
    assert public["order_submission_authorized"] is False
    assert public["tcp_probe_only"] is True
    assert not any(marker in rendered for marker in (MD_ONE, TD_ONE, MD_TWO, TD_TWO))
    assert ACCOUNT_MARKER not in rendered
    assert SECRET_MARKER not in rendered
    assert len(calls) == 1
    assert imported_capabilities == []


def test_all_failed_pairs_return_redacted_per_index_counts(monkeypatch):
    registry, _binding, _registration, effective, _private, pairs = _install_fake_profile_gates(
        monkeypatch
    )
    evidence = (
        _pair_evidence(0, td_front=TD_ONE, md_front=MD_ONE, md_connections=0, td_connections=0),
        _pair_evidence(1, td_front=TD_TWO, md_front=MD_TWO, md_connections=1, td_connections=0),
    )

    def no_reachable_pair(_front_pairs: object, **_kwargs: object) -> CtpFrontPairSelection:
        raise CtpFrontPairProbeError("no_configured_front_pair_reachable", evidence)

    monkeypatch.setattr(front_check, "select_ctp_front_pair", no_reachable_pair)
    result = front_check.check_configured_ctp_fronts(effective, registry)
    public = result.as_public_dict()
    rendered = json.dumps(public, sort_keys=True)

    assert result.succeeded is False
    assert result.status == "no_pair_reachable"
    assert result.selected_config_index is None
    assert [
        (pair["config_index"], pair["md_connected_count"], pair["td_connected_count"])
        for pair in public["pairs"]
    ] == [
        (0, 0, 0),
        (1, 1, 0),
    ]
    assert not any(marker in rendered for marker in (MD_ONE, TD_ONE, MD_TWO, TD_TWO))
    assert ACCOUNT_MARKER not in rendered
    assert SECRET_MARKER not in rendered
    assert public["trading_writes"] == public["settlement_writes"] == 0


def test_success_selection_evidence_must_match_every_sealed_candidate(monkeypatch):
    registry, _binding, _registration, effective, _private, _pairs = _install_fake_profile_gates(
        monkeypatch
    )
    invalid = _selection(1)
    evidence = list(invalid.evidence)
    evidence[0] = _pair_evidence(
        0,
        td_front=TD_TWO,
        md_front=MD_TWO,
        md_connections=0,
        td_connections=1,
    )
    invalid = CtpFrontPairSelection(
        pair=invalid.pair,
        config_index=invalid.config_index,
        latency_score_ms=invalid.latency_score_ms,
        evidence=tuple(evidence),
        timeout_seconds=invalid.timeout_seconds,
        repeated_samples=invalid.repeated_samples,
    )
    monkeypatch.setattr(front_check, "select_ctp_front_pair", lambda *_a, **_k: invalid)

    with pytest.raises(RuntimeConfigError):
        front_check.check_configured_ctp_fronts(effective, registry)


def test_success_selection_rejects_forged_latency_and_nonfastest_pair(monkeypatch):
    registry, _binding, _registration, effective, _private, _pairs = _install_fake_profile_gates(
        monkeypatch
    )
    selection = _selection(1)
    forged = replace(selection, latency_score_ms=999.0)
    monkeypatch.setattr(front_check, "select_ctp_front_pair", lambda *_a, **_k: forged)
    with pytest.raises(RuntimeConfigError):
        front_check.check_configured_ctp_fronts(effective, registry)

    faster = _pair_evidence(
        0, td_front=TD_ONE, md_front=MD_ONE, md_connections=3, td_connections=3
    )
    slower = _pair_evidence(
        1, td_front=TD_TWO, md_front=MD_TWO, md_connections=3, td_connections=3
    )
    slower = replace(
        slower,
        md=CtpFrontEndpointEvidence(
            MD_TWO,
            tuple(replace(sample, latency_ms=2.0) for sample in slower.md.samples),
        ),
        td=CtpFrontEndpointEvidence(
            TD_TWO,
            tuple(replace(sample, latency_ms=2.0) for sample in slower.td.samples),
        ),
        latency_score_ms=2.0,
    )
    nonfastest = replace(selection, evidence=(faster, slower), latency_score_ms=2.0)
    monkeypatch.setattr(front_check, "select_ctp_front_pair", lambda *_a, **_k: nonfastest)
    with pytest.raises(RuntimeConfigError):
        front_check.check_configured_ctp_fronts(effective, registry)


@pytest.mark.parametrize(
    "invalid_evidence", ["single_sample", "missing_latency", "repeated_samples"]
)
def test_success_selection_rejects_incomplete_probe_samples(monkeypatch, invalid_evidence):
    registry, _binding, _registration, effective, _private, _pairs = _install_fake_profile_gates(
        monkeypatch
    )
    selection = _selection(1)
    evidence = list(selection.evidence)
    selected_evidence = evidence[1]
    if invalid_evidence == "single_sample":
        md = CtpFrontEndpointEvidence(selected_evidence.md.front, selected_evidence.md.samples[:1])
        evidence[1] = replace(selected_evidence, md=md)
    elif invalid_evidence == "missing_latency":
        samples = list(selected_evidence.md.samples)
        samples[0] = replace(samples[0], latency_ms=None)
        md = CtpFrontEndpointEvidence(selected_evidence.md.front, tuple(samples))
        evidence[1] = replace(selected_evidence, md=md)
    elif invalid_evidence == "repeated_samples":
        selection = replace(selection, repeated_samples=2)
    invalid = replace(selection, evidence=tuple(evidence))
    monkeypatch.setattr(front_check, "select_ctp_front_pair", lambda *_a, **_k: invalid)

    with pytest.raises(RuntimeConfigError):
        front_check.check_configured_ctp_fronts(effective, registry)


def test_cli_returns_nonzero_and_keeps_all_failed_pair_counts(monkeypatch):
    registration = _Registration()

    class _CliRegistry:
        def require_runtime_dir(self, _path: object) -> _Registration:
            return registration

    effective = SimpleNamespace(
        mode="simulation",
        preset="sandbox",
        config=SimpleNamespace(strategy_dir=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR),
    )
    monkeypatch.setattr(cli, "_require_config_driven_ctp_binding", lambda *_args: object())
    monkeypatch.setattr(cli, "validate_runtime_config", lambda *_args: effective)

    class _FailedCheck:
        succeeded = False

        def as_public_dict(self) -> dict[str, object]:
            return {
                "status": "no_pair_reachable",
                "pairs": [
                    {"config_index": 0, "md_connected_count": 0, "td_connected_count": 0},
                    {"config_index": 1, "md_connected_count": 1, "td_connected_count": 0},
                ],
            }

    monkeypatch.setattr(cli, "dispatch_registered_ctp_front_check", lambda *_args: _FailedCheck())
    stdout = io.StringIO()
    stderr = io.StringIO()
    status = cli.main(
        ["check-ctp-fronts", "--strategy-dir", str(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)],
        registry=_CliRegistry(),  # type: ignore[arg-type]
        environ={"CTP_SIMNOW_SET": "set2_7x24", "CTP_FRONT_PAIR_INDEX": "0"},
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 2
    assert stdout.getvalue() == ""
    payload = json.loads(stderr.getvalue())
    assert payload["status"] == "no_pair_reachable"
    assert payload["pairs"] == [
        {"config_index": 0, "md_connected_count": 0, "td_connected_count": 0},
        {"config_index": 1, "md_connected_count": 1, "td_connected_count": 0},
    ]


def test_live_config_at_private_runtime_directory_is_refused_before_probe(monkeypatch):
    registry, _binding, registration, effective, _private, _pairs = _install_fake_profile_gates(
        monkeypatch
    )
    effective.mode = "live"
    effective.preset = "managed_live_direct"
    calls: list[str] = []
    monkeypatch.setattr(
        front_check, "select_ctp_front_pair", lambda *_a, **_k: calls.append("probe")
    )

    with pytest.raises(RuntimeConfigError):
        front_check.check_configured_ctp_fronts(effective, registry)
    assert calls == []
    assert registration.runtime_dir == ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR


def test_front_check_parser_has_no_mode_or_address_override():
    args = cli.build_parser().parse_args(
        ["check-ctp-fronts", "--strategy-dir", str(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)]
    )
    assert args.command == "check-ctp-fronts"
    assert args.strategy_dir == ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    assert not hasattr(args, "mode")
    assert not hasattr(args, "preset")
    assert not hasattr(args, "md_front")
    assert not hasattr(args, "td_front")
    assert not hasattr(args, "front_set")


def test_real_registry_rejects_unsealed_effective_before_probe(monkeypatch):
    probes: list[str] = []
    monkeypatch.setattr(
        front_check,
        "select_ctp_front_pair",
        lambda *_args, **_kwargs: probes.append("probe"),
    )
    fake_effective = SimpleNamespace(
        mode="simulation",
        preset="sandbox",
        config=SimpleNamespace(strategy_dir=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR),
    )

    with pytest.raises(RuntimeConfigError):
        front_check.check_configured_ctp_fronts(
            fake_effective,  # type: ignore[arg-type]
            iteration41_runtime_registry(),
        )
    assert probes == []


def test_cli_rejects_same_directory_live_config_before_front_probe(monkeypatch):
    registration = _Registration()

    class _CliRegistry:
        def require_runtime_dir(self, _path: object) -> _Registration:
            return registration

    registry = _CliRegistry()
    live_effective = SimpleNamespace(
        mode="live",
        preset="managed_live_direct",
        config=SimpleNamespace(strategy_dir=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR),
    )
    validated: list[object] = []
    dispatched: list[str] = []
    monkeypatch.setattr(cli, "_require_config_driven_ctp_binding", lambda *_args: object())
    monkeypatch.setattr(
        cli,
        "validate_runtime_config",
        lambda path, _registry: validated.append(path) or live_effective,
    )
    monkeypatch.setattr(
        cli,
        "dispatch_registered_ctp_front_check",
        lambda *_args: dispatched.append("probe") or None,
    )
    monkeypatch.setattr(cli, "_operator_error_payload", lambda error, **_kwargs: error.as_dict())
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = cli.main(
        ["check-ctp-fronts", "--strategy-dir", str(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)],
        registry=registry,  # type: ignore[arg-type]
        environ={"CTP_SIMNOW_SET": "set2_7x24"},
        stdout=stdout,
        stderr=stderr,
    )
    error = json.loads(stderr.getvalue())

    assert status == 2
    assert validated == [ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR]
    assert dispatched == []
    assert error["reason"] == "ctp_front_check_profile_required"
    assert stdout.getvalue() == ""


def test_cli_rejects_unregistered_directory_and_missing_config_without_probe(monkeypatch):
    calls: list[str] = []

    class _Unregistered:
        def require_runtime_dir(self, _path: object) -> None:
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "unregistered",
                field_path="strategy_dir",
                reason="runtime_not_registered",
            )

    monkeypatch.setattr(cli, "_operator_error_payload", lambda error, **_kwargs: error.as_dict())
    validate_calls: list[str] = []
    monkeypatch.setattr(
        cli,
        "validate_runtime_config",
        lambda *_args: validate_calls.append("validate") or None,
    )
    monkeypatch.setattr(
        cli, "dispatch_registered_ctp_front_check", lambda *_a: calls.append("probe")
    )
    status = cli.main(
        ["check-ctp-fronts", "--strategy-dir", "unregistered"],
        registry=_Unregistered(),  # type: ignore[arg-type]
        environ={},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert status == 2
    assert validate_calls == []
    assert calls == []

    registration = _Registration()

    class _Registered:
        def require_runtime_dir(self, _path: object) -> _Registration:
            return registration

    monkeypatch.setattr(cli, "_require_config_driven_ctp_binding", lambda *_args: object())

    def missing_config(*_args: object) -> None:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "config required",
            field_path="config",
            reason="config_required",
        )

    monkeypatch.setattr(cli, "validate_runtime_config", missing_config)
    stderr = io.StringIO()
    status = cli.main(
        ["check-ctp-fronts", "--strategy-dir", str(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)],
        registry=_Registered(),  # type: ignore[arg-type]
        environ={},
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert status == 2
    assert json.loads(stderr.getvalue())["reason"] == "config_required"
    assert calls == []
