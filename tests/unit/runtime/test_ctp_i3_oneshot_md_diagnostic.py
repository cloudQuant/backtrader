"""Composition-boundary tests for the unregistered I3 MD-only diagnostic."""

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
from backtrader_runtime import ctp_i3_oneshot_md_diagnostic as diagnostic
from backtrader_runtime.ctp_i3_oneshot_md_readonly import CtpI3OneShotMdObservation
from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from backtrader_runtime.errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from backtrader_runtime.inventory import ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID


TD_FRONT = "tcp://127.0.0.1:10130"
MD_FRONT = "tcp://127.0.0.1:10131"
TD_FRONT_2 = "tcp://127.0.0.1:10132"
MD_FRONT_2 = "tcp://127.0.0.1:10133"
_ACCOUNT_FINGERPRINT = hashlib.sha256(b"9999:i3-diagnostic-user").hexdigest()
_PRIVATE_SENTINEL = "must-never-appear-in-output"


class _Client:
    __module__ = "bt_api_ctp.ctp.client"


class _StopReceipt:
    __module__ = "bt_api_ctp.ctp.client"


def _observation(admission: Any) -> CtpI3OneShotMdObservation:
    return CtpI3OneShotMdObservation(
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
) -> tuple[Any, Any]:
    registration = SimpleNamespace(runtime_id=ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID)
    effective = SimpleNamespace(
        config=SimpleNamespace(strategy_dir=Path("registered-runtime")),
        registration=registration,
    )
    registry = SimpleNamespace()
    registry.require_runtime_dir = lambda _directory: registration
    binding = None
    configured_pairs = (
        {"td_front": TD_FRONT, "md_front": MD_FRONT},
        {"td_front": TD_FRONT_2, "md_front": MD_FRONT_2},
    )
    selected_config = configured_pairs[selected_index]
    admission = SimpleNamespace(
        td_front=selected_config["td_front"],
        md_front=selected_config["md_front"],
        account_fingerprint_sha256=_ACCOUNT_FINGERPRINT,
        instrument_id=_PRIVATE_SENTINEL,
        exchange_id=_PRIVATE_SENTINEL,
    )
    scope = object()
    selected_pair = SimpleNamespace(**selected_config)

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
    monkeypatch.setattr(
        simnow_operator,
        "CtpSimNowConfigReadOnlyBinding",
        _Binding,
    )
    monkeypatch.setattr(
        simnow_operator,
        "_select_configured_front_pair",
        lambda pairs: events.append(("front_selection", pairs))
        or SimpleNamespace(pair=selected_pair),
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


def test_bad_runtime_schema_rejects_before_front_selection_or_sensitive_work(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events)

    def _bad_schema(*_args: Any) -> Any:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "invalid sealed config",
            field_path="ctp.front_pairs",
            reason="private_config_schema_invalid",
        )

    monkeypatch.setattr(diagnostic, "validate_runtime_config", _bad_schema)
    monkeypatch.setattr(
        artifact_provenance,
        "verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts",
        lambda **_kwargs: events.append("artifact_verification"),
    )

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "rejected"
    assert payload["stage"] == "configuration"
    assert events == []


def test_bad_i3_pin_rejects_before_network_credentials_or_sdk_import(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events)

    def _bad_pin(**_kwargs: Any) -> None:
        events.append("artifact_verification")
        raise artifact_provenance.CtpArtifactProvenanceError("artifact_pin_mismatch")

    monkeypatch.setattr(
        artifact_provenance,
        "verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts",
        _bad_pin,
    )

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "rejected"
    assert payload["reason"] == "sdk_artifact_rejected"
    assert events == ["sealed_private_config", "artifact_verification"]


def test_success_imports_i3_types_only_after_pin_and_emits_redacted_projection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[Any] = []
    effective, admission = _install_composition_fakes(monkeypatch, events=events)
    verified_pairs: list[tuple[str, str]] = []

    def _verify(*, td_front: str, md_front: str) -> None:
        events.append("artifact_verification")
        verified_pairs.append((td_front, md_front))

    monkeypatch.setattr(
        artifact_provenance,
        "verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts",
        _verify,
    )

    def _probe(**kwargs: Any) -> CtpI3OneShotMdObservation:
        events.append("one_shot_probe")
        assert kwargs["admission"] is admission
        assert kwargs["client_type"] is _Client
        assert kwargs["stop_receipt_type"] is _StopReceipt
        assert kwargs["credential_source"]._effective is effective
        return _observation(admission)

    monkeypatch.setattr(diagnostic, "probe_i3_oneshot_md_readonly", _probe)

    assert diagnostic.run_diagnostic([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "client_stop_returned": True,
        "front_callback_observed": None,
        "login_callback_count": None,
        "login_callback_disposition": None,
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
        "settlement_writes": 0,
        "stage": "market_data",
        "status": "diagnostic_complete",
        "subscription_acknowledged": True,
        "trading_writes": 0,
    }
    assert verified_pairs == [(TD_FRONT, MD_FRONT), (TD_FRONT, MD_FRONT)]
    artifact_indexes = [
        index for index, event in enumerate(events) if event == "artifact_verification"
    ]
    assert len(artifact_indexes) == 2
    assert artifact_indexes[1] < _event_index(events, "credential_resolution")
    assert _event_index(events, "artifact_verification") < _event_index(events, "front_selection")
    assert _event_index(events, "front_selection") < _event_index(events, "credential_resolution")
    assert _event_index(events, "credential_seal") < _event_index(events, "sdk_import")
    assert _event_index(events, "sdk_import") < _event_index(events, "one_shot_probe")
    assert _PRIVATE_SENTINEL not in json.dumps(payload)
    assert TD_FRONT not in json.dumps(payload)
    assert MD_FRONT not in json.dumps(payload)


def test_join_pending_is_incomplete_and_never_projected_as_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events)
    monkeypatch.setattr(
        artifact_provenance,
        "verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts",
        lambda **_kwargs: None,
    )

    def _pending(**_kwargs: Any) -> Any:
        raise CtpSdkMarketReadOnlyError(
            "market_client_stop_failed",
            close_state="native_join_pending",
            primary_reason="native_join_pending",
            login_broker_id_shape="exact_match",
            client_stop_returned=True,
        )

    monkeypatch.setattr(diagnostic, "probe_i3_oneshot_md_readonly", _pending)

    assert diagnostic.run_diagnostic([]) == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "incomplete"
    assert payload["native_join_pending"] is True
    assert payload["native_shutdown_uncertain"] is True
    assert payload["client_stop_returned"] is True
    assert payload["probe_session_closed"] is False
    assert "login_broker_id_shape" not in payload
    assert payload["order_submission_authorized"] is False
    assert payload["trading_writes"] == payload["settlement_writes"] == 0


def test_selector_may_choose_second_configured_pair_and_exact_pair_is_reverified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[Any] = []
    _effective, admission = _install_composition_fakes(
        monkeypatch,
        events=events,
        selected_index=1,
    )
    verified_pairs: list[tuple[str, str]] = []

    def _verify(*, td_front: str, md_front: str) -> None:
        events.append("artifact_verification")
        verified_pairs.append((td_front, md_front))

    monkeypatch.setattr(
        artifact_provenance,
        "verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts",
        _verify,
    )

    def _probe(**kwargs: Any) -> CtpI3OneShotMdObservation:
        events.append("one_shot_probe")
        assert kwargs["admission"] is admission
        assert (kwargs["admission"].td_front, kwargs["admission"].md_front) == (
            TD_FRONT_2,
            MD_FRONT_2,
        )
        return _observation(admission)

    monkeypatch.setattr(diagnostic, "probe_i3_oneshot_md_readonly", _probe)

    assert diagnostic.run_diagnostic([]) == 0
    capsys.readouterr()
    assert verified_pairs == [(TD_FRONT, MD_FRONT), (TD_FRONT_2, MD_FRONT_2)]
    selection = next(event for event in events if isinstance(event, tuple) and event[0] == "front_selection")
    assert selection[1][1] == {"td_front": TD_FRONT_2, "md_front": MD_FRONT_2}
    route = next(event for event in events if isinstance(event, tuple) and event[0] == "route")
    assert (route[1].td_front, route[1].md_front) == (TD_FRONT_2, MD_FRONT_2)
    artifact_indexes = [
        index for index, event in enumerate(events) if event == "artifact_verification"
    ]
    assert len(artifact_indexes) == 2
    assert artifact_indexes[1] < _event_index(events, "credential_resolution")
    assert _event_index(events, "artifact_verification") < _event_index(events, "front_selection")
    assert _event_index(events, "front_selection") < _event_index(events, "credential_resolution")
