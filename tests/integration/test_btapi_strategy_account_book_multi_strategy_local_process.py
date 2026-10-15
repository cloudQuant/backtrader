"""Two Cerebro Strategies read separate owner books through one Broker.

This local synthetic integration node starts a real SDK ServiceHost with CURVE
authentication and SQLite state. It verifies the Backtrader Strategy binding
and runtime lifecycle, not provider/account acceptance.
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
    ServiceStrategyAccountBookRoute,
)
from backtrader.stores.service_strategy_account_book import (  # noqa: E402
    ServiceStrategyAccountBookError,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store  # noqa: E402

_DOMAIN = "paper:backtrader-multi-strategy-book"
_SERVICE_ID = "bt-multi-book-service"
_SERVICE_PRINCIPAL = "bt-multi-book-service-principal"
_INSTANCE_ID = "bt-multi-book-owner"
_SERVICE_SCOPE_REF = "bt-multi-book-root-v1"
_SERVER_SECURITY_REF = "bt-multi-book-server-curve-v1"
_CLIENT_SECURITY_REF = "bt-multi-book-client-curve-v1"
_ACCOUNT = "account.synthetic.shared"
_STRATEGY_A = "strategy.synthetic.alpha"
_STRATEGY_B = "strategy.synthetic.beta"
_PRINCIPAL_A = "bt-multi-book-alpha-principal"
_PRINCIPAL_B = "bt-multi-book-beta-principal"
_ORDER_SCOPE_A = "bt-multi-book-alpha-orders-v1"
_QUERY_SCOPE_A = "bt-multi-book-alpha-query-v1"
_QUERY_SCOPE_B = "bt-multi-book-beta-query-v1"
_TRANSPORT_REF = "bt-multi-book-connect-v1"
_LISTENER_REF = "bt-multi-book-listener-v1"
_MAX_MESSAGE_BYTES = 65_536
_INSTRUMENT = "PAPER:SIM:BTC-USDT"
_WIRE_SCOPE_A = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY_A)
_WIRE_SCOPE_B = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY_B)
_STRATEGY_QUANTITY = {_STRATEGY_A: Decimal("0.25"), _STRATEGY_B: Decimal("0.75")}


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
        "registration_policy_ref": "bt-multi-book-registration-v1",
        "service_requirements_ref": "bt-multi-book-requirements-v1",
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


def _client_config(
    endpoint: str,
    *,
    strategy_ref: str,
    include_writer: bool,
    order_scope_ref: str | None,
    query_scope_ref: str,
) -> dict:
    bindings = []
    if include_writer:
        bindings.append(
            {
                "mount": "broker.orders",
                "service_id": _SERVICE_ID,
                "instance_id": _INSTANCE_ID,
                "scope_ref": order_scope_ref,
                "transport_ref": _TRANSPORT_REF,
                "account_ref": _ACCOUNT,
            }
        )
    bindings.append(
        {
            "mount": "broker.order_query",
            "service_id": _SERVICE_ID,
            "instance_id": _INSTANCE_ID,
            "scope_ref": query_scope_ref,
            "transport_ref": _TRANSPORT_REF,
            "account_ref": _ACCOUNT,
        }
    )
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": strategy_ref},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": bindings,
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
    """A synthetic service that records and rejects every write."""

    def __init__(self):
        self.submit_count = 0
        self.cancel_count = 0

    def submit(self, _intent):
        self.submit_count += 1
        raise AssertionError("the local read-only integration must not dispatch an order")

    def cancel(self, _intent):
        self.cancel_count += 1
        raise AssertionError("the local read-only integration must not dispatch a cancel")


class _ClosedAdmissionGate:
    def reserve(self, _intent):
        raise AssertionError("the local read-only integration must not reserve a write")

    def claim_before_dispatch(self, _intent):
        raise AssertionError("the local read-only integration must not admit a cancel")


class _SyntheticOwnerFacts:
    """Complete deterministic facts for two owners within one account."""

    def __init__(self, execution_scopes):
        self._execution_scopes = tuple(execution_scopes)
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
            OwnerPosition,
            PositionFact,
        )
        from bt_api_py.service_execution_account_books import ExecutionAccountBookReadInputsV1

        if account_key != self._execution_scopes[0].account_key:
            raise AssertionError("account-book source received an unexpected account")
        self.read_count += 1
        self.last_cut = (journal_generation, execution_cursor)
        baseline_ns = self._baseline_ns
        current_ns = max(time.time_ns(), baseline_ns + 3)
        directory_revision = "synthetic-two-owner-directory-r1"
        provider_generation = "synthetic-two-owner-provider-r1"
        scopes = tuple(
            ExecutionOwnerScope(
                execution_scope,
                AllocationOwnerKind.STRATEGY,
                strategy_ref,
                wire_scope,
            )
            for strategy_ref, execution_scope, wire_scope in (
                (_STRATEGY_A, self._execution_scopes[0], _WIRE_SCOPE_A),
                (_STRATEGY_B, self._execution_scopes[1], _WIRE_SCOPE_B),
            )
        )
        directory = ExecutionScopeDirectory(
            account_key=account_key,
            source="synthetic-trusted-owner-registry",
            source_ref="synthetic-two-owner-registry-r1",
            revision=directory_revision,
            covers_from_ns=baseline_ns,
            as_of_ns=current_ns,
            scopes=scopes,
        )
        owner_positions = tuple(
            OwnerPosition(
                AllocationOwnerKind.STRATEGY,
                strategy_ref,
                _INSTRUMENT,
                quantity,
            )
            for strategy_ref, quantity in _STRATEGY_QUANTITY.items()
        )
        baseline_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source="synthetic-net-position-snapshot",
            source_ref="synthetic-two-owner-baseline-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=baseline_ns,
            execution_cursor=0,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, Decimal("1.0")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0")),),
            fee_coverage_start_ns=baseline_ns,
        )
        allocation_baseline = ExecutionAllocationBaseline(
            account_key=account_key,
            source="synthetic-trusted-strategy-ledger",
            source_ref="synthetic-two-owner-baseline-r1",
            revision="synthetic-two-owner-baseline-revision-r1",
            scope_directory_revision=directory_revision,
            provider_generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=baseline_ns,
            execution_cursor=0,
            positions=owner_positions,
        )
        activity = ExternalActivitySnapshot(
            account_key=account_key,
            source="synthetic-complete-provider-activity",
            source_ref="synthetic-two-owner-activity-r1",
            generation=provider_generation,
            coverage_start_ns=baseline_ns,
            coverage_end_ns=current_ns,
            fills=(),
            orders=(),
        )
        current_snapshot = ExecutionAccountSnapshot(
            account_key=account_key,
            source=baseline_snapshot.source,
            source_ref="synthetic-two-owner-current-r1",
            generation=provider_generation,
            journal_generation=journal_generation,
            as_of_ns=current_ns,
            execution_cursor=execution_cursor,
            position_mode="NET",
            positions=(PositionFact(_INSTRUMENT, Decimal("1.0")),),
            cumulative_fees=(CurrencyAmount("USDT", Decimal("0")),),
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
    execution_scopes = (
        ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY_A, "20261015"),
        ExecutionScope("PAPER", "simulation", _ACCOUNT, _STRATEGY_B, "20261015"),
    )
    source = _SyntheticOwnerFacts(execution_scopes)
    dispatch = _NoOrderDispatch()
    gate = _ClosedAdmissionGate()
    host = None
    try:
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="bt-multi-book-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="bt-multi-book-registration-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="bt-multi-book-requirements-v1",
            curve_public_key=keys["server_public"],
            curve_secret_key=keys["server_secret"],
            principals={
                keys["client_a_public"]: _PRINCIPAL_A,
                keys["client_b_public"]: _PRINCIPAL_B,
            },
            grants={
                _PRINCIPAL_A: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL_A, _STRATEGY_A),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_entry",
                                _ORDER_SCOPE_A,
                                _WIRE_SCOPE_A,
                                frozenset({"orders.submit", "orders.cancel"}),
                            ),
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_A,
                                _WIRE_SCOPE_A,
                                frozenset(
                                    {"orders.query", "execution.account_books.query"}
                                ),
                            ),
                        ),
                    ),
                ),
                _PRINCIPAL_B: (
                    PrincipalGrant(
                        WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL_B, _STRATEGY_B),
                        (
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_B,
                                _WIRE_SCOPE_B,
                                frozenset(
                                    {"orders.query", "execution.account_books.query"}
                                ),
                            ),
                        ),
                    ),
                ),
            },
        )

        def resource_provider(component, instance_id, _options, _scope):
            if component != "execution" or instance_id != _INSTANCE_ID:
                raise AssertionError("unexpected service resource request")
            return ComponentResources.borrowed(
                {
                    "store": store,
                    "targets": {
                        _WIRE_SCOPE_A: execution_scopes[0],
                        _WIRE_SCOPE_B: execution_scopes[1],
                    },
                    "dispatch": dispatch,
                    "admission": {"order_gate": gate, "cancel_gate": gate},
                    "account_books": source,
                },
                ready=lambda: True,
            )

        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        control.send(("ready", host.endpoint, host.state))
        while True:
            host.serve_once(timeout_ms=20)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("metrics",):
                control.send(("metrics", source.read_count, dispatch.submit_count, dispatch.cancel_count))
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


def _receive(pipe, timeout: float = 20.0):
    if not pipe.poll(timeout):
        raise TimeoutError("timed out waiting for the synthetic ServiceHost")
    return pipe.recv()


def _start_host(tmp_path):
    context = multiprocessing.get_context("spawn")
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    client_a_public, client_a_secret = zmq.curve_keypair()
    client_b_public, client_b_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "client_a_public": client_a_public,
        "client_a_secret": client_a_secret,
        "client_b_public": client_b_public,
        "client_b_secret": client_b_secret,
    }
    parent_pipe, child_pipe = context.Pipe(duplex=True)
    process = context.Process(
        target=_host_process,
        args=(
            child_pipe,
            _service_config(endpoint),
            str(tmp_path / "multi-book-registry.sqlite3"),
            str(tmp_path / "multi-book-execution.sqlite3"),
            keys,
        ),
        name="bt-multi-strategy-account-book-service",
    )
    process.start()
    child_pipe.close()
    host = {"pipe": parent_pipe, "process": process, "forced_cleanup": False}
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
            host["forced_cleanup"] = True
            process.terminate()
            process.join(5)
        if process.is_alive():
            host["forced_cleanup"] = True
            process.kill()
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
        assert host["forced_cleanup"] is False


def _scope_resolver(strategy_ref: str, query_scope_ref: str, order_scope_ref: str | None = None):
    scopes = {query_scope_ref: WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=strategy_ref)}
    if order_scope_ref is not None:
        scopes[order_scope_ref] = WireScope(
            _DOMAIN, account_ref=_ACCOUNT, strategy_ref=strategy_ref
        )
    return scopes


def _client_runtime(endpoint, keys, *, strategy_ref, principal, client_suffix, scopes):
    client_public = keys[f"client_{client_suffix}_public"]
    client_secret = keys[f"client_{client_suffix}_secret"]
    config = parse_client_config(
        _client_config(
            endpoint,
            strategy_ref=strategy_ref,
            include_writer=client_suffix == "a",
            order_scope_ref=_ORDER_SCOPE_A if client_suffix == "a" else None,
            query_scope_ref=_QUERY_SCOPE_A if client_suffix == "a" else _QUERY_SCOPE_B,
        )
    )
    requested_operations = {
        "broker.order_query": frozenset(
            {"orders.query", "execution.account_books.query"}
        )
    }
    if client_suffix == "a":
        requested_operations["broker.orders"] = frozenset({"orders.submit", "orders.cancel"})
    return ServiceClientRuntime(
        config,
        identity=WireIdentity(WireRole.STRATEGY_CLIENT, principal, strategy_ref),
        scope_resolver=scopes.__getitem__,
        peer_resolver=lambda _service_id: WireIdentity(
            WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
        ),
        transport_factory=ZmqTransportFactory(
            {
                _CLIENT_SECURITY_REF: ClientCurveKeys(
                    keys["server_public"], client_public, client_secret
                )
            }
        ),
        requested_operations=requested_operations,
    )


class _AccountBookStrategy(bt.Strategy):
    params = (
        ("strategy_ref", None),
        ("account_ref", None),
        ("risk_budget", None),
        ("attempt_order", False),
    )

    def start(self):
        self.rejected_order = None
        self._order_attempted = False
        self.correct_binding = self.broker.bind_strategy_account_book(
            self,
            strategy_ref=self.p.strategy_ref,
            account_ref=self.p.account_ref,
        )
        try:
            self.broker.get_strategy_account_book_view(
                strategy_ref=self.p.strategy_ref,
                account_ref="account.untrusted-route",
            )
        except ServiceExecutionSessionConfigError as error:
            self.wrong_account_route_code = error.code
        else:  # pragma: no cover - a missing account route must fail locally
            self.wrong_account_route_code = "unexpectedly_available"
        self.wrong_strategy_binding_code = None
        if self.p.strategy_ref == _STRATEGY_B:
            try:
                self.broker.bind_strategy_account_book(
                    self,
                    strategy_ref=_STRATEGY_A,
                    account_ref=_ACCOUNT,
                )
            except ServiceExecutionSessionConfigError as error:
                self.wrong_strategy_binding_code = error.code

    def next(self):
        snapshot = self.account_book.snapshot()
        book_position = self.account_book.getposition(self.data)
        try:
            self.account_book.getcash()
        except ServiceStrategyAccountBookError as error:
            cash_error = error.code
        else:  # pragma: no cover - this contract has no cash
            cash_error = "unexpectedly_available"
        try:
            self.account_book.getvalue()
        except ServiceStrategyAccountBookError as error:
            value_error = error.code
        else:  # pragma: no cover - this contract has no valuation basis
            value_error = "unexpectedly_available"
        self.account_observation = {
            "snapshot": snapshot,
            "book_position": book_position,
            "cash_error": cash_error,
            "value_error": value_error,
            "account_cash": self.broker.getcash(),
            "account_value": self.broker.getvalue(),
            "account_position": self.broker.getposition(self.data),
            "risk_budget": self.p.risk_budget,
        }
        if self.p.attempt_order and not self._order_attempted:
            self._order_attempted = True
            self.rejected_order = self.buy(data=self.data, size=1.0)


class _DuplicateIdentityStrategy(bt.Strategy):
    params = (("strategy_ref", _STRATEGY_A), ("account_ref", _ACCOUNT))

    def start(self):
        self.account_book = self.broker.get_strategy_account_book_view(
            strategy_ref=self.p.strategy_ref,
            account_ref=self.p.account_ref,
        )
        try:
            self.broker.bind_strategy_account_book(
                self,
                strategy_ref=self.p.strategy_ref,
                account_ref=self.p.account_ref,
            )
        except ServiceExecutionSessionConfigError as error:
            self.duplicate_identity_code = error.code
        else:  # pragma: no cover - a bound route cannot be shared by two instances
            self.duplicate_identity_code = "unexpectedly_available"
        self.rejected_order = None
        self._order_attempted = False

    def next(self):
        if not self._order_attempted:
            self._order_attempted = True
            self.rejected_order = self.buy(data=self.data, size=1.0)


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
        index=[dt.datetime(2026, 10, 16)],
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=_INSTRUMENT)
    cerebro.addstrategy(
        _AccountBookStrategy,
        strategy_ref=_STRATEGY_A,
        account_ref=_ACCOUNT,
        risk_budget=9_999_999.0,
    )
    cerebro.addstrategy(
        _AccountBookStrategy,
        strategy_ref=_STRATEGY_B,
        account_ref=_ACCOUNT,
        risk_budget=8_888_888.0,
        attempt_order=True,
    )
    cerebro.addstrategy(_DuplicateIdentityStrategy)
    return cerebro


def test_two_strategies_bind_distinct_read_books_on_one_shared_broker(tmp_path):
    endpoint, keys, host = _start_host(tmp_path)
    primary_runtime = None
    second_runtime = None
    store = None
    session = None
    try:
        primary_runtime = _client_runtime(
            endpoint,
            keys,
            strategy_ref=_STRATEGY_A,
            principal=_PRINCIPAL_A,
            client_suffix="a",
            scopes=_scope_resolver(_STRATEGY_A, _QUERY_SCOPE_A, _ORDER_SCOPE_A),
        )
        second_runtime = _client_runtime(
            endpoint,
            keys,
            strategy_ref=_STRATEGY_B,
            principal=_PRINCIPAL_B,
            client_suffix="b",
            scopes=_scope_resolver(_STRATEGY_B, _QUERY_SCOPE_B),
        )
        store = make_store(
            api=FakeBtApiClient(
                balance={"cash": 12_345.0, "value": 54_321.0},
                positions=[{"instrument": _INSTRUMENT, "volume": 9.0, "price": 77.0}],
            ),
            provider="btapi",
        )
        broker = store.getbroker(
            validation_enabled=False,
            cash_check_enabled=False,
            account_refresh_interval=3_600.0,
            positions_refresh_interval=3_600.0,
            open_orders_refresh_interval=3_600.0,
        )
        session = ServiceExecutionSession(
            primary_runtime,
            mount="broker.orders",
            scope_ref=_ORDER_SCOPE_A,
            query_mount="broker.order_query",
            query_scope_ref=_QUERY_SCOPE_A,
            strategy_account_book_routes=(
                ServiceStrategyAccountBookRoute(
                    strategy_ref=_STRATEGY_B,
                    account_ref=_ACCOUNT,
                    runtime=second_runtime,
                    mount="broker.order_query",
                    scope_ref=_QUERY_SCOPE_B,
                    owned=True,
                ),
            ),
        )

        strategies = session.run(_cerebro(broker))
        assert session.state == "closed"
        assert session.cleanup_report.errors == ()
        assert session.cleanup_report.store_connected is False
        assert session.cleanup_report.runtime_state == "closed"
        assert primary_runtime.state == "closed"
        assert second_runtime.state == "closed"
        assert len(strategies) == 3
        alpha, beta, duplicate = strategies
        assert alpha.broker is beta.broker is duplicate.broker is broker
        assert alpha.correct_binding is alpha.account_book
        assert beta.correct_binding is beta.account_book
        assert alpha.account_book.strategy_ref == _STRATEGY_A
        assert beta.account_book.strategy_ref == _STRATEGY_B
        with pytest.raises(AttributeError, match="immutable"):
            beta.account_book.strategy_ref = _STRATEGY_A

        for strategy, expected_ref, expected_quantity in (
            (alpha, _STRATEGY_A, Decimal("0.25")),
            (beta, _STRATEGY_B, Decimal("0.75")),
        ):
            assert strategy.wrong_account_route_code == "ACCOUNT_BOOK_ROUTE_UNAVAILABLE"
            observation = strategy.account_observation
            assert observation["snapshot"].strategy_ref == expected_ref
            assert observation["snapshot"].account_ref == _ACCOUNT
            assert observation["snapshot"].positions == {_INSTRUMENT: expected_quantity}
            assert observation["book_position"].size == pytest.approx(float(expected_quantity))
            assert observation["book_position"].price is None
            assert observation["cash_error"] == "STRATEGY_CASH_UNAVAILABLE"
            assert observation["value_error"] == "STRATEGY_VALUE_UNAVAILABLE"
            assert observation["account_cash"] == pytest.approx(12_345.0)
            assert observation["account_value"] == pytest.approx(54_321.0)
            assert observation["account_position"].size == pytest.approx(9.0)
            assert observation["risk_budget"] > observation["account_cash"]

        assert beta.wrong_strategy_binding_code == "STRATEGY_IDENTITY_MISMATCH"
        assert beta.rejected_order is not None
        assert beta.rejected_order.getstatusname() == "Rejected"
        assert beta.rejected_order.info.error_code == "strategy_writer_route_mismatch"
        assert duplicate.duplicate_identity_code == "STRATEGY_ROUTE_ALREADY_BOUND"
        assert duplicate.rejected_order is not None
        assert duplicate.rejected_order.getstatusname() == "Rejected"
        assert duplicate.rejected_order.info.error_code == "strategy_writer_strategy_not_bound"

        host["pipe"].send(("metrics",))
        metrics = _receive(host["pipe"])
        assert metrics == ("metrics", 4, 0, 0)
    finally:
        if store is not None and store.is_connected:
            with suppress(Exception):
                store.stop()
        for runtime in (second_runtime, primary_runtime):
            if runtime is not None and runtime.state not in {"closed", "failed"}:
                with suppress(Exception):
                    runtime.close()
        _close_host(host, require_normal=True)


def test_preflight_empty_run_and_refresh_setup_release_owned_runtime_claims(monkeypatch):
    endpoint = _endpoint()
    server_public, _server_secret = zmq.curve_keypair()
    client_a_public, client_a_secret = zmq.curve_keypair()
    client_b_public, client_b_secret = zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "client_a_public": client_a_public,
        "client_a_secret": client_a_secret,
        "client_b_public": client_b_public,
        "client_b_secret": client_b_secret,
    }
    primary_runtime = _client_runtime(
        endpoint,
        keys,
        strategy_ref=_STRATEGY_A,
        principal=_PRINCIPAL_A,
        client_suffix="a",
        scopes=_scope_resolver(_STRATEGY_A, _QUERY_SCOPE_A, _ORDER_SCOPE_A),
    )
    second_runtime = _client_runtime(
        endpoint,
        keys,
        strategy_ref=_STRATEGY_B,
        principal=_PRINCIPAL_B,
        client_suffix="b",
        scopes=_scope_resolver(_STRATEGY_B, _QUERY_SCOPE_B),
    )

    def make_session():
        return ServiceExecutionSession(
            primary_runtime,
            mount="broker.orders",
            scope_ref=_ORDER_SCOPE_A,
            query_mount="broker.order_query",
            query_scope_ref=_QUERY_SCOPE_A,
            strategy_account_book_routes=(
                ServiceStrategyAccountBookRoute(
                    strategy_ref=_STRATEGY_B,
                    account_ref=_ACCOUNT,
                    runtime=second_runtime,
                    mount="broker.order_query",
                    scope_ref=_QUERY_SCOPE_B,
                    owned=True,
                ),
            ),
        )

    session = make_session()
    with pytest.raises(ServiceExecutionSessionConfigError, match="INVALID_BROKER"):
        session.run(bt.Cerebro())
    assert session.cleanup_report.runtime_close_attempted is False
    assert primary_runtime.state == second_runtime.state == "new"

    # Construction with the same owned runtimes proves the rejected preflight
    # released both ownership fences without starting or closing either one.
    empty_session = make_session()
    store = make_store(api=FakeBtApiClient(), provider="btapi")
    broker = store.getbroker()
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(broker)
    assert empty_session.run(cerebro) == []
    assert empty_session.state == "closed_unstarted"
    assert empty_session.cleanup_report.runtime_close_attempted is False
    assert primary_runtime.state == second_runtime.state == "new"

    # The no-data return also relinquishes ownership, so a further caller can
    # make a fresh decision with those still-new runtimes.
    final_session = make_session()
    with pytest.raises(ServiceExecutionSessionConfigError, match="INVALID_BROKER"):
        final_session.run(bt.Cerebro())
    assert primary_runtime.state == second_runtime.state == "new"

    refresh_session = make_session()
    valid_store = make_store(api=FakeBtApiClient(), provider="btapi")
    valid_broker = valid_store.getbroker()
    original_import = __import__

    def fail_refresh_loop_import(name, *args, **kwargs):
        if name == "backtrader.stores.service_refresh_loop":
            raise ImportError("synthetic refresh-loop import failure")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr("builtins.__import__", fail_refresh_loop_import)
        with pytest.raises(ImportError, match="synthetic refresh-loop import failure"):
            refresh_session.run(_cerebro(valid_broker))
    assert refresh_session.state == "rejected"
    assert refresh_session.cleanup_report.errors[0] == "REFRESH_LOOP_SETUP_FAILED"
    assert refresh_session.cleanup_report.runtime_close_attempted is False
    assert primary_runtime.state == second_runtime.state == "new"

    replacement_session = make_session()
    with pytest.raises(ServiceExecutionSessionConfigError, match="INVALID_BROKER"):
        replacement_session.run(bt.Cerebro())
    assert primary_runtime.state == second_runtime.state == "new"
    with suppress(Exception):
        primary_runtime.close()
    with suppress(Exception):
        second_runtime.close()
