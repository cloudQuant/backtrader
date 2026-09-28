"""Offline tests for the explicitly injected managed SimNow composition root."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import backtrader_runtime.config as runtime_config
import backtrader_runtime.ctp_native_shutdown as ctp_native_shutdown_module
import backtrader_runtime.ctp_simnow_managed_runtime as managed_runtime
from backtrader_runtime.ctp_simnow_managed_operator import CtpSimNowManagedExecutionPolicy
from backtrader_runtime.ctp_simnow_td_trading_readiness import (
    verify_ctp_simnow_td_trading_readiness,
)
from backtrader_runtime.ctp_simulation_execution import CtpSimulationSessionIdentity
from backtrader_runtime.registry import RegisteredRuntime, RuntimeRegistry, validate_runtime_config


RUNTIME_ID = "iteration41.ctp.simnow.managed-runtime-test"
STRATEGY_ID = "iteration41.ctp.simnow.managed_runtime_test"
PAIRS = (
    ("tcp://127.0.0.1:11001", "tcp://127.0.0.1:12001"),
    ("tcp://127.0.0.1:11002", "tcp://127.0.0.1:12002"),
    ("tcp://127.0.0.1:11003", "tcp://127.0.0.1:12003"),
)
BROKER_ID = "9999"
USER_ID = "offline-runtime-test"


@dataclass(frozen=True)
class _FakeNativeStopReceipt:
    connection_generation: int
    join_required: bool = False
    join_completed: bool = True
    native_released: bool = True
    thread_alive: bool = False
    timed_out: bool = False

    @property
    def complete(self) -> bool:
        return (
            self.native_released
            and (not self.join_required or self.join_completed)
            and self.thread_alive is False
            and self.timed_out is False
        )


def _install_stop_receipt(client: Any) -> None:
    client.connection_generation = 1

    def stop_and_wait(*, timeout: float) -> _FakeNativeStopReceipt:
        assert timeout > 0
        client.stop()
        return _FakeNativeStopReceipt(client.connection_generation)

    client.stop_and_wait = stop_and_wait


class _Verifier:
    def verify(self, *_args: Any, **_kwargs: Any) -> bool:
        return True


class _WriterFence:
    environment = "simnow"
    fence_id = "offline-fence-1"

    def __init__(self) -> None:
        account_fingerprint = hashlib.sha256(f"{BROKER_ID}:{USER_ID}".encode("utf-8")).hexdigest()[
            :16
        ]
        self.account_fingerprint_sha256 = hashlib.sha256(
            ("acct_" + account_fingerprint).encode("ascii")
        ).hexdigest()
        self.calls = 0

    def assert_active(self) -> None:
        self.calls += 1


class _FakePort:
    def __init__(self, registration, client=None) -> None:
        self.registration = registration
        self.client = client
        self.config = SimpleNamespace(
            md_front=registration.md_front,
            td_front=registration.td_front,
            broker_id=BROKER_ID,
            user_id=USER_ID,
        )
        self.close_calls = 0
        self.identity = CtpSimulationSessionIdentity(
            environment="simnow",
            sdk_profile="config_front_pair",
            td_front=registration.td_front,
            md_front=registration.md_front,
            account_fingerprint_sha256=registration.account_fingerprint_sha256,
            trading_day="20260924",
            connection_generation=1,
            production=False,
            native_gate_armed=False,
            native_simnow_managed_mode=True,
        )

    def get_execution_identity(self):
        return self.identity

    def close(self) -> None:
        self.close_calls += 1
        if self.client is not None and not managed_runtime.stop_ctp_native_client(self.client):
            raise managed_runtime.CtpSimulationExecutionError("native_session_close_failed")


@pytest.fixture(autouse=True)
def _allow_synthetic_private_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_config, "_require_private_config_security", lambda *a, **k: None)
    monkeypatch.setattr(
        ctp_native_shutdown_module,
        "_native_stop_receipt_type",
        lambda: _FakeNativeStopReceipt,
    )


def _runtime(tmp_path: Path) -> tuple[Path, RuntimeRegistry, CtpSimNowManagedExecutionPolicy]:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    pair_lines = ["  front_pairs:"]
    for md_front, td_front in PAIRS:
        pair_lines.extend((f"    - md_front: {md_front}", f"      td_front: {td_front}"))
    (runtime_dir / "config.yaml").write_text(
        "\n".join(
            [
                "config_schema_version: 4",
                "strategy:",
                f"  id: {STRATEGY_ID}",
                "runtime:",
                "  mode: simulation",
                "  preset: sandbox",
                "parameters: {}",
                "secrets_ref: config_yaml",
                "ctp:",
                *pair_lines,
                "  instrument_id: rb2701",
                "  exchange_id: SHFE",
                "  hedge_flag: '1'",
                f"  broker_id: '{BROKER_ID}'",
                f"  user_id: {USER_ID}",
                "  password: offline-fake-password",
                "  app_id: offline-fake-app",
                "  auth_code: offline-fake-auth",
                "",
            ]
        ),
        encoding="utf-8",
    )
    registered = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id=RUNTIME_ID,
        strategy_id=STRATEGY_ID,
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor"),
        sandbox_write_policy="receipt_required",
        approval_receipt_digest="a" * 64,
    )
    registry = RuntimeRegistry((registered,), registry_id="test.simnow.managed-runtime")
    policy = CtpSimNowManagedExecutionPolicy(
        runtime_registration=registered,
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=2,
        max_gross_position=2,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("1"),
        approval_key_id="offline-key",
        approval_ttl_seconds=20,
    )
    return runtime_dir, registry, policy


def _connector(calls: list, latency_by_port: dict[int, float] | None = None):
    latency_by_port = latency_by_port or {}

    def connect(host: str, port: int, timeout: float):
        calls.append((host, port, timeout))
        latency = latency_by_port.get(port, float(port % 7 + 5))
        return SimpleNamespace(
            latency_ms=latency,
            dns_resolution_ms=0.0,
            tcp_connect_ms=latency,
            close=lambda: None,
        )

    return connect


def _open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    readiness_override=None,
    managed_factory_override=None,
    writer_fence_override=None,
    td_trading_readiness_check=None,
    lifecycle_events: list[str] | None = None,
    market_stop_fails: bool = False,
    sink_capture: list | None = None,
):
    runtime_dir, registry, policy = _runtime(tmp_path)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        managed_runtime._execution,
        "_prepare_state_root",
        lambda: tmp_path / "private-state",
    )
    connector_calls = []
    factory_calls = []
    client = SimpleNamespace(stop_calls=0)

    def stop():
        client.stop_calls += 1
        if lifecycle_events is not None:
            lifecycle_events.append("td-stop")

    client.stop = stop
    _install_stop_receipt(client)
    market_client = SimpleNamespace(stop_calls=0)
    market_client.is_ready = False
    market_client.active_md_identity = None

    def stop_market_client():
        market_client.stop_calls += 1
        if lifecycle_events is not None:
            lifecycle_events.append("md-stop")
        if market_stop_fails:
            raise RuntimeError("redacted fake MD stop failure")

    market_client.stop = stop_market_client
    _install_stop_receipt(market_client)
    market_client.connection_generation = 0

    def native_client_factory(*_args, **_kwargs):
        factory_calls.append("native-client")
        return client

    ports = []

    def create_port(current_effective, current_registry, registration, **kwargs):
        assert current_effective is effective
        assert current_registry is registry
        assert registration.config_digest == effective.config.config_digest
        assert registration.md_front in tuple(pair[0] for pair in PAIRS)
        assert registration.td_front in tuple(pair[1] for pair in PAIRS)
        factory_calls.append(("managed-port", registration, registration.config_digest))
        raw_client = kwargs["trader_client_factory"](
            registration.td_front, BROKER_ID, USER_ID, "offline", md_front=registration.md_front
        )
        _install_td_query_surface(raw_client, registration)
        port = _FakePort(registration, raw_client)
        ports.append(port)
        return port

    monkeypatch.setattr(
        managed_runtime,
        "create_sealed_ctp_simnow_managed_port",
        managed_factory_override or create_port,
    )
    fence = writer_fence_override or _WriterFence()
    authority = _Verifier()

    def readiness(
        port,
        selection,
        trader_client,
        *,
        market_client_sink,
        failure_cleanup,
    ):
        # The readiness adapter receives the exact client created after the
        # artifact-first factory, without unwrapping a private port attribute.
        assert trader_client is client
        assert getattr(port, "client", trader_client) is trader_client
        assert callable(failure_cleanup)
        if sink_capture is not None:
            sink_capture.append(market_client_sink)
        market_client_sink(market_client)
        if readiness_override is not None:
            return readiness_override(port, selection)
        assert port.registration is selection.execution_registration
        evidence = managed_runtime.CtpSimNowNativeReadiness(
            config_digest=selection.config_digest,
            registration_digest=selection.execution_registration.digest,
            account_fingerprint_sha256=(
                selection.execution_registration.account_fingerprint_sha256
            ),
            md_front=selection.execution_registration.md_front,
            td_front=selection.execution_registration.td_front,
            td_ready=True,
            md_ready=True,
        )
        assert evidence.td_trading_ready is False
        assert evidence.order_submission_authorized is False
        return evidence

    runtime = managed_runtime.open_ctp_simnow_managed_runtime(
        effective,
        registry,
        policy,
        execution_capability=object(),
        runtime_admission_check=lambda: True,
        runtime_order_binding=lambda *_: {},
        runtime_credential_binding_factory=lambda **_: object(),
        approval_verifier=authority,
        sdk_approval_rechecker=lambda *_: True,
        query_evidence_verifier=authority,
        writer_fence=fence,
        native_client_factory=native_client_factory,
        native_readiness_check=readiness,
        td_trading_readiness_check=td_trading_readiness_check,
        connector=_connector(connector_calls),
        repeated_samples=1,
    )
    return runtime, effective, connector_calls, factory_calls, ports, client, market_client, fence


def _install_td_query_surface(client: Any, registration: Any) -> None:
    """Expose the same public identity/query shape consumed by the adapter."""

    account_fingerprint = hashlib.sha256(f"{BROKER_ID}:{USER_ID}".encode("utf-8")).hexdigest()[:16]
    state = {
        "account_fingerprint": account_fingerprint,
        "connected": True,
        "auth_state": "authenticated",
        "login_state": "logged_in",
        "settlement_state": "not_requested",
        "read_only_ready": True,
        "trading_ready": False,
        "auto_settlement_confirm": False,
        "connection_generation": 1,
        "trading_day": "20260924",
        "settlement_connection_generation": None,
        "settlement_account_fingerprint": None,
        "settlement_trading_day": None,
        "settlement_proof_source": "none",
        "settlement_proof_query_request_id": None,
        "settlement_readback_verified": False,
        "execution_gate_armed": False,
        "last_error": {},
    }
    counts = dict.fromkeys(
        (
            "authenticate",
            "login",
            "settlement_confirm",
            "order_insert",
            "order_action",
            "query_account",
            "query_positions",
            "query_orders",
            "query_trades",
            "query_instruments",
            "query_margin_rate",
            "query_commission_rate",
            "query_depth_market_data",
            "query_option_trade_cost",
            "query_option_commission_rate",
            "query_settlement_confirmation",
        ),
        0,
    )
    counts["authenticate"] = 1
    counts["login"] = 1
    client.td_state = state
    client.td_request_counts = counts
    client.td_trading_day = "20260924"
    client.td_settlement_confirm_date = "20260923"

    client.get_session_state = lambda: dict(client.td_state)
    client.get_front_binding_state = lambda: {
        "configured_front": registration.td_front,
        "registered_front": registration.td_front,
        "connection_confirmed_front": registration.td_front,
        "connected": True,
        "connection_generation": 1,
        "native_api_current": True,
        "bound_identity_current": True,
    }
    client.get_query_session_scope = lambda: SimpleNamespace(
        read_only_ready=True,
        connection_generation=1,
        trading_day=client.td_trading_day,
        broker_id=BROKER_ID,
        investor_id=USER_ID,
        account_fingerprint=account_fingerprint,
    )
    client.get_request_counts = lambda: dict(client.td_request_counts)

    def verify_settlement_confirmation(*, timeout: float):
        client.td_query_timeout = timeout
        client.td_request_counts["query_settlement_confirmation"] += 1
        client.td_state.update(
            {
                "settlement_state": "confirmed",
                "trading_ready": True,
                "settlement_connection_generation": 1,
                "settlement_account_fingerprint": account_fingerprint,
                "settlement_trading_day": client.td_trading_day,
                "settlement_proof_source": "confirmation_query",
                "settlement_proof_query_request_id": 73,
                "settlement_readback_verified": True,
            }
        )
        return SimpleNamespace(
            request_type="settlement_confirmation",
            request_id=73,
            connection_generation=1,
            account_fingerprint=account_fingerprint,
            is_last_seen=True,
            error_code=0,
            timed_out=False,
            complete=True,
            late_callback_count=0,
            unsupported=False,
            submit_code=0,
            records=(
                {
                    "BrokerID": BROKER_ID,
                    "InvestorID": USER_ID,
                    "AccountID": "offline-account",
                    "ConfirmDate": client.td_settlement_confirm_date,
                    "SettlementID": 73,
                },
            ),
        )

    client.verify_settlement_confirmation = verify_settlement_confirmation


def test_composition_preserves_one_selected_scope_through_client_and_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, effective, connector_calls, factory_calls, ports, client, market_client, fence = _open(
        tmp_path, monkeypatch
    )
    try:
        selected = runtime.selection
        registration = selected.execution_registration
        assert registration is runtime.session.registration
        assert (
            registration.config_digest == selected.config_digest == effective.config.config_digest
        )
        assert registration.front_pair_set_sha256 == selected.front_pair_set_sha256
        assert registration.md_front == selected.front_pair_selection.pair.md_front
        assert registration.td_front == selected.front_pair_selection.pair.td_front
        assert factory_calls[0][0] == "managed-port"
        assert factory_calls[0][1] is registration
        assert factory_calls[0][2] == selected.config_digest
        assert ports[0].registration is registration
        assert runtime.td_trading_readiness is None
        assert len(connector_calls) == len(PAIRS) * 2
        assert fence.calls >= 2
    finally:
        runtime.close()
    runtime.close()
    assert ports[0].close_calls == 1
    assert client.stop_calls == 1
    assert market_client.stop_calls == 1


def test_optional_td_readiness_refuses_unbound_confirmation_before_execution_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    with pytest.raises(managed_runtime.CtpSimulationExecutionError):
        _open(
            tmp_path,
            monkeypatch,
            td_trading_readiness_check=verify_ctp_simnow_td_trading_readiness,
            lifecycle_events=events,
        )

    assert events == ["md-stop", "td-stop"]


def test_failed_md_td_readiness_closes_client_and_never_reselects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, policy = _runtime(tmp_path)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        managed_runtime._execution,
        "_prepare_state_root",
        lambda: tmp_path / "private-state",
    )
    connector_calls = []
    created_clients = []
    ports = []

    class Client:
        def __init__(self):
            self.stop_calls = 0
            self.connection_generation = 1

        def stop(self):
            self.stop_calls += 1

        def stop_and_wait(self, *, timeout):
            assert timeout > 0
            self.stop()
            return _FakeNativeStopReceipt(self.connection_generation)

    def native_factory(*_args, **_kwargs):
        client = Client()
        created_clients.append(client)
        return client

    def create_port(_effective, _registry, registration, **kwargs):
        client = kwargs["trader_client_factory"]()
        port = _FakePort(registration, client)
        ports.append(port)
        return port

    monkeypatch.setattr(managed_runtime, "create_sealed_ctp_simnow_managed_port", create_port)
    authority = _Verifier()
    market_client = SimpleNamespace(stop_calls=0)
    market_client.is_ready = False
    market_client.active_md_identity = None
    market_client.stop = lambda: setattr(
        market_client, "stop_calls", market_client.stop_calls + 1
    )
    _install_stop_receipt(market_client)
    market_client.connection_generation = 0
    callback_calls = []

    def readiness_failure(
        _port,
        _selection,
        _trader,
        *,
        market_client_sink,
        failure_cleanup,
    ):
        callback_calls.append("called")
        assert callable(failure_cleanup)
        market_client_sink(market_client)
        return False

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as rejected:
        managed_runtime.open_ctp_simnow_managed_runtime(
            effective,
            registry,
            policy,
            execution_capability=object(),
            runtime_admission_check=lambda: True,
            runtime_order_binding=lambda *_: {},
            runtime_credential_binding_factory=lambda **_: object(),
            approval_verifier=authority,
            sdk_approval_rechecker=lambda *_: True,
            query_evidence_verifier=authority,
            writer_fence=_WriterFence(),
            native_client_factory=native_factory,
            native_readiness_check=readiness_failure,
            connector=_connector(connector_calls),
            repeated_samples=1,
        )
    assert rejected.value.reason == "native_session_identity_unavailable"
    assert len(connector_calls) == len(PAIRS) * 2
    assert len(created_clients) == 1
    assert ports[0].close_calls == 1
    assert created_clients[0].stop_calls == 1
    assert market_client.stop_calls == 1
    assert callback_calls == ["called"]


def test_managed_open_rejects_legacy_readiness_without_ownership_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, policy = _runtime(tmp_path)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        managed_runtime._execution,
        "_prepare_state_root",
        lambda: tmp_path / "private-state",
    )
    callback_calls: list[str] = []
    connector_calls: list[Any] = []
    created_clients: list[Any] = []
    ports: list[Any] = []

    def native_client_factory(*_args, **_kwargs):
        client = SimpleNamespace(stop_calls=0)
        client.stop = lambda: setattr(client, "stop_calls", client.stop_calls + 1)
        _install_stop_receipt(client)
        created_clients.append(client)
        return client

    def create_port(_effective, _registry, registration, **kwargs):
        client = kwargs["trader_client_factory"]()
        port = _FakePort(registration, client)
        ports.append(port)
        return port

    monkeypatch.setattr(managed_runtime, "create_sealed_ctp_simnow_managed_port", create_port)

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as rejected:
        managed_runtime.open_ctp_simnow_managed_runtime(
            effective,
            registry,
            policy,
            execution_capability=object(),
            runtime_admission_check=lambda: True,
            runtime_order_binding=lambda *_: {},
            runtime_credential_binding_factory=lambda **_: object(),
            approval_verifier=_Verifier(),
            sdk_approval_rechecker=lambda *_: True,
            query_evidence_verifier=_Verifier(),
            writer_fence=_WriterFence(),
            native_client_factory=native_client_factory,
            native_readiness_check=lambda *_args: callback_calls.append("called"),
            connector=_connector(connector_calls),
            repeated_samples=1,
        )

    assert rejected.value.reason == "native_session_identity_unavailable"
    assert callback_calls == []
    assert created_clients[0].stop_calls == 1
    assert ports[0].close_calls == 1
    assert len(connector_calls) == len(PAIRS) * 2


def test_market_client_sink_is_sealed_after_readiness_and_rejects_late_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink_capture: list[Any] = []
    runtime, _effective, _connectors, _factories, _ports, _td, _md, _fence = _open(
        tmp_path,
        monkeypatch,
        sink_capture=sink_capture,
    )
    runtime.close()
    assert len(sink_capture) == 1

    late_client = SimpleNamespace(start_calls=0)
    late_client.start = lambda: setattr(late_client, "start_calls", late_client.start_calls + 1)

    def handoff_then_start() -> None:
        sink_capture[0](late_client)
        late_client.start()

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as rejected:
        handoff_then_start()

    assert rejected.value.reason == "managed_simnow_md_client_registration_closed"
    assert late_client.start_calls == 0


def test_late_registration_while_owner_is_open_poisons_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink_capture: list[Any] = []
    runtime, _effective, _connectors, _factories, ports, trader, md, _fence = _open(
        tmp_path,
        monkeypatch,
        sink_capture=sink_capture,
    )
    resources = sink_capture[0].__self__
    registration = runtime.session.registration
    late_client = SimpleNamespace(start_calls=0)
    late_client.start = lambda: setattr(late_client, "start_calls", late_client.start_calls + 1)

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as late:
        sink_capture[0](late_client)
    assert late.value.reason == "managed_simnow_md_client_registration_closed"
    assert resources._close_failed is True
    assert late_client.start_calls == 0

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as rejected:
        runtime.close()
    assert rejected.value.reason == "execution_close_failed"
    assert md.stop_calls == trader.stop_calls == ports[0].close_calls == 1

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as poisoned:
        runtime.close()
    assert poisoned.value.reason == "session_poisoned"
    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as owned:
        managed_runtime._execution.CtpAccountFlowLease(
            registration.account_fingerprint_sha256,
            tmp_path / "private-state" / "flow-locks",
        ).acquire()
    assert owned.value.reason == "account_flow_already_owned"


def test_readiness_failure_uses_shared_md_and_td_close_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, policy = _runtime(tmp_path)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        managed_runtime._execution,
        "_prepare_state_root",
        lambda: tmp_path / "private-state",
    )
    md = SimpleNamespace(stop_calls=0)
    md.is_ready = False
    md.active_md_identity = None
    md.stop = lambda: setattr(md, "stop_calls", md.stop_calls + 1)
    _install_stop_receipt(md)
    md.connection_generation = 0
    trader = SimpleNamespace(stop_calls=0)
    trader.stop = lambda: setattr(trader, "stop_calls", trader.stop_calls + 1)
    _install_stop_receipt(trader)
    port_instances = []

    def create_port(_effective, _registry, registration, **kwargs):
        trader = kwargs["trader_client_factory"]()
        port = _FakePort(registration, trader)
        port_instances.append(port)
        return port

    monkeypatch.setattr(managed_runtime, "create_sealed_ctp_simnow_managed_port", create_port)
    authority = _Verifier()

    def fail_readiness(
        _port,
        _selection,
        _trader,
        *,
        market_client_sink,
        failure_cleanup,
    ):
        market_client_sink(md)
        failure_cleanup()
        raise managed_runtime.CtpSimulationExecutionError("native_readiness_failed")

    with pytest.raises(managed_runtime.CtpSimulationExecutionError):
        managed_runtime.open_ctp_simnow_managed_runtime(
            effective,
            registry,
            policy,
            execution_capability=object(),
            runtime_admission_check=lambda: True,
            runtime_order_binding=lambda *_: {},
            runtime_credential_binding_factory=lambda **_: object(),
            approval_verifier=authority,
            sdk_approval_rechecker=lambda *_: True,
            query_evidence_verifier=authority,
            writer_fence=_WriterFence(),
            native_client_factory=lambda *_args, **_kwargs: trader,
            native_readiness_check=fail_readiness,
            connector=_connector([]),
            repeated_samples=1,
        )

    assert md.stop_calls == 1
    assert trader.stop_calls == 1
    assert len(port_instances) == 1
    assert port_instances[0].close_calls == 1
    assert port_instances[0].client is not None


def test_late_execution_open_failure_closes_md_before_releasing_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, policy = _runtime(tmp_path)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        managed_runtime._execution,
        "_prepare_state_root",
        lambda: tmp_path / "private-state",
    )
    trader = SimpleNamespace(stop_calls=0)
    trader.stop = lambda: setattr(trader, "stop_calls", trader.stop_calls + 1)
    _install_stop_receipt(trader)
    md = SimpleNamespace(stop_calls=0)
    md.is_ready = False
    md.active_md_identity = None
    md.stop = lambda: setattr(md, "stop_calls", md.stop_calls + 1)
    _install_stop_receipt(md)
    md.connection_generation = 0
    ports = []

    def create_port(_effective, _registry, registration, **kwargs):
        raw = kwargs["trader_client_factory"]()
        port = _FakePort(registration, raw)
        ports.append(port)
        return port

    monkeypatch.setattr(managed_runtime, "create_sealed_ctp_simnow_managed_port", create_port)
    authority = _Verifier()

    class FailAfterNativeReadiness(_WriterFence):
        def assert_active(self):
            super().assert_active()
            if self.calls == 3:
                raise RuntimeError("fake post-start fence loss")

    def native_factory(*_args, **_kwargs):
        return trader

    def readiness(
        _port,
        selection,
        actual_trader,
        *,
        market_client_sink,
        failure_cleanup,
    ):
        assert actual_trader is trader
        market_client_sink(md)
        return managed_runtime.CtpSimNowNativeReadiness(
            config_digest=selection.config_digest,
            registration_digest=selection.execution_registration.digest,
            account_fingerprint_sha256=(
                selection.execution_registration.account_fingerprint_sha256
            ),
            md_front=selection.execution_registration.md_front,
            td_front=selection.execution_registration.td_front,
            td_ready=True,
            md_ready=True,
        )

    with pytest.raises(managed_runtime.CtpSimulationExecutionError):
        managed_runtime.open_ctp_simnow_managed_runtime(
            effective,
            registry,
            policy,
            execution_capability=object(),
            runtime_admission_check=lambda: True,
            runtime_order_binding=lambda *_: {},
            runtime_credential_binding_factory=lambda **_: object(),
            approval_verifier=authority,
            sdk_approval_rechecker=lambda *_: True,
            query_evidence_verifier=authority,
            writer_fence=FailAfterNativeReadiness(),
            native_client_factory=native_factory,
            native_readiness_check=readiness,
            connector=_connector([]),
            repeated_samples=1,
        )

    assert md.stop_calls == trader.stop_calls == 1
    assert ports[0].close_calls == 1
    registration = ports[0].registration
    with managed_runtime._execution.CtpAccountFlowLease(
        registration.account_fingerprint_sha256,
        tmp_path / "private-state" / "flow-locks",
    ):
        pass


def test_md_stop_failure_poisons_session_and_retains_account_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _effective, _connectors, _factories, ports, trader, md, _fence = _open(
        tmp_path,
        monkeypatch,
        market_stop_fails=True,
    )
    registration = runtime.session.registration
    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as rejected:
        runtime.close()
    assert rejected.value.reason == "execution_close_failed"
    assert md.stop_calls == trader.stop_calls == ports[0].close_calls == 1

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as poisoned:
        runtime.close()
    assert poisoned.value.reason == "session_poisoned"
    assert md.stop_calls == trader.stop_calls == ports[0].close_calls == 1

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as owned:
        managed_runtime._execution.CtpAccountFlowLease(
            registration.account_fingerprint_sha256,
            tmp_path / "private-state" / "flow-locks",
        ).acquire()
    assert owned.value.reason == "account_flow_already_owned"


def test_pending_md_join_poisons_session_and_does_not_retry_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, _effective, _connectors, _factories, ports, trader, md, _fence = _open(
        tmp_path, monkeypatch
    )

    def pending_stop(*, timeout: float) -> _FakeNativeStopReceipt:
        assert timeout > 0
        md.stop_calls += 1
        return _FakeNativeStopReceipt(
            connection_generation=md.connection_generation,
            join_required=True,
            join_completed=False,
            native_released=False,
            thread_alive=True,
            timed_out=True,
        )

    md.stop_and_wait = pending_stop
    registration = runtime.session.registration

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as rejected:
        runtime.close()
    assert rejected.value.reason == "execution_close_failed"
    assert md.stop_calls == trader.stop_calls == ports[0].close_calls == 1

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as poisoned:
        runtime.close()
    assert poisoned.value.reason == "session_poisoned"
    assert md.stop_calls == trader.stop_calls == ports[0].close_calls == 1

    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as owned:
        managed_runtime._execution.CtpAccountFlowLease(
            registration.account_fingerprint_sha256,
            tmp_path / "private-state" / "flow-locks",
        ).acquire()
    assert owned.value.reason == "account_flow_already_owned"


def test_artifact_first_failure_does_not_construct_native_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, policy = _runtime(tmp_path)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        managed_runtime._execution,
        "_prepare_state_root",
        lambda: tmp_path / "private-state",
    )
    connector_calls = []
    native_calls = []

    def fail_artifact_gate(*_args, **_kwargs):
        raise managed_runtime.CtpSimulationExecutionError(
            "managed_simnow_artifact_provenance_rejected"
        )

    monkeypatch.setattr(
        managed_runtime, "create_sealed_ctp_simnow_managed_port", fail_artifact_gate
    )
    authority = _Verifier()
    with pytest.raises(managed_runtime.CtpSimulationExecutionError) as rejected:
        managed_runtime.open_ctp_simnow_managed_runtime(
            effective,
            registry,
            policy,
            execution_capability=object(),
            runtime_admission_check=lambda: True,
            runtime_order_binding=lambda *_: {},
            runtime_credential_binding_factory=lambda **_: object(),
            approval_verifier=authority,
            sdk_approval_rechecker=lambda *_: True,
            query_evidence_verifier=authority,
            writer_fence=_WriterFence(),
            native_client_factory=lambda *_args, **_kwargs: native_calls.append("called"),
            native_readiness_check=lambda *_: None,
            connector=_connector(connector_calls),
            repeated_samples=1,
        )
    assert rejected.value.reason == "native_session_identity_unavailable"
    assert len(connector_calls) == len(PAIRS) * 2
    assert native_calls == []


def test_partial_native_construction_failure_closes_client_under_owned_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, policy = _runtime(tmp_path)
    effective = validate_runtime_config(runtime_dir, registry)
    monkeypatch.setattr(
        managed_runtime._execution,
        "_prepare_state_root",
        lambda: tmp_path / "private-state",
    )
    connector_calls = []
    clients = []

    class Client:
        def __init__(self):
            self.stop_calls = 0
            self.connection_generation = 1

        def stop(self):
            self.stop_calls += 1

        def stop_and_wait(self, *, timeout):
            assert timeout > 0
            self.stop()
            return _FakeNativeStopReceipt(self.connection_generation)

    def native_factory(*_args, **_kwargs):
        client = Client()
        clients.append(client)
        return client

    def partial_port_creation(_effective, _registry, _registration, **kwargs):
        kwargs["trader_client_factory"]()
        raise managed_runtime.CtpSimulationExecutionError("managed_port_creation_failed")

    monkeypatch.setattr(
        managed_runtime,
        "create_sealed_ctp_simnow_managed_port",
        partial_port_creation,
    )
    authority = _Verifier()
    with pytest.raises(managed_runtime.CtpSimulationExecutionError):
        managed_runtime.open_ctp_simnow_managed_runtime(
            effective,
            registry,
            policy,
            execution_capability=object(),
            runtime_admission_check=lambda: True,
            runtime_order_binding=lambda *_: {},
            runtime_credential_binding_factory=lambda **_: object(),
            approval_verifier=authority,
            sdk_approval_rechecker=lambda *_: True,
            query_evidence_verifier=authority,
            writer_fence=_WriterFence(),
            native_client_factory=native_factory,
            native_readiness_check=lambda *_: None,
            connector=_connector(connector_calls),
            repeated_samples=1,
        )
    assert len(clients) == 1
    assert clients[0].stop_calls == 1
    assert len(connector_calls) == len(PAIRS) * 2


def test_missing_authority_rejects_before_any_front_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime_dir, registry, policy = _runtime(tmp_path)
    effective = validate_runtime_config(runtime_dir, registry)
    calls = []
    authority = _Verifier()
    with pytest.raises(managed_runtime.CtpSimulationExecutionError):
        managed_runtime.open_ctp_simnow_managed_runtime(
            effective,
            registry,
            policy,
            execution_capability=None,
            runtime_admission_check=lambda: True,
            runtime_order_binding=lambda *_: {},
            runtime_credential_binding_factory=lambda **_: object(),
            approval_verifier=authority,
            sdk_approval_rechecker=lambda *_: True,
            query_evidence_verifier=authority,
            writer_fence=_WriterFence(),
            native_client_factory=lambda *_args, **_kwargs: None,
            native_readiness_check=lambda *_: None,
            connector=_connector(calls),
        )
    assert calls == []
