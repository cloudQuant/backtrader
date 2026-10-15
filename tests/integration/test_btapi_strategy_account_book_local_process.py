"""Strategy-owned account-book reads through a spawned execution service.

This is a local synthetic integration test: it starts a real SDK ServiceHost
and uses the normal Backtrader Store, Broker, Strategy, and Cerebro lifecycle.
The service's account snapshots and attributed fill are deterministic test
facts; this does not exercise a broker/provider adapter or establish account
acceptance.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import multiprocessing
import socket
import time
from contextlib import suppress
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_py")
if importlib.util.find_spec("bt_api_execution") is None:
    pytest.skip("bt_api_execution package is not installed", allow_module_level=True)
zmq = pytest.importorskip("zmq")
pandas = pytest.importorskip("pandas")

import backtrader as bt  # noqa: E402
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_py.service_config import parse_client_config, parse_service_config  # noqa: E402
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority  # noqa: E402
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant  # noqa: E402
from bt_api_py.service_runtime import (  # noqa: E402
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)

from backtrader.stores.service_execution_session import (  # noqa: E402
    ServiceExecutionSession,
    ServiceExecutionSessionConfigError,
)
from backtrader.stores.service_strategy_account_book import (  # noqa: E402
    ServiceStrategyAccountBookError,
)
from tests.fixtures.fake_btapi import make_store  # noqa: E402

_DOMAIN = "paper:backtrader-account-book"
_SERVICE_ID = "bt-account-book-service"
_SERVICE_PRINCIPAL = "bt-account-book-service-principal"
_INSTANCE_ID = "bt-account-book-owner"
_SERVICE_SCOPE_REF = "bt-account-book-root-v1"
_SERVER_SECURITY_REF = "bt-account-book-server-curve-v1"
_CLIENT_SECURITY_REF = "bt-account-book-client-curve-v1"
_ACCOUNT = "account.synthetic"
_STRATEGY = "strategy.synthetic"
_PRINCIPAL = "bt-account-book-strategy-principal"
_ORDER_SCOPE_REF = "bt-account-book-orders-v1"
_QUERY_SCOPE_REF = "bt-account-book-query-v1"
_TRANSPORT_REF = "bt-account-book-connect-v1"
_LISTENER_REF = "bt-account-book-listener-v1"
_MAX_MESSAGE_BYTES = 65_536
_INSTRUMENT = "PAPER:SIM:BTC-USDT"
_WIRE_SCOPE = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY)


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _service_config(endpoint: str) -> dict:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SERVICE_SCOPE_REF,
        "transport_ref": _LISTENER_REF,
        "registration_policy_ref": "bt-account-book-registration-v1",
        "service_requirements_ref": "bt-account-book-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.order_entry", "service.order_query"],
                    "options": {"role": "account_owner"},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _LISTENER_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SERVER_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _client_config(endpoint: str) -> dict:
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _STRATEGY},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "broker.orders",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": _ORDER_SCOPE_REF,
                            "transport_ref": _TRANSPORT_REF,
                            "account_ref": _ACCOUNT,
                        },
                        {
                            "mount": "broker.order_query",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": _QUERY_SCOPE_REF,
                            "transport_ref": _TRANSPORT_REF,
                            "account_ref": _ACCOUNT,
                        },
                    ],
                    "options": {"request_timeout_ms": 2_000},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": _CLIENT_SECURITY_REF,
                    "options": {
                        "request_timeout_ms": 2_000,
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


class _NoOrderDispatch:
    """A test service that fails if the read-only scenario tries to write."""

    def submit(self, _intent):
        raise AssertionError("synthetic account-book test attempted an order write")

    def cancel(self, _intent):
        raise AssertionError("synthetic account-book test attempted a cancel write")


class _ClosedAdmissionGate:
    """Deny every write if an accidental order reaches the service."""

    def reserve(self, _intent):
        raise AssertionError("synthetic account-book test attempted order admission")

    def claim_before_dispatch(self, _intent):
        raise AssertionError("synthetic account-book test attempted cancel admission")


class _SyntheticOwnerFacts:
    """Complete provider/account facts for exactly one strategy owner."""

    def __init__(self, execution_scope):
        self._execution_scope = execution_scope
        self._baseline_ns = time.time_ns()
        self.read_count = 0
        self.last_cut = None

    def authorize_account_view(self, **_kwargs) -> bool:
        return False

    def authorize_manual_book_view(self, **_kwargs) -> bool:
        return False

    def read_inputs(self, *, account_key, journal_generation, execution_cursor):
        from bt_api_execution import (
            AllocationOwnerKind,
            CurrencyAmount,
            ExecutionAccountSnapshot,
            ExecutionAllocationBaseline,
            ExecutionOwnerScope,
            ExecutionScopeDirectory,
            ExternalActivitySnapshot,
            ExternalFillFact,
            ExternalOrderFact,
            OwnerPosition,
            PositionFact,
            Side,
        )
        from bt_api_py.service_execution_account_books import ExecutionAccountBookReadInputsV1

        if account_key != self._execution_scope.account_key:
            raise AssertionError("account-book source received an unexpected account")
        self.read_count += 1
        self.last_cut = (journal_generation, execution_cursor)
        baseline_ns = self._baseline_ns
        current_ns = max(time.time_ns(), baseline_ns + 3)
        directory_revision = "synthetic-owner-directory-r1"
        provider_generation = "synthetic-provider-generation-r1"
        owner_scope = ExecutionOwnerScope(
            self._execution_scope,
            AllocationOwnerKind.STRATEGY,
            _STRATEGY,
            _WIRE_SCOPE,
        )
        directory = ExecutionScopeDirectory(
            account_key=account_key,
            source="synthetic-trusted-owner-registry",
            source_ref="synthetic-owner-registry-r1",
            revision=directory_revision,
            covers_from_ns=baseline_ns,
            as_of_ns=current_ns,
            scopes=(owner_scope,),
        )
        baseline_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source="synthetic-net-position-snapshot",
            source_ref="synthetic-provider-baseline-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=baseline_ns,
            execution_cursor=0,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, Decimal("0.5")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0.10")),),
            fee_coverage_start_ns=baseline_ns,
        )
        allocation_baseline = ExecutionAllocationBaseline(
            account_key=account_key,
            source="synthetic-trusted-strategy-ledger",
            source_ref="synthetic-strategy-baseline-r1",
            revision="synthetic-strategy-baseline-revision-r1",
            scope_directory_revision=directory_revision,
            provider_generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=baseline_ns,
            execution_cursor=0,
            positions=(
                OwnerPosition(
                    AllocationOwnerKind.STRATEGY,
                    _STRATEGY,
                    _INSTRUMENT,
                    Decimal("0.5"),
                ),
            ),
        )
        order_ref = "synthetic-provider-order-r1"
        external_fill = ExternalFillFact(
            "synthetic-provider-fill-r1",
            _INSTRUMENT,
            Side.BUY,
            Decimal("0.5"),
            Decimal("100"),
            occurred_at_ns=baseline_ns + 1,
            owner_kind=AllocationOwnerKind.STRATEGY,
            owner_ref=_STRATEGY,
            fee=Decimal("0.04"),
            fee_currency="USDT",
            provider_order_ref=order_ref,
        )
        external_order = ExternalOrderFact(
            order_ref,
            _INSTRUMENT,
            Side.BUY,
            Decimal("0.5"),
            Decimal("0.5"),
            "FILLED",
            observed_at_ns=baseline_ns + 1,
            owner_kind=AllocationOwnerKind.STRATEGY,
            owner_ref=_STRATEGY,
        )
        activity = ExternalActivitySnapshot(
            account_key=account_key,
            source="synthetic-complete-provider-activity",
            source_ref="synthetic-activity-r1",
            generation=provider_generation,
            coverage_start_ns=baseline_ns,
            coverage_end_ns=current_ns,
            fills=(external_fill,),
            orders=(external_order,),
        )
        current_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source=baseline_snapshot.source,
            source_ref="synthetic-provider-current-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=current_ns,
            execution_cursor=execution_cursor,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, Decimal("1.0")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0.14")),),
            fee_coverage_start_ns=baseline_ns,
        )
        return ExecutionAccountBookReadInputsV1(
            directory,
            baseline_snapshot,
            current_snapshot,
            allocation_baseline,
            activity,
        )


def _host_process(control, raw_config, registry_path: str, store_path: str, keys) -> None:
    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources

    config = parse_service_config(raw_config)
    store = SqliteExecutionStore(store_path)
    execution_scope = ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY, "20261015")
    source = _SyntheticOwnerFacts(execution_scope)
    dispatch = _NoOrderDispatch()
    gate = _ClosedAdmissionGate()
    host = None
    try:
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="bt-account-book-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="bt-account-book-registration-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="bt-account-book-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={keys["client_public"]: _PRINCIPAL},
            grants={
                _PRINCIPAL: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _ORDER_SCOPE_REF,
                                _WIRE_SCOPE,
                                frozenset({"orders.submit", "orders.cancel"}),
                            ),
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_REF,
                                _WIRE_SCOPE,
                                frozenset(
                                    {"orders.query", "execution.account_books.query"}
                                ),
                            ),
                        ),
                    ),
                )
            },
        )

        def resource_provider(component, instance_id, _options, _scope):
            if component != "execution" or instance_id != _INSTANCE_ID:
                raise AssertionError("unexpected service resource request")
            return ComponentResources.borrowed(
                {
                    "store": store,
                    "targets": {_WIRE_SCOPE: execution_scope},
                    "dispatch": dispatch,
                    "admission": {"order_gate": gate, "cancel_gate": gate},
                    "account_books": source,
                },
                ready=lambda: True,
            )

        host = ServiceHost(
            config,
            authority,
            registry_path,
            resource_provider,
        )
        host.start()
        control.send(("ready", host.endpoint, host.state))
        while True:
            host.serve_once(timeout_ms=20)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("metrics",):
                control.send(("metrics", source.read_count, source.last_cut))
            elif command == ("close",):
                host.close()
                store.close()
                control.send(("closed", host.state))
                return
            else:
                raise AssertionError("unknown synthetic service-host command")
    except BaseException as error:
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(BaseException):
            store.close()
        with suppress(Exception):
            control.send(("host_error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        control.close()


def _receive(pipe, timeout: float = 15.0):
    if not pipe.poll(timeout):
        raise TimeoutError("timed out waiting for the synthetic ServiceHost")
    return pipe.recv()


def _start_host(tmp_path):
    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "client_public": client_public,
        "client_secret": client_secret,
    }
    parent_pipe, child_pipe = context.Pipe(duplex=True)
    process = context.Process(
        target=_host_process,
        args=(
            child_pipe,
            _service_config(endpoint),
            str(tmp_path / "account-book-registry.sqlite3"),
            str(tmp_path / "account-book-execution.sqlite3"),
            keys,
        ),
        name="bt-strategy-account-book-service",
    )
    process.start()
    child_pipe.close()
    host = {"pipe": parent_pipe, "process": process}
    try:
        ready = _receive(parent_pipe)
    except BaseException:
        _close_host(host, require_normal=False)
        raise
    if ready[0] != "ready":
        _close_host(host, require_normal=False)
        raise AssertionError(f"synthetic ServiceHost startup failed: {ready!r}")
    assert ready[1] == endpoint
    return endpoint, keys, host


def _close_host(host, *, require_normal: bool) -> None:
    pipe = host["pipe"]
    process = host["process"]
    close_reply = None
    close_error = None
    process_exitcode = None
    try:
        if not pipe.closed and process.is_alive():
            pipe.send(("close",))
            close_reply = _receive(pipe, timeout=20.0)
    except BaseException as error:
        close_error = error
    finally:
        process.join(20)
        if process.is_alive():
            process.terminate()
            process.join(5)
        if not process.is_alive():
            process_exitcode = process.exitcode
        if not pipe.closed:
            pipe.close()
        if not process.is_alive():
            process.close()
    if require_normal:
        if close_error is not None:
            raise AssertionError("synthetic ServiceHost normal close failed") from close_error
        assert close_reply == ("closed", "closed"), (
            "synthetic ServiceHost did not confirm normal close",
            close_reply,
        )
        assert process_exitcode == 0


def _client_runtime(endpoint: str, keys) -> ServiceClientRuntime:
    config = parse_client_config(_client_config(endpoint))
    return ServiceClientRuntime(
        config,
        identity=WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
        scope_resolver=lambda _ref: _WIRE_SCOPE,
        peer_resolver=lambda _service_id: WireIdentity(
            WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
        ),
        transport_factory=ZmqTransportFactory(
            {
                _CLIENT_SECURITY_REF: ClientCurveKeys(
                    keys["server_public"],
                    keys["client_public"],
                    keys["client_secret"],
                )
            }
        ),
        requested_operations={
            "broker.order_query": frozenset(
                {"orders.query", "execution.account_books.query"}
            )
        },
    )


def _cerebro(broker):
    frame = pandas.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=[dt.datetime(2026, 10, 15)],
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=_INSTRUMENT)
    cerebro.addstrategy(_ReadStrategy)
    return cerebro


class _ReadStrategy(bt.Strategy):
    def next(self):
        view = self.broker.get_strategy_account_book_view(
            strategy_ref=_STRATEGY,
            account_ref=_ACCOUNT,
        )
        snapshot = view.snapshot()
        position = view.getposition(self.data)
        try:
            view.getcash()
        except ServiceStrategyAccountBookError as error:
            cash_error = error.code
        else:  # pragma: no cover - unavailable cash must not be fabricated
            cash_error = "unexpectedly_available"
        try:
            view.getvalue()
        except ServiceStrategyAccountBookError as error:
            value_error = error.code
        else:  # pragma: no cover - unavailable value must not be fabricated
            value_error = "unexpectedly_available"
        try:
            self.broker.get_strategy_account_book_view(
                strategy_ref=_STRATEGY,
                account_ref="account.other",
            )
        except ServiceExecutionSessionConfigError as error:
            scope_error = error.code
        else:  # pragma: no cover - another account must never be inferred
            scope_error = "unexpectedly_available"
        self.book_observation = (snapshot, position, cash_error, value_error, scope_error)


def test_strategy_reads_its_owned_account_book_during_normal_cerebro_run(tmp_path):
    endpoint, keys, host = _start_host(tmp_path)
    runtime = None
    store = None
    session = None
    try:
        runtime = _client_runtime(endpoint, keys)
        store = make_store()
        broker = store.getbroker(
            validation_enabled=False,
            cash_check_enabled=False,
            account_refresh_interval=3_600.0,
            positions_refresh_interval=3_600.0,
            open_orders_refresh_interval=3_600.0,
        )
        session = ServiceExecutionSession(
            runtime,
            mount="broker.orders",
            scope_ref=_ORDER_SCOPE_REF,
            query_mount="broker.order_query",
            query_scope_ref=_QUERY_SCOPE_REF,
        )
        strategies = session.run(_cerebro(broker))
        assert session.state == "closed"
        assert session.cleanup_report.errors == ()
        assert session.cleanup_report.store_connected is False
        assert runtime.state == "closed"
        assert len(strategies) == 1
        snapshot, position, cash_error, value_error, scope_error = (
            strategies[0].book_observation
        )

        assert snapshot.strategy_ref == _STRATEGY
        assert snapshot.account_ref == _ACCOUNT
        assert snapshot.scope_directory_revision == "synthetic-owner-directory-r1"
        assert snapshot.baseline_execution_cursor == 0
        assert snapshot.current_execution_cursor == 0
        assert snapshot.positions == {_INSTRUMENT: Decimal("1.0")}
        assert snapshot.fees_since_baseline == {"USDT": Decimal("0.04")}
        assert position.size == pytest.approx(1.0)
        assert position.price is None
        assert cash_error == "STRATEGY_CASH_UNAVAILABLE"
        assert value_error == "STRATEGY_VALUE_UNAVAILABLE"
        assert scope_error == "ACCOUNT_BOOK_SCOPE_MISMATCH"

        host["pipe"].send(("metrics",))
        metrics = _receive(host["pipe"])
        assert metrics[0] == "metrics"
        assert metrics[1] == 2  # snapshot() plus getposition(); wrong-scope stayed local
        assert metrics[2][1] == 0
    finally:
        if store is not None and store.is_connected:
            with suppress(Exception):
                store.stop()
        if runtime is not None and runtime.state not in {"closed", "failed"}:
            with suppress(Exception):
                runtime.close()
        _close_host(host, require_normal=True)
