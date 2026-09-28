"""Composition and value-free projection tests for the unregistered I7 probe."""

from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import backtrader_runtime.ctp_artifact_provenance as artifact_provenance
import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_simnow_operator as simnow_operator
import backtrader_runtime.inventory as runtime_inventory
from backtrader_runtime import ctp_i7_oneshot_md_diagnostic as diagnostic
from backtrader_runtime.ctp_i4_oneshot_md_readonly import CtpI4OneShotMdObservation
from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError
from backtrader_runtime.inventory import (
    ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
    iteration41_runtime_registry,
)
from backtrader_runtime.cli import build_parser
from backtrader_runtime.registry import RuntimeRegistry


TD_FRONT = "tcp://127.0.0.1:10130"
MD_FRONT = "tcp://127.0.0.1:10131"
TD_FRONT_2 = "tcp://127.0.0.1:10132"
MD_FRONT_2 = "tcp://127.0.0.1:10133"
_ACCOUNT_FINGERPRINT = hashlib.sha256(b"9999:i7-diagnostic-user").hexdigest()
_PRIVATE_SENTINEL = "must-never-appear-in-output"
_VERIFY_NAME = "verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts"
_NATIVE_SHAPES = frozenset(
    {"not_observed", "unreadable", "empty", "nonempty_terminated", "unterminated"}
)


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
    admission = SimpleNamespace(
        td_front=selected_config["td_front"],
        md_front=selected_config["md_front"],
        account_fingerprint_sha256=_ACCOUNT_FINGERPRINT,
        instrument_id=_PRIVATE_SENTINEL,
        exchange_id=_PRIVATE_SENTINEL,
    )
    scope = object()
    selected_pair = SimpleNamespace(**selected_config)
    selection = SimpleNamespace(pair=selected_pair, config_index=selected_index)

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
            assert selected_front_pair is selection.pair
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
        lambda _pairs: events.append("front_selection") or selection,
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


def _install_verifier(monkeypatch: pytest.MonkeyPatch, callback: Any) -> None:
    monkeypatch.setattr(artifact_provenance, _VERIFY_NAME, callback)


def test_i7_artifact_pin_matches_the_reviewed_diagnostic_wheel() -> None:
    i6_pins = artifact_provenance.CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    i7_pins = artifact_provenance.CTP_I7_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS
    base_pin = i7_pins["bt_api_base"]
    i7_pin = i7_pins["bt_api_ctp"]
    assert i7_pins["bt_api_base"] is i6_pins["bt_api_base"]
    assert base_pin.wheel_sha256 == (
        "1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d"
    )
    assert base_pin.record_sha256 == (
        "aa91bfa982d473eb2b8ce59192196f87a84e7c9c19aafd8e961c73e5ea87ce90"
    )
    assert i7_pin.distribution == i7_pin.module == "bt_api_ctp"
    assert i7_pin.version == "2.0.3+iteration41.i7"
    assert i7_pin.wheel_filename == ("bt_api_ctp-2.0.3+iteration41.i7-cp311-cp311-win_amd64.whl")
    assert i7_pin.wheel_sha256 == (
        "22bc34140233785abcad61e7c3bc4dbb85c9d97b171692d5e6b44cf89eda94b4"
    )
    assert i7_pin.record_sha256 == (
        "03b4d23a6a647c4b29c392304e56dcd3be8b776e9c3eef695af0adcfbbdc45b6"
    )


def test_i7_artifact_gate_rejects_before_selection_credentials_or_sdk_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events)

    def _bad_pin(**_kwargs: Any) -> None:
        events.append("artifact_verification")
        raise artifact_provenance.CtpArtifactProvenanceError("artifact_pin_mismatch")

    _install_verifier(monkeypatch, _bad_pin)

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "iteration41.ctp-i7-md-oneshot-diagnostic.v1"
    assert payload["reason"] == "sdk_artifact_rejected"
    assert payload["stage"] == "sdk_artifact"
    assert events == ["sealed_private_config", "artifact_verification"]


def test_i7_reaches_artifact_gate_with_default_profile_binding_before_later_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    default_registry = iteration41_runtime_registry()
    default_registration = runtime_inventory.ITERATION41_013_3_CTP_PRIVATE_READONLY_REGISTRATION
    registration = replace(default_registration, runtime_dir=tmp_path)
    registry = RuntimeRegistry(
        tuple(
            registration if item is default_registration else item
            for item in default_registry.registrations
        ),
        runtime_sets=default_registry.runtime_sets,
        ctp_simnow_readonly_bindings=default_registry.ctp_simnow_readonly_bindings,
        registry_id=default_registry.registry_id,
    )
    (tmp_path / "config.yaml").write_text(
        """config_schema_version: 4
strategy:
  id: {strategy_id}
runtime:
  mode: simulation
  preset: sandbox
parameters: {{}}
secrets_ref: config_yaml
ctp_simnow:
  front_pairs:
    - md_front: tcp://192.0.2.11:10111
      td_front: tcp://192.0.2.10:10101
    - md_front: tcp://192.0.2.21:10111
      td_front: tcp://192.0.2.20:10101
  instrument_id: SA610
  exchange_id: CZCE
  hedge_flag: '1'
  broker_id: '9999'
  user_id: synthetic-user
  password: synthetic-password
  app_id: synthetic-app
  auth_code: synthetic-auth
""".format(
            strategy_id=registration.strategy_id
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)
    monkeypatch.setattr(diagnostic, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.setattr(diagnostic, "ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR", tmp_path)
    original_validate = diagnostic.validate_runtime_config

    def validate_profile(*args: Any, **kwargs: Any) -> Any:
        effective = original_validate(*args, **kwargs)
        assert effective.profile is registration.profiles[0]
        return effective

    monkeypatch.setattr(diagnostic, "validate_runtime_config", validate_profile)
    monkeypatch.setattr(diagnostic, "trusted_installed_capability_import_context", nullcontext)
    events: list[Any] = []

    def reject_artifact(*, td_front: str, md_front: str) -> None:
        events.append(("artifact", td_front, md_front))
        raise artifact_provenance.CtpArtifactProvenanceError("artifact_pin_mismatch")

    _install_verifier(monkeypatch, reject_artifact)
    monkeypatch.setattr(
        simnow_operator,
        "_select_configured_front_pair",
        lambda _pairs: events.append("front_selection"),
    )
    monkeypatch.setattr(
        diagnostic,
        "resolve_runtime_credentials",
        lambda *_a, **_k: events.append("credential_resolution"),
    )
    original_import_module = importlib.import_module

    def track_sdk_import(name: str, package: str | None = None) -> Any:
        if name == "bt_api_ctp.ctp.client":
            events.append("sdk_import")
        return original_import_module(name, package)

    monkeypatch.setattr(diagnostic.importlib, "import_module", track_sdk_import)

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason"] == "sdk_artifact_rejected"
    assert payload["stage"] == "sdk_artifact"
    assert events == [("artifact", "tcp://192.0.2.10:10101", "tcp://192.0.2.11:10111")]


def test_injected_verifier_keeps_gates_and_emits_only_fixed_i7_fields(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
    assert payload["schema_version"] == "iteration41.ctp-i7-md-oneshot-diagnostic.v1"
    assert payload["status"] == "diagnostic_complete"
    assert set(payload) == {
        "client_stop_returned",
        "front_callback_observed",
        "login_broker_id_shape",
        "login_user_id_shape",
        "login_trading_day_shape",
        "login_callback_count",
        "login_callback_disposition",
        "login_failure_category",
        "login_request_id_relation",
        "login_response_error_status",
        "market_login_ready",
        "matching_tick_observed",
        "native_broker_id_shape",
        "native_join_pending",
        "native_shutdown_uncertain",
        "native_user_id_shape",
        "order_submission_authorized",
        "probe_primary_reason",
        "probe_session_closed",
        "reason",
        "schema_version",
        "selected_config_index",
        "settlement_writes",
        "stage",
        "status",
        "subscription_acknowledged",
        "trading_writes",
    }
    assert payload["native_broker_id_shape"] is None
    assert payload["native_user_id_shape"] is None
    assert payload["order_submission_authorized"] is False
    assert payload["trading_writes"] == payload["settlement_writes"] == 0
    assert verified_pairs == [(TD_FRONT, MD_FRONT), (TD_FRONT_2, MD_FRONT_2)]
    assert _event_index(events, "artifact_verification") < _event_index(events, "front_selection")
    assert _event_index(events, "front_selection") < _event_index(events, "credential_resolution")
    assert _event_index(events, "credential_seal") < _event_index(events, "sdk_import")
    assert _event_index(events, "sdk_import") < _event_index(events, "one_shot_probe")
    assert _PRIVATE_SENTINEL not in json.dumps(payload)
    assert TD_FRONT not in json.dumps(payload)
    assert MD_FRONT_2 not in json.dumps(payload)


@pytest.mark.parametrize(
    ("broker_shape", "user_shape", "expected_broker", "expected_user"),
    [
        ("nonempty_terminated", "unterminated", "nonempty_terminated", "unterminated"),
        (_PRIVATE_SENTINEL, "empty", None, "empty"),
        ("not_observed", _PRIVATE_SENTINEL, "not_observed", None),
    ],
)
def test_i7_native_field_shapes_are_exact_value_free_enums(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    broker_shape: str,
    user_shape: str,
    expected_broker: str | None,
    expected_user: str | None,
) -> None:
    events: list[Any] = []
    _install_composition_fakes(monkeypatch, events=events)
    _install_verifier(monkeypatch, lambda **_kwargs: None)

    def _probe(**_kwargs: Any) -> Any:
        error = CtpSdkMarketReadOnlyError(
            "market_login_identity_mismatch",
            login_callback_count=1,
            login_callback_disposition="identity_rejected",
            login_request_id_relation="zero",
            login_response_error_status="zero",
            login_failure_category="broker_id_mismatch",
            native_broker_id_shape="nonempty_terminated",
            native_user_id_shape="empty",
        )
        error.native_broker_id_shape = broker_shape
        error.native_user_id_shape = user_shape
        for private_name in (
            "broker_id",
            "user_id",
            "trading_day",
            "front",
            "password",
            "instrument_id",
        ):
            setattr(error, private_name, _PRIVATE_SENTINEL)
        raise error

    monkeypatch.setattr(diagnostic, "probe_i4_oneshot_md_readonly", _probe)

    assert diagnostic.run_diagnostic([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["native_broker_id_shape"] == expected_broker
    assert payload["native_user_id_shape"] == expected_user
    assert payload["login_failure_category"] == "broker_id_mismatch"
    assert _NATIVE_SHAPES == diagnostic._I7_NATIVE_FIELD_SHAPES
    assert _PRIVATE_SENTINEL not in json.dumps(payload)


def test_i7_diagnostic_does_not_add_a_runtime_or_cli_route() -> None:
    registry = iteration41_runtime_registry()
    assert all(
        "i7" not in registration.runtime_id.lower() for registration in registry.registrations
    )
    command_choices = build_parser()._subparsers._group_actions[0].choices
    assert not any("i7" in command.lower() for command in command_choices)
