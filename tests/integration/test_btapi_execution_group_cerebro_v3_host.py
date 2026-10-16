"""One normal v3 C/P/F Cerebro flow through authenticated SDK ServiceHosts.

The account-owner and coordinator hosts use the accepted SDK local-process
fixture with a pinned SQLite-backed synthetic provider. The strategy's group
calls cross real ZMQ/CURVE ServiceClientRuntime connections; this is local
service integration evidence, not exchange or account acceptance.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import importlib
import importlib.util
import multiprocessing
import os
import socket
import sqlite3
import sys
import time
from copy import deepcopy
from contextlib import suppress
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

pytest.importorskip("bt_api_py")
pytest.importorskip("bt_api_execution")
pytest.importorskip("bt_api_risk")
pytest.importorskip("bt_api_monitor")
zmq = pytest.importorskip("zmq")
pandas = pytest.importorskip("pandas")

import backtrader as bt  # noqa: E402
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_execution import (  # noqa: E402
    GroupAccountReservationSnapshot,
    GroupBudgetLegQuote,
    GroupBudgetQuote,
    GroupBudgetReservation,
    GroupBudgetReservationState,
    GroupLegProgress,
    GroupOrderIntent,
    GroupOrderLegPlan,
    GroupOrderSnapshot,
    GroupOrderState,
    GroupReservationPhase,
    PortfolioGroupBudgetPolicy,
    Side,
    group_leg_intent_id,
)
from bt_api_monitor.durable import DurableOutbox  # noqa: E402
from bt_api_monitor.service_component import MonitorReadTarget  # noqa: E402
from bt_api_py.service_runtime import (  # noqa: E402
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)

from backtrader.stores.service_execution_group import (  # noqa: E402
    ServiceExecutionGroupAdapter,
    ServiceExecutionGroupError,
    ServiceExecutionGroupUnknownOutcomeError,
    ServiceStrategyGroupRoute,
)
from backtrader.stores.service_execution_session import (  # noqa: E402
    ServiceExecutionSession,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store  # noqa: E402
from tests.integration import test_btapi_execution_group_cerebro as p5a  # noqa: E402

_SDK_HOST_FIXTURE_ENV = "BT_API_PY_TESTS_ROOT"
_SDK_HOST_FIXTURE_MODULE = "_bt_api_py_group_local_process_host_fixture"
_SDK_PROVIDER_FIXTURE_MODULE = "tests.unit._service_group_provider_fixtures"

_MONITOR_SERVICE_ID = "v3-group-monitor-service"
_MONITOR_INSTANCE = "v3-group-monitor"
_MONITOR_PRINCIPAL = "v3-group-monitor-principal"
_MONITOR_SCOPE_REF = "v3-group-monitor-scope"
_MONITOR_RESIDUAL_SCOPE = "v3-group-residuals"
_MONITOR_LISTENER_REF = "v3-group-monitor-listener"
_MONITOR_SERVER_SECURITY_REF = "v3-group-monitor-server-curve"
_MONITOR_CLIENT_SECURITY_REF = "v3-group-monitor-client-curve"
_MONITOR_TRANSPORT_REF = "v3-group-monitor-connect"
_MONITOR_TIMEOUT_MS = 5_000
_MONITOR_MAX_MESSAGE_BYTES = 65_536

# Distinct, same-account Call/Put/Future keys exercise the accepted SDK v3
# coordinator contract with provider-native contract counts. The Call is the
# 1.0 reference leg (10 * 0.01 = 0.10 BTC); the Put is 0.5
# (5 * 0.01 = 0.05 BTC); and the Future is 2.0 (2 * 0.1 = 0.20 BTC). Their
# explicit metadata multipliers preserve each leg's base-unit exposure while
# the synthetic fixture uses its supported native-size order route.
_CPF_LEGS = (
    {
        "leg_id": "leg-call",
        "instrument": "BTC-USD-261127-110000-C",
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "price": Decimal("800"),
        "ratio": Decimal("1"),
        "step": Decimal("1"),
        "base_units": Decimal("0.01"),
        "gross_notional": Decimal("80"),
    },
    {
        "leg_id": "leg-put",
        "instrument": "BTC-USD-261127-90000-P",
        "side": Side.BUY,
        "quantity": Decimal("5"),
        "price": Decimal("1200"),
        "ratio": Decimal("0.5"),
        "step": Decimal("1"),
        "base_units": Decimal("0.01"),
        "gross_notional": Decimal("60"),
    },
    {
        "leg_id": "leg-future",
        "instrument": "BTC-USD-261127",
        "side": Side.SELL,
        "quantity": Decimal("2"),
        "price": Decimal("100000"),
        "ratio": Decimal("2"),
        "step": Decimal("1"),
        "base_units": Decimal("0.1"),
        "gross_notional": Decimal("20000"),
    },
)


def _load_sdk_host_fixture() -> ModuleType:
    """Load only the accepted SDK test support pinned by the focused runner."""

    tests_root_text = os.environ.get(_SDK_HOST_FIXTURE_ENV)
    if type(tests_root_text) is not str or not tests_root_text.strip():
        raise AssertionError(f"{_SDK_HOST_FIXTURE_ENV} must name the fixed SDK tests export")
    tests_root = Path(tests_root_text).resolve()
    provider_path = tests_root / "unit" / "_service_group_provider_fixtures.py"
    host_fixture_path = (
        tests_root / "integration" / "test_service_execution_group_local_process.py"
    )
    if not provider_path.is_file() or not host_fixture_path.is_file():
        raise AssertionError("fixed SDK group-host test support is incomplete")

    provider_module = sys.modules.get(_SDK_PROVIDER_FIXTURE_MODULE)
    if provider_module is not None:
        loaded_path = Path(getattr(provider_module, "__file__", "")).resolve()
        if loaded_path != provider_path:
            raise AssertionError("a different SDK synthetic provider fixture is already loaded")
    else:
        unit_package = sys.modules.get("tests.unit")
        if unit_package is None:
            # The Backtrader source export intentionally omits unrelated unit
            # tests. Install only the package anchor needed for this exact
            # pinned SDK fixture module; the fixture itself is loaded by path
            # and remains checked against BT_API_PY_TESTS_ROOT below.
            unit_package = ModuleType("tests.unit")
            unit_package.__path__ = []
            sys.modules["tests.unit"] = unit_package
        provider_spec = importlib.util.spec_from_file_location(
            _SDK_PROVIDER_FIXTURE_MODULE, provider_path
        )
        if provider_spec is None or provider_spec.loader is None:
            raise AssertionError("fixed SDK provider fixture cannot be loaded")
        provider_module = importlib.util.module_from_spec(provider_spec)
        sys.modules[_SDK_PROVIDER_FIXTURE_MODULE] = provider_module
        provider_spec.loader.exec_module(provider_module)
        setattr(unit_package, "_service_group_provider_fixtures", provider_module)

    host_module = sys.modules.get(_SDK_HOST_FIXTURE_MODULE)
    if host_module is not None:
        loaded_path = Path(getattr(host_module, "__file__", "")).resolve()
        if loaded_path != host_fixture_path:
            raise AssertionError("a different SDK group-host fixture is already loaded")
        return host_module
    host_spec = importlib.util.spec_from_file_location(
        _SDK_HOST_FIXTURE_MODULE, host_fixture_path
    )
    if host_spec is None or host_spec.loader is None:
        raise AssertionError("fixed SDK group-host fixture cannot be loaded")
    host_module = importlib.util.module_from_spec(host_spec)
    sys.modules[_SDK_HOST_FIXTURE_MODULE] = host_module
    host_spec.loader.exec_module(host_module)
    return host_module


def _cpf_metadata_records(base_metadata):
    """Build exact typed risk metadata for the three v3 instruments."""

    return tuple(
        replace(
            base_metadata,
            instrument=spec["instrument"],
            contract_multiplier=spec["base_units"],
            quantity_step=spec["step"],
            quantity_unit="native",
        )
        for spec in _CPF_LEGS
    )


def _configure_v3_sdk_host_fixture(fixture) -> None:
    """Expand the accepted SDK's single-instrument host fixture in memory.

    The fixed SDK test files remain byte-for-byte accepted inputs. These
    process-local constructor adapters preserve their real typed return values
    while supplying three trusted instrument records to the real host path.
    """

    original_registry = fixture.InstrumentRiskRegistry

    def _registry_with_cpf_instruments(records):
        expanded = []
        for record in records:
            if record.instrument == fixture._V2_INSTRUMENT:
                expanded.extend(_cpf_metadata_records(record))
            else:
                expanded.append(record)
        return original_registry(tuple(expanded))

    fixture.InstrumentRiskRegistry = _registry_with_cpf_instruments

    original_provider_contract = fixture.RiskBtApiProviderContract

    def _provider_contract_with_cpf_quotes(*args, **kwargs):
        if kwargs.get("normalizer_schema") == "bt-api-order-source-provenance-v2":
            kwargs["quote_currency_by_instrument"] = tuple(
                sorted((spec["instrument"], "USD") for spec in _CPF_LEGS)
            )
        return original_provider_contract(*args, **kwargs)

    fixture.RiskBtApiProviderContract = _provider_contract_with_cpf_quotes

    original_route_type = fixture.GroupAccountRoute

    def _route_with_cpf_instruments(*args, **kwargs):
        route = original_route_type(*args, **kwargs)
        if set(route.instruments) != {fixture._V2_INSTRUMENT}:
            return route
        base_metadata = route.instruments[fixture._V2_INSTRUMENT].metadata
        instrument_rules = {
            meta.instrument: fixture.GroupInstrumentRule(
                metadata=meta,
                base_units_per_order_unit=spec["base_units"],
                allowed_order_types=route.instruments[
                    fixture._V2_INSTRUMENT
                ].allowed_order_types,
            )
            for spec, meta in zip(
                _CPF_LEGS,
                _cpf_metadata_records(base_metadata),
                strict=True,
            )
        }
        return replace(route, instruments=instrument_rules)

    fixture.GroupAccountRoute = _route_with_cpf_instruments

    def _cpf_provider_make_order(
        provider,
        symbol,
        volume,
        price,
        order_type,
        *,
        client_order_id,
        **kwargs,
    ):
        expected = next(
            (spec for spec in _CPF_LEGS if spec["instrument"] == symbol), None
        )
        assert expected is not None
        assert Decimal(str(volume)) == expected["quantity"]
        assert Decimal(str(price)) == expected["price"]
        assert order_type == expected["side"].value.lower() + "-limit"
        assert client_order_id.startswith("grp-") and len(client_order_id) == 44
        assert kwargs == {
            "offset": "open",
            "post_only": False,
            "reduce_only": False,
            "time_in_force": "IOC",
        }
        return fixture._V2SyntheticBtApiFeed.make_order(
            provider,
            symbol,
            volume,
            price,
            order_type,
            client_order_id=client_order_id,
            **kwargs,
        )

    fixture._GroupMappedV2SyntheticFeed.make_order = _cpf_provider_make_order


def _read_provider_order_facts(path: str) -> dict[str, dict[str, str]]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT client_order_id, order_json FROM provider_orders ORDER BY client_order_id"
        ).fetchall()
    return {str(client_id): json.loads(payload) for client_id, payload in rows}


def _read_group_proof_provider_requests(path: str) -> tuple[tuple[str, dict], ...]:
    """Read the persisted, SDK-bound request facts without opening SQLite for writes."""

    database_uri = f"file:{Path(path).as_posix()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT leg_id, payload_json FROM group_proof_events "
            "WHERE event_type='ATTEMPT_STARTED' ORDER BY revision"
        ).fetchall()
    return tuple(
        (str(leg_id), json.loads(payload_json)["provider_request"])
        for leg_id, payload_json in rows
    )


def _account_host_entry(control, *args) -> None:
    fixture = _load_sdk_host_fixture()
    _configure_v3_sdk_host_fixture(fixture)
    import bt_api_py.service_execution_group as service_group_module
    import bt_api_py.service_execution_group_proofs as proof_module

    original_submit = service_group_module.ExecutionGroupOrderEntryService._submit
    original_provider_submit = proof_module.GroupProofDispatchSession.submit
    submit_diagnostics = []
    provider_submit_diagnostics = []
    paths = args[2] if len(args) > 2 and isinstance(args[2], dict) else {}
    diagnostics_path = paths.get("submit_diagnostics")
    provider_diagnostics_path = paths.get("provider_submit_diagnostics")

    def _safe_exception_projection(error):
        projection = []
        current = error
        for _ in range(4):
            if current is None:
                break
            name = type(current).__name__
            if type(name) is not str or not name.isascii() or not name.isidentifier():
                name = "UNCLASSIFIED_ERROR"
            try:
                code = getattr(current, "code", None)
            except BaseException:
                code = None
            if (
                type(code) is not str
                or not code.isascii()
                or len(code) > 96
                or any(not (character.isalnum() or character in "_.:-") for character in code)
            ):
                code = None
            frames = []
            traceback = current.__traceback__
            while traceback is not None and len(frames) < 8:
                function = traceback.tb_frame.f_code.co_name
                line = traceback.tb_lineno
                if (
                    type(function) is str
                    and function.isascii()
                    and function.isidentifier()
                    and type(line) is int
                    and line > 0
                ):
                    frames.append((function, line))
                traceback = traceback.tb_next
            projection.append((name, code, tuple(frames)))
            current = current.__context__
        return tuple(projection)

    def _capture_account_submit(self, *call_args, **call_kwargs):
        try:
            return original_submit(self, *call_args, **call_kwargs)
        except BaseException as error:
            if len(submit_diagnostics) < 8:
                try:
                    submit_diagnostics.append(_safe_exception_projection(error))
                except BaseException:
                    submit_diagnostics.append((
                        ("UNCLASSIFIED_ERROR", None, ()),
                    ))
                if type(diagnostics_path) is str:
                    try:
                        Path(diagnostics_path).write_text(
                            json.dumps(
                                {"attempts": tuple(submit_diagnostics)},
                                ensure_ascii=True,
                                separators=(",", ":"),
                            ),
                            encoding="utf-8",
                        )
                    except BaseException:
                        # Diagnostics must never alter the account service's
                        # fail-closed response or replace its primary error.
                        pass
            raise

    def _capture_provider_submit(self, *call_args, **call_kwargs):
        try:
            return original_provider_submit(self, *call_args, **call_kwargs)
        except BaseException as error:
            if len(provider_submit_diagnostics) < 8:
                try:
                    provider_submit_diagnostics.append(
                        _safe_exception_projection(error)
                    )
                except BaseException:
                    provider_submit_diagnostics.append(
                        (("UNCLASSIFIED_ERROR", None, ()),)
                    )
                if type(provider_diagnostics_path) is str:
                    try:
                        Path(provider_diagnostics_path).write_text(
                            json.dumps(
                                {"attempts": tuple(provider_submit_diagnostics)},
                                ensure_ascii=True,
                                separators=(",", ":"),
                            ),
                            encoding="utf-8",
                        )
                    except BaseException:
                        # Keep this same-call diagnostic from changing the
                        # dispatch result or masking its primary exception.
                        pass
            raise

    service_group_module.ExecutionGroupOrderEntryService._submit = _capture_account_submit
    proof_module.GroupProofDispatchSession.submit = _capture_provider_submit
    try:
        fixture._account_host_process(control, *args)
    finally:
        service_group_module.ExecutionGroupOrderEntryService._submit = original_submit
        proof_module.GroupProofDispatchSession.submit = original_provider_submit


def _coordinator_host_entry(control, *args) -> None:
    fixture = _load_sdk_host_fixture()
    _configure_v3_sdk_host_fixture(fixture)
    # This round binds one strategy route to the single account required by
    # the accepted same-account three-leg contract.
    fixture._ACCOUNTS = ("account-a",)
    import bt_api_py.service_execution_group as service_group_module

    submit_diagnostics = []
    original_submit_group_leg = service_group_module._OrdersRpcPort.submit_group_leg

    def _capture_submit_group_leg(self, intent, permit):
        try:
            receipt = original_submit_group_leg(self, intent, permit)
        except BaseException as error:
            code = getattr(error, "code", None)
            if (
                type(code) is not str
                or not code.isascii()
                or len(code) > 96
                or any(not (character.isalnum() or character in "_.:-") for character in code)
            ):
                code = None
            submit_diagnostics.append(("raised", type(error).__name__, code))
            raise
        status = getattr(receipt, "status", None)
        state = getattr(getattr(status, "state", None), "value", None)
        if type(state) is not str or not state.isascii() or len(state) > 64:
            state = None
        submit_diagnostics.append(
            (
                "returned",
                type(receipt).__name__,
                state,
                str(getattr(status, "filled_quantity", ""))[:64],
                getattr(receipt, "claim", None) is not None,
                getattr(getattr(receipt, "resolution", None), "resolution_kind", None),
            )
        )
        return receipt

    service_group_module._OrdersRpcPort.submit_group_leg = _capture_submit_group_leg

    class _CoordinatorControlProxy:
        _pending_command = None

        def poll(self, timeout=0):
            if not control.poll(timeout):
                return False
            command = control.recv()
            if command == "diagnostics":
                control.send(("diagnostics", tuple(submit_diagnostics)))
                return False
            self._pending_command = command
            return True

        def send(self, value):
            return control.send(value)

        def recv(self):
            if self._pending_command is not None:
                command = self._pending_command
                self._pending_command = None
                return command
            command = control.recv()
            return command

        def close(self):
            return control.close()

    fixture._coordinator_host_process(_CoordinatorControlProxy(), *args)


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _monitor_service_config(endpoint: str) -> dict:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _MONITOR_SERVICE_ID,
        "scope_ref": "v3-group-monitor-root",
        "transport_ref": _MONITOR_LISTENER_REF,
        "registration_policy_ref": "v3-group-monitor-registration",
        "service_requirements_ref": "v3-group-monitor-requirements",
        "components": {
            "monitor": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _MONITOR_INSTANCE,
                    "bind_ports": ["service.monitor_query"],
                    "options": {},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _MONITOR_LISTENER_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _MONITOR_SERVER_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MONITOR_MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _monitor_host_process(
    control,
    raw_config: dict,
    registry_path: str,
    outbox_path: str,
    server_public: bytes,
    server_secret: bytes,
    strategy_client_public: bytes,
) -> None:
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_monitor.durable import DurableOutbox
    from bt_api_monitor.service_component import MonitorReadTarget
    from bt_api_py.service_components import ComponentResources
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    stage = "parse_service_config"
    config = None
    host = None
    outbox = None
    try:
        config = parse_service_config(raw_config)
        stage = "open_monitor_outbox"
        outbox = DurableOutbox(outbox_path, read_only=True)
        scope = WireScope(
            "paper:group-process",
            strategy_ref="strategy-group-process",
            portfolio_ref="portfolio-group-process",
        )
        service_identity = WireIdentity(
            WireRole.SERVICE, _MONITOR_PRINCIPAL, _MONITOR_SERVICE_ID
        )
        strategy_identity = WireIdentity(
            WireRole.STRATEGY_CLIENT,
            "group-strategy-principal",
            "strategy-group-process",
        )

        def resource_provider(component, instance_id, _options, _host_scope):
            if component != "monitor" or instance_id != _MONITOR_INSTANCE:
                raise AssertionError("unexpected v3 Monitor resource request")
            return ComponentResources.borrowed(
                {
                    "outbox": outbox,
                    "targets": {
                        scope: MonitorReadTarget(
                            _MONITOR_RESIDUAL_SCOPE, ("group.residual",)
                        )
                    },
                },
                ready=lambda: True,
            )

        stage = "construct_service_host"
        host = ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=service_identity,
                scope=WireScope("paper:group-process"),
                scope_ref=config.scope_ref,
                scope_version="v3-group-monitor-scope-v1",
                security_ref=_MONITOR_SERVER_SECURITY_REF,
                security_version="v3-group-monitor-curve-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version="v3-group-monitor-registration-v1",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version="v3-group-monitor-requirements-v1",
                curve_public_key=server_public,
                curve_secret_key=server_secret,
                principals={strategy_client_public: "group-strategy-principal"},
                grants={
                    "group-strategy-principal": (
                        PrincipalGrant(
                            strategy_identity,
                            (
                                ResourceGrant(
                                    _MONITOR_INSTANCE,
                                    "service.monitor_query",
                                    _MONITOR_SCOPE_REF,
                                    scope,
                                    frozenset({"monitor.read_after"}),
                                ),
                            ),
                        ),
                    )
                },
            ),
            registry_path,
            resource_provider,
        )
        stage = "start_service_host"
        host.start()
        stage = "announce_service_host_ready"
        control.send(("ready", host.endpoint, host.state))
        stage = "serve_service_host"
        while True:
            host.serve_once(timeout_ms=15)
            if not control.poll(0):
                continue
            if control.recv() == "close":
                stage = "close_service_host"
                host.close()
                stage = "announce_service_host_closed"
                control.send(("closed", host.state))
                return
            raise AssertionError("unknown v3 Monitor control command")
    except BaseException as error:
        summary = host.summary if host is not None else {}
        host_start_failure = summary.get("start_failure")
        if type(host_start_failure) is not str or len(host_start_failure) > 96:
            host_start_failure = None
        host_cleanup_failures = summary.get("cleanup_failures", ())
        if (
            type(host_cleanup_failures) is not tuple
            or len(host_cleanup_failures) > 16
            or any(type(item) is not str or len(item) > 96 for item in host_cleanup_failures)
        ):
            host_cleanup_failures = ()
        failure_code = getattr(error, "code", None)
        if type(failure_code) is not str:
            failure_code = type(error).__name__
        if not failure_code.isascii() or not failure_code or len(failure_code) > 96:
            failure_code = "UNCLASSIFIED_ERROR"
        cause_projection = []
        cause = error.__context__
        for _ in range(3):
            if cause is None:
                break
            cause_type = type(cause).__name__
            if (
                type(cause_type) is not str
                or not cause_type.isascii()
                or not cause_type.isidentifier()
                or len(cause_type) > 64
            ):
                cause_type = "UNCLASSIFIED_ERROR"
            cause_code = getattr(cause, "code", None)
            if (
                type(cause_code) is not str
                or not cause_code
                or not cause_code.isascii()
                or len(cause_code) > 96
                or any(not (character.isalnum() or character in "_.:-") for character in cause_code)
            ):
                cause_code = None
            cause_projection.append((cause_type, cause_code))
            cause = cause.__context__
        if host is not None and host.state not in {"closed", "failed"}:
            with suppress(BaseException):
                host.close()
        with suppress(Exception):
            control.send(
                (
                    "error",
                    stage,
                    failure_code,
                    host_start_failure,
                    host_cleanup_failures,
                    tuple(cause_projection),
                )
            )
        raise
    finally:
        if host is not None and host.state != "closed":
            with suppress(BaseException):
                host.close()
        # DurableOutbox owns no persistent connection: each operation uses
        # its _connection context manager and closes that SQLite handle.
        # It deliberately has no instance close() API.
        control.close()


def _receive(control, *, timeout: float = 25.0):
    if not control.poll(timeout):
        raise TimeoutError("v3 group ServiceHost missed its bounded response")
    message = control.recv()
    if not message or message[0] == "error":
        raise AssertionError(f"v3 group ServiceHost startup failed: {message!r}")
    return message


def _start_process(context, *, name: str, target, args: tuple):
    parent_control, child_control = context.Pipe(duplex=True)
    process = context.Process(name=name, target=target, args=(child_control, *args))
    try:
        process.start()
    except BaseException:
        child_control.close()
        parent_control.close()
        raise
    child_control.close()
    return process, parent_control


class _DeferredProcessClose:
    """Keep exit facts available after the pinned SDK close helper returns."""

    def __init__(self, process) -> None:
        self._process = process
        self.close_requested = False

    def __getattr__(self, name):
        return getattr(self._process, name)

    def close(self) -> None:
        self.close_requested = True


class _ObservedHostControl:
    """Retain the SDK helper's close acknowledgement for exact assertions."""

    def __init__(self, control) -> None:
        self._control = control
        self.close_reply = None

    def __getattr__(self, name):
        return getattr(self._control, name)

    def recv(self):
        message = self._control.recv()
        if message and message[0] == "closed":
            self.close_reply = message
        return message


def _with_monitor_route(raw_client_config: dict, fixture, monitor_endpoint: str) -> dict:
    raw = raw_client_config
    raw["clients"]["monitor"] = {
        "config_schema_version": 1,
        "settings": {
            "bindings": [
                {
                    "mount": "broker.group_monitor",
                    "service_id": _MONITOR_SERVICE_ID,
                    "instance_id": _MONITOR_INSTANCE,
                    "scope_ref": _MONITOR_SCOPE_REF,
                    "portfolio_ref": fixture._PORTFOLIO,
                    "transport_ref": _MONITOR_TRANSPORT_REF,
                }
            ],
            "options": {
                "request_timeout_ms": _MONITOR_TIMEOUT_MS,
                "heartbeat_interval_seconds": 5,
            },
        },
    }
    raw["communication"]["profiles"][_MONITOR_TRANSPORT_REF] = fixture._profile(
        monitor_endpoint,
        server=False,
        security_ref=_MONITOR_CLIENT_SECURITY_REF,
    )
    return raw


def _v3_intent(fixture, *, metadata_reference_ns: int, group_id: str) -> GroupOrderIntent:
    now_ns = time.time_ns()
    deadline_ns = now_ns + 120_000_000_000
    metadata = _cpf_metadata_records(fixture._metadata(metadata_reference_ns))
    plans = []
    for spec, metadata_record in zip(_CPF_LEGS, metadata, strict=True):
        maximum_intent = fixture._intent(
            group_id,
            spec["leg_id"],
            "account-a",
            spec["side"],
            deadline_ns,
            metadata_record,
        )
        maximum_intent = replace(
            maximum_intent,
            quantity=spec["quantity"],
            price=spec["price"],
        )
        plans.append(
            GroupOrderLegPlan(
                leg_id=spec["leg_id"],
                account_ref="account-a",
                maximum_intent=maximum_intent,
                base_units_per_order_unit=spec["base_units"],
                quantity_step=spec["step"],
                metadata_valid_until_ns=metadata_record.expires_at_ns,
                ratio=spec["ratio"],
            )
        )
    return GroupOrderIntent(
        version=3,
        group_id=group_id,
        portfolio_ref=fixture._PORTFOLIO,
        strategy_id=fixture._STRATEGY,
        coordinator_principal_ref=fixture._COORDINATOR_PRINCIPAL,
        received_at_ns=now_ns,
        deadline_ns=deadline_ns,
        first_leg_id="leg-call",
        legs=tuple(plans),
    )


def _synthetic_group_snapshot_reply(
    intent: GroupOrderIntent,
    *,
    server_received_at_ns: int,
    server_principal_ref: str,
) -> dict:
    """Build a typed reply with coordinator-normalized server-owned fields."""

    policy = PortfolioGroupBudgetPolicy(
        portfolio_ref=intent.portfolio_ref,
        policy_id="tamper-test-budget-policy",
        policy_version=1,
        valuation_unit="USD",
        max_group_gross_notional=Decimal("10"),
        max_active_gross_notional=Decimal("20"),
        max_active_groups=2,
    )
    quote_legs = tuple(
        GroupBudgetLegQuote(
            leg_id=plan.leg_id,
            account_ref=plan.account_ref,
            intent_fingerprint=plan.maximum_intent.fingerprint,
            metadata_digest=plan.maximum_intent.tags["instrument_metadata_digest"],
            assessment_fingerprint=hashlib.sha256(
                f"tamper-assessment:{plan.leg_id}".encode("utf-8")
            ).hexdigest(),
            valuation_unit="USD",
            gross_notional=Decimal("1"),
            assessed_at_ns=server_received_at_ns,
            valid_until_ns=intent.deadline_ns + 1,
        )
        for plan in intent.legs
    )
    quote = GroupBudgetQuote(
        policy_fingerprint=policy.fingerprint,
        valuation_unit="USD",
        gross_notional=Decimal(len(quote_legs)),
        legs=quote_legs,
    )
    accepted_request = replace(
        intent,
        version=2 if intent.version == 1 else intent.version,
        coordinator_principal_ref=server_principal_ref,
        received_at_ns=server_received_at_ns,
        budget_quote=quote,
    )
    reservation = GroupBudgetReservation(
        policy_fingerprint=policy.fingerprint,
        policy=policy,
        quote_fingerprint=quote.fingerprint,
        valuation_unit=quote.valuation_unit,
        gross_notional=quote.gross_notional,
        deadline_ns=intent.deadline_ns,
        state=GroupBudgetReservationState.HELD,
    )
    scope_fingerprint = hashlib.sha256(b"v3-tamper-test-scope").hexdigest()
    snapshot = GroupOrderSnapshot(
        request=accepted_request,
        state=GroupOrderState.PAIRED,
        revision=1,
        reservations=tuple(
            GroupAccountReservationSnapshot(
                group_id=intent.group_id,
                account_ref=account_ref,
                scope_fingerprint=scope_fingerprint,
                phase="ACTIVE",
            )
            for account_ref in intent.account_refs
        ),
        legs=tuple(GroupLegProgress(leg_id=plan.leg_id) for plan in intent.legs),
        residual_base_units=Decimal("0"),
        error_code=None,
        created_at_ns=server_received_at_ns,
        updated_at_ns=server_received_at_ns,
        budget_reservation=reservation,
        residual_vector=(
            tuple(Decimal("0") for _ in intent.legs)
            if accepted_request.version == 3
            else None
        ),
    )
    return {
        "ok": True,
        "code": "OK",
        "result": {"found": True, "snapshot": snapshot.to_payload()},
    }


class _SyntheticGroupReplyLeaf:
    """Final local reply leaf; the production adapter parses its payload."""

    def __init__(self, reply: dict) -> None:
        self.reply = reply
        self.calls = []

    def call(self, mount, operation, arguments, **kwargs):
        self.calls.append((mount, operation, deepcopy(arguments), dict(kwargs)))
        return deepcopy(self.reply)


def _adapter_for_synthetic_reply(intent: GroupOrderIntent, reply: dict):
    broker = object()
    strategy = SimpleNamespace(
        broker=broker,
        p=SimpleNamespace(
            strategy_ref=intent.strategy_id,
            portfolio_ref=intent.portfolio_ref,
        ),
    )
    route_key = (intent.strategy_id, intent.portfolio_ref)
    runtime = _SyntheticGroupReplyLeaf(reply)
    route = ServiceStrategyGroupRoute(
        strategy_ref=intent.strategy_id,
        portfolio_ref=intent.portfolio_ref,
        account_refs=intent.account_refs,
        runtime=runtime,
        group_scope_ref="synthetic-group-scope",
        monitor_scope_ref="synthetic-monitor-scope",
    )
    session = SimpleNamespace(_state="running", _broker=broker)
    adapter = ServiceExecutionGroupAdapter(session, (route,))
    # This node isolates reply binding; the neighboring Cerebro node exercises
    # actual route registration and Strategy binding over local CURVE hosts.
    adapter._registered = True
    adapter._owners[route_key] = strategy
    adapter._bound_by_object[id(strategy)] = (strategy, route_key)
    return adapter, strategy, broker, runtime


def test_adapter_binds_wire_plan_accepts_v1_and_rejects_tampered_plan_metadata():
    fixture = _load_sdk_host_fixture()
    fixture._ACCOUNTS = ("account-a",)
    generated_intent = _v3_intent(
        fixture, metadata_reference_ns=time.time_ns(), group_id="bt-cerebro-v3-tamper-001"
    )
    # These fields are client-side hints only: the service derives both from
    # its trusted clock and coordinator identity, and neither is sent on wire.
    intent = replace(generated_intent, coordinator_principal_ref="client-coordinator-hint")
    server_received_at_ns = intent.received_at_ns + 17
    reply = _synthetic_group_snapshot_reply(
        intent,
        server_received_at_ns=server_received_at_ns,
        server_principal_ref=fixture._COORDINATOR_PRINCIPAL,
    )

    valid_adapter, strategy, broker, valid_runtime = _adapter_for_synthetic_reply(
        intent, reply
    )
    valid_snapshot = valid_adapter.submit(strategy, broker, intent)
    assert valid_snapshot.request.version == 3
    assert valid_snapshot.request.budget_quote is not None
    assert valid_snapshot.request.coordinator_principal_ref == fixture._COORDINATOR_PRINCIPAL
    assert valid_snapshot.request.coordinator_principal_ref != intent.coordinator_principal_ref
    assert valid_snapshot.request.received_at_ns == server_received_at_ns
    assert valid_snapshot.request.received_at_ns != intent.received_at_ns
    assert len(valid_runtime.calls) == 1
    mount, operation, arguments, kwargs = valid_runtime.calls[0]
    assert (mount, operation) == ("broker.order_groups", "groups.submit")
    assert arguments == {
        "version": 3,
        "group_id": intent.group_id,
        "deadline_ns": intent.deadline_ns,
        "first_leg_id": intent.first_leg_id,
        "legs": [
            {
                "leg_id": plan.leg_id,
                "account_ref": plan.account_ref,
                "intent": plan.maximum_intent.to_payload(),
                "ratio": format(plan.ratio, "f"),
            }
            for plan in intent.legs
        ],
    }
    assert "coordinator_principal_ref" not in arguments
    assert "received_at_ns" not in arguments
    assert kwargs == {
        "portfolio_ref": intent.portfolio_ref,
        "scope_ref": "synthetic-group-scope",
    }

    tamper_cases = (
        ("base_units_per_order_unit", "0.02"),
        ("quantity_step", "2"),
        (
            "metadata_valid_until_ns",
            intent.legs[0].metadata_valid_until_ns + 1,
        ),
    )
    for field, changed_value in tamper_cases:
        tampered_reply = deepcopy(reply)
        tampered_reply["result"]["snapshot"]["request"]["legs"][0][field] = changed_value
        # This remains a valid SDK snapshot, isolating rejection to the
        # adapter's comparison against the caller's exact original plan.
        parsed = GroupOrderSnapshot.from_payload(tampered_reply["result"]["snapshot"])
        expected_value = (
            changed_value
            if field == "metadata_valid_until_ns"
            else Decimal(changed_value)
        )
        assert getattr(parsed.request.legs[0], field) == expected_value
        adapter, strategy, broker, runtime = _adapter_for_synthetic_reply(
            intent, tampered_reply
        )
        with pytest.raises(ServiceExecutionGroupUnknownOutcomeError) as error:
            adapter.submit(strategy, broker, intent)
        assert error.value.code == "REQUEST_OUTCOME_UNKNOWN"
        assert error.value.group_id == intent.group_id
        assert len(runtime.calls) == 1

    # The legacy unversioned body remains v1 on the wire. The current service
    # may normalize a newly accepted v1 request to budget-quoted v2; the
    # adapter must accept that exact contract and its server-owned identity/time.
    legacy_group_id = "bt-cerebro-v1-server-normalized-001"
    legacy_legs = tuple(
        replace(
            plan,
            maximum_intent=replace(
                plan.maximum_intent,
                intent_id=group_leg_intent_id(legacy_group_id, plan.leg_id),
            ),
            ratio=None,
        )
        for plan in (intent.legs[0], intent.legs[2])
    )
    legacy_intent = GroupOrderIntent(
        version=1,
        group_id=legacy_group_id,
        portfolio_ref=intent.portfolio_ref,
        strategy_id=intent.strategy_id,
        coordinator_principal_ref="client-v1-coordinator-hint",
        received_at_ns=intent.received_at_ns,
        deadline_ns=intent.deadline_ns,
        first_leg_id=legacy_legs[0].leg_id,
        legs=legacy_legs,
    )
    legacy_server_received_at_ns = legacy_intent.received_at_ns + 29
    legacy_reply = _synthetic_group_snapshot_reply(
        legacy_intent,
        server_received_at_ns=legacy_server_received_at_ns,
        server_principal_ref=fixture._COORDINATOR_PRINCIPAL,
    )
    legacy_adapter, legacy_strategy, legacy_broker, legacy_runtime = (
        _adapter_for_synthetic_reply(legacy_intent, legacy_reply)
    )
    legacy_snapshot = legacy_adapter.submit(
        legacy_strategy, legacy_broker, legacy_intent
    )
    assert legacy_snapshot.request.version == 2
    assert legacy_snapshot.request.budget_quote is not None
    assert legacy_snapshot.request.coordinator_principal_ref == fixture._COORDINATOR_PRINCIPAL
    assert legacy_snapshot.request.received_at_ns == legacy_server_received_at_ns
    assert len(legacy_runtime.calls) == 1
    legacy_mount, legacy_operation, legacy_arguments, legacy_kwargs = legacy_runtime.calls[0]
    assert legacy_mount == "broker.order_groups"
    assert legacy_operation == "groups.submit"
    assert legacy_arguments == {
        "group_id": legacy_intent.group_id,
        "deadline_ns": legacy_intent.deadline_ns,
        "first_leg_id": legacy_intent.first_leg_id,
        "legs": [
            {
                "leg_id": plan.leg_id,
                "account_ref": plan.account_ref,
                "intent": plan.maximum_intent.to_payload(),
            }
            for plan in legacy_intent.legs
        ],
    }
    assert "version" not in legacy_arguments
    assert all("ratio" not in leg for leg in legacy_arguments["legs"])
    assert legacy_kwargs == {
        "portfolio_ref": legacy_intent.portfolio_ref,
        "scope_ref": "synthetic-group-scope",
    }


def test_submit_business_error_envelopes_preserve_unknown_and_definite_rejection():
    fixture = _load_sdk_host_fixture()
    fixture._ACCOUNTS = ("account-a",)
    ambiguous_replies = (
        {
            "ok": False,
            "code": "GROUP_ORDER_OUTCOME_UNPROVEN",
            "result": {},
        },
        {
            "ok": False,
            "code": "GROUP_ORDER_UNAVAILABLE",
            "result": {},
        },
        # A transport-success/business-success shape with an invalid result is
        # still uncertain: the service may have advanced before serialization.
        {"ok": True, "code": "OK", "result": []},
    )
    for index, reply in enumerate(ambiguous_replies):
        group_id = f"bt-cerebro-envelope-unknown-{index}"
        intent = _v3_intent(
            fixture, metadata_reference_ns=time.time_ns(), group_id=group_id
        )
        adapter, strategy, broker, runtime = _adapter_for_synthetic_reply(
            intent, reply
        )
        with pytest.raises(ServiceExecutionGroupUnknownOutcomeError) as error:
            adapter.submit(strategy, broker, intent)
        assert error.value.code == "REQUEST_OUTCOME_UNKNOWN"
        assert error.value.group_id == group_id

        # Recovery is a query under the immutable original group ID, never a
        # second submit or a replacement group after an ambiguous reply.
        runtime.reply = {
            "ok": True,
            "code": "OK",
            "result": {"found": False, "snapshot": None},
        }
        assert adapter.query(strategy, broker, group_id) is None
        assert [call[1] for call in runtime.calls] == [
            "groups.submit",
            "groups.query",
        ]
        assert runtime.calls[0][2]["group_id"] == group_id
        assert runtime.calls[1][2] == {"group_id": group_id}

    # The accepted SDK emits this code only when durable coordinator accept
    # fails before advance_group (and therefore before provider dispatch).
    group_id = "bt-cerebro-envelope-definite-001"
    intent = _v3_intent(
        fixture, metadata_reference_ns=time.time_ns(), group_id=group_id
    )
    adapter, strategy, broker, runtime = _adapter_for_synthetic_reply(
        intent,
        {
            "ok": False,
            "code": "GROUP_ACCEPTANCE_REJECTED",
            "result": {},
        },
    )
    with pytest.raises(ServiceExecutionGroupError) as error:
        adapter.submit(strategy, broker, intent)
    assert type(error.value) is ServiceExecutionGroupError
    assert error.value.code == "GROUP_ACCEPTANCE_REJECTED"
    assert error.value.group_id == group_id
    assert [call[1] for call in runtime.calls] == ["groups.submit"]


class _V3PairedGroupStrategy(bt.Strategy):
    params = (
        ("strategy_ref", "strategy-group-process"),
        ("portfolio_ref", "portfolio-group-process"),
        ("intent", None),
    )

    def start(self):
        self.bind_service_execution_group()
        self.before_group = (
            self.broker.getcash(),
            self.broker.getvalue(),
            self.broker.getposition(self.data).size,
        )

    def next(self):
        self.submitted = self.submit_group_order(self.p.intent)
        self.queried = self.query_group_order(self.p.intent.group_id)
        self.after_group = (
            self.broker.getcash(),
            self.broker.getvalue(),
            self.broker.getposition(self.data).size,
        )


def _cerebro(broker, intent):
    day = dt.datetime(2026, 10, 16)
    frame = pandas.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=[day],
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    for spec in _CPF_LEGS:
        cerebro.adddata(
            bt.feeds.PandasData(dataname=frame.copy(deep=True)),
            name=spec["instrument"],
        )
    cerebro.addstrategy(_V3PairedGroupStrategy, intent=intent)
    return cerebro


def _client_group_runtime(fixture, endpoint: str, keys, monitor_endpoint: str, monitor_keys):
    raw_config = _with_monitor_route(
        fixture._strategy_client_config(endpoint, "strategy-client-security-v1"),
        fixture,
        monitor_endpoint,
    )
    from bt_api_py.service_config import parse_client_config

    config = parse_client_config(raw_config)
    identity = WireIdentity(
        WireRole.STRATEGY_CLIENT, fixture._STRATEGY_PRINCIPAL, fixture._STRATEGY
    )
    coordinator_identity = WireIdentity(
        WireRole.SERVICE, fixture._COORDINATOR_PRINCIPAL, fixture._COORDINATOR_SERVICE_ID
    )
    monitor_identity = WireIdentity(WireRole.SERVICE, _MONITOR_PRINCIPAL, _MONITOR_SERVICE_ID)
    return ServiceClientRuntime(
        config,
        identity=identity,
        scope_resolver=lambda scope_ref: (
            fixture._stable_strategy_scope()
            if scope_ref == fixture._COORDINATOR_SCOPE_REF
            else WireScope(
                fixture._DOMAIN,
                strategy_ref=fixture._STRATEGY,
                portfolio_ref=fixture._PORTFOLIO,
            )
        ),
        peer_resolver=lambda service_id: coordinator_identity
        if service_id == fixture._COORDINATOR_SERVICE_ID
        else monitor_identity,
        transport_factory=ZmqTransportFactory(
            {
                "strategy-client-security-v1": ClientCurveKeys(
                    server_key=keys["server_public"],
                    public_key=keys["client_public"],
                    secret_key=keys["client_secret"],
                ),
                _MONITOR_CLIENT_SECURITY_REF: ClientCurveKeys(
                    server_key=monitor_keys["server_public"],
                    public_key=keys["client_public"],
                    secret_key=keys["client_secret"],
                ),
            }
        ),
        run_id=fixture._RUN,
        requested_operations={
            "broker.order_groups": frozenset({"groups.submit", "groups.query"}),
            "broker.group_monitor": frozenset({"monitor.read_after"}),
        },
    )


def test_v3_cerebro_paired_three_leg_snapshot_over_real_curve_hosts(tmp_path):
    fixture = _load_sdk_host_fixture()
    fixture._ACCOUNTS = ("account-a",)
    metadata_reference_ns = time.time_ns()
    intent = _v3_intent(
        fixture,
        metadata_reference_ns=metadata_reference_ns,
        group_id="bt-cerebro-v3-paired-001",
    )

    account_paths = {
        name: str(tmp_path / f"account-a-{name}.sqlite3")
        for name in (
            "registry",
            "provider",
            "execution",
            "risk_order_journal",
            "proof",
            "risk_gate",
            "accepted",
            "group_authority",
        )
    }
    account_paths["submit_diagnostics"] = str(
        tmp_path / "account-a-submit-diagnostics.json"
    )
    account_paths["provider_submit_diagnostics"] = str(
        tmp_path / "account-a-provider-submit-diagnostics.json"
    )
    coordinator_paths = {
        "registry": str(tmp_path / "coordinator-registry.sqlite3"),
        "groups": str(tmp_path / "coordinator-groups.sqlite3"),
        "run_bindings": str(tmp_path / "coordinator-run-bindings.sqlite3"),
    }
    account_endpoint = fixture._endpoint()
    account_server_public, account_server_secret = zmq.curve_keypair()
    coordinator_server_public, coordinator_server_secret = zmq.curve_keypair()
    coordinator_client_public, coordinator_client_secret = zmq.curve_keypair()
    strategy_client_public, strategy_client_secret = zmq.curve_keypair()
    monitor_server_public, monitor_server_secret = zmq.curve_keypair()
    account_configs = {
        "account-a": fixture._account_service_config(
            "account-a", account_endpoint, "account-server-security-account-a"
        )
    }
    coordinator_endpoint = fixture._endpoint()
    coordinator_raw = fixture._coordinator_service_config(
        coordinator_endpoint,
        "coordinator-server-security-v1",
        account_configs,
        {"account-a": account_endpoint},
    )
    monitor_endpoint = _endpoint()
    monitor_raw = _monitor_service_config(monitor_endpoint)
    # Initialize the empty SQLite schema in the test owner before handing
    # the monitor service its permanently read-only outbox view.
    monitor_outbox_path = tmp_path / "monitor-outbox.sqlite3"
    DurableOutbox(monitor_outbox_path)
    account_context = multiprocessing.get_context("spawn")
    account_process = coordinator_process = monitor_process = None
    account_control = coordinator_control = monitor_control = None
    primary_runtime = group_runtime = None
    primary_registry = None
    primary_outbox = primary_readonly_outbox = None
    store = None
    host_shutdowns = []
    primary_exception = None

    try:
        account_process, account_control = _start_process(
            account_context,
            name="bt-v3-account-owner-host",
            target=_account_host_entry,
            args=(
                account_configs["account-a"],
                account_paths["registry"],
                account_paths,
                "account-a",
                account_server_public,
                account_server_secret,
                coordinator_client_public,
                metadata_reference_ns,
                ("filled", "filled", "filled"),
            ),
        )
        account_ready = _receive(account_control)
        assert account_ready[0] == "ready"
        assert account_ready[1] == account_endpoint

        coordinator_process, coordinator_control = _start_process(
            account_context,
            name="bt-v3-group-coordinator-host",
            target=_coordinator_host_entry,
            args=(
                coordinator_raw,
                {"account-a": account_configs["account-a"]},
                coordinator_paths["registry"],
                coordinator_paths["groups"],
                coordinator_paths["run_bindings"],
                {"account-a": account_endpoint},
                {"account-a": account_server_public},
                coordinator_server_public,
                coordinator_server_secret,
                coordinator_client_public,
                coordinator_client_secret,
                strategy_client_public,
                metadata_reference_ns,
            ),
        )
        coordinator_ready = _receive(coordinator_control)
        assert coordinator_ready[0] == "ready"
        assert coordinator_ready[1] == coordinator_endpoint
        upstream_bindings = coordinator_ready[2]
        expected_routes = {
            ("upstream.orders", "account-a", fixture._route_refs("account-a")[1]),
            ("upstream.order_query", "account-a", fixture._route_refs("account-a")[2]),
            (
                "upstream.account_reservations",
                "account-a",
                fixture._route_refs("account-a")[0],
            ),
        }
        assert {
            (mount, account, scope_ref)
            for mount, account, scope_ref, _registration_id, _operations in upstream_bindings
        } == expected_routes
        assert len(upstream_bindings) == 3
        assert all(registration_id for *_route, registration_id, _operations in upstream_bindings)

        order_registration_id = next(
            registration_id
            for mount, _account, _scope_ref, registration_id, _operations in upstream_bindings
            if mount == "upstream.orders"
        )
        account_control.send(("activate", order_registration_id))
        activation = _receive(account_control)
        assert activation[0] == "activated"
        assert activation[1] == order_registration_id
        assert type(activation[2]) is int and activation[2] > 0

        monitor_keys = {
            "server_public": monitor_server_public,
            "server_secret": monitor_server_secret,
            "client_public": strategy_client_public,
            "client_secret": strategy_client_secret,
        }
        monitor_process, monitor_control = _start_process(
            account_context,
            name="bt-v3-group-monitor-host",
            target=_monitor_host_process,
            args=(
                monitor_raw,
                str(tmp_path / "monitor-registry.sqlite3"),
                str(monitor_outbox_path),
                monitor_server_public,
                monitor_server_secret,
                strategy_client_public,
            ),
        )
        monitor_ready = _receive(monitor_control)
        assert monitor_ready[0] == "ready"
        assert monitor_ready[1] == monitor_endpoint
        assert monitor_ready[2] == "started"

        group_runtime = _client_group_runtime(
            fixture,
            coordinator_endpoint,
            {
                "server_public": coordinator_server_public,
                "client_public": strategy_client_public,
                "client_secret": strategy_client_secret,
            },
            monitor_endpoint,
            monitor_keys,
        )

        primary_outbox = DurableOutbox(tmp_path / "primary-monitor-outbox.sqlite3")
        primary_readonly_outbox = DurableOutbox(
            tmp_path / "primary-monitor-outbox.sqlite3", read_only=True
        )
        primary_monitor = p5a.MonitorReadService(
            primary_readonly_outbox,
            {
                WireScope(
                    p5a._DOMAIN,
                    strategy_ref=p5a._STRATEGY_A,
                    portfolio_ref=p5a._PORTFOLIO,
                ): p5a.MonitorReadTarget(
                    p5a._RESIDUAL_SCOPE, ("group.residual",)
                )
            },
        )
        primary_provider = p5a._SyntheticProviderLeaf()
        (
            primary_registry,
            _unused_coordinator,
            _unused_writes,
            _group_scope,
            _monitor_scope,
            order_scope,
            query_scope,
        ) = p5a._registry(
            tmp_path,
            intent,
            primary_provider,
            primary_outbox,
            primary_monitor,
        )
        primary_runtime = p5a._client_runtime(
            primary_registry,
            strategy_ref=p5a._STRATEGY_B,
            principal_ref=p5a._PRINCIPAL_B,
            bindings=(
                {
                    "mount": "broker.orders",
                    "service_id": p5a._SERVICE_ID,
                    "instance_id": p5a._BROKER_INSTANCE,
                    "scope_ref": p5a._ORDER_SCOPE_REF,
                    "account_ref": p5a._ACCOUNT,
                    "transport_ref": "execution-rpc",
                },
                {
                    "mount": "broker.order_query",
                    "service_id": p5a._SERVICE_ID,
                    "instance_id": p5a._BROKER_INSTANCE,
                    "scope_ref": p5a._QUERY_SCOPE_REF,
                    "account_ref": p5a._ACCOUNT,
                    "transport_ref": "execution-rpc",
                },
            ),
            scopes={
                p5a._ORDER_SCOPE_REF: order_scope,
                p5a._QUERY_SCOPE_REF: query_scope,
            },
            requested={
                "broker.orders": p5a._WRITER_OPERATIONS,
                "broker.order_query": p5a._QUERY_OPERATIONS,
            },
        )
        store = make_store(
            api=FakeBtApiClient(
                balance={"cash": 10_000.0, "value": 10_200.0},
                positions=[{"instrument": "BTC-USD", "volume": 0.0, "price": 0.0}],
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
            primary_runtime,
            mount="broker.orders",
            scope_ref=p5a._ORDER_SCOPE_REF,
            query_mount="broker.order_query",
            query_scope_ref=p5a._QUERY_SCOPE_REF,
            strategy_group_routes=(
                ServiceStrategyGroupRoute(
                    strategy_ref=fixture._STRATEGY,
                    portfolio_ref=fixture._PORTFOLIO,
                    account_refs=fixture._ACCOUNTS,
                    runtime=group_runtime,
                    group_scope_ref=fixture._COORDINATOR_SCOPE_REF,
                    monitor_scope_ref=_MONITOR_SCOPE_REF,
                    owned=True,
                ),
            ),
        )

        strategies = session.run(_cerebro(broker, intent))
        assert session.state == "closed"
        assert session.cleanup_report.errors == ()
        assert session.cleanup_report.store_connected is False
        assert session.cleanup_report.runtime_state == "closed"
        assert primary_runtime.state == "closed"
        assert group_runtime.state == "closed"
        assert len(strategies) == 1
        strategy = strategies[0]
        submitted = strategy.submitted
        queried = strategy.queried
        assert submitted == queried
        coordinator_control.send("diagnostics")
        coordinator_diagnostics = _receive(coordinator_control)
        assert coordinator_diagnostics[0] == "diagnostics"
        account_diagnostics_path = Path(account_paths["submit_diagnostics"])
        account_submit_diagnostics = (
            json.loads(account_diagnostics_path.read_text(encoding="utf-8"))["attempts"]
            if account_diagnostics_path.is_file()
            else ()
        )
        provider_diagnostics_path = Path(account_paths["provider_submit_diagnostics"])
        provider_submit_diagnostics = (
            json.loads(provider_diagnostics_path.read_text(encoding="utf-8"))["attempts"]
            if provider_diagnostics_path.is_file()
            else ()
        )
        assert submitted.state is GroupOrderState.PAIRED, (
            f"coordinator snapshot state={submitted.state.value!r}, "
            f"error_code={submitted.error_code!r}, "
            f"first_leg_state={submitted.legs[0].child_status.state.value if submitted.legs[0].child_status else None!r}, "
            f"coordinator_submit_diagnostics={coordinator_diagnostics[1]!r}, "
            f"account_submit_diagnostics={account_submit_diagnostics!r}, "
            f"provider_submit_diagnostics={provider_submit_diagnostics!r}"
        )
        assert submitted.error_code is None
        assert submitted.request.version == 3
        assert submitted.request.first_leg_id == "leg-call"
        assert tuple(leg.leg_id for leg in submitted.request.legs) == (
            "leg-call",
            "leg-put",
            "leg-future",
        )
        assert tuple(leg.ratio for leg in submitted.request.legs) == tuple(
            spec["ratio"] for spec in _CPF_LEGS
        )
        assert tuple(
            (
                leg.maximum_intent.instrument,
                leg.maximum_intent.quantity,
                leg.maximum_intent.price,
                leg.base_units_per_order_unit,
                leg.quantity_step,
            )
            for leg in submitted.request.legs
        ) == tuple(
            (
                spec["instrument"],
                spec["quantity"],
                spec["price"],
                spec["base_units"],
                spec["step"],
            )
            for spec in _CPF_LEGS
        )
        proof_provider_requests = _read_group_proof_provider_requests(
            account_paths["proof"]
        )
        assert tuple(
            (
                leg_id,
                request["symbol"],
                Decimal(request["quantity"]),
                Decimal(request["price"]),
                request["quantity_unit"],
                request["side"],
            )
            for leg_id, request in proof_provider_requests
        ) == tuple(
            (
                spec["leg_id"],
                spec["instrument"],
                spec["quantity"],
                spec["price"],
                "native",
                spec["side"].value.lower(),
            )
            for spec in _CPF_LEGS
        )
        assert submitted.request.budget_quote is not None
        assert len(submitted.request.budget_quote.legs) == 3
        assert tuple(
            (
                quote_leg.leg_id,
                quote_leg.metadata_digest,
                quote_leg.intent_fingerprint,
                quote_leg.gross_notional,
            )
            for quote_leg in submitted.request.budget_quote.legs
        ) == tuple(
            (
                plan.leg_id,
                plan.maximum_intent.tags["instrument_metadata_digest"],
                plan.maximum_intent.fingerprint,
                spec["gross_notional"],
            )
            for plan, spec in zip(submitted.request.legs, _CPF_LEGS, strict=True)
        )
        assert len(
            {
                quote_leg.metadata_digest
                for quote_leg in submitted.request.budget_quote.legs
            }
        ) == 3
        assert submitted.request.budget_quote.gross_notional == Decimal("20140")
        assert submitted.budget_reservation is not None
        assert submitted.budget_reservation.state is GroupBudgetReservationState.HELD
        assert submitted.residual_vector == (
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
        )
        assert submitted.residual_base_units == Decimal("0")
        assert len(submitted.legs) == 3
        assert all(leg.child_status is not None for leg in submitted.legs)
        assert all(leg.child_status.state.value == "FILLED" for leg in submitted.legs)
        assert all(leg.child_status.average_price is not None for leg in submitted.legs)
        assert tuple(
            (
                leg.submitted_intent.instrument,
                leg.submitted_intent.quantity,
                leg.child_status.filled_quantity,
                leg.child_status.average_price,
            )
            for leg in submitted.legs
        ) == tuple(
            (
                spec["instrument"],
                spec["quantity"],
                spec["quantity"],
                spec["price"],
            )
            for spec in _CPF_LEGS
        )
        assert tuple(data._name for data in strategy.datas) == (
            "BTC-USD-261127-110000-C",
            "BTC-USD-261127-90000-P",
            "BTC-USD-261127",
        )
        assert all(leg.claim_receipt is not None for leg in submitted.legs)
        assert all(leg.resolution_receipt is not None for leg in submitted.legs)
        assert strategy.before_group == strategy.after_group

        account_control.send(("status",))
        provider_status = _receive(account_control)
        assert provider_status[0] == "status"
        writes, counters, pending_holds = provider_status[1:]
        assert len(writes) == 3 and len(set(writes)) == 3
        assert counters == {"order_queries": 3, "fill_queries": 3}
        assert pending_holds == ()
        provider_facts = _read_provider_order_facts(account_paths["provider"])
        assert set(provider_facts) == set(writes)
        assert tuple(
            (
                provider_facts[write]["symbol"],
                Decimal(provider_facts[write]["quantity"]),
                Decimal(provider_facts[write]["price"]),
                provider_facts[write]["side"],
                provider_facts[write]["filled"],
            )
            for write in writes
        ) == tuple(
            (
                spec["instrument"],
                spec["quantity"],
                spec["price"],
                spec["side"].value.lower(),
                format(spec["quantity"], "f"),
            )
            for spec in _CPF_LEGS
        )
    except BaseException as error:
        primary_exception = error
        raise
    finally:
        for runtime in (group_runtime, primary_runtime):
            if runtime is not None and runtime.state not in {
                "closed",
                "failed",
                "close_failed",
            }:
                with suppress(BaseException):
                    runtime.close()
        if store is not None and store.is_connected:
            with suppress(BaseException):
                store.stop()
        if primary_registry is not None:
            with suppress(BaseException):
                primary_registry.close()
        # DurableOutbox closes each SQLite connection inside its operation;
        # there is no object-level close() method to call here.

        # The accepted helper performs a bounded close handshake and join with
        # no terminate/kill fallback. Any unclear Host cleanup fails the test.
        host_fixture = _load_sdk_host_fixture()
        cleanup_errors = []
        for name, process, control in (
            ("coordinator", coordinator_process, coordinator_control),
            ("monitor", monitor_process, monitor_control),
            ("account-a", account_process, account_control),
        ):
            if process is None or control is None:
                continue
            alive_before_close = process.is_alive()
            observed_process = _DeferredProcessClose(process)
            observed_control = _ObservedHostControl(control)
            try:
                host_fixture._stop_process(observed_process, observed_control)
                alive_after_join = process.is_alive()
                exitcode = process.exitcode
                if (
                    not alive_before_close
                    or not observed_process.close_requested
                    or observed_control.close_reply is None
                    or any(state != "closed" for state in observed_control.close_reply[1:])
                    or alive_after_join
                    or exitcode != 0
                ):
                    cleanup_errors.append(name)
                else:
                    host_shutdowns.append(
                        (
                            name,
                            observed_control.close_reply,
                            alive_before_close,
                            alive_after_join,
                            exitcode,
                        )
                    )
            except BaseException as error:
                cleanup_errors.append(f"{name}:{type(error).__name__}")
                with suppress(BaseException):
                    control.close()
            finally:
                if not process.is_alive():
                    with suppress(BaseException):
                        process.close()
        if cleanup_errors:
            cleanup_message = (
                "one or more ServiceHosts missed bounded normal shutdown: "
                + ",".join(cleanup_errors)
            )
            if primary_exception is None:
                raise AssertionError(cleanup_message)
            add_note = getattr(primary_exception, "add_note", None)
            if callable(add_note):
                with suppress(BaseException):
                    add_note(cleanup_message)

    assert tuple(item[0] for item in host_shutdowns) == (
        "coordinator",
        "monitor",
        "account-a",
    )
    assert all(
        item[2:] == (True, False, 0) and all(state == "closed" for state in item[1][1:])
        for item in host_shutdowns
    )

