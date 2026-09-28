"""Synthetic-only tests for the unregistered I8 one-shot MD candidate."""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import backtrader_runtime.ctp_artifact_provenance as artifact_provenance
import backtrader_runtime.ctp_simnow_operator as simnow_operator
from backtrader_runtime import ctp_i8_oneshot_md_diagnostic as diagnostic
from backtrader_runtime import ctp_i8_oneshot_md_readonly as adapter
from backtrader_runtime import ctp_readonly_job_supervisor as supervisor
from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from backtrader_runtime.inventory import (
    ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
)


TD_FRONT = "tcp://192.0.2.10:10101"
MD_FRONT = "tcp://192.0.2.11:10111"
TD_FRONT_2 = "tcp://192.0.2.20:10101"
MD_FRONT_2 = "tcp://192.0.2.21:10111"
INSTRUMENT = "SA610"
EXCHANGE = "CZCE"
HEDGE_FLAG = "1"
BROKER_ID = "9999"
USER_ID = "synthetic-user"
PASSWORD = "synthetic-password"
ACCOUNT_FINGERPRINT = hashlib.sha256(f"{BROKER_ID}:{USER_ID}".encode("utf-8")).hexdigest()


def _observation(admission: Any) -> adapter.CtpI8OneShotMdObservation:
    return adapter.CtpI8OneShotMdObservation(
        md_front_sha256=hashlib.sha256(admission.md_front.encode("utf-8")).hexdigest(),
        account_fingerprint_sha256=admission.account_fingerprint_sha256,
        instrument_id=admission.instrument_id,
        exchange_id=admission.exchange_id,
        connection_generation=1,
        identity_unverified=True,
        market_login_ready=False,
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
        client_stop_returned=True,
        native_join_pending=False,
        diagnostic_evidence=adapter.CtpI8OneShotMdDiagnosticEvidence(
            evidence_level="complete",
            close_state="stop_returned",
            primary_error=None,
            login_callback_count="one",
            login_callback_disposition="identity_unverified",
            login_request_id_relation="zero",
            login_response_error_status="zero",
            login_broker_id_shape="empty",
            login_user_id_shape="empty",
            login_trading_day_shape="valid",
            native_broker_id_shape="empty",
            native_user_id_shape="empty",
            identity_unverified=True,
            subscription_acknowledged=True,
            matching_tick_observed=True,
            same_trading_day_observed=True,
            client_stop_returned=True,
            native_join_pending=False,
        ),
    )


def _install_composition_fakes(
    monkeypatch: pytest.MonkeyPatch,
    events: list[Any],
    *,
    selected_index: int = 1,
) -> tuple[Any, Any]:
    registration = SimpleNamespace(runtime_id=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)
    effective = SimpleNamespace(
        config=SimpleNamespace(strategy_dir=Path("registered-runtime")),
        registration=registration,
    )
    configured_pairs = (
        {"td_front": TD_FRONT, "md_front": MD_FRONT},
        {"td_front": TD_FRONT_2, "md_front": MD_FRONT_2},
    )
    chosen_pair = configured_pairs[selected_index]
    private = SimpleNamespace(
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
        hedge_flag=HEDGE_FLAG,
    )
    admission = SimpleNamespace(
        td_front=chosen_pair["td_front"],
        md_front=chosen_pair["md_front"],
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
        hedge_flag=HEDGE_FLAG,
        account_fingerprint_sha256=ACCOUNT_FINGERPRINT,
    )
    scope = object()
    selected_pair = SimpleNamespace(**chosen_pair)
    selection = SimpleNamespace(pair=selected_pair, config_index=selected_index)

    class _Binding:
        def _sealed_private_config(self, _effective: Any, _registry: Any) -> Any:
            events.append("sealed_private_config")
            return private, registration, configured_pairs

        def _route(
            self,
            _effective: Any,
            _registry: Any,
            *,
            selected_front_pair: Any,
        ) -> Any:
            events.append("route")
            assert selected_front_pair is selection.pair
            return admission, scope

    binding = _Binding()
    registry = SimpleNamespace()
    registry.require_runtime_dir = lambda _directory: registration
    registry.require_ctp_simnow_readonly_binding = lambda _runtime_id: binding
    monkeypatch.setattr(diagnostic, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.setattr(diagnostic, "validate_runtime_config", lambda *_args: effective)
    monkeypatch.setattr(diagnostic, "require_effective_runtime_config_seal", lambda *_args: None)
    monkeypatch.setattr(simnow_operator, "CtpSimNowConfigReadOnlyBinding", _Binding)
    monkeypatch.setattr(
        simnow_operator,
        "_select_configured_front_pair",
        lambda _pairs: events.append("front_selection") or selection,
    )
    monkeypatch.setattr(
        diagnostic,
        "trusted_installed_capability_import_context",
        lambda _modules: nullcontext(),
    )
    monkeypatch.setattr(
        diagnostic,
        "resolve_runtime_credentials",
        lambda *_args: events.append("credential_resolution") or object(),
    )
    monkeypatch.setattr(
        diagnostic,
        "require_resolved_runtime_credentials_seal",
        lambda *_args: events.append("credential_seal"),
    )
    import backtrader_runtime.ctp_simnow_readonly_runtime as readonly_runtime

    monkeypatch.setattr(
        readonly_runtime,
        "_SealedCtpCredentialSource",
        lambda *_args: events.append("credential_source") or object(),
    )
    original_import = importlib.import_module

    def _import_module(name: str, package: str | None = None) -> Any:
        if name == "bt_api_ctp.ctp.client":
            events.append("sdk_import")
            return SimpleNamespace(
                OneShotMdDiagnosticClient=object,
                CtpNativeStopReceipt=object,
            )
        return original_import(name, package)

    monkeypatch.setattr(diagnostic.importlib, "import_module", _import_module)
    return admission, scope


def _install_pin_verifier(monkeypatch: pytest.MonkeyPatch, callback: Any) -> None:
    monkeypatch.setattr(
        artifact_provenance,
        "verify_ctp_i8_oneshot_md_diagnostic_artifact_provenance_for_fronts",
        callback,
    )


def test_i8_pin_records_the_retained_wheel_and_record_identities() -> None:
    pins = artifact_provenance.CTP_I8_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS
    base, ctp = pins["bt_api_base"], pins["bt_api_ctp"]

    assert base.wheel_filename == "bt_api_base-0.15.5-py3-none-any.whl"
    assert base.wheel_sha256 == ("2f413f7e914c4bbd1dcd47b3b95a3fb36e224dda2c4db97bdda35bf61797ad68")
    assert base.record_sha256 == (
        "40052081b6ddff201e059818d310e83c012f7e428ba2e76dc64af0417e68de4d"
    )
    assert ctp.version == "2.0.3+iteration41.i8"
    assert ctp.wheel_filename == ("bt_api_ctp-2.0.3+iteration41.i8-cp311-cp311-win_amd64.whl")
    assert ctp.wheel_sha256 == ("f354327f092993cce7954339deca3b5cc32ab953f5fd330ba5a6b3a7ea94f715")
    assert ctp.record_sha256 == ("1b2ce3ad778712e735d9e76f44e81748c8af323ece5bc0a0e96e51148882c48a")


def test_i8_verifier_uses_only_the_code_owned_pin_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[Any] = []
    monkeypatch.setattr(
        artifact_provenance,
        "_verify_pinned_sdk_distributions",
        lambda modules, *, pins: captured.append((modules, pins)) or {},
    )

    artifact_provenance.verify_ctp_i8_oneshot_md_diagnostic_artifact_provenance_for_fronts(
        td_front=TD_FRONT,
        md_front=MD_FRONT,
    )

    assert captured == [
        (
            ("bt_api_base", "bt_api_ctp"),
            artifact_provenance.CTP_I8_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS,
        )
    ]


def test_i8_artifact_mismatch_rejects_before_front_selection_credentials_or_sdk_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events)

    def _bad_pin(**_kwargs: Any) -> None:
        events.append("artifact_verification")
        raise artifact_provenance.CtpArtifactProvenanceError("artifact_record_pin_mismatch")

    _install_pin_verifier(monkeypatch, _bad_pin)

    assert diagnostic._run_diagnostic_impl([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert (
        diagnostic.parse_i8_child_receipt(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        )
        == payload
    )
    assert payload["reason"] == "sdk_artifact_rejected"
    assert payload["stage"] == "sdk_artifact"
    assert events == ["sealed_private_config", "artifact_verification"]


def test_i8_composition_binds_exact_pair_and_instrument_before_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[Any] = []
    admission, _scope = _install_composition_fakes(monkeypatch, events, selected_index=1)
    _install_pin_verifier(
        monkeypatch,
        lambda **kwargs: events.append(("artifact_verification", kwargs["md_front"])),
    )

    def _probe(**kwargs: Any) -> adapter.CtpI8OneShotMdObservation:
        events.append(("probe", kwargs["expected_diagnostic_instrument"]))
        assert kwargs["admission"].md_front == MD_FRONT_2
        return _observation(kwargs["admission"])

    monkeypatch.setattr(diagnostic, "probe_i8_oneshot_md_readonly", _probe)

    assert diagnostic._run_diagnostic_impl([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "diagnostic_complete"
    assert payload["reason"] == "identity_unverified_tick_observed"
    assert payload["identity_unverified"] is True
    assert payload["market_login_ready"] is False
    assert payload["subscription_acknowledged"] is True
    assert payload["same_trading_day_observed"] is True
    assert payload["order_submission_authorized"] is False
    assert events == [
        "sealed_private_config",
        ("artifact_verification", MD_FRONT),
        "front_selection",
        "route",
        ("artifact_verification", MD_FRONT_2),
        "credential_resolution",
        "credential_seal",
        "credential_source",
        "sdk_import",
        ("probe", INSTRUMENT),
    ]


@pytest.mark.parametrize("stop_returned", [True, None])
def test_i8_composition_preserves_partial_stop_evidence_without_false_negatives(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stop_returned: bool | None,
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events, selected_index=1)
    _install_pin_verifier(monkeypatch, lambda **_kwargs: None)
    partial = adapter.CtpI8OneShotMdDiagnosticEvidence(
        evidence_level="partial",
        close_state="native_stop_incomplete",
        primary_error="market_subscription_rejected",
        login_callback_count="one",
        login_callback_disposition="identity_unverified",
        login_request_id_relation="zero",
        login_response_error_status="zero",
        login_broker_id_shape="empty",
        login_user_id_shape="empty",
        login_trading_day_shape="valid",
        native_broker_id_shape="empty",
        native_user_id_shape="empty",
        identity_unverified=True,
        subscription_acknowledged=None,
        matching_tick_observed=None,
        same_trading_day_observed=None,
        client_stop_returned=stop_returned,
        native_join_pending=None,
    )

    def _probe(**_kwargs: Any) -> Any:
        error = CtpSdkMarketReadOnlyError("market_client_stop_failed")
        error.i8_diagnostic_evidence = partial
        raise error

    monkeypatch.setattr(diagnostic, "probe_i8_oneshot_md_readonly", _probe)

    assert diagnostic._run_diagnostic_impl([]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "incomplete"
    assert payload["reason"] == "native_shutdown_uncertain"
    assert payload["evidence_level"] == "partial"
    assert payload["close_state"] == "native_stop_incomplete"
    assert payload["primary_error"] == "market_subscription_rejected"
    assert payload["identity_unverified"] is True
    assert payload["subscription_acknowledged"] is None
    assert payload["matching_tick_observed"] is None
    assert payload["same_trading_day_observed"] is None
    assert payload["client_stop_returned"] is stop_returned
    assert payload["native_join_pending"] is None
    assert payload["native_shutdown_uncertain"] is True
    assert payload["probe_session_closed"] is False
    assert (
        diagnostic.parse_i8_child_receipt(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode()
        )
        == payload
    )


def test_i8_receipt_rejects_unrecognized_fields_secrets_and_duplicate_keys() -> None:
    payload = {
        "close_state": "stop_returned",
        "client_stop_returned": True,
        "evidence_level": "complete",
        "identity_unverified": True,
        "login_broker_id_shape": "empty",
        "login_callback_count": "one",
        "login_callback_disposition": "identity_unverified",
        "login_request_id_relation": "zero",
        "login_response_error_status": "zero",
        "login_trading_day_shape": "valid",
        "login_user_id_shape": "empty",
        "matching_tick_observed": True,
        "market_login_ready": False,
        "native_broker_id_shape": "empty",
        "native_join_pending": False,
        "native_shutdown_uncertain": False,
        "native_user_id_shape": "empty",
        "order_submission_authorized": False,
        "primary_error": None,
        "probe_session_closed": True,
        "reason": "identity_unverified_tick_observed",
        "same_trading_day_observed": True,
        "stage": "market_data",
        "status": "diagnostic_complete",
        "subscription_acknowledged": True,
    }
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert diagnostic.parse_i8_child_receipt(raw) == payload
    assert (
        diagnostic.parse_i8_child_receipt(raw.rstrip(b"\n")[:-1] + b',"password":"hunter2"}\n')
        is None
    )
    duplicate = raw[:-2] + b',"native_join_pending":null}\n'
    assert diagnostic.parse_i8_child_receipt(duplicate) is None


def test_i8_supervisor_requires_latch(monkeypatch: pytest.MonkeyPatch) -> None:
    command = supervisor.FixedChildCommand(
        (
            r"D:\fixed\python.exe",
            "-c",
            "private-child-entry",
        ),
        Path.cwd(),
        {"PYTHONNOUSERSITE": "1"},
        job_handle_env_name="bt_i8_parent_job_handle",
    )
    monkeypatch.setattr(diagnostic, "_fixed_i8_child_command", lambda: command)

    missing = diagnostic._supervise_i8_child(None)
    assert missing.status == "supervisor_error"
    assert missing.reason == "i8_runtime_or_latch_unavailable"
    assert missing.process_evidence.process_created is False

    class _Latch:
        def begin_attempt(self) -> bool:
            return True

        def is_tripped(self) -> bool:
            return False

        def trip(self, _reason: str) -> bool:
            return True

    latch = _Latch()
    captured: dict[str, Any] = {}

    def fake_runner(child_command: Any, parser: Any, **kwargs: Any) -> Any:
        captured.update(command=child_command, parser=parser, **kwargs)
        return supervisor.SupervisedResult(
            "child_exited",
            "child_process_exited",
            None,
            supervisor.ProcessEvidence(
                False, False, False, None, None, False, None, None, "verified"
            ),
        )

    result = diagnostic._supervise_i8_child(latch, runner=fake_runner)
    assert result.status == "child_exited"
    assert captured["command"] is command
    assert captured["parser"] is diagnostic.parse_i8_child_receipt
    assert captured["receipt_schema"] is diagnostic.I8_CHILD_RECEIPT_SCHEMA
    assert captured["fail_closed_latch"] is latch
    assert captured["deadline_seconds"] == 45.0
    assert captured["max_stdout_bytes"] == 16 * 1024
    assert captured["termination_grace_seconds"] == 5.0


def test_public_supervisor_has_no_latch_or_runner_injection_surface() -> None:
    assert tuple(inspect.signature(diagnostic.supervise_i8_child).parameters) == ()
    assert "supervise_i8_child" not in diagnostic.__all__
    assert "_supervise_i8_child" not in diagnostic.__all__


@pytest.mark.skipif(os.name != "nt", reason="the reviewed child runtime is Windows-only")
def test_i8_child_command_is_fixed_and_uses_a_credential_free_environment() -> None:
    command = diagnostic._fixed_i8_child_command()
    assert command is not None
    assert command.argv == (
        r"D:\temp\i8-readonly-installed-wheel-venv-a7d9b04\Scripts\python.exe",
        "-c",
        diagnostic._I8_CHILD_ENTRY_SOURCE,
    )
    assert command.job_handle_env_name == diagnostic._I8_JOB_HANDLE_ENV
    assert command.cwd == Path(diagnostic.__file__).resolve().parents[1]
    assert set(command.env) == {
        "SYSTEMROOT",
        "WINDIR",
        "PATH",
        "TEMP",
        "TMP",
        "PYTHONNOUSERSITE",
        "PYTHONDONTWRITEBYTECODE",
        "PYTHONUNBUFFERED",
        "PYTHONUTF8",
    }
    assert "PYTHONPATH" not in command.env
    assert "PASSWORD" not in command.env


def _complete_parent_result() -> supervisor.SupervisedResult:
    receipt = {
        "close_state": "stop_returned",
        "client_stop_returned": True,
        "evidence_level": "complete",
        "identity_unverified": True,
        "login_broker_id_shape": "empty",
        "login_callback_count": "one",
        "login_callback_disposition": "identity_unverified",
        "login_request_id_relation": "zero",
        "login_response_error_status": "zero",
        "login_trading_day_shape": "valid",
        "login_user_id_shape": "empty",
        "matching_tick_observed": True,
        "market_login_ready": False,
        "native_broker_id_shape": "empty",
        "native_join_pending": False,
        "native_shutdown_uncertain": False,
        "native_user_id_shape": "empty",
        "order_submission_authorized": False,
        "primary_error": None,
        "probe_session_closed": True,
        "reason": "identity_unverified_tick_observed",
        "same_trading_day_observed": True,
        "stage": "market_data",
        "status": "diagnostic_complete",
        "subscription_acknowledged": True,
    }
    evidence = supervisor.ProcessEvidence(
        True,
        True,
        True,
        True,
        0,
        False,
        None,
        True,
        "verified",
    )
    return supervisor.SupervisedResult(
        "child_exited",
        "child_process_exited",
        receipt,
        evidence,
    )


def _incomplete_child_result() -> supervisor.SupervisedResult:
    completed = _complete_parent_result()
    receipt = dict(completed.sdk_receipt)
    receipt.update(
        close_state="native_join_state_unknown",
        client_stop_returned=True,
        evidence_level="partial",
        identity_unverified=None,
        matching_tick_observed=None,
        market_login_ready=None,
        native_join_pending=None,
        native_shutdown_uncertain=True,
        probe_session_closed=False,
        reason="native_shutdown_uncertain",
        same_trading_day_observed=None,
        status="incomplete",
        subscription_acknowledged=None,
    )
    evidence = supervisor.ProcessEvidence(
        True,
        True,
        True,
        True,
        3,
        False,
        None,
        True,
        "verified",
    )
    return supervisor.SupervisedResult(
        "child_exited",
        "child_process_exited",
        receipt,
        evidence,
    )


def test_parent_requires_exact_receipt_and_job_exit_evidence() -> None:
    complete = _complete_parent_result()
    assert diagnostic._parent_confirms_i8_diagnostic(complete)
    partial_level = dict(complete.sdk_receipt)
    partial_level["evidence_level"] = "partial"
    assert not diagnostic._parent_confirms_i8_diagnostic(
        supervisor.SupervisedResult(
            complete.status,
            complete.reason,
            partial_level,
            complete.process_evidence,
        )
    )
    unknown_observation = dict(complete.sdk_receipt)
    unknown_observation["subscription_acknowledged"] = None
    assert not diagnostic._parent_confirms_i8_diagnostic(
        supervisor.SupervisedResult(
            complete.status,
            complete.reason,
            unknown_observation,
            complete.process_evidence,
        )
    )
    assert not diagnostic._parent_confirms_i8_diagnostic(
        supervisor.SupervisedResult(
            complete.status,
            complete.reason,
            complete.sdk_receipt,
            supervisor.ProcessEvidence(True, True, True, True, 0, False, None, None, "verified"),
        )
    )
    pending = dict(complete.sdk_receipt)
    pending["native_join_pending"] = True
    assert not diagnostic._parent_confirms_i8_diagnostic(
        supervisor.SupervisedResult(
            complete.status, complete.reason, pending, complete.process_evidence
        )
    )


def test_supervisor_promotes_only_complete_receipt_with_verified_job_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = supervisor.FixedChildCommand(
        (r"D:\fixed\python.exe", "-c", "private-child-entry"),
        Path.cwd(),
        {"PYTHONNOUSERSITE": "1"},
        job_handle_env_name="bt_i8_parent_job_handle",
    )
    monkeypatch.setattr(diagnostic, "_fixed_i8_child_command", lambda: command)

    class _Latch:
        def begin_attempt(self) -> bool:
            return True

        def is_tripped(self) -> bool:
            return False

        def trip(self, _reason: str) -> bool:
            return True

    accepted = diagnostic._supervise_i8_child(
        _Latch(), runner=lambda *_args, **_kwargs: _complete_parent_result()
    )
    assert accepted.status == "diagnostic_complete"
    assert accepted.sdk_receipt["native_join_pending"] is False
    assert accepted.process_evidence.job_empty_observed is True

    pending_receipt = dict(_complete_parent_result().sdk_receipt)
    pending_receipt["native_join_pending"] = True
    pending_receipt["reason"] = "native_join_pending"
    pending_receipt["status"] = "incomplete"
    pending = supervisor.SupervisedResult(
        "child_exited",
        "child_process_exited",
        pending_receipt,
        _complete_parent_result().process_evidence,
    )
    rejected = diagnostic._supervise_i8_child(_Latch(), runner=lambda *_args, **_kwargs: pending)
    assert rejected.status == "incomplete"
    assert rejected.reason == "child_diagnostic_incomplete"
    assert rejected.sdk_receipt == pending_receipt
    assert rejected.process_evidence == pending.process_evidence
    forged_completion = supervisor.SupervisedResult(
        "diagnostic_complete",
        "identity_unverified_tick_observed",
        _complete_parent_result().sdk_receipt,
        supervisor.ProcessEvidence(
            False, False, False, None, None, False, None, None, "unavailable"
        ),
    )
    rejected_forgery = diagnostic._supervise_i8_child(
        _Latch(), runner=lambda *_args, **_kwargs: forged_completion
    )
    assert rejected_forgery.status == "incomplete"
    assert rejected_forgery.reason == "parent_completion_evidence_missing"


@pytest.mark.parametrize(
    ("child_status", "expected_status", "expected_reason"),
    (
        ("incomplete", "incomplete", "child_diagnostic_incomplete"),
        ("rejected", "rejected", "child_diagnostic_rejected"),
    ),
)
def test_parent_maps_noncomplete_child_receipts_and_preserves_os_evidence(
    monkeypatch: pytest.MonkeyPatch,
    child_status: str,
    expected_status: str,
    expected_reason: str,
) -> None:
    command = supervisor.FixedChildCommand(
        (r"D:\fixed\python.exe", "-c", "private-child-entry"),
        Path.cwd(),
        {"PYTHONNOUSERSITE": "1"},
        job_handle_env_name="bt_i8_parent_job_handle",
    )
    monkeypatch.setattr(diagnostic, "_fixed_i8_child_command", lambda: command)

    class _Latch:
        def begin_attempt(self) -> bool:
            return True

        def is_tripped(self) -> bool:
            return False

        def trip(self, _reason: str) -> bool:
            return True

    child_result = _incomplete_child_result()
    receipt = dict(child_result.sdk_receipt)
    if child_status == "rejected":
        receipt.update(reason="runtime_policy_rejected", status="rejected")
        child_result = supervisor.SupervisedResult(
            child_result.status,
            child_result.reason,
            receipt,
            child_result.process_evidence,
        )
    normalized = diagnostic._supervise_i8_child(
        _Latch(), runner=lambda *_args, **_kwargs: child_result
    )
    assert normalized.status == expected_status
    assert normalized.reason == expected_reason
    assert normalized.sdk_receipt == receipt
    assert normalized.process_evidence is child_result.process_evidence


def test_main_returns_nonzero_for_exact_incomplete_child_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["ctp_i8_oneshot_md_diagnostic"])
    child_result = _incomplete_child_result()
    normalized = supervisor.SupervisedResult(
        "incomplete",
        "child_diagnostic_incomplete",
        child_result.sdk_receipt,
        child_result.process_evidence,
    )
    monkeypatch.setattr(diagnostic, "supervise_i8_child", lambda: normalized)

    assert diagnostic.main() != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "incomplete"
    assert payload["reason"] == "child_diagnostic_incomplete"
    assert payload["process_evidence"]["process_exit_code"] == 3
    assert payload["process_evidence"]["job_empty_observed"] is True
    assert payload["sdk_receipt"]["native_shutdown_uncertain"] is True


def test_public_module_main_uses_parent_supervisor_never_direct_probe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["ctp_i8_oneshot_md_diagnostic"])
    latch = object()
    result = _complete_parent_result()
    parent_success = supervisor.SupervisedResult(
        "diagnostic_complete",
        "identity_unverified_tick_observed",
        result.sdk_receipt,
        result.process_evidence,
    )
    monkeypatch.setattr(diagnostic, "_PersistentI8NoRetryLatch", lambda: latch)
    monkeypatch.setattr(
        diagnostic,
        "supervise_i8_child",
        lambda: parent_success,
    )
    monkeypatch.setattr(
        diagnostic,
        "run_diagnostic",
        lambda *_args, **_kwargs: pytest.fail("public main bypassed the supervisor"),
    )

    assert diagnostic.main() == 0
    parent_payload = json.loads(capsys.readouterr().out)
    assert parent_payload["status"] == "diagnostic_complete"
    assert parent_payload["process_evidence"]["job_empty_observed"] is True
    assert parent_payload["sdk_receipt"]["native_join_pending"] is False


def test_public_module_rejects_cli_arguments_before_latch_or_child(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["-m", "--help"])
    monkeypatch.setattr(
        diagnostic,
        "_PersistentI8NoRetryLatch",
        lambda: pytest.fail("arguments reached latch creation"),
    )
    monkeypatch.setattr(
        diagnostic,
        "supervise_i8_child",
        lambda *_args, **_kwargs: pytest.fail("arguments reached child launch"),
    )

    assert diagnostic.main() == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "rejected"
    assert receipt["reason"] == "arguments_not_allowed"
    assert receipt["stage"] == "arguments"


def test_private_child_entry_rejects_outside_exact_job_before_probe(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(diagnostic, "_is_current_process_in_job", lambda: False)
    monkeypatch.setattr(
        diagnostic,
        "run_diagnostic",
        lambda *_args, **_kwargs: pytest.fail("uncontained child entered provider path"),
    )

    assert diagnostic._run_child_entry() == 2
    child_receipt = json.loads(capsys.readouterr().out)
    assert child_receipt["reason"] == "supervisor_context_required"
    assert child_receipt["stage"] == "arguments"


def test_public_direct_diagnostic_api_rejects_before_credentials_or_config(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        diagnostic,
        "resolve_runtime_credentials",
        lambda *_args, **_kwargs: (
            events.append("credentials") or pytest.fail("direct API reached credential resolution")
        ),
    )

    assert diagnostic.run_diagnostic([]) == 2
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["reason"] == "supervisor_context_required"
    assert receipt["stage"] == "arguments"
    assert events == []
    assert "run_diagnostic" not in diagnostic.__all__


def _protect_test_directory(path: Path) -> None:
    path.mkdir()
    if os.name == "nt":
        from backtrader_runtime.ctp_private_config_setup import (
            _protect_target_directory,
            _verified_target_directory,
        )

        with _verified_target_directory(path) as descriptor:
            _protect_target_directory(descriptor)
    else:
        path.chmod(0o700)


def test_persistent_latch_blocks_fresh_process_after_one_attempt(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _protect_test_directory(state)
    path = state / "one-shot.latch"

    first = diagnostic._PersistentI8NoRetryLatch(path)
    assert first.begin_attempt() is True
    assert first.is_tripped() is False
    assert first.trip("native_join_pending") is True

    restarted = diagnostic._PersistentI8NoRetryLatch(path)
    assert restarted.is_tripped() is True
    assert restarted.begin_attempt() is False


def test_poisoned_latch_blocks_supervised_child_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    _protect_test_directory(state)
    path = state / "one-shot.latch"
    first = diagnostic._PersistentI8NoRetryLatch(path)
    assert first.begin_attempt() is True
    path.write_bytes(b"poison")
    latch = diagnostic._PersistentI8NoRetryLatch(path)
    command = supervisor.FixedChildCommand(
        (r"D:\fixed\python.exe", "-c", "private-child-entry"),
        Path.cwd(),
        {"PYTHONNOUSERSITE": "1"},
        job_handle_env_name="bt_i8_parent_job_handle",
    )
    monkeypatch.setattr(diagnostic, "_fixed_i8_child_command", lambda: command)
    launches: list[str] = []

    def _runner(*_args: Any, **_kwargs: Any) -> supervisor.SupervisedResult:
        launches.append("child")
        return _complete_parent_result()

    result = diagnostic._supervise_i8_child(latch, runner=_runner)
    assert result.status == "supervisor_error"
    assert launches == []


class _FakeLease:
    def __init__(self, _key: str) -> None:
        self.acquired = False

    def acquire(self) -> None:
        self.acquired = True

    def release(self) -> None:
        self.acquired = False


def _i8_admission() -> Any:
    from backtrader_runtime.ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration

    return CtpSandboxReadOnlyRegistration(
        runtime_registration=ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION,
        environment="simnow",
        sdk_profile="config_front_pair",
        account_fingerprint_sha256=ACCOUNT_FINGERPRINT,
        allowed_secrets_ref="config_yaml",
        instrument_id=INSTRUMENT,
        exchange_id=EXCHANGE,
        hedge_flag=HEDGE_FLAG,
        td_front=TD_FRONT,
        md_front=MD_FRONT,
    )


def _fake_i8_sdk_types() -> tuple[type[Any], type[Any]]:
    class _StopReceipt:
        def __init__(self) -> None:
            self.connection_generation = 1
            self.join_required = True
            self.join_completed = True
            self.native_released = True
            self.thread_alive = False
            self.timed_out = False
            self.client_stop_returned = True
            self.complete = True

    _StopReceipt.__name__ = "CtpNativeStopReceipt"
    _StopReceipt.__module__ = "bt_api_ctp.ctp.client"

    class _Client:
        def __init__(
            self,
            front: str,
            broker_id: str,
            user_id: str,
            _password: str,
            *,
            expected_diagnostic_instrument: str,
        ) -> None:
            self.front = front
            self.broker_id = broker_id
            self.user_id = user_id
            self.expected_diagnostic_instrument = expected_diagnostic_instrument
            self._state_lock = threading.RLock()
            self._connection_generation = 0
            self._connected = False
            self._loggedin = False
            self._active_md_identity = None
            self._diagnostic_identity_unverified = False
            self._diagnostic_identity_unverified_active = False
            self._diagnostic_identity_unverified_trading_day = None
            self._diagnostic_terminal = False
            self._diagnostic_terminal_reason = None
            self._diagnostic_subscription_acknowledged = False
            self._diagnostic_first_tick_received = False
            self._thread = None
            self.diagnostic_callbacks_active = 0
            self.on_identity_unverified = None
            self.on_login = None
            self.on_error = None
            self.on_disconnect = None
            self.on_subscribe = None
            self.on_tick = None
            self.subscribed: list[str] = []

        @property
        def connection_generation(self) -> int:
            return self._connection_generation

        @property
        def diagnostic_identity_unverified(self) -> bool:
            return self._diagnostic_identity_unverified

        @property
        def diagnostic_subscription_acknowledged(self) -> bool:
            return self._diagnostic_subscription_acknowledged

        @property
        def diagnostic_first_tick_received(self) -> bool:
            return self._diagnostic_first_tick_received

        @property
        def diagnostic_terminal(self) -> bool:
            return self._diagnostic_terminal

        @property
        def diagnostic_terminal_reason(self) -> str | None:
            return self._diagnostic_terminal_reason

        @property
        def active_md_identity(self) -> None:
            return self._active_md_identity

        @property
        def is_ready(self) -> bool:
            return False

        @property
        def login_callback_diagnostic(self) -> Any:
            return SimpleNamespace(
                callback_count=1,
                disposition=SimpleNamespace(value="identity_unverified"),
                request_id_relation=SimpleNamespace(value="zero"),
                response_error_status=SimpleNamespace(value="zero"),
                broker_id_shape=SimpleNamespace(value="empty"),
                user_id_shape=SimpleNamespace(value="empty"),
                native_broker_id_shape=SimpleNamespace(value="empty"),
                native_user_id_shape=SimpleNamespace(value="empty"),
                trading_day_shape=SimpleNamespace(value="valid"),
            )

        def start(self, *, block: bool) -> None:
            assert block is False
            with self._state_lock:
                self._connection_generation = 1
                self._connected = True
                self._diagnostic_identity_unverified = True
                self._diagnostic_identity_unverified_active = True
                self._diagnostic_identity_unverified_trading_day = "20260925"
            self.on_identity_unverified()

        def subscribe(self, instrument: str) -> int:
            assert instrument == self.expected_diagnostic_instrument
            self.subscribed.append(instrument)
            with self._state_lock:
                self._diagnostic_subscription_acknowledged = True
            self.on_subscribe(
                SimpleNamespace(InstrumentID=instrument),
                SimpleNamespace(ErrorID=0),
            )
            with self._state_lock:
                self._diagnostic_first_tick_received = True
                self._diagnostic_terminal = True
                self._diagnostic_terminal_reason = "diagnostic_complete"
                self._diagnostic_identity_unverified_active = False
                self._connected = False
            self.on_tick(
                SimpleNamespace(
                    InstrumentID=instrument,
                    ExchangeID=EXCHANGE,
                    TradingDay="20260925",
                    LastPrice=13.0,
                    Volume=1,
                )
            )
            return 0

        def stop_and_wait(self, *, timeout: float) -> Any:
            assert timeout > 0
            return _StopReceipt()

    _Client.__name__ = "OneShotMdDiagnosticClient"
    _Client.__module__ = "bt_api_ctp.ctp.client"
    return _Client, _StopReceipt


def test_i8_fake_adapter_subscribes_only_exact_config_instrument_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_AccountLease", _FakeLease)
    client_type, receipt_type = _fake_i8_sdk_types()

    class _Credentials:
        values = {"broker_id": BROKER_ID, "user_id": USER_ID, "password": PASSWORD}

        def require_credential(self, name: str) -> str:
            return self.values[name]

    observation = adapter.probe_i8_oneshot_md_readonly(
        admission=_i8_admission(),
        credential_source=_Credentials(),
        client_type=client_type,
        stop_receipt_type=receipt_type,
        expected_diagnostic_instrument=INSTRUMENT,
        timeout_seconds=0.5,
    )

    assert type(observation) is adapter.CtpI8OneShotMdObservation
    assert observation.instrument_id == INSTRUMENT
    assert observation.identity_unverified is True
    assert observation.market_login_ready is False
    assert observation.subscription_acknowledged is True
    assert observation.matching_tick_observed is True
    assert observation.same_trading_day_observed is True
    assert observation.probe_session_closed is True
    assert observation.order_submission_authorized is False
    assert observation.trading_writes == observation.settlement_writes == 0


def test_i8_fake_adapter_rejects_instrument_override_before_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter, "_AccountLease", _FakeLease)
    client_type, receipt_type = _fake_i8_sdk_types()

    class _Credentials:
        def require_credential(self, _name: str) -> str:
            raise AssertionError("credentials must not be read for an instrument mismatch")

    with pytest.raises(CtpSdkMarketReadOnlyError):
        adapter.probe_i8_oneshot_md_readonly(
            admission=_i8_admission(),
            credential_source=_Credentials(),
            client_type=client_type,
            stop_receipt_type=receipt_type,
            expected_diagnostic_instrument="OTHER",
            timeout_seconds=0.5,
        )
