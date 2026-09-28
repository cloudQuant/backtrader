"""Fake-client acceptance for the sealed production CTP SDK read adapter."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, Optional

import pytest

import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_production_credentials as production_credentials
import backtrader_runtime.ctp_production_readonly_runtime as production_runtime
import backtrader_runtime.ctp_production_sdk_readonly as sdk_readonly
from backtrader_runtime.ctp_production_readonly_admission import _front_pair_set_sha256
import backtrader_runtime.ctp_sdk_market_readonly as market_probe
from backtrader_runtime import RegisteredRuntime, RuntimeRegistry
from backtrader_runtime.ctp_production_readonly_admission import (
    CtpProductionReadOnlyRegistration,
    production_account_binding_sha256,
)
from backtrader_runtime.ctp_production_readonly_runtime import (
    CtpProductionReadOnlyRuntimeError,
    CtpProductionReadOnlySessionRequest,
    run_ctp_production_readonly_preflight,
)
from backtrader_runtime.ctp_production_sdk_readonly import (
    CtpProductionSdkReadOnlyError,
    CtpProductionSdkReadOnlySessionFactory,
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
_QUERY_NAMES = (
    "account",
    "positions",
    "orders",
    "trades",
    "instruments",
    "margin_rate",
    "commission_rate",
)
_WRITE_COUNTERS = ("settlement_confirm", "order_insert", "order_action")


@pytest.fixture(autouse=True)
def _isolate_market_probe_locks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setattr(
        market_probe,
        "_account_lock_root",
        lambda: tmp_path / market_probe._LOCK_DIRECTORY_NAME,
    )
    monkeypatch.setattr(market_probe, "_PROCESS_LOCKS", {})
    monkeypatch.setattr(market_probe, "_PENDING_LEASES", {})
    _FakeMdClient.behavior = "success"
    _FakeMdClient.instances.clear()
    yield
    for lease, _client, _thread in market_probe._PENDING_LEASES.values():
        lease.release()
    market_probe._PENDING_LEASES.clear()


@pytest.mark.parametrize("unknown_count", [0, 1])
def test_unknown_native_request_counter_fails_closed(unknown_count: int) -> None:
    counts = dict.fromkeys(_WRITE_COUNTERS, 0)
    counts["new_native_write"] = unknown_count
    client = SimpleNamespace(get_request_counts=lambda: counts)

    with pytest.raises(CtpProductionSdkReadOnlyError) as rejected:
        sdk_readonly._require_zero_writes(client)

    assert rejected.value.reason == "native_write_detected"


def _document(private_values: Optional[dict] = None, *, canonical: bool = True) -> dict:
    private_block = dict(_PRIVATE_VALUES if private_values is None else private_values)
    return {
        "config_schema_version": 4,
        "strategy": {
            "id": "example.013_3.sa_midfreq_simnow"
            if canonical
            else "example.007_ctp.production"
        },
        "runtime": {"mode": "live", "preset": "managed_live_direct"},
        "parameters": {},
        "secrets_ref": "config_yaml",
        "ctp" if canonical else "ctp_production": private_block,
    }


def _bound_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    private_values: Optional[dict] = None,
    *,
    pin_fronts: bool = True,
    canonical: bool = True,
):
    monkeypatch.setattr(
        production_runtime,
        "select_ctp_front_pair",
        lambda front_pairs, **_kwargs: SimpleNamespace(pair=SimpleNamespace(**front_pairs[0])),
    )
    monkeypatch.setattr(
        sdk_readonly,
        "select_ctp_front_pair",
        lambda front_pairs, **_kwargs: SimpleNamespace(pair=SimpleNamespace(**front_pairs[0])),
    )
    runtime_dir = tmp_path / "runtime-ctp-private" if canonical else tmp_path
    if canonical:
        runtime_dir.mkdir()
    monkeypatch.setattr(runtime_config, "CTP_PRODUCTION_RUNTIME_DIR", runtime_dir)
    registration = RegisteredRuntime(
        runtime_dir=runtime_dir,
        strategy_id=(
            "example.013_3.sa_midfreq_simnow"
            if canonical
            else "example.007_ctp.production"
        ),
        allowed_presets=("managed_live_direct",),
        allowed_secrets_refs=("config_yaml",),
    )
    registry = RuntimeRegistry((registration,))
    config = runtime_config._validate_schema(
        _document(private_values, canonical=canonical), runtime_dir, runtime_dir / "config.yaml"
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


class _FakeClient:
    instances = []
    generation = 7
    generation_changes_after_query = False
    front_state_available = True
    connection_confirmed_front = _PRIVATE_VALUES["td_front"]
    reported_investor_id = _PRIVATE_VALUES["user_id"]
    incomplete_join_state = False
    join_behavior = "complete"
    wait_ready_error = None

    def __init__(
        self,
        front,
        broker_id,
        user_id,
        password,
        *,
        app_id,
        auth_code,
        auto_settlement_confirm,
    ) -> None:
        assert front == _PRIVATE_VALUES["td_front"]
        assert (broker_id, user_id) == (
            _PRIVATE_VALUES["broker_id"],
            _PRIVATE_VALUES["user_id"],
        )
        assert password == _PRIVATE_VALUES["password"]
        assert app_id == _PRIVATE_VALUES["app_id"]
        assert auth_code == _PRIVATE_VALUES["auth_code"]
        assert auto_settlement_confirm is False
        self.calls = []
        self.stopped = 0
        self.counts = dict.fromkeys(_WRITE_COUNTERS, 0)
        self.join_timeouts = []
        self._thread = None
        self._join_active = False
        self._native_init_started = False
        if self.incomplete_join_state:
            del self._thread
        self.instances.append(self)

    def start(self, *, block: bool) -> None:
        assert block is False
        if self.join_behavior in ("pending", "complete_on_stop"):
            self.join_release = threading.Event()
            self._join_active = True
            self._native_init_started = True

            def join_worker() -> None:
                self.join_release.wait()
                self._join_active = False
                self._native_init_started = False

            self._thread = threading.Thread(target=join_worker, daemon=True)
            original_join = self._thread.join

            def record_join(timeout=None):
                self.join_timeouts.append(timeout)
                return original_join(timeout)

            self._thread.join = record_join
            self._thread.start()

    def wait_ready(self, *, timeout: float) -> bool:
        assert 0 < timeout <= 15
        if self.wait_ready_error is not None:
            raise RuntimeError(self.wait_ready_error)
        return True

    def get_session_state(self):
        return {"auto_settlement_confirm": False}

    def get_query_session_scope(self):
        scope = {
            "read_only_ready": True,
            "broker_id": _PRIVATE_VALUES["broker_id"],
            "investor_id": self.reported_investor_id,
            "trading_day": "20260924",
            "connection_generation": self.generation,
        }
        return SimpleNamespace(**scope)

    def get_front_binding_state(self):
        if not self.front_state_available:
            return None
        return {
            "configured_front": _PRIVATE_VALUES["td_front"],
            "registered_front": _PRIVATE_VALUES["td_front"],
            "connection_confirmed_front": self.connection_confirmed_front,
            "connected": True,
            "connection_generation": self.generation,
            "native_api_current": True,
            "bound_identity_current": True,
        }

    def get_request_counts(self):
        return dict(self.counts)

    def stop(self):
        self.stopped += 1
        if self.join_behavior == "complete_on_stop":
            self.join_release.set()

    def _query(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self.generation_changes_after_query and len(self.calls) == 1:
            type(self).generation += 1
        return name

    def query_account_result(self, **kwargs):
        return self._query("account", **kwargs)

    def query_positions_result(self, **kwargs):
        return self._query("positions", **kwargs)

    def query_orders_result(self, **kwargs):
        return self._query("orders", **kwargs)

    def query_trades_result(self, **kwargs):
        return self._query("trades", **kwargs)

    def query_instruments_result(self, **kwargs):
        return self._query("instruments", **kwargs)

    def query_instrument_margin_rate_result(self, instrument_id, **kwargs):
        return self._query("margin_rate", instrument_id=instrument_id, **kwargs)

    def query_instrument_commission_rate_result(self, instrument_id, **kwargs):
        return self._query("commission_rate", instrument_id=instrument_id, **kwargs)


class _FakeBuilder:
    def __init__(self, client, *, instrument_id, exchange_id, hedge_flag) -> None:
        assert isinstance(client, _FakeClient)
        assert (instrument_id, exchange_id, hedge_flag) == (
            _PRIVATE_VALUES["instrument_id"],
            _PRIVATE_VALUES["exchange_id"],
            _PRIVATE_VALUES["hedge_flag"],
        )
        self.names = []

    def add(self, result):
        self.names.append(result)

    def finish(self):
        assert tuple(self.names) == _QUERY_NAMES
        return SimpleNamespace(
            query_digests=tuple(
                (name, hashlib.sha256(name.encode("ascii")).hexdigest()) for name in self.names
            ),
            certificate_sha256=hashlib.sha256(b"production-native-certificate").hexdigest(),
        )


class _FakeMdClient:
    """Small MD facade that drives the real production callback probe."""

    instances = []
    behavior = "success"

    def __init__(self, front, broker_id, user_id, password) -> None:
        assert front == _PRIVATE_VALUES["md_front"]
        assert (broker_id, user_id, password) == (
            _PRIVATE_VALUES["broker_id"],
            _PRIVATE_VALUES["user_id"],
            _PRIVATE_VALUES["password"],
        )
        self.front = front
        self.broker_id = broker_id
        self.user_id = user_id
        self._state_lock = threading.RLock()
        self._connected = False
        self._loggedin = False
        self._connection_generation = 12
        self._thread = None
        self.subscriptions = []
        self.stopped = 0
        self.market_requests = []
        self.trading_writes = 0
        type(self).instances.append(self)

    @property
    def connection_generation(self):
        with self._state_lock:
            return self._connection_generation

    def subscribe(self, instruments):
        self.subscriptions.append(list(instruments))
        self.market_requests.append("subscribe")

    def start(self, *, block):
        assert block is False
        behavior = type(self).behavior
        with self._state_lock:
            self._connected = behavior not in ("timeout",)
            self._loggedin = behavior not in ("timeout",)
        if behavior == "timeout":
            return
        if behavior == "wrong_front":
            self.front = "tcp://192.0.2.99:41211"
        if behavior == "wrong_generation":
            self.on_login(SimpleNamespace(BrokerID=self.broker_id, UserID=self.user_id))
            with self._state_lock:
                self._connection_generation += 1
        else:
            self.on_login(
                SimpleNamespace(
                    BrokerID=self.broker_id,
                    UserID=("other-account" if behavior == "wrong_account" else self.user_id),
                )
            )
        ack_instrument = (
            "rb2610" if behavior == "wrong_instrument" else _PRIVATE_VALUES["instrument_id"]
        )
        self.on_subscribe(SimpleNamespace(InstrumentID=ack_instrument), SimpleNamespace(ErrorID=0))
        if behavior in ("success", "wrong_generation", "wrong_instrument_tick"):
            instrument = (
                "rb2610"
                if behavior == "wrong_instrument_tick"
                else _PRIVATE_VALUES["instrument_id"]
            )
            self.on_tick(
                SimpleNamespace(
                    InstrumentID=instrument,
                    ExchangeID=_PRIVATE_VALUES["exchange_id"],
                    LastPrice=3600.0,
                    Volume=1,
                )
            )

    def stop(self):
        self.stopped += 1
        if type(self).behavior == "failed_close":
            raise RuntimeError("sensitive native close details")


def _factory(config, registry, pin, monkeypatch, *, connect_timeout=0.25):
    # Local fake config values are sufficient for these tests. No protected
    # file, Credential Manager, SDK install, or provider is consulted.
    monkeypatch.setattr(production_credentials, "_require_private_config_acl", lambda *_args: None)
    monkeypatch.setattr(sdk_readonly, "verify_ctp_production_sdk_artifact_provenance", lambda: None)
    loaded = []

    def load_fake_sdk():
        loaded.append("sdk")
        return _FakeClient, _FakeBuilder

    def load_fake_md_client():
        client = _FakeClient.instances[-1]
        assert len(client.calls) == len(_QUERY_NAMES)
        assert client.stopped == 1
        loaded.append("md_sdk")
        return _FakeMdClient

    factory = CtpProductionSdkReadOnlySessionFactory(
        config=config,
        registry=registry,
        admission_registration=pin,
        connect_timeout=connect_timeout,
        sdk_components_loader=load_fake_sdk,
        md_client_type_loader=load_fake_md_client,
    )
    return factory, loaded


def test_missing_production_artifact_pin_rejects_before_credentials_and_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    touched = []

    def unexpected_credentials(*_args):
        touched.append("credentials")
        raise AssertionError("credentials were read before the artifact gate")

    def unexpected_sdk():
        touched.append("sdk")
        raise AssertionError("the SDK was loaded before the artifact gate")

    def unexpected_md_sdk():
        touched.append("md_sdk")
        raise AssertionError("the MD SDK was loaded before the artifact gate")

    monkeypatch.setattr(sdk_readonly, "resolve_ctp_production_credentials", unexpected_credentials)
    factory = CtpProductionSdkReadOnlySessionFactory(
        config=config,
        registry=registry,
        admission_registration=pin,
        sdk_components_loader=unexpected_sdk,
        md_client_type_loader=unexpected_md_sdk,
    )

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    assert caught.value.reason == "artifact_provenance_rejected"
    assert touched == []


def test_canonical_live_config_in_simnow_directory_rejects_before_credentials_and_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, canonical=True)
    assert config.ctp is not None
    assert config.ctp_production is None
    touched = []

    def unexpected_credentials(*_args):
        touched.append("credentials")
        raise AssertionError("credentials were read before the artifact gate")

    monkeypatch.setattr(
        sdk_readonly,
        "verify_ctp_production_sdk_artifact_provenance",
        lambda: (_ for _ in ()).throw(RuntimeError("unreviewed SDK artifact")),
    )
    monkeypatch.setattr(sdk_readonly, "resolve_ctp_production_credentials", unexpected_credentials)
    monkeypatch.setattr(
        sdk_readonly,
        "select_ctp_front_pair",
        lambda front_pairs, **_kwargs: SimpleNamespace(pair=SimpleNamespace(**front_pairs[0])),
    )
    factory = CtpProductionSdkReadOnlySessionFactory(
        config=config,
        registry=registry,
        admission_registration=pin,
        sdk_components_loader=lambda: pytest.fail("SDK imported before artifact review"),
        md_client_type_loader=lambda: pytest.fail("MD SDK imported before artifact review"),
    )

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    assert caught.value.reason == "artifact_provenance_rejected"
    assert touched == []


def test_legacy_production_block_rejects_before_probe_credentials_or_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch, canonical=False)
    touched = []

    def unexpected(label):
        def reject(*_args, **_kwargs):
            touched.append(label)
            raise AssertionError("legacy config reached {0}".format(label))

        return reject

    monkeypatch.setattr(sdk_readonly, "select_ctp_front_pair", unexpected("front_probe"))
    monkeypatch.setattr(
        sdk_readonly,
        "verify_ctp_production_sdk_artifact_provenance",
        unexpected("artifact_gate"),
    )
    monkeypatch.setattr(
        sdk_readonly, "resolve_ctp_production_credentials", unexpected("credentials")
    )
    factory = CtpProductionSdkReadOnlySessionFactory(
        config=config,
        registry=registry,
        admission_registration=pin,
        sdk_components_loader=unexpected("td_sdk"),
        md_client_type_loader=unexpected("md_sdk"),
    )

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    assert caught.value.reason == "config_binding_rejected"
    assert touched == []


def test_direct_factory_single_front_probe_failure_precedes_all_sdk_and_secret_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    touched = []
    selected = []

    def fail_probe(front_pairs, **kwargs):
        selected.append((front_pairs, kwargs))
        raise RuntimeError("synthetic probe failure")

    def artifact_gate():
        touched.append("artifact")
        raise AssertionError("artifact gate must not run after probe failure")

    def credentials(*_args):
        touched.append("credentials")
        raise AssertionError("credentials must not run after probe failure")

    def sdk_loader():
        touched.append("sdk")
        raise AssertionError("SDK loader must not run after probe failure")

    monkeypatch.setattr(sdk_readonly, "verify_ctp_production_sdk_artifact_provenance", artifact_gate)
    monkeypatch.setattr(sdk_readonly, "resolve_ctp_production_credentials", credentials)
    monkeypatch.setattr(sdk_readonly, "select_ctp_front_pair", fail_probe)
    factory = CtpProductionSdkReadOnlySessionFactory(
        config=config,
        registry=registry,
        admission_registration=pin,
        sdk_components_loader=sdk_loader,
    )

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    assert caught.value.reason == "front_probe_rejected"
    assert selected == [
        (
            ({"md_front": pin.md_front, "td_front": pin.td_front},),
            {"timeout_seconds": 2.0, "max_pairs": 1, "repeated_samples": 3},
        )
    ]
    assert touched == []


def test_direct_factory_multi_pair_request_probes_only_the_selected_sealed_pair(
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
    events = []
    probe_inputs = []

    def select_exact_pair(front_pairs, **kwargs):
        events.append("front_probe")
        probe_inputs.append((front_pairs, kwargs))
        return SimpleNamespace(pair=SimpleNamespace(**front_pairs[0]))

    def reject_artifact():
        events.append("artifact_gate")
        raise RuntimeError("production wheel pin remains unavailable")

    def unexpected_credentials(*_args, **_kwargs):
        events.append("credentials")
        raise AssertionError("credentials must follow the artifact gate")

    monkeypatch.setattr(sdk_readonly, "select_ctp_front_pair", select_exact_pair)
    monkeypatch.setattr(sdk_readonly, "verify_ctp_production_sdk_artifact_provenance", reject_artifact)
    monkeypatch.setattr(
        sdk_readonly, "resolve_ctp_production_credentials", unexpected_credentials
    )
    factory, loaded = _factory(config, registry, pin, monkeypatch)
    # _factory installs a default artifact stub; restore the explicit rejecting
    # gate after it has built the SDK factory.
    monkeypatch.setattr(sdk_readonly, "verify_ctp_production_sdk_artifact_provenance", reject_artifact)
    selected_pair = (pairs[1]["md_front"], pairs[1]["td_front"])
    candidate_pairs = tuple((pair["md_front"], pair["td_front"]) for pair in pairs)
    request = factory_request_for(
        pin,
        selected_pair=selected_pair,
        front_pairs=candidate_pairs,
    )

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(request)

    assert caught.value.reason == "artifact_provenance_rejected"
    assert probe_inputs == [
        (
            ({"md_front": selected_pair[0], "td_front": selected_pair[1]},),
            {"timeout_seconds": 2.0, "max_pairs": 1, "repeated_samples": 3},
        )
    ]
    assert events == ["front_probe", "artifact_gate"]
    assert loaded == []


def test_sealed_production_adapter_runs_seven_reads_and_closes_without_write_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    _FakeClient.generation = 7
    _FakeClient.generation_changes_after_query = False
    _FakeClient.front_state_available = True
    _FakeClient.connection_confirmed_front = _PRIVATE_VALUES["td_front"]
    _FakeClient.incomplete_join_state = False
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, loaded = _factory(config, registry, pin, monkeypatch)
    events = []

    wrapper_selector = production_runtime.select_ctp_front_pair
    factory_selector = sdk_readonly.select_ctp_front_pair
    artifact_gate = sdk_readonly.verify_ctp_production_sdk_artifact_provenance
    credential_resolver = sdk_readonly.resolve_ctp_production_credentials
    sdk_loader = factory._sdk_components_loader

    def record_wrapper_probe(*args, **kwargs):
        events.append("composition_probe")
        return wrapper_selector(*args, **kwargs)

    def record_factory_probe(*args, **kwargs):
        events.append("factory_probe")
        return factory_selector(*args, **kwargs)

    def record_artifact_gate():
        events.append("artifact_gate")
        return artifact_gate()

    def record_credentials(*args, **kwargs):
        events.append("credentials")
        return credential_resolver(*args, **kwargs)

    def record_sdk_loader():
        events.append("sdk_import")
        return sdk_loader()

    monkeypatch.setattr(production_runtime, "select_ctp_front_pair", record_wrapper_probe)
    monkeypatch.setattr(sdk_readonly, "select_ctp_front_pair", record_factory_probe)
    monkeypatch.setattr(
        sdk_readonly, "verify_ctp_production_sdk_artifact_provenance", record_artifact_gate
    )
    monkeypatch.setattr(sdk_readonly, "resolve_ctp_production_credentials", record_credentials)
    factory._sdk_components_loader = record_sdk_loader

    class _CaptureSessionFactory:
        session = None

        def open_read_only(self, request):
            self.session = factory.open_read_only(request)
            return self.session

    capture = _CaptureSessionFactory()

    observation = run_ctp_production_readonly_preflight(
        config=config,
        registry=registry,
        admission_registration=pin,
        session_factory=capture,
    )

    assert events == [
        "composition_probe",
        "factory_probe",
        "artifact_gate",
        "credentials",
        "sdk_import",
    ]
    client = _FakeClient.instances[-1]
    assert loaded == ["sdk", "md_sdk"]
    assert [name for name, _ in client.calls] == list(_QUERY_NAMES)
    assert client.calls[4][1]["instrument_id"] == pin.instrument_id
    assert client.calls[5][1]["hedge_flag"] == pin.hedge_flag
    assert client.counts == dict.fromkeys(_WRITE_COUNTERS, 0)
    assert client.stopped == 1
    assert observation.connection_generation == 7
    assert observation.query_snapshot.instrument_id == pin.instrument_id
    assert observation.query_snapshot.exchange_id == pin.exchange_id
    md_observation = observation.query_snapshot.market_data_observation
    assert md_observation is not None
    assert md_observation.tick_observation_count == 1
    assert md_observation.connection_generation == 12
    assert md_observation.remote_front_identity_verified is False
    assert md_observation.client_stop_returned is True
    assert md_observation.native_join_pending is False
    assert observation.as_public_dict()["remote_front_identity_verified"] is False
    assert (
        observation.as_public_dict()["md_front_evidence"]
        == "local_sdk_login_subscription_post_ack_tick"
    )
    assert _FakeMdClient.instances[-1].subscriptions == [[pin.instrument_id]]
    assert _FakeMdClient.instances[-1].stopped == 1
    assert _FakeMdClient.instances[-1].market_requests == ["subscribe"]
    assert _FakeMdClient.instances[-1].trading_writes == 0
    assert (
        observation.query_snapshot.native_certificate_sha256
        == hashlib.sha256(b"production-native-certificate").hexdigest()
    )
    session = capture.session
    assert not hasattr(session, "submit_order")
    assert not hasattr(session, "cancel_order")
    assert not hasattr(session, "confirm_settlement")
    public_text = str(observation.as_public_dict())
    assert pin.md_front not in public_text
    assert pin.td_front not in public_text
    assert _PRIVATE_VALUES["user_id"] not in public_text
    assert _PRIVATE_VALUES["password"] not in public_text


@pytest.mark.parametrize(
    ("behavior", "expected_reason", "timeout"),
    [
        ("wrong_front", "market_front_binding_mismatch", 0.2),
        ("wrong_account", "market_login_identity_mismatch", 0.2),
        ("wrong_instrument", "market_subscription_instrument_mismatch", 0.2),
        ("wrong_generation", "market_connection_generation_changed", 0.2),
        ("wrong_instrument_tick", "market_tick_not_observed", 0.1),
        ("no_tick", "market_tick_not_observed", 0.1),
        ("timeout", "market_login_timeout", 0.05),
        ("failed_close", "market_client_stop_failed", 0.2),
    ],
)
def test_production_md_probe_rejects_scope_drift_timeout_and_unclean_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    behavior: str,
    expected_reason: str,
    timeout: float,
) -> None:
    _FakeClient.instances.clear()
    _FakeClient.generation = 7
    _FakeClient.generation_changes_after_query = False
    _FakeMdClient.behavior = behavior
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, loaded = _factory(config, registry, pin, monkeypatch, connect_timeout=timeout)
    session = factory.open_read_only(factory_request_for(pin))

    try:
        with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
            session.read_query_snapshot()
        assert caught.value.reason == expected_reason
        assert loaded == ["sdk", "md_sdk"]
        assert [name for name, _ in _FakeClient.instances[-1].calls] == list(_QUERY_NAMES)
        assert _FakeClient.instances[-1].stopped == 1
        assert _FakeClient.instances[-1].counts == dict.fromkeys(_WRITE_COUNTERS, 0)
        md_client = _FakeMdClient.instances[-1]
        assert md_client.subscriptions == [[pin.instrument_id]]
        assert md_client.market_requests == ["subscribe"]
        assert md_client.stopped == 1
        assert md_client.trading_writes == 0
    finally:
        try:
            session.close_read_only()
        except CtpProductionSdkReadOnlyError:
            pass


def factory_request_for(
    pin,
    *,
    selected_pair=None,
    front_pairs=None,
) -> CtpProductionReadOnlySessionRequest:
    import time

    selected_pair = selected_pair or (pin.md_front, pin.td_front)
    front_pairs = front_pairs or (selected_pair,)

    return CtpProductionReadOnlySessionRequest(
        environment="production",
        account_binding_sha256=pin.account_binding_sha256,
        front_pair_set_sha256=_front_pair_set_sha256(tuple(front_pairs)),
        md_front_sha256=hashlib.sha256(selected_pair[0].encode("utf-8")).hexdigest(),
        td_front_sha256=hashlib.sha256(selected_pair[1].encode("utf-8")).hexdigest(),
        instrument_id=pin.instrument_id,
        exchange_id=pin.exchange_id,
        hedge_flag=pin.hedge_flag,
        valid_until=time.time() + 30,
    )


def test_front_request_mismatch_is_rejected_before_credentials_or_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, loaded = _factory(config, registry, pin, monkeypatch)
    calls = []
    original = sdk_readonly.resolve_ctp_production_credentials

    def resolve(*args):
        calls.append("credentials")
        return original(*args)

    monkeypatch.setattr(sdk_readonly, "resolve_ctp_production_credentials", resolve)
    request = factory_request_for(pin)
    forged = CtpProductionReadOnlySessionRequest(
        environment=request.environment,
        account_binding_sha256=request.account_binding_sha256,
        front_pair_set_sha256=request.front_pair_set_sha256,
        md_front_sha256="0" * 64,
        td_front_sha256=request.td_front_sha256,
        instrument_id=request.instrument_id,
        exchange_id=request.exchange_id,
        hedge_flag=request.hedge_flag,
        valid_until=request.valid_until,
    )

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(forged)

    assert caught.value.reason == "request_scope_mismatch"
    assert calls == []
    assert loaded == []


def test_config_seal_rejection_precedes_credentials_and_sdk_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, loaded = _factory(config, registry, pin, monkeypatch)
    calls = []

    def unexpected_credentials(*_args):
        calls.append("credentials")
        raise AssertionError("credentials must not resolve before the config gate")

    monkeypatch.setattr(sdk_readonly, "resolve_ctp_production_credentials", unexpected_credentials)
    object.__setattr__(config.ctp, "td_front", "tcp://192.0.2.99:41201")

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    assert caught.value.reason == "config_binding_rejected"
    assert calls == []
    assert loaded == []


def test_client_account_mismatch_is_rejected_and_client_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    _FakeClient.generation = 7
    monkeypatch.setattr(_FakeClient, "reported_investor_id", "different-production-account")
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, _loaded = _factory(config, registry, pin, monkeypatch)

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    assert caught.value.reason == "session_account_mismatch"
    assert _FakeClient.instances[-1].stopped == 1


def test_early_account_rejection_requires_complete_native_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    _FakeClient.generation = 7
    _FakeClient.incomplete_join_state = True
    monkeypatch.setattr(_FakeClient, "reported_investor_id", "different-production-account")
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, _loaded = _factory(config, registry, pin, monkeypatch)
    try:
        with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
            factory.open_read_only(factory_request_for(pin))
        assert caught.value.reason == "session_join_state_unknown"
        assert _FakeClient.instances[-1].stopped == 1
    finally:
        _FakeClient.incomplete_join_state = False


def test_session_generation_change_during_native_reads_is_rejected_and_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    _FakeClient.generation = 7
    _FakeClient.generation_changes_after_query = True
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, _loaded = _factory(config, registry, pin, monkeypatch)

    with pytest.raises(CtpProductionReadOnlyRuntimeError) as caught:
        run_ctp_production_readonly_preflight(
            config=config,
            registry=registry,
            admission_registration=pin,
            session_factory=factory,
        )

    assert caught.value.reason == "query_snapshot_unavailable"
    assert _FakeClient.instances[-1].stopped == 1
    _FakeClient.generation_changes_after_query = False


def test_front_report_mismatch_is_rejected_and_client_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    _FakeClient.generation = 7
    _FakeClient.front_state_available = True
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, _loaded = _factory(config, registry, pin, monkeypatch)
    monkeypatch.setattr(_FakeClient, "connection_confirmed_front", "tcp://192.0.2.99:41201")
    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    assert caught.value.reason == "session_front_mismatch"
    assert _FakeClient.instances[-1].stopped == 1


def test_missing_connected_front_callback_evidence_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    _FakeClient.generation = 7
    monkeypatch.setattr(_FakeClient, "front_state_available", False)
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, _loaded = _factory(config, registry, pin, monkeypatch)

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    assert caught.value.reason == "front_binding_evidence_unavailable"
    assert _FakeClient.instances[-1].stopped == 1


def test_incomplete_native_close_state_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    _FakeClient.generation = 7
    _FakeClient.incomplete_join_state = True
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, _loaded = _factory(config, registry, pin, monkeypatch)
    session = factory.open_read_only(factory_request_for(pin))
    client = _FakeClient.instances[-1]
    try:
        with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
            session.close_read_only()
        assert caught.value.reason == "session_join_state_unknown"
        assert client.stopped == 1
    finally:
        _FakeClient.incomplete_join_state = False


def test_early_open_failure_joins_client_thread_and_redacts_sdk_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr(_FakeClient, "join_behavior", "complete_on_stop")
    monkeypatch.setattr(
        _FakeClient, "wait_ready_error", _PRIVATE_VALUES["password"] + " leaked by SDK"
    )
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, _loaded = _factory(config, registry, pin, monkeypatch)

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    client = _FakeClient.instances[-1]
    assert caught.value.reason == "session_open_failed"
    assert _PRIVATE_VALUES["password"] not in str(caught.value)
    assert client.stopped == 1
    assert client._thread is not None and not client._thread.is_alive()
    assert client.join_timeouts == [sdk_readonly._MAX_CLOSE_JOIN_WAIT_SECONDS]


def test_early_open_failure_rejects_a_thread_that_misses_bounded_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _FakeClient.instances.clear()
    monkeypatch.setattr(_FakeClient, "join_behavior", "pending")
    monkeypatch.setattr(sdk_readonly, "_MAX_CLOSE_JOIN_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(_FakeClient, "wait_ready_error", None)
    monkeypatch.setattr(_FakeClient, "front_state_available", False)
    config, registry, pin = _bound_inputs(tmp_path, monkeypatch)
    factory, _loaded = _factory(config, registry, pin, monkeypatch)

    with pytest.raises(CtpProductionSdkReadOnlyError) as caught:
        factory.open_read_only(factory_request_for(pin))

    client = _FakeClient.instances[-1]
    try:
        assert caught.value.reason == "session_close_incomplete"
        assert client.stopped == 1
        assert client._thread is not None and client._thread.is_alive()
        assert client.join_timeouts == [0.01]
    finally:
        client.join_release.set()
        client._thread.join(1.0)
