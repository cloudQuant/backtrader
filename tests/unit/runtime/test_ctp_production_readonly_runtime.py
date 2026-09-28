"""Fake-session contracts for the unregistered CTP production read-only runtime."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_production_readonly_runtime as readonly_runtime
from backtrader_runtime import RegisteredRuntime, RuntimeRegistry
from backtrader_runtime.ctp_preflight import REQUIRED_CTP_READ_ONLY_QUERIES
from backtrader_runtime.ctp_front_pair_probe import CtpFrontPairProbeError
from backtrader_runtime.ctp_production_readonly_admission import (
    CtpProductionReadOnlyRegistration,
    production_account_binding_sha256,
)
from backtrader_runtime.ctp_production_readonly_runtime import (
    CtpProductionReadOnlyQuerySnapshot,
    CtpProductionReadOnlyRuntimeError,
    CtpProductionReadOnlySessionIdentity,
    _LOCAL_TD_FRONT_EVIDENCE,
    run_ctp_production_readonly_preflight,
)


_PRIVATE_VALUES = {
    "md_front": "tcp://192.0.2.11:41211",
    "td_front": "tcp://192.0.2.10:41201",
    "instrument_id": "IF2612",
    "exchange_id": "CFFEX",
    "hedge_flag": "1",
    "broker_id": "synthetic-production-broker",
    "user_id": "synthetic-production-account",
    "password": "synthetic-production-password-never-use",
    "app_id": "synthetic-production-app",
    "auth_code": "synthetic-production-auth",
}


def _document(private_values: Optional[dict] = None) -> dict:
    return {
        "config_schema_version": 4,
        "strategy": {"id": "example.013_3.sa_midfreq_simnow"},
        "runtime": {"mode": "live", "preset": "managed_live_direct"},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp": dict(_PRIVATE_VALUES if private_values is None else private_values),
    }


def _bound_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    private_values: Optional[dict] = None,
    *,
    pin_fronts: bool = True,
):
    def deterministic_selector(front_pairs, **_kwargs):
        return SimpleNamespace(pair=SimpleNamespace(**front_pairs[0]))

    monkeypatch.setattr(readonly_runtime, "select_ctp_front_pair", deterministic_selector)
    runtime_dir = tmp_path / "runtime-ctp-private"
    runtime_dir.mkdir()
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.013_3.sa_midfreq_simnow",
        runtime_id="example.013_3.sa_midfreq_simnow.injected_production_readonly",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    config = runtime_config._validate_schema(
        _document(private_values), runtime_dir, runtime_dir / "config.yaml"
    )
    runtime_config._seal_loaded_runtime_config(config, registry)
    pin = CtpProductionReadOnlyRegistration(
        runtime_registration=registration,
        environment="production",
        account_binding_sha256=production_account_binding_sha256(
            _PRIVATE_VALUES["broker_id"], _PRIVATE_VALUES["user_id"]
        ),
        md_front=_PRIVATE_VALUES["md_front"] if pin_fronts else None,
        td_front=_PRIVATE_VALUES["td_front"] if pin_fronts else None,
        instrument_id=_PRIVATE_VALUES["instrument_id"],
        exchange_id=_PRIVATE_VALUES["exchange_id"],
        hedge_flag=_PRIVATE_VALUES["hedge_flag"],
    )
    return config, registry, pin


class _FakeSession:
    def __init__(
        self,
        pin,
        *,
        writes=0,
        identity=None,
        snapshot=None,
        md_front_sha256=None,
        td_front_sha256=None,
    ):
        self.pin = pin
        self.writes = writes
        self.identity = identity or CtpProductionReadOnlySessionIdentity(
            account_binding_sha256=pin.account_binding_sha256,
            trading_day="20260924",
            connection_generation=7,
            md_front_sha256=md_front_sha256
            or hashlib.sha256(pin.md_front.encode("utf-8")).hexdigest(),
            td_front_sha256=td_front_sha256
            or hashlib.sha256(pin.td_front.encode("utf-8")).hexdigest(),
            td_front_binding_evidence=_LOCAL_TD_FRONT_EVIDENCE,
        )
        digests = tuple(
            (name, hashlib.sha256(name.encode("ascii")).hexdigest())
            for name in REQUIRED_CTP_READ_ONLY_QUERIES
        )
        self.snapshot = snapshot or CtpProductionReadOnlyQuerySnapshot.from_query_digests(
            self.identity,
            digests,
            instrument_id=pin.instrument_id,
            exchange_id=pin.exchange_id,
            hedge_flag=pin.hedge_flag,
        )
        self.calls = []

    def read_identity(self):
        self.calls.append("identity")
        return self.identity

    def read_query_snapshot(self):
        self.calls.append("queries")
        return self.snapshot

    def read_write_counters(self):
        self.calls.append("counters")
        return {
            "settlement_confirm": 0,
            "order_insert": self.writes,
            "order_action": 0,
        }

    def close_read_only(self):
        self.calls.append("close")


class _FakeFactory:
    def __init__(self, pin, session=None):
        self.pin = pin
        self.session = session or (_FakeSession(pin) if pin.md_front is not None else None)
        self.requests = []

    def open_read_only(self, request):
        self.requests.append(request)
        if self.pin.md_front is None:
            self.session = _FakeSession(
                self.pin,
                md_front_sha256=request.md_front_sha256,
                td_front_sha256=request.td_front_sha256,
            )
        assert self.session is not None
        return self.session


def test_production_config_binding_runs_fake_seven_query_protocol_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    selected_inputs = []

    def select_single_pair(front_pairs, **kwargs):
        selected_inputs.append((front_pairs, kwargs))
        return SimpleNamespace(pair=SimpleNamespace(**front_pairs[0]))

    monkeypatch.setattr(readonly_runtime, "select_ctp_front_pair", select_single_pair)
    factory = _FakeFactory(pin)

    result = run_ctp_production_readonly_preflight(
        config=config,
        registry=registry,
        admission_registration=pin,
        session_factory=factory,
    )

    assert len(factory.requests) == 1
    assert len(selected_inputs) == 1
    assert selected_inputs[0][0] == tuple(
        dict(pair) for pair in config.ctp.front_pairs
    )
    assert selected_inputs[0][1] == {
        "timeout_seconds": 2.0,
        "max_pairs": 8,
        "repeated_samples": 3,
    }
    request = factory.requests[0]
    assert request.environment == "production"
    assert request.account_binding_sha256 == pin.account_binding_sha256
    assert request.md_front_sha256 == hashlib.sha256(pin.md_front.encode("utf-8")).hexdigest()
    assert request.td_front_sha256 == hashlib.sha256(pin.td_front.encode("utf-8")).hexdigest()
    assert request.instrument_id == pin.instrument_id
    assert factory.session.calls == [
        "counters",
        "identity",
        "queries",
        "counters",
        "identity",
        "close",
        "counters",
    ]
    assert result.evidence_class == "INJECTED_SESSION_PROTOCOL"
    assert result.provider_session_verified is False
    assert result.provider_read_authorized is False
    assert result.execution_authorized is False
    assert result.external_writes_authorized is False
    assert result.external_write_requests == 0
    assert result.as_public_dict()["td_front_binding_evidence"] == _LOCAL_TD_FRONT_EVIDENCE
    assert result.as_public_dict()["md_front_evidence"] == "sealed_config_pin_only"
    assert result.as_public_dict()["remote_front_identity_verified"] is False
    with pytest.raises(TypeError, match="non-authorizing"):
        bool(result)

    public_text = json.dumps(result.as_public_dict(), sort_keys=True)
    assert "192.0.2.11" not in public_text
    assert _PRIVATE_VALUES["user_id"] not in public_text
    assert _PRIVATE_VALUES["password"] not in public_text


def test_configured_multiple_production_fronts_use_config_only_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pairs = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    private_values = {
        key: value for key, value in _PRIVATE_VALUES.items() if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = pairs
    runtime_dir = tmp_path / "runtime-ctp-private"
    runtime_dir.mkdir()
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id="example.013_3.sa_midfreq_simnow",
        runtime_id="example.013_3.sa_midfreq_simnow.injected_production_readonly",
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    config = runtime_config._validate_schema(
        _document(private_values), runtime_dir, runtime_dir / "config.yaml"
    )
    runtime_config._seal_loaded_runtime_config(config, registry)
    pin = CtpProductionReadOnlyRegistration(
        runtime_registration=registration,
        environment="production",
        account_binding_sha256=production_account_binding_sha256(
            _PRIVATE_VALUES["broker_id"], _PRIVATE_VALUES["user_id"]
        ),
        md_front=None,
        td_front=None,
        instrument_id=_PRIVATE_VALUES["instrument_id"],
        exchange_id=_PRIVATE_VALUES["exchange_id"],
        hedge_flag=_PRIVATE_VALUES["hedge_flag"],
    )
    calls = []

    def select_from_config(front_pairs, **kwargs):
        calls.append((front_pairs, kwargs))
        return SimpleNamespace(pair=SimpleNamespace(**pairs[1]))

    monkeypatch.setattr(
        "backtrader_runtime.ctp_production_readonly_runtime.select_ctp_front_pair",
        select_from_config,
    )
    factory = _FakeFactory(pin)

    result = run_ctp_production_readonly_preflight(
        config=config,
        registry=registry,
        admission_registration=pin,
        session_factory=factory,
    )

    assert len(calls) == 1
    assert calls[0][0] == tuple(pairs)
    assert calls[0][1] == {
        "timeout_seconds": 2.0,
        "max_pairs": 8,
        "repeated_samples": 3,
    }
    request = factory.requests[0]
    assert request.md_front_sha256 == hashlib.sha256(pairs[1]["md_front"].encode()).hexdigest()
    assert request.td_front_sha256 == hashlib.sha256(pairs[1]["td_front"].encode()).hexdigest()
    assert request.front_pair_set_sha256 == result.binding.front_pair_set_sha256
    assert result.binding.md_front == pairs[1]["md_front"]
    assert result.binding.td_front == pairs[1]["td_front"]
    assert result.binding.provider_read_authorized is False
    assert result.binding.execution_authorized is False


def test_front_probe_failure_precedes_session_factory_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pairs = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    private_values = {
        key: value for key, value in _PRIVATE_VALUES.items() if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = pairs
    config, registry, pin = _bound_inputs(
        tmp_path, monkeypatch, private_values, pin_fronts=False
    )

    def fail_probe(*_args, **_kwargs):
        raise CtpFrontPairProbeError("no_configured_front_pair_reachable")

    monkeypatch.setattr(
        "backtrader_runtime.ctp_production_readonly_runtime.select_ctp_front_pair", fail_probe
    )
    factory = _FakeFactory(pin)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "front_probe_rejected"
    assert factory.requests == []


def test_single_front_probe_failure_precedes_session_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)

    def fail_probe(*_args, **_kwargs):
        raise CtpFrontPairProbeError("no_configured_front_pair_reachable")

    monkeypatch.setattr(readonly_runtime, "select_ctp_front_pair", fail_probe)
    factory = _FakeFactory(pin)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "front_probe_rejected"
    assert factory.requests == []


def test_multi_pair_legacy_front_pin_rejects_before_probe_or_session_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pairs = [
        {"md_front": "tcp://md-a.example.net:42001", "td_front": "tcp://td-a.example.net:43001"},
        {"md_front": "tcp://md-b.example.net:42002", "td_front": "tcp://td-b.example.net:43002"},
    ]
    private_values = {
        key: value for key, value in _PRIVATE_VALUES.items() if key not in {"md_front", "td_front"}
    }
    private_values["front_pairs"] = pairs
    config, registry, pin = _bound_inputs(
        tmp_path, monkeypatch, private_values, pin_fronts=True
    )
    probe_calls = []

    def record_probe(*args, **kwargs):
        probe_calls.append((args, kwargs))
        return SimpleNamespace(pair=SimpleNamespace(**pairs[0]))

    monkeypatch.setattr(readonly_runtime, "select_ctp_front_pair", record_probe)
    factory = _FakeFactory(pin)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "legacy_front_pin_incompatible_with_multi_pair_config"
    assert probe_calls == []
    assert factory.requests == []


def test_seal_rejection_happens_before_the_injected_factory_is_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    object.__setattr__(config.ctp, "md_front", "tcp://192.0.2.99:41211")
    factory = _FakeFactory(pin)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "config_binding_rejected"
    assert factory.requests == []


def test_nonzero_write_counter_closes_fake_session_and_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    session = _FakeSession(pin, writes=1)
    factory = _FakeFactory(pin, session)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "write_counter_rejected"
    assert session.calls[-1] == "close"


def test_snapshot_constructor_rejects_missing_required_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    identity = CtpProductionReadOnlySessionIdentity(
        account_binding_sha256=pin.account_binding_sha256,
        trading_day="20260924",
        connection_generation=7,
        md_front_sha256=hashlib.sha256(pin.md_front.encode("utf-8")).hexdigest(),
        td_front_sha256=hashlib.sha256(pin.td_front.encode("utf-8")).hexdigest(),
        td_front_binding_evidence=_LOCAL_TD_FRONT_EVIDENCE,
    )
    partial = tuple((name, "a" * 64) for name in REQUIRED_CTP_READ_ONLY_QUERIES[:-1])
    with pytest.raises(CtpProductionReadOnlyRuntimeError) as snapshot_error:
        CtpProductionReadOnlyQuerySnapshot.from_query_digests(
            identity,
            partial,
            instrument_id=pin.instrument_id,
            exchange_id=pin.exchange_id,
            hedge_flag=pin.hedge_flag,
        )
    assert snapshot_error.value.reason == "incomplete_query_set"

    complete = CtpProductionReadOnlyQuerySnapshot.from_query_digests(
        identity,
        tuple((name, "b" * 64) for name in REQUIRED_CTP_READ_ONLY_QUERIES),
        instrument_id=pin.instrument_id,
        exchange_id=pin.exchange_id,
        hedge_flag=pin.hedge_flag,
    )
    assert len(complete.query_digests) == len(REQUIRED_CTP_READ_ONLY_QUERIES)


def test_invalid_snapshot_from_session_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    session = _FakeSession(pin, snapshot=object())
    factory = _FakeFactory(pin, session)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "invalid_query_snapshot"
    assert session.calls[-1] == "close"


def test_session_front_pair_mismatch_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    identity = CtpProductionReadOnlySessionIdentity(
        account_binding_sha256=pin.account_binding_sha256,
        trading_day="20260924",
        connection_generation=7,
        md_front_sha256="0" * 64,
        td_front_sha256=hashlib.sha256(pin.td_front.encode("utf-8")).hexdigest(),
        td_front_binding_evidence=_LOCAL_TD_FRONT_EVIDENCE,
    )
    session = _FakeSession(pin, identity=identity)
    factory = _FakeFactory(pin, session)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "session_identity_mismatch"
    assert session.calls[-1] == "close"


def test_query_snapshot_instrument_scope_must_match_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    identity = CtpProductionReadOnlySessionIdentity(
        account_binding_sha256=pin.account_binding_sha256,
        trading_day="20260924",
        connection_generation=7,
        md_front_sha256=hashlib.sha256(pin.md_front.encode("utf-8")).hexdigest(),
        td_front_sha256=hashlib.sha256(pin.td_front.encode("utf-8")).hexdigest(),
        td_front_binding_evidence=_LOCAL_TD_FRONT_EVIDENCE,
    )
    digests = tuple(
        (name, hashlib.sha256(name.encode("ascii")).hexdigest())
        for name in REQUIRED_CTP_READ_ONLY_QUERIES
    )
    snapshot = CtpProductionReadOnlyQuerySnapshot.from_query_digests(
        identity,
        digests,
        instrument_id="wrong-contract",
        exchange_id=pin.exchange_id,
        hedge_flag=pin.hedge_flag,
    )
    session = _FakeSession(pin, identity=identity, snapshot=snapshot)
    factory = _FakeFactory(pin, session)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "snapshot_identity_mismatch"
    assert session.calls[-1] == "close"
