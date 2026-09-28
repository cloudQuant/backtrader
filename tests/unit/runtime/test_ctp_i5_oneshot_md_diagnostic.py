"""Composition-boundary tests for the unregistered I5 MD-only diagnostic."""

from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import backtrader_runtime.ctp_artifact_provenance as artifact_provenance
import backtrader_runtime.ctp_simnow_operator as simnow_operator
from backtrader_runtime import ctp_i5_oneshot_md_diagnostic as diagnostic
from backtrader_runtime.ctp_i4_oneshot_md_readonly import CtpI4OneShotMdObservation
from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from backtrader_runtime.inventory import ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
from backtrader_runtime.cli import build_parser
from backtrader_runtime.inventory import iteration41_runtime_registry


TD_FRONT = "tcp://127.0.0.1:10130"
MD_FRONT = "tcp://127.0.0.1:10131"
TD_FRONT_2 = "tcp://127.0.0.1:10132"
MD_FRONT_2 = "tcp://127.0.0.1:10133"
_ACCOUNT_FINGERPRINT = hashlib.sha256(b"9999:i5-diagnostic-user").hexdigest()
_PRIVATE_SENTINEL = "must-never-appear-in-output"
_VERIFY_NAME = "verify_ctp_i5_oneshot_diagnostic_artifact_provenance_for_fronts"


class _Client:
    __module__ = "bt_api_ctp.ctp.client"


class _StopReceipt:
    __module__ = "bt_api_ctp.ctp.client"


def _observation(admission: Any) -> CtpI4OneShotMdObservation:
    return CtpI4OneShotMdObservation(
        md_front_sha256=hashlib.sha256(admission.md_front.encode()).hexdigest(),
        account_fingerprint_sha256=admission.account_fingerprint_sha256,
        instrument_id=admission.instrument_id,
        exchange_id=admission.exchange_id,
        connection_generation=2,
        login_request_id=0,
        market_login_ready=True,
        subscription_acknowledged=True,
        matching_tick_observed=True,
        client_stop_returned=True,
        native_join_pending=False,
    )


def _event_index(events: list[Any], name: str) -> int:
    return next(
        index
        for index, event in enumerate(events)
        if event == name or (isinstance(event, tuple) and event[0] == name)
    )


def _install_composition_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[Any],
    selected_index: int = 0,
    selection_index: Any = None,
    selected_pair_override: Any = None,
    admission_pair_override: tuple[str, str] | None = None,
) -> tuple[Any, Any]:
    registration = SimpleNamespace(runtime_id=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)
    effective = SimpleNamespace(
        config=SimpleNamespace(strategy_dir=Path("registered-runtime")),
        registration=registration,
    )
    registry = SimpleNamespace()
    registry.require_runtime_dir = lambda _directory: registration
    configured_pairs = (
        {"td_front": TD_FRONT, "md_front": MD_FRONT},
        {"td_front": TD_FRONT_2, "md_front": MD_FRONT_2},
    )
    selected_config = configured_pairs[selected_index]
    admission_td, admission_md = admission_pair_override or (
        selected_config["td_front"],
        selected_config["md_front"],
    )
    admission = SimpleNamespace(
        td_front=admission_td,
        md_front=admission_md,
        account_fingerprint_sha256=_ACCOUNT_FINGERPRINT,
        instrument_id=_PRIVATE_SENTINEL,
        exchange_id=_PRIVATE_SENTINEL,
    )
    scope = object()
    selected_pair = selected_pair_override or SimpleNamespace(
        td_front=selected_config["td_front"],
        md_front=selected_config["md_front"],
    )
    chosen_index = selected_index if selection_index is None else selection_index
    selection = SimpleNamespace(pair=selected_pair, config_index=chosen_index)

    class _Binding:
        def _sealed_private_config(self, _effective: Any, _registry: Any) -> Any:
            events.append("sealed_private_config")
            return object(), registration, configured_pairs

        def _route(
            self,
            _effective: Any,
            _registry: Any,
            *,
            selected_front_pair: Any,
        ) -> Any:
            events.append(("route", selected_front_pair))
            assert selected_front_pair is selected_pair
            return admission, scope

    binding = _Binding()
    registry.require_ctp_simnow_readonly_binding = lambda _runtime_id: binding

    monkeypatch.setattr(diagnostic, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.setattr(diagnostic, "validate_runtime_config", lambda *_args: effective)
    monkeypatch.setattr(diagnostic, "require_effective_runtime_config_seal", lambda *_args: None)
    monkeypatch.setattr(simnow_operator, "CtpSimNowConfigReadOnlyBinding", _Binding)
    monkeypatch.setattr(
        simnow_operator,
        "_select_configured_front_pair",
        lambda pairs: events.append(("front_selection", pairs)) or selection,
    )
    monkeypatch.setattr(
        diagnostic,
        "trusted_installed_capability_import_context",
        lambda _modules: nullcontext(),
    )
    monkeypatch.setattr(diagnostic, "_discard_provider_process_output", nullcontext)

    def _resolve(*_args: Any) -> object:
        events.append("credential_resolution")
        return object()

    monkeypatch.setattr(diagnostic, "resolve_runtime_credentials", _resolve)
    monkeypatch.setattr(
        diagnostic,
        "require_resolved_runtime_credentials_seal",
        lambda *_args: events.append("credential_seal"),
    )
    original_import_module = importlib.import_module

    def _import_module(name: str, package: str | None = None) -> Any:
        if name == "bt_api_ctp.ctp.client":
            events.append("sdk_import")
            return SimpleNamespace(
                OneShotMdDiagnosticClient=_Client,
                CtpNativeStopReceipt=_StopReceipt,
            )
        return original_import_module(name, package)

    monkeypatch.setattr(diagnostic.importlib, "import_module", _import_module)
    return effective, admission


def _install_verifier(
    monkeypatch: pytest.MonkeyPatch,
    callback: Any,
) -> None:
    monkeypatch.setattr(artifact_provenance, _VERIFY_NAME, callback, raising=False)


def test_i5_pin_rejects_before_network_credentials_or_sdk_import(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events)

    def _bad_pin(**_kwargs: Any) -> None:
        events.append("artifact_verification")
        raise artifact_provenance.CtpArtifactProvenanceError("artifact_pin_mismatch")

    _install_verifier(monkeypatch, _bad_pin)

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "rejected"
    assert payload["reason"] == "sdk_artifact_rejected"
    assert payload["stage"] == "sdk_artifact"
    assert payload["selected_config_index"] is None
    assert events == ["sealed_private_config", "artifact_verification"]


def test_success_binds_index_to_exact_pair_and_emits_i5_only_projection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[Any] = []
    effective, admission = _install_composition_fakes(
        monkeypatch,
        events=events,
        selected_index=1,
    )
    verified_pairs: list[tuple[str, str]] = []

    def _verify(*, td_front: str, md_front: str) -> None:
        events.append("artifact_verification")
        verified_pairs.append((td_front, md_front))

    _install_verifier(monkeypatch, _verify)

    def _probe(**kwargs: Any) -> CtpI4OneShotMdObservation:
        events.append("one_shot_probe")
        assert kwargs["admission"] is admission
        assert kwargs["client_type"] is _Client
        assert kwargs["stop_receipt_type"] is _StopReceipt
        assert kwargs["credential_source"]._effective is effective
        return _observation(admission)

    monkeypatch.setattr(diagnostic, "probe_i4_oneshot_md_readonly", _probe)

    assert diagnostic.run_diagnostic([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "client_stop_returned": True,
        "front_callback_observed": None,
        "login_broker_id_shape": None,
        "login_callback_count": None,
        "login_callback_disposition": None,
        "login_failure_category": None,
        "login_request_id_relation": None,
        "login_response_error_status": None,
        "market_login_ready": True,
        "matching_tick_observed": True,
        "native_join_pending": False,
        "native_shutdown_uncertain": False,
        "order_submission_authorized": False,
        "probe_primary_reason": None,
        "probe_session_closed": True,
        "reason": "matching_tick_observed",
        "selected_config_index": 1,
        "settlement_writes": 0,
        "stage": "market_data",
        "status": "diagnostic_complete",
        "subscription_acknowledged": True,
        "trading_writes": 0,
    }
    assert verified_pairs == [(TD_FRONT, MD_FRONT), (TD_FRONT_2, MD_FRONT_2)]
    assert _event_index(events, "artifact_verification") < _event_index(events, "front_selection")
    assert _event_index(events, "front_selection") < _event_index(events, "credential_resolution")
    assert _event_index(events, "credential_seal") < _event_index(events, "sdk_import")
    assert _event_index(events, "sdk_import") < _event_index(events, "one_shot_probe")
    assert _PRIVATE_SENTINEL not in json.dumps(payload)
    assert TD_FRONT not in json.dumps(payload)
    assert MD_FRONT_2 not in json.dumps(payload)


@pytest.mark.parametrize("index", [True, -1, 2, 8])
def test_invalid_config_index_rejects_before_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    index: Any,
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events, selection_index=index)
    _install_verifier(monkeypatch, lambda **_kwargs: events.append("artifact_verification"))

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "front_selection"
    assert payload["selected_config_index"] is None
    assert "credential_resolution" not in events
    assert events.count("artifact_verification") == 1


def test_selected_pair_must_match_index_and_admission(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[Any] = []
    wrong_selected_pair = SimpleNamespace(td_front=TD_FRONT_2, md_front=MD_FRONT_2)
    _install_composition_fakes(
        monkeypatch,
        events=events,
        selected_index=0,
        selected_pair_override=wrong_selected_pair,
    )
    _install_verifier(monkeypatch, lambda **_kwargs: events.append("artifact_verification"))

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "front_selection"
    assert payload["selected_config_index"] is None
    assert "route" not in [event[0] for event in events if isinstance(event, tuple)]
    assert "credential_resolution" not in events


def test_admission_pair_must_match_selected_sealed_pair(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[Any] = []
    _install_composition_fakes(
        monkeypatch,
        events=events,
        admission_pair_override=(TD_FRONT_2, MD_FRONT_2),
    )
    _install_verifier(monkeypatch, lambda **_kwargs: events.append("artifact_verification"))

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == "front_selection"
    assert payload["selected_config_index"] is None
    assert events.count("artifact_verification") == 1
    assert "credential_resolution" not in events


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ("exact_match", "exact_match"),
        ("ascii_mismatch", "ascii_mismatch"),
        (_PRIVATE_SENTINEL, None),
    ],
)
def test_i5_failure_projection_allowlists_broker_id_shape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    shape: str,
    expected: str | None,
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events)
    _install_verifier(monkeypatch, lambda **_kwargs: None)

    def _probe(**_kwargs: Any) -> Any:
        raise CtpSdkMarketReadOnlyError(
            "market_login_identity_mismatch",
            login_callback_count=1,
            login_callback_disposition="identity_rejected",
            login_request_id_relation="zero",
            login_response_error_status="zero",
            login_failure_category="broker_id_mismatch",
            login_broker_id_shape=shape,
        )

    monkeypatch.setattr(diagnostic, "probe_i4_oneshot_md_readonly", _probe)

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["login_broker_id_shape"] == expected
    assert payload["login_failure_category"] == "broker_id_mismatch"
    assert payload["selected_config_index"] == 0
    assert _PRIVATE_SENTINEL not in json.dumps(payload)


def test_i5_callback_count_uses_the_supervisor_bound_at_projection_and_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    at_limit = CtpSdkMarketReadOnlyError("market_probe_failed", login_callback_count=1024)
    over_limit = CtpSdkMarketReadOnlyError("market_probe_failed", login_callback_count=1025)
    bool_count = CtpSdkMarketReadOnlyError("market_probe_failed", login_callback_count=True)

    assert diagnostic._login_failure_projection(at_limit)["login_callback_count"] == 1024
    assert diagnostic._login_failure_projection(over_limit)["login_callback_count"] is None
    assert diagnostic._login_failure_projection(bool_count)["login_callback_count"] is None

    diagnostic._emit_i5(
        status="rejected",
        reason="market_probe_rejected",
        stage="market_data",
        login_callback_count=1024,
    )
    assert json.loads(capsys.readouterr().out)["login_callback_count"] == 1024

    diagnostic._emit_i5(
        status="rejected",
        reason="market_probe_rejected",
        stage="market_data",
        login_callback_count=1025,
    )
    assert json.loads(capsys.readouterr().out)["login_callback_count"] is None

    diagnostic._emit_i5(
        status="rejected",
        reason="market_probe_rejected",
        stage="market_data",
        login_callback_count=True,
    )
    assert json.loads(capsys.readouterr().out)["login_callback_count"] is None


def test_uncertain_native_shutdown_stays_incomplete_and_keeps_valid_index(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events)
    _install_verifier(monkeypatch, lambda **_kwargs: None)

    def _pending(**_kwargs: Any) -> Any:
        raise CtpSdkMarketReadOnlyError(
            "market_client_stop_failed",
            close_state="native_join_pending",
            primary_reason="native_join_pending",
            client_stop_returned=True,
            login_broker_id_shape="not_observed",
        )

    monkeypatch.setattr(diagnostic, "probe_i4_oneshot_md_readonly", _pending)

    assert diagnostic.run_diagnostic([]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "incomplete"
    assert payload["selected_config_index"] == 0
    assert payload["native_join_pending"] is True
    assert payload["native_shutdown_uncertain"] is True
    assert payload["login_broker_id_shape"] == "not_observed"
    assert payload["trading_writes"] == payload["settlement_writes"] == 0


def test_i5_diagnostic_does_not_add_a_runtime_or_cli_route() -> None:
    registry = iteration41_runtime_registry()
    assert all(
        "i5" not in registration.runtime_id.lower() for registration in registry.registrations
    )

    parser = build_parser()
    command_choices = parser._subparsers._group_actions[0].choices
    assert not any("i5" in command.lower() for command in command_choices)
