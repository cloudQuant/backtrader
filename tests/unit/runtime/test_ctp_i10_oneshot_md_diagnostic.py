"""Fake-only safety contract tests for the unregistered I10 Job composition."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backtrader_runtime import ctp_i10_oneshot_md_diagnostic as diagnostic
from backtrader_runtime.ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontPairSelection,
)
from backtrader_runtime.ctp_i10_oneshot_md_readonly import CtpI10OneShotMdObservation
from backtrader_runtime.ctp_readonly_job_supervisor import (
    FixedChildCommand,
    ProcessEvidence,
    SupervisedResult,
)
from backtrader_runtime.inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
)
from backtrader_runtime.registry import RuntimeProfile


TD_ONE = "tcp://127.0.0.1:10130"
MD_ONE = "tcp://127.0.0.1:10131"
TD_TWO = "tcp://127.0.0.1:10132"
MD_TWO = "tcp://127.0.0.1:10133"
ACCOUNT_FP = "a" * 64
INSTRUMENT = "IF2612"
EXCHANGE = "CFFEX"


def _profile() -> RuntimeProfile:
    return RuntimeProfile(
        mode="simulation",
        preset="sandbox",
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=(),
        approval_receipt_digest=None,
        runner_module=None,
        runner_entrypoint="run_runtime",
        capability_modules=(),
        offline_managed_execution=False,
        sandbox_write_policy="deny",
    )


class _Registration:
    runtime_id = ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
    digest = "registration-digest"

    def __init__(self) -> None:
        self._profile = _profile()

    def profile_for(self, mode: str, preset: str) -> RuntimeProfile | None:
        return self._profile if (mode, preset) == ("simulation", "sandbox") else None


class _Registry:
    def __init__(self, registration: _Registration, binding: object) -> None:
        self.registration = registration
        self.binding = binding

    def require_runtime_dir(self, _directory: object) -> _Registration:
        return self.registration

    def require_ctp_simnow_readonly_binding(self, _runtime_id: str) -> object:
        return self.binding


def _valid_observation(_admission: object) -> CtpI10OneShotMdObservation:
    return CtpI10OneShotMdObservation(
        md_front_sha256=hashlib.sha256(MD_TWO.encode("utf-8")).hexdigest(),
        account_fingerprint_sha256=ACCOUNT_FP,
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
        connection_generation=7,
        login_identity_state="verified",
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
        client_stop_returned=True,
        native_join_pending=False,
    )


def _complete_receipt() -> dict[str, object]:
    return {
        "account_ready": False,
        "client_stop_returned": True,
        "login_identity_state": "verified",
        "market_login_ready": False,
        "matching_tick_observed": True,
        "native_join_pending": False,
        "order_submission_authorized": False,
        "probe_session_closed": True,
        "reason": "matching_tick_observed",
        "same_trading_day_observed": True,
        "settlement_writes": "zero",
        "stage": "market_data",
        "status": "diagnostic_complete",
        "subscription_acknowledged": True,
        "trading_ready": False,
        "trading_writes": "zero",
    }


def _complete_evidence(**changes: object) -> ProcessEvidence:
    values: dict[str, object] = {
        "process_created": True,
        "job_assignment_observed": True,
        "process_resumed": True,
        "process_exit_observed": True,
        "process_exit_code": 0,
        "job_termination_requested": False,
        "job_termination_call_succeeded": None,
        "job_empty_observed": True,
        "containment": "verified",
    }
    values.update(changes)
    return ProcessEvidence(**values)  # type: ignore[arg-type]


def test_child_pipeline_orders_configured_pair_artifact_and_credentials(monkeypatch, capsys):
    from backtrader_runtime import ctp_simnow_operator, ctp_simnow_readonly_runtime

    events: list[object] = []
    monkeypatch.setattr(diagnostic, "_has_supervised_i10_attempt_context", lambda: True)
    registration = _Registration()
    binding_type = ctp_simnow_operator.CtpSimNowConfigReadOnlyBinding
    binding = binding_type(runtime_id=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)
    registry = _Registry(registration, binding)
    profile = registration.profile_for("simulation", "sandbox")
    config = SimpleNamespace(strategy_dir=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR)
    effective = SimpleNamespace(
        config=config,
        registration=registration,
        profile=profile,
        mode="simulation",
        preset="sandbox",
        strategy_id="013_3",
        effective_digest="effective-digest",
    )
    first_pair = {"td_front": TD_ONE, "md_front": MD_ONE}
    second_pair = {"td_front": TD_TWO, "md_front": MD_TWO}
    private = SimpleNamespace(
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
        hedge_flag="1",
    )
    selection = CtpFrontPairSelection(
        pair=CtpConfiguredFrontPair(md_front=MD_TWO, td_front=TD_TWO),
        config_index=1,
        latency_score_ms=1.0,
        evidence=(),
        timeout_seconds=1.0,
        repeated_samples=1,
    )
    admission = SimpleNamespace(
        td_front=TD_TWO,
        md_front=MD_TWO,
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
        hedge_flag="1",
        account_fingerprint_sha256=ACCOUNT_FP,
    )

    monkeypatch.setattr(diagnostic, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.setattr(
        diagnostic,
        "validate_runtime_config",
        lambda directory, _registry: events.append(("config", directory)) or effective,
    )
    monkeypatch.setattr(
        diagnostic,
        "require_effective_runtime_config_seal",
        lambda _effective, _registry: events.append("sealed_config"),
    )
    monkeypatch.setattr(
        binding_type,
        "_sealed_private_config",
        lambda _self, _effective, _registry: (
            events.append("sealed_private") or (private, registration, (first_pair, second_pair))
        ),
    )
    monkeypatch.setattr(
        binding_type,
        "_route",
        lambda _self, _effective, _registry, **kwargs: (
            events.append(("route", kwargs["selected_config_index"])) or (admission, object())
        ),
    )
    monkeypatch.setattr(
        ctp_simnow_operator,
        "_select_configured_front_pair",
        lambda pairs: events.append(("probe_configured", pairs)) or selection,
    )

    def verify(*, td_front: str, md_front: str) -> None:
        events.append(("artifact", td_front, md_front))

    monkeypatch.setattr(
        diagnostic,
        "verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts",
        verify,
    )

    @contextmanager
    def installed_context(modules: object):
        events.append(("capability_context", modules))
        yield

    monkeypatch.setattr(
        diagnostic, "trusted_installed_capability_import_context", installed_context
    )
    monkeypatch.setattr(
        diagnostic,
        "resolve_runtime_credentials",
        lambda *_args: events.append("resolve_credentials") or object(),
    )
    monkeypatch.setattr(
        diagnostic,
        "require_resolved_runtime_credentials_seal",
        lambda *_args: events.append("credential_seal"),
    )

    class _CredentialSource:
        def __init__(self, *_args: object) -> None:
            events.append("credential_source")

    monkeypatch.setattr(
        ctp_simnow_readonly_runtime, "_SealedCtpCredentialSource", _CredentialSource
    )
    monkeypatch.setattr(
        diagnostic.importlib,
        "import_module",
        lambda name: (
            events.append(("sdk_import", name))
            or SimpleNamespace(
                OneShotMdDiagnosticClient=object,
                CtpNativeStopReceipt=object,
            )
        ),
    )

    def probe(**kwargs: object) -> CtpI10OneShotMdObservation:
        events.append(("probe", kwargs["timeout_seconds"]))
        return _valid_observation(admission)

    monkeypatch.setattr(diagnostic, "probe_i10_oneshot_md_readonly", probe)

    assert diagnostic._run_diagnostic_impl(()) == 0
    receipt = diagnostic.parse_i10_child_receipt(capsys.readouterr().out.encode("utf-8"))
    assert receipt is not None
    assert receipt["status"] == "diagnostic_complete"

    labels = [entry[0] if isinstance(entry, tuple) else entry for entry in events]
    assert (
        labels.index("sealed_config") < labels.index("artifact") < labels.index("probe_configured")
    )
    assert events.count(("artifact", TD_ONE, MD_ONE)) == 1
    assert events.count(("artifact", TD_TWO, MD_TWO)) == 1
    assert events.index("resolve_credentials") > labels.index("probe_configured")
    assert events.index("credential_seal") < next(
        index
        for index, entry in enumerate(events)
        if isinstance(entry, tuple) and entry[0] == "sdk_import"
    )
    probed_pairs = next(
        entry[1] for entry in events if isinstance(entry, tuple) and entry[0] == "probe_configured"
    )
    assert probed_pairs == (first_pair, second_pair)


def test_child_rejects_selector_pair_outside_sealed_fronts_before_credentials(monkeypatch, capsys):
    from backtrader_runtime import ctp_simnow_operator

    events: list[str] = []
    monkeypatch.setattr(diagnostic, "_has_supervised_i10_attempt_context", lambda: True)
    registration = _Registration()
    binding_type = ctp_simnow_operator.CtpSimNowConfigReadOnlyBinding
    binding = binding_type(runtime_id=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)
    registry = _Registry(registration, binding)
    effective = SimpleNamespace(
        config=SimpleNamespace(strategy_dir=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR),
        registration=registration,
        profile=registration.profile_for("simulation", "sandbox"),
        mode="simulation",
        preset="sandbox",
    )
    private = SimpleNamespace(instrument_id=INSTRUMENT, exchange_id=EXCHANGE, hedge_flag="1")
    configured_pair = {"td_front": TD_ONE, "md_front": MD_ONE}
    out_of_config_selection = CtpFrontPairSelection(
        pair=CtpConfiguredFrontPair(md_front="tcp://127.0.0.1:10999", td_front=TD_ONE),
        config_index=0,
        latency_score_ms=1.0,
        evidence=(),
        timeout_seconds=1.0,
        repeated_samples=1,
    )
    monkeypatch.setattr(diagnostic, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.setattr(diagnostic, "validate_runtime_config", lambda *_args: effective)
    monkeypatch.setattr(diagnostic, "require_effective_runtime_config_seal", lambda *_args: None)
    monkeypatch.setattr(
        binding_type,
        "_sealed_private_config",
        lambda *_args: (private, registration, (configured_pair,)),
    )

    @contextmanager
    def empty_context(*_args: object):
        yield

    monkeypatch.setattr(diagnostic, "trusted_installed_capability_import_context", empty_context)
    monkeypatch.setattr(
        diagnostic,
        "verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts",
        lambda **_kwargs: events.append("artifact"),
    )
    monkeypatch.setattr(
        ctp_simnow_operator,
        "_select_configured_front_pair",
        lambda _pairs: out_of_config_selection,
    )
    monkeypatch.setattr(
        diagnostic,
        "resolve_runtime_credentials",
        lambda *_args: events.append("credentials") or object(),
    )

    assert diagnostic._run_diagnostic_impl(()) == 2
    receipt = diagnostic.parse_i10_child_receipt(capsys.readouterr().out.encode("utf-8"))
    assert receipt is not None
    assert receipt["status"] == "rejected"
    assert receipt["stage"] == "front_selection"
    assert events == ["artifact"]


def test_receipt_schema_rejects_sensitive_extra_fields_and_duplicate_keys():
    safe = json.dumps(_complete_receipt(), sort_keys=True).encode("utf-8") + b"\n"
    assert diagnostic.parse_i10_child_receipt(safe) is not None
    leaked = dict(_complete_receipt(), password="do-not-emit")
    assert (
        diagnostic.parse_i10_child_receipt(
            json.dumps(leaked, sort_keys=True).encode("utf-8") + b"\n"
        )
        is None
    )
    duplicate = b'{"status":"diagnostic_complete","status":"rejected"}\n'
    assert diagnostic.parse_i10_child_receipt(duplicate) is None


def test_parent_acceptance_requires_exact_job_completion_evidence():
    receipt = _complete_receipt()
    valid = SupervisedResult(
        "child_exited",
        "child_process_exited",
        receipt,
        _complete_evidence(),
    )
    assert diagnostic._parent_confirms_i10_diagnostic(valid)
    assert not diagnostic._parent_confirms_i10_diagnostic(
        SupervisedResult(
            "child_exited",
            "child_process_exited",
            receipt,
            _complete_evidence(job_empty_observed=False),
        )
    )
    assert not diagnostic._parent_confirms_i10_diagnostic(
        SupervisedResult(
            "child_exited",
            "child_process_exited",
            receipt,
            _complete_evidence(job_termination_requested=True),
        )
    )


def test_latch_is_reserved_before_fixed_runner_and_deadline(monkeypatch):
    events: list[object] = []
    command = FixedChildCommand(
        (r"D:\temp\i10-isolated-pin-20260925\venv\Scripts\python.exe", "-c", "fixed"),
        r"D:\source_code\backtrader",
        {"PYTHONNOUSERSITE": "1"},
        job_handle_env_name=diagnostic._I10_JOB_HANDLE_ENV,
    )

    class _Latch:
        def begin_attempt(self) -> bool:
            events.append("latch")
            return True

        def is_tripped(self) -> bool:
            return False

        def trip(self, _reason: str) -> bool:
            return True

    monkeypatch.setattr(diagnostic, "_fixed_i10_child_command", lambda: command)

    def runner(
        actual_command: FixedChildCommand, _parser: Any, **kwargs: object
    ) -> SupervisedResult:
        events.append(("runner", actual_command, kwargs))
        return SupervisedResult(
            "timed_out", "child_deadline_exceeded", None, _empty_process_evidence()
        )

    result = diagnostic._supervise_i10_child(_Latch(), runner=runner)
    assert result.status == "timed_out"
    assert events[0] == "latch"
    runner_call = events[1]
    assert isinstance(runner_call, tuple) and runner_call[0] == "runner"
    assert runner_call[1] is command
    runner_kwargs = runner_call[2]
    assert runner_kwargs["deadline_seconds"] == diagnostic._I10_TOTAL_DEADLINE_SECONDS
    assert runner_kwargs["termination_grace_seconds"] == diagnostic._I10_TERMINATION_GRACE_SECONDS
    assert runner_kwargs["max_stdout_bytes"] == diagnostic._I10_MAX_STDOUT_BYTES


def _empty_process_evidence() -> ProcessEvidence:
    return ProcessEvidence(False, False, False, None, None, False, None, None, "uncertain")


def test_latch_refusal_never_calls_child_runner(monkeypatch):
    calls: list[str] = []
    command = FixedChildCommand(
        (r"D:\temp\i10-isolated-pin-20260925\venv\Scripts\python.exe", "-c", "fixed"),
        r"D:\source_code\backtrader",
        {"PYTHONNOUSERSITE": "1"},
        job_handle_env_name=diagnostic._I10_JOB_HANDLE_ENV,
    )

    class _UsedLatch:
        def begin_attempt(self) -> bool:
            calls.append("latch")
            return False

    monkeypatch.setattr(diagnostic, "_fixed_i10_child_command", lambda: command)
    result = diagnostic._supervise_i10_child(
        _UsedLatch(),
        runner=lambda *_args, **_kwargs: calls.append("runner") or None,
    )
    assert result.status == "latched"
    assert calls == ["latch"]


def test_code_owned_worker_is_i10_environment_and_wheel_a_path():
    assert Path(r"D:\temp\i10-runtime-env-20260925") == diagnostic._I10_RUNTIME_ROOT
    assert (
        Path(r"D:\temp\i10-runtime-env-20260925") / "Scripts" / "python.exe"
    ) == diagnostic._I10_INTERPRETER
    assert (
        Path(r"D:\temp\i10-final-wheel-repro-20260925\artifacts\a") == diagnostic._I10_WHEEL_A_ROOT
    )
    assert diagnostic.I10_SOURCE_COMMIT == "a6253a58b1ebca11f58c8836fbed757d0daf7582"


def test_fixed_command_is_pinned_without_starting_a_child():
    command = diagnostic._fixed_i10_child_command()
    if os.name != "nt":
        assert command is None
        return
    assert command is not None
    assert command.argv[0] == str(diagnostic._I10_INTERPRETER)
    assert command.argv[1:] == ("-c", diagnostic._I10_CHILD_ENTRY_SOURCE)
    assert command.job_handle_env_name == diagnostic._I10_JOB_HANDLE_ENV
    assert "PYTHONPATH" not in command.env
    assert "PYTHONHOME" not in command.env


def test_child_entry_rejects_without_inherited_job(monkeypatch, capsys):
    monkeypatch.setattr(diagnostic, "_is_current_process_in_job", lambda: False)
    assert diagnostic._run_child_entry() == 2
    receipt = diagnostic.parse_i10_child_receipt(capsys.readouterr().out.encode("utf-8"))
    assert receipt is not None
    assert receipt["reason"] == "supervisor_context_required"
    assert receipt["stage"] == "arguments"


def test_private_child_body_rejects_direct_call_before_config_or_provider(monkeypatch, capsys):
    monkeypatch.setattr(diagnostic, "_is_current_process_in_job", lambda: False)
    monkeypatch.setattr(
        diagnostic,
        "validate_runtime_config",
        lambda *_args: (_ for _ in ()).throw(AssertionError("config read")),
    )
    assert diagnostic._run_diagnostic_impl(()) == 2
    receipt = diagnostic.parse_i10_child_receipt(capsys.readouterr().out.encode("utf-8"))
    assert receipt is not None
    assert receipt["reason"] == "supervisor_context_required"


def test_job_membership_without_canonical_latch_still_rejects(monkeypatch, capsys):
    monkeypatch.setattr(diagnostic, "_is_current_process_in_job", lambda: True)

    class MissingLatch:
        def __init__(self, path: Path) -> None:
            assert path == diagnostic.I10_LATCH_PATH

        def is_tripped(self) -> bool:
            return False

    monkeypatch.setattr(diagnostic, "PersistentI10OneShotAttemptLatch", MissingLatch)
    assert diagnostic._run_diagnostic_impl(()) == 2
    receipt = diagnostic.parse_i10_child_receipt(capsys.readouterr().out.encode("utf-8"))
    assert receipt is not None
    assert receipt["reason"] == "supervisor_context_required"
