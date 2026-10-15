"""Focused lifecycle tests for the explicit execution-session owner."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from bt_api_base.service_protocol import (
    WireEnvelope,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
)
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_registry import (
    PrincipalGrant,
    ResourceGrant,
    ServiceCapability,
    ServiceRegistry,
)
from bt_api_py.service_runtime import ServiceClientRuntime, ServiceRuntimeError

from backtrader import Cerebro, Strategy
from backtrader.stores.service_execution_adapter import ServiceExecutionReadError
from backtrader.stores.service_execution_session import (
    ServiceExecutionSession,
    ServiceExecutionSessionCleanupError,
    ServiceExecutionSessionConfigError,
    ServiceExecutionSessionError,
    run_configured_cerebro,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store


_CLIENT = WireIdentity(WireRole.STRATEGY_CLIENT, "strategy-principal", "strategy-a")
_PEER = WireIdentity(WireRole.SERVICE, "execution-principal", "execution-service")
_SERVICE_ID = "execution-service"
_INSTANCE_ID = "execution-a"
_WRITER_OPERATIONS = frozenset({"orders.submit", "orders.cancel"})
_QUERY_OPERATIONS = frozenset({"orders.query"})


class _RegistryTransport:
    """In-process wire transport that exercises the SDK's real registry."""

    def __init__(self, registry: ServiceRegistry) -> None:
        self.registry = registry
        self.requests = []
        self.closed = False

    def request(self, request, *, timeout):
        del timeout
        self.requests.append(request)
        payload = self.registry.handle(_CLIENT.principal_ref, request)
        return WireEnvelope(
            replace(
                request.header,
                kind=WireMessageKind.REPLY,
                message_id=f"reply-{request.header.message_id}",
                correlation_id=request.header.message_id,
                identity=_PEER,
            ),
            payload,
        )

    def close(self) -> None:
        self.closed = True


class _CountingApi(FakeBtApiClient):
    def __init__(self) -> None:
        super().__init__()
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.required_runtime = None

    def connect(self) -> None:
        self.connect_calls += 1
        if self.required_runtime is not None:
            assert self.required_runtime.state == "registered"
        super().connect()

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        super().disconnect()


@pytest.fixture
def runtime_builder(tmp_path, request):
    """Create a real runtime with a local registry and no network transport."""

    created = 0

    def build(*, query_required=True, query_account="account-a", monotonic_clock=None):
        nonlocal created
        created += 1
        scopes = {
            "orders-scope": WireScope(
                "paper:sim", account_ref="account-a", strategy_ref="strategy-a"
            ),
            "query-scope": WireScope(
                "paper:sim", account_ref=query_account, strategy_ref="strategy-a"
            ),
        }
        raw_config = {
            "client_config_schema_version": 1,
            "process_role": "strategy_client",
            "registration": {"strategy_ref": "strategy-a"},
            "clients": {
                "execution": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "broker.orders",
                                "service_id": _SERVICE_ID,
                                "instance_id": _INSTANCE_ID,
                                "scope_ref": "orders-scope",
                                "account_ref": "account-a",
                                "transport_ref": "execution-rpc",
                            },
                            {
                                "mount": "broker.order_query",
                                "service_id": _SERVICE_ID,
                                "instance_id": _INSTANCE_ID,
                                "scope_ref": "query-scope",
                                "account_ref": query_account,
                                "transport_ref": "execution-rpc",
                                "required": query_required,
                            },
                        ],
                        "options": {"request_timeout_ms": 500},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "execution-rpc": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": "tcp://127.0.0.1:7601"},
                        "security_profile_ref": "local-test-keys",
                    }
                },
            },
        }
        registry = ServiceRegistry(
            tmp_path / f"session-registry-{created}.sqlite3",
            service_id=_SERVICE_ID,
            capabilities=(
                ServiceCapability(_INSTANCE_ID, "service.order_entry", _WRITER_OPERATIONS),
                ServiceCapability(_INSTANCE_ID, "service.order_query", _QUERY_OPERATIONS),
            ),
            grants={
                _CLIENT.principal_ref: (
                    PrincipalGrant(
                        _CLIENT,
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                "orders-scope",
                                scopes["orders-scope"],
                                _WRITER_OPERATIONS,
                            ),
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                "query-scope",
                                scopes["query-scope"],
                                _QUERY_OPERATIONS,
                            ),
                        ),
                    ),
                )
            },
            policy_version="access-v1",
            requirements_version="ready-v1",
            lease_seconds=30,
        )
        transports = []

        def transport_factory(_profile, _peer):
            transport = _RegistryTransport(registry)
            transports.append(transport)
            return transport

        runtime_kwargs = {}
        if monotonic_clock is not None:
            runtime_kwargs["monotonic_clock"] = monotonic_clock
        runtime = ServiceClientRuntime(
            parse_client_config(raw_config),
            identity=_CLIENT,
            scope_resolver=scopes.__getitem__,
            peer_resolver=lambda _service_id: _PEER,
            transport_factory=transport_factory,
            run_id="run-one",
            requested_operations={
                "broker.orders": _WRITER_OPERATIONS,
                "broker.order_query": _QUERY_OPERATIONS,
            },
            **runtime_kwargs,
        )
        # Finalizers run last-in-first-out, so close the runtime before its server.
        request.addfinalizer(registry.close)
        request.addfinalizer(runtime.close)
        return runtime, registry, transports

    return build


def _broker_bundle(*, api=None, include_data=False):
    api = api or _CountingApi()
    store = make_store(api=api, provider="btapi", autostart=False)
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        flatten_on_stop=False,
        account_refresh_interval=3600.0,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    cerebro = Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    if include_data:
        # The test replaces run() with a controlled lifecycle body.
        cerebro.datas.append(object())
    return cerebro, broker, store, api


def _session(runtime, *, clock=lambda: 0.0, **kwargs):
    return ServiceExecutionSession(
        runtime,
        mount="broker.orders",
        scope_ref="orders-scope",
        query_mount="broker.order_query",
        query_scope_ref="query-scope",
        monotonic_clock=clock,
        **kwargs,
    )


def _raw_client_config(*, query_required=True):
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": "strategy-a"},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "broker.orders",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": "orders-scope",
                            "account_ref": "account-a",
                            "transport_ref": "execution-rpc",
                        },
                        {
                            "mount": "broker.order_query",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": "query-scope",
                            "account_ref": "account-a",
                            "transport_ref": "execution-rpc",
                            "required": query_required,
                        },
                    ],
                    "options": {"request_timeout_ms": 500},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "execution-rpc": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": "tcp://127.0.0.1:7601"},
                    "security_profile_ref": "local-test-keys",
                }
            },
        },
    }


def test_run_configured_cerebro_builds_session_from_supported_sdk_routes(monkeypatch):
    import backtrader.stores.service_execution_session as session_module

    runtime = object()
    sentinel = object()
    captured = {}

    class _Session:
        def __init__(self, actual_runtime, **kwargs):
            captured["runtime"] = actual_runtime
            captured["session_kwargs"] = kwargs

        def run(self, cerebro, **kwargs):
            captured["cerebro"] = cerebro
            captured["run_kwargs"] = kwargs
            return sentinel

    monkeypatch.setattr(session_module, "ServiceExecutionSession", _Session)
    cerebro = object()
    parsed_configs = []

    def runtime_factory(parsed):
        parsed_configs.append(parsed)
        return runtime

    result = run_configured_cerebro(
        cerebro,
        _raw_client_config(),
        runtime_factory=runtime_factory,
        session_options={"limit": 8},
        runonce=False,
    )

    assert result is sentinel
    assert len(parsed_configs) == 1
    assert parsed_configs[0].process_role == "strategy_client"
    assert captured["runtime"] is runtime
    assert captured["session_kwargs"] == {
        "mount": "broker.orders",
        "scope_ref": "orders-scope",
        "query_mount": "broker.order_query",
        "query_scope_ref": "query-scope",
        "limit": 8,
    }
    assert captured["cerebro"] is cerebro
    assert captured["run_kwargs"] == {"runonce": False}


def test_run_configured_cerebro_preserves_direct_path_when_config_is_absent():
    calls = []

    class _Cerebro:
        def run(self, **kwargs):
            calls.append(kwargs)
            return ["ordinary-result"]

    result = run_configured_cerebro(_Cerebro(), runonce=False, preload=False)

    assert result == ["ordinary-result"]
    assert calls == [{"runonce": False, "preload": False}]


def test_run_configured_cerebro_rejects_optional_query_without_runtime_creation():
    factory_calls = []

    with pytest.raises(ServiceExecutionSessionConfigError) as raised:
        run_configured_cerebro(
            object(),
            _raw_client_config(query_required=False),
            runtime_factory=lambda parsed: factory_calls.append(parsed),
        )

    assert raised.value.code == "EXECUTION_BINDING_NOT_REQUIRED"
    assert factory_calls == []


def test_plain_broker_lifecycle_does_not_create_or_attach_a_session():
    """The unconfigured Broker keeps its existing direct Store path."""

    cerebro, broker, store, api = _broker_bundle()
    assert broker._service_execution_session is None
    assert store.managed_execution_active is False

    broker.start()
    broker.next()
    broker.stop()

    assert broker._service_execution_session is None
    assert store.managed_execution_active is False
    assert api.connect_calls == 1
    assert api.disconnect_calls == 1
    assert api.submitted_orders == []
    assert cerebro.getbroker() is broker


def test_session_poll_maintains_runtime_during_refresh_idle_and_backoff(
    runtime_builder, monkeypatch
):
    """Lease maintenance runs on every Broker tick, even without a due refresh."""

    clock = [0.0]
    runtime, _registry, transports = runtime_builder(monotonic_clock=lambda: clock[0])
    session = _session(runtime, clock=lambda: clock[0], max_refresh_interval_seconds=4.0)
    cerebro, broker, _store, api = _broker_bundle(include_data=True)
    api.required_runtime = runtime
    maintain = runtime.maintain
    maintenance_calls = []

    def observed_maintain():
        maintenance_calls.append(True)
        return maintain()

    monkeypatch.setattr(runtime, "maintain", observed_maintain)
    refresh = broker.refresh_managed_orders
    refresh_calls = []

    def fail_second_refresh(*, limit):
        refresh_calls.append(limit)
        if len(refresh_calls) == 2:
            raise ServiceExecutionReadError("QUERY_UNAVAILABLE")
        return refresh(limit=limit)

    monkeypatch.setattr(broker, "refresh_managed_orders", fail_second_refresh)

    def run(**_kwargs):
        broker.start()
        broker.next()  # due: success
        broker.next()  # not due: maintenance still runs
        clock[0] = 1.0
        broker.next()  # due: refresh fails and backs off
        broker.next()  # backoff window: maintenance still runs
        return broker.stop()

    monkeypatch.setattr(cerebro, "run", run)
    result = session.run(cerebro)

    assert result["shutdown_state"] == "PASS"
    assert maintenance_calls == [True, True, True, True]
    assert refresh_calls == [32, 32]
    assert session.refresh_stats.attempts == 2
    assert session.refresh_stats.failures == 1
    assert session.refresh_stats.last_error_code == "QUERY_UNAVAILABLE"
    assert session.refresh_stats.current_interval_seconds == 2.0
    operations = [request.header.operation for request in transports[0].requests]
    assert operations.count("service.renew") == 0
    assert "orders.submit" not in operations
    assert "orders.query" not in operations


def test_maintenance_failure_stops_broker_tick_and_triggers_cleanup(runtime_builder, monkeypatch):
    runtime, _registry, _transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle(include_data=True)
    api.required_runtime = runtime
    failure = ServiceRuntimeError("MAINTENANCE_FAILED")

    def fail_maintenance():
        raise failure

    monkeypatch.setattr(runtime, "maintain", fail_maintenance)
    strategy_tick = []

    def run(**_kwargs):
        broker.start()
        broker.next()
        strategy_tick.append(True)

    monkeypatch.setattr(cerebro, "run", run)
    with pytest.raises(ServiceRuntimeError) as raised:
        session.run(cerebro)

    assert raised.value is failure
    assert strategy_tick == []
    assert session.refresh_stats.attempts == 0
    assert session.state == "closed"
    assert runtime.state == "closed"
    assert store.is_connected is False
    assert api.disconnect_calls == 1


def test_preflight_rejections_do_not_start_runtime_or_store(runtime_builder):
    cases = ("channel", "optimization", "read_only", "store_owner")
    for case in cases:
        runtime, _registry, transports = runtime_builder()
        session = _session(runtime)
        api = _CountingApi()
        if case == "read_only":
            api.service_read_only = True
        cerebro, broker, store, _api = _broker_bundle(api=api, include_data=True)
        if case == "store_owner":
            store._cerebro_managed_lifecycle = False
        if case == "optimization":
            cerebro.optstrategy(Strategy)
        run_kwargs = {"channel": object()} if case == "channel" else {}

        with pytest.raises(ServiceExecutionSessionConfigError):
            session.run(cerebro, **run_kwargs)

        assert runtime.state == "new"
        assert transports == []
        assert api.connect_calls == 0
        assert store.is_connected is False
        assert store.managed_execution_active is False
        assert broker._service_execution_session is None


def test_wrong_thread_and_reused_session_fail_before_resource_acquisition(runtime_builder):
    runtime, _registry, transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle()
    errors = []

    def wrong_thread_run():
        try:
            session.run(cerebro)
        except ServiceExecutionSessionError as error:
            errors.append(error.code)

    worker = threading.Thread(target=wrong_thread_run)
    worker.start()
    worker.join()
    assert errors == ["WRONG_SESSION_THREAD"]
    assert session.state == "new"
    assert session.run(cerebro) == []
    with pytest.raises(ServiceExecutionSessionError, match="SESSION_ALREADY_USED"):
        session.run(cerebro)
    assert runtime.state == "new"
    assert transports == []
    assert api.connect_calls == 0
    assert store.managed_execution_active is False
    assert broker._service_execution_session is None


def test_registered_route_scope_error_precedes_store_connection(runtime_builder, monkeypatch):
    runtime, _registry, transports = runtime_builder(query_account="account-b")
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle(include_data=True)
    monkeypatch.setattr(
        cerebro,
        "run",
        lambda **_kwargs: pytest.fail("Cerebro ran before route validation"),
    )

    with pytest.raises(
        ServiceExecutionSessionConfigError,
        match="EXECUTION_QUERY_SCOPE_MISMATCH",
    ):
        session.run(cerebro)

    assert runtime.state == "closed"
    assert store.is_connected is False
    assert api.connect_calls == 0
    assert broker._service_execution_session is session
    assert store.managed_execution_active is True
    assert transports and transports[0].closed is True


def test_broker_stop_hook_rejects_wrong_thread_before_store_shutdown(runtime_builder, monkeypatch):
    runtime, _registry, _transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle(include_data=True)
    api.required_runtime = runtime
    errors = []

    def run(**_kwargs):
        broker.start()

        def wrong_thread_stop():
            try:
                broker.stop()
            except ServiceExecutionSessionError as error:
                errors.append(error.code)

        worker = threading.Thread(target=wrong_thread_stop)
        worker.start()
        worker.join()
        assert store.is_connected is True
        return broker.stop()

    monkeypatch.setattr(cerebro, "run", run)

    session.run(cerebro)

    assert errors == ["WRONG_SESSION_THREAD"]
    assert api.disconnect_calls == 1
    assert session.state == "closed"


@pytest.mark.parametrize(
    ("reported_key", "reported_status", "error_code"),
    [
        ("status", "INCOMPLETE", "BROKER_STOP_NOT_PASS"),
        ("shutdown_state", "FAIL", "STORE_SHUTDOWN_NOT_PASS"),
    ],
)
def test_nonpass_stop_result_is_reported_from_this_stop_call(
    runtime_builder, monkeypatch, reported_key, reported_status, error_code
):
    runtime, _registry, _transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle(include_data=True)
    api.required_runtime = runtime
    stop = broker._stop_live_resources

    def report_nonpass():
        result = stop()
        return {**result, reported_key: reported_status}

    monkeypatch.setattr(broker, "_stop_live_resources", report_nonpass)
    monkeypatch.setattr(
        cerebro,
        "run",
        lambda **_kwargs: (broker.start(), broker.stop())[1],
    )

    with pytest.raises(
        ServiceExecutionSessionCleanupError,
        match="SESSION_CLEANUP_UNCERTAIN",
    ):
        session.run(cerebro)

    assert session.state == "close_failed"
    assert error_code in session.cleanup_report.errors
    assert session.cleanup_report.broker_stop_attempted is True
    assert store.is_connected is False
    assert api.disconnect_calls == 1


def test_primary_run_error_survives_failed_stop_without_repeating_winddown(
    runtime_builder, monkeypatch
):
    runtime, _registry, _transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle(include_data=True)
    api.required_runtime = runtime
    primary = ValueError("primary-run-failure")
    stop_failure = RuntimeError("stop-failure")
    stop_calls = []

    def fail_store_stop(*_args, **_kwargs):
        stop_calls.append(True)
        raise stop_failure

    monkeypatch.setattr(store, "stop", fail_store_stop)

    def run(**_kwargs):
        broker.start()
        raise primary

    monkeypatch.setattr(cerebro, "run", run)
    with pytest.raises(ValueError) as raised:
        session.run(cerebro)

    assert raised.value is primary
    assert stop_calls == [True]
    assert session.state == "close_failed"
    assert "BROKER_STOP_FAILED" in session.cleanup_report.errors
    assert "STORE_STILL_CONNECTED" in session.cleanup_report.errors
    assert session.cleanup_report.runtime_close_attempted is True
    assert runtime.state == "closed"
    assert store.is_connected is True
    assert api.disconnect_calls == 0


def test_fallback_stop_nonpass_result_is_merged_into_cleanup_report(runtime_builder, monkeypatch):
    runtime, _registry, _transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle(include_data=True)
    api.required_runtime = runtime
    stop = broker._stop_live_resources

    def incomplete_stop():
        result = stop()
        return {**result, "status": "INCOMPLETE"}

    monkeypatch.setattr(broker, "_stop_live_resources", incomplete_stop)
    monkeypatch.setattr(cerebro, "run", lambda **_kwargs: (broker.start(), "strategy-result")[1])

    with pytest.raises(ServiceExecutionSessionCleanupError):
        session.run(cerebro)

    assert session.state == "close_failed"
    assert "BROKER_STOP_NOT_PASS" in session.cleanup_report.errors
    assert session.cleanup_report.broker_stop_attempted is True
    assert store.is_connected is False
    assert api.disconnect_calls == 1


def test_unstarted_broker_none_stop_result_does_not_use_default_summary(
    runtime_builder, monkeypatch
):
    runtime, _registry, _transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, _api = _broker_bundle(include_data=True)
    monkeypatch.setattr(cerebro, "run", lambda **_kwargs: broker.stop())

    assert session.run(cerebro) is None
    assert session.state == "closed"
    assert session.cleanup_report.errors == ()
    assert store.is_connected is False


def test_broker_cannot_reconnect_after_its_session_has_ended(runtime_builder, monkeypatch):
    runtime, _registry, _transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle(include_data=True)
    api.required_runtime = runtime
    monkeypatch.setattr(cerebro, "run", lambda **_kwargs: (broker.start(), broker.stop())[1])

    session.run(cerebro)
    connect_calls = api.connect_calls
    assert session.state == "closed"
    assert runtime.state == "closed"
    assert store.is_connected is False

    with pytest.raises(ServiceExecutionSessionError, match="SESSION_NOT_ACTIVE"):
        broker.start()

    assert api.connect_calls == connect_calls
    assert store.is_connected is False


@pytest.mark.parametrize(
    ("stop_status", "expected_state"),
    [(None, "closed_with_uncertainty"), ("INCOMPLETE", "close_failed")],
)
def test_unregister_uncertainty_remains_visible_after_session_close(
    runtime_builder, monkeypatch, stop_status, expected_state
):
    runtime, registry, transports = runtime_builder()
    session = _session(runtime)
    cerebro, broker, store, api = _broker_bundle(include_data=True)
    api.required_runtime = runtime

    class _UncertainUnregisterTransport(_RegistryTransport):
        def request(self, request, *, timeout):
            reply = super().request(request, timeout=timeout)
            if request.header.operation != "service.unregister":
                return reply
            body = dict(reply.payload)
            result = dict(body["result"])
            result["unregistered"] = False
            return WireEnvelope(reply.header, {**body, "result": result})

    def factory(_profile, _peer):
        transport = _UncertainUnregisterTransport(registry)
        transports.append(transport)
        return transport

    monkeypatch.setattr(runtime, "_factory", factory)
    if stop_status is not None:
        stop = broker._stop_live_resources

        def nonpass_stop():
            result = stop()
            return {**result, "status": stop_status}

        monkeypatch.setattr(broker, "_stop_live_resources", nonpass_stop)
    monkeypatch.setattr(cerebro, "run", lambda **_kwargs: (broker.start(), broker.stop())[1])

    with pytest.raises(ServiceExecutionSessionCleanupError):
        session.run(cerebro)

    assert runtime.state == "closed"
    assert runtime.unregister_uncertainties == 2
    assert session.state == expected_state
    assert "UNREGISTER_UNCERTAIN" in session.cleanup_report.errors
    assert session.cleanup_report.store_connected is False
    assert store.is_connected is False
    assert transports[0].closed is True
