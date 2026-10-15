"""One real ServiceHost/Cerebro managed fill and duplicate-projection check.

The service, authenticated CURVE clients, SDK execution component, SQLite
journal, Backtrader Broker, and Session.run(Cerebro) path are real local
components. Only the provider observation and admission decision are explicit
synthetic leaves; this test is not provider, account, or formal-case evidence.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import multiprocessing
import os
import socket
from contextlib import suppress
from decimal import Decimal
from pathlib import Path

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
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store  # noqa: E402

_DOMAIN = "paper:bt-cerebro-execution-callbacks"
_SERVICE_ID = "bt-callback-service"
_SERVICE_PRINCIPAL = "bt-callback-service-principal"
_STRATEGY = "strategy.synthetic.callbacks"
_PRINCIPAL = "bt-callback-strategy-principal"
_ACCOUNT = "account.synthetic.callbacks"
_INSTANCE_ID = "bt-callback-execution-owner"
_ORDER_SCOPE_REF = "bt-callback-orders-v1"
_QUERY_SCOPE_REF = "bt-callback-query-v1"
_SERVICE_SCOPE_REF = "bt-callback-root-v1"
_SERVER_SECURITY_REF = "bt-callback-server-curve-v1"
_CLIENT_SECURITY_REF = "bt-callback-client-curve-v1"
_LISTENER_REF = "bt-callback-listener-v1"
_TRANSPORT_REF = "bt-callback-connect-v1"
_REQUEST_TIMEOUT_MS = 2_000
_MAX_MESSAGE_BYTES = 65_536
_TRADING_DAY = "20261016"
_INSTRUMENT = "PAPER:SIM:BTC-USDT"
_INTENT_ID = "bt-cerebro-fill-intent-r1"
_SIGNAL_ID = "bt-cerebro-fill-signal-r1"
_METADATA_VERSION = "bt-cerebro-fill-metadata-r1"
_PROVIDER_ORDER_ID = "synthetic-provider-order-callback-r1"
_FILL_QUANTITY = Decimal("1.0")
_FILL_PRICE = Decimal("100.25")
_FILL_FEE = Decimal("0.05")
_SCOPE = WireScope(_DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY)
_SOURCE_ROOT_ENV = {
    "sdk": "BT_STRATEGY_FINANCIAL_SDK_ROOT",
    "base": "BT_STRATEGY_FINANCIAL_BASE_ROOT",
    "execution": "BT_STRATEGY_FINANCIAL_EXECUTION_ROOT",
    "transport": "BT_STRATEGY_FINANCIAL_TRANSPORT_ROOT",
}


def _loaded_source_origins():
    import bt_api_base.service_protocol as base_protocol
    import bt_api_execution.service_order_entry as order_entry
    import bt_api_execution.store as execution_store
    import bt_api_py.service_components as service_components
    import bt_api_py.service_host as service_host
    import bt_api_py.service_runtime as service_runtime
    import bt_api_transport_zmq.service_v2 as service_transport

    return {
        "sdk": {
            "service_components": str(Path(service_components.__file__).resolve()),
            "service_host": str(Path(service_host.__file__).resolve()),
            "service_runtime": str(Path(service_runtime.__file__).resolve()),
        },
        "base": {"service_protocol": str(Path(base_protocol.__file__).resolve())},
        "execution": {
            "service_order_entry": str(Path(order_entry.__file__).resolve()),
            "store": str(Path(execution_store.__file__).resolve()),
        },
        "transport": {"service_v2": str(Path(service_transport.__file__).resolve())},
    }


def _assert_source_origins(origins):
    for package, modules in origins.items():
        configured_root = os.environ.get(_SOURCE_ROOT_ENV[package])
        expected_root = Path(configured_root).resolve() if configured_root else None
        for module_name, raw_path in modules.items():
            module_path = Path(raw_path).resolve()
            if not module_path.is_file():
                raise AssertionError(f"{package}.{module_name} source file is missing")
            if expected_root is not None and not module_path.is_relative_to(expected_root):
                raise AssertionError(
                    f"{package}.{module_name} loaded outside its fixed source export"
                )
    return origins


def _report_source_origins(label, origins):
    if any(os.environ.get(name) for name in _SOURCE_ROOT_ENV.values()):
        print(f"{label} source origins: {json.dumps(origins, sort_keys=True)}", flush=True)


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
        "registration_policy_ref": "bt-callback-registration-v1",
        "service_requirements_ref": "bt-callback-requirements-v1",
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
                    "options": {"request_timeout_ms": _REQUEST_TIMEOUT_MS},
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
                        "request_timeout_ms": _REQUEST_TIMEOUT_MS,
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


class _SyntheticAdmissionPermit:
    def __init__(self, permit_id: str) -> None:
        self.permit_id = permit_id


class _SyntheticAdmissionGate:
    """Explicit local-only admission leaf for one synthetic fill."""

    def __init__(self) -> None:
        self.reserved: list[str] = []
        self.validated: list[str] = []
        self.settled: list[str] = []
        self.released: list[str] = []

    def reserve(self, intent):
        self.reserved.append(intent.intent_id)
        return _SyntheticAdmissionPermit(f"callback-permit-{intent.intent_id}")

    def validate(self, permit_id, intent):
        expected = f"callback-permit-{intent.intent_id}"
        if permit_id != expected:
            raise AssertionError("synthetic admission permit identity changed")
        self.validated.append(intent.intent_id)
        return _SyntheticAdmissionPermit(permit_id)

    def settle(self, permit_id):
        if not permit_id.startswith("callback-permit-"):
            raise AssertionError("unexpected synthetic admission settlement")
        self.settled.append(permit_id.removeprefix("callback-permit-"))

    def release(self, permit_id, reason):
        if not permit_id.startswith("callback-permit-") or not reason:
            raise AssertionError("unexpected synthetic admission release")
        self.released.append(permit_id.removeprefix("callback-permit-"))

    def claim_before_dispatch(self, permit_reference, intent):
        from bt_api_execution import CancelDispatchClaimReceiptV1

        if not permit_reference.startswith("callback-permit-"):
            raise AssertionError("unexpected synthetic cancellation permit reference")
        return CancelDispatchClaimReceiptV1(
            permit_reference=permit_reference,
            scope_key=intent.scope.key,
            cancel_id=intent.cancel_id,
            intent_fingerprint=intent.fingerprint,
        )


class _SyntheticFullFillProvider:
    """One deterministic provider leaf; dispatch and journal remain real."""

    def __init__(self) -> None:
        self.submitted: list[str] = []
        self.cancelled: list[str] = []

    def submit(self, intent):
        from bt_api_execution import ExecutionState, ProviderObservation

        self.submitted.append(intent.intent_id)
        return ProviderObservation(
            intent_id=intent.intent_id,
            state=ExecutionState.FILLED,
            provider_order_id=_PROVIDER_ORDER_ID,
            filled_quantity=intent.quantity,
            average_price=_FILL_PRICE,
            cumulative_commission=_FILL_FEE,
            cumulative_commission_currency="USDT",
        )

    def cancel(self, intent):
        from bt_api_execution import CancelObservation

        self.cancelled.append(intent.cancel_id)
        return CancelObservation.accepted(
            intent.cancel_id, intent.target_intent_id, intent.provider_order_id
        )


def _host_process(control, raw_config, registry_path: str, store_path: str, keys) -> None:
    from bt_api_execution import ExecutionScope, SqliteExecutionStore
    from bt_api_py.service_components import ComponentResources

    config = parse_service_config(raw_config)
    store = SqliteExecutionStore(store_path)
    provider = _SyntheticFullFillProvider()
    gate = _SyntheticAdmissionGate()
    host = None
    execution_scope = ExecutionScope(
        "PAPER", "simulation", _ACCOUNT, _STRATEGY, _TRADING_DAY
    )
    try:
        authority = TrustedServiceAuthority(
            identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
            scope=WireScope(_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="bt-callback-service-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="bt-callback-registration-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="bt-callback-requirements-v1",
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
                                _SCOPE,
                                frozenset({"orders.submit", "orders.cancel"}),
                            ),
                            ResourceGrant(
                                _INSTANCE_ID,
                                "service.order_query",
                                _QUERY_SCOPE_REF,
                                _SCOPE,
                                frozenset({"orders.query"}),
                            ),
                        ),
                    ),
                )
            },
        )

        def resource_provider(component, instance_id, _options, _scope):
            if component != "execution" or instance_id != _INSTANCE_ID:
                raise AssertionError("unexpected callback-test component resource request")
            return ComponentResources.borrowed(
                {
                    "store": store,
                    "targets": {_SCOPE: execution_scope},
                    "dispatch": provider,
                    "admission": {"order_gate": gate, "cancel_gate": gate},
                },
                ready=lambda: True,
            )

        host = ServiceHost(config, authority, registry_path, resource_provider)
        host.start()
        origins = _assert_source_origins(_loaded_source_origins())
        control.send(("ready", host.endpoint, host.state, origins))
        while True:
            host.serve_once(timeout_ms=20)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("metrics",):
                record = store.get(_INTENT_ID, scope=execution_scope)
                control.send(
                    (
                        "metrics",
                        tuple(provider.submitted),
                        tuple(provider.cancelled),
                        tuple(gate.reserved),
                        tuple(gate.validated),
                        tuple(gate.settled),
                        None if record is None else record.state.value,
                        None if record is None else record.dispatch_attempts,
                        None if record is None else str(record.filled_quantity),
                        None
                        if record is None or record.average_price is None
                        else str(record.average_price),
                        None
                        if record is None or record.cumulative_commission is None
                        else str(record.cumulative_commission),
                    )
                )
            elif command == ("close",):
                host.close()
                store.close()
                control.send(("closed", host.state))
                return
            else:
                raise AssertionError("unknown synthetic callback-host command")
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
        raise TimeoutError("synthetic callback ServiceHost missed its response bound")
    return pipe.recv()


def _close_host(host) -> dict:
    pipe = host["pipe"]
    process = host["process"]
    close_reply = None
    close_error = None
    forced = False
    try:
        if not pipe.closed and process.is_alive():
            pipe.send(("close",))
            close_reply = _receive(pipe, timeout=20.0)
    except BaseException as error:
        close_error = type(error).__name__
    finally:
        process.join(20)
        if process.is_alive():
            forced = True
            process.terminate()
            process.join(5)
        if process.is_alive():
            forced = True
            process.kill()
            process.join(5)
        exitcode = process.exitcode if not process.is_alive() else None
        if not pipe.closed:
            pipe.close()
        if not process.is_alive():
            process.close()
    facts = {
        "close_reply": close_reply,
        "close_error": close_error,
        "exitcode": exitcode,
        "forced_cleanup": forced,
        "normal_close": (
            close_error is None
            and close_reply == ("closed", "closed")
            and exitcode == 0
            and not forced
        ),
    }
    host["cleanup_facts"] = facts
    return facts


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
            str(tmp_path / "callback-registry.sqlite3"),
            str(tmp_path / "callback-execution.sqlite3"),
            keys,
        ),
        name="bt-cerebro-execution-callback-service",
    )
    process.start()
    child_pipe.close()
    host = {"pipe": parent_pipe, "process": process}
    try:
        ready = _receive(parent_pipe)
        if not isinstance(ready, tuple) or not ready or ready[0] != "ready":
            raise AssertionError(f"synthetic callback ServiceHost startup failed: {ready!r}")
        assert ready[1] == endpoint
        origins = _assert_source_origins(ready[3])
        _report_source_origins("spawned callback ServiceHost", origins)
        host["source_origins"] = origins
    except BaseException:
        _close_host(host)
        raise
    return endpoint, keys, host


def _client_runtime(endpoint, keys):
    config = parse_client_config(_client_config(endpoint))
    return ServiceClientRuntime(
        config,
        identity=WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL, _STRATEGY),
        run_id="bt-callback-cerebro-run-r1",
        scope_resolver=lambda _scope_ref: _SCOPE,
        peer_resolver=lambda _service_id: WireIdentity(
            WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
        ),
        transport_factory=ZmqTransportFactory(
            {
                _CLIENT_SECURITY_REF: ClientCurveKeys(
                    keys["server_public"], keys["client_public"], keys["client_secret"]
                )
            }
        ),
        requested_operations={
            "broker.orders": frozenset({"orders.submit", "orders.cancel"}),
            "broker.order_query": frozenset({"orders.query"}),
        },
    )


class _ManagedFillStrategy(bt.Strategy):
    params = (("strategy_ref", _STRATEGY), ("account_ref", _ACCOUNT))

    def start(self):
        self.order = None
        self.submit_calls = 0
        self.order_statuses = []
        self.order_callback_fills = []
        self.trade_callbacks = []
        self.duplicate_projection = None
        self.position_after_duplicate = None
        self.position_price_after_duplicate = None
        self.executed_after_duplicate = None
        self.commission_after_duplicate = None

    def next(self):
        if self.order is not None:
            return
        self.submit_calls += 1
        self.order = self.buy(
            data=self.data,
            size=float(_FILL_QUANTITY),
            price=float(_FILL_PRICE),
            exectype=bt.Order.Limit,
            managed_order_type="LIMIT",
            managed_intent_id=_INTENT_ID,
            managed_signal_id=_SIGNAL_ID,
            managed_instrument=_INSTRUMENT,
            managed_position_effect="OPEN",
            managed_metadata_version=_METADATA_VERSION,
            managed_instrument_metadata_digest="a" * 64,
            offset="open",
            reduce_only=False,
        )

    def notify_order(self, order):
        self.order_statuses.append(order.getstatusname())
        self.order_callback_fills.append(
            (order.getstatusname(), float(order.executed.size), float(order.executed.comm))
        )
        if order.status != order.Completed or self.duplicate_projection is not None:
            return

        live_order = self.broker.orders[order.ref]
        projection = self.broker.store.refresh_managed_order_projection(live_order)
        self.duplicate_projection = dict(projection)
        if projection.get("managed_execution_replayed") is not True:
            raise AssertionError("the second read did not identify the durable fill as replay")

        # Feed the exact authenticated same-revision service projection through
        # the Broker's ordinary order-update sink. A cumulative checkpoint may
        # be observed more than once; only a positive quantity delta can book.
        update = dict(projection)
        update.update(
            bt_order_ref=order.ref,
            data_name=self.data._name,
            side="buy",
        )
        self.broker._apply_order_update(update)
        position = self.broker.get_cached_report_state()["positions"][
            self.broker._position_key(self.data)
        ]
        self.position_after_duplicate = float(position.size)
        self.position_price_after_duplicate = (
            None if position.price is None else float(position.price)
        )
        self.executed_after_duplicate = float(live_order.executed.size)
        self.commission_after_duplicate = float(live_order.executed.comm)

    def notify_trade(self, trade):
        self.trade_callbacks.append(
            (
                "Open" if trade.isopen else "Closed" if trade.isclosed else "Other",
                float(trade.size),
                float(trade.price),
                float(trade.commission),
            )
        )


def _cerebro(broker):
    dates = [dt.datetime(2026, 10, 16) + dt.timedelta(days=day) for day in range(4)]
    closes = [100.5, 100.6, 100.7, 100.8]
    frame = pandas.DataFrame(
        {
            "open": closes,
            "high": [price + 0.5 for price in closes],
            "low": [price - 0.5 for price in closes],
            "close": closes,
            "volume": [10.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=dates,
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=_INSTRUMENT)
    cerebro.addstrategy(_ManagedFillStrategy)
    return cerebro


def _host_metrics(host):
    host["pipe"].send(("metrics",))
    return _receive(host["pipe"])


def test_cerebro_projects_one_durable_full_fill_once_through_real_service(tmp_path):
    endpoint, keys, host = _start_host(tmp_path)
    runtime = None
    store = None
    try:
        origins = _assert_source_origins(_loaded_source_origins())
        _report_source_origins("Cerebro callback process", origins)
        runtime = _client_runtime(endpoint, keys)
        store = make_store(
            api=FakeBtApiClient(
                balance={"cash": 1_000.0},
                positions=[],
                open_orders=[],
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
        assert session.cleanup_report.runtime_state == "closed"
        assert session.cleanup_report.runtime_close_attempted is True
        assert runtime.state == "closed"
        assert len(strategies) == 1
        strategy = strategies[0]
        assert strategy.submit_calls == 1
        assert strategy.order is not None
        assert strategy.order.getstatusname() == "Completed"
        assert strategy.order.executed.size == pytest.approx(float(_FILL_QUANTITY))
        assert strategy.order.executed.price == pytest.approx(float(_FILL_PRICE))
        assert strategy.order.executed.comm == pytest.approx(float(_FILL_FEE))
        cached_positions = broker.get_cached_report_state()["positions"]
        cached_position = cached_positions[broker._position_key(strategy.data)]
        assert cached_position.size == pytest.approx(float(_FILL_QUANTITY))
        assert cached_position.price == pytest.approx(float(_FILL_PRICE))

        allowed_statuses = {"Submitted", "Accepted", "Completed"}
        assert strategy.order_statuses
        assert set(strategy.order_statuses) <= allowed_statuses
        assert strategy.order_statuses[-1] == "Completed"
        assert strategy.order_statuses.count("Completed") == 1
        ranks = {"Submitted": 0, "Accepted": 1, "Completed": 2}
        assert [ranks[status] for status in strategy.order_statuses] == sorted(
            ranks[status] for status in strategy.order_statuses
        )
        completed_callbacks = [
            item for item in strategy.order_callback_fills if item[0] == "Completed"
        ]
        assert completed_callbacks == [
            ("Completed", float(_FILL_QUANTITY), float(_FILL_FEE))
        ]
        assert strategy.duplicate_projection["service_execution_state"] == "FILLED"
        assert strategy.duplicate_projection["managed_execution_replayed"] is True
        assert strategy.position_after_duplicate == pytest.approx(float(_FILL_QUANTITY))
        assert strategy.position_price_after_duplicate == pytest.approx(float(_FILL_PRICE))
        assert strategy.executed_after_duplicate == pytest.approx(float(_FILL_QUANTITY))
        assert strategy.commission_after_duplicate == pytest.approx(float(_FILL_FEE))
        assert len(strategy.trade_callbacks) == 1
        assert strategy.trade_callbacks[0][0] == "Open"
        assert strategy.trade_callbacks[0][1] == pytest.approx(float(_FILL_QUANTITY))

        metrics = _host_metrics(host)
        assert metrics[0] == "metrics"
        assert metrics[1] == (_INTENT_ID,)
        assert metrics[2] == ()
        assert metrics[3] == (_INTENT_ID,)
        assert metrics[4] == (_INTENT_ID,)
        assert metrics[5] == (_INTENT_ID,)
        assert metrics[6:8] == ("FILLED", 1)
        assert Decimal(metrics[8]) == _FILL_QUANTITY
        assert Decimal(metrics[9]) == _FILL_PRICE
        assert Decimal(metrics[10]) == _FILL_FEE
    finally:
        if store is not None and store.is_connected:
            with suppress(Exception):
                store.stop()
        if runtime is not None and runtime.state not in {"closed", "failed"}:
            with suppress(Exception):
                runtime.close()
        cleanup = _close_host(host)

    assert cleanup["normal_close"] is True
    assert cleanup["forced_cleanup"] is False
