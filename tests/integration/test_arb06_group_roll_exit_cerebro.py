"""Normal Cerebro roll-exit through the real Coordinator, Risk and account Hosts.

The accepted group/source and Risk service come from a fixed SDK integration
fixture. This test starts a separate production ``GroupCoordinatorService``
Host and calls it from a normal Backtrader Strategy through
``ServiceExecutionSession``. Only the Gateway account provider, Risk terminal
fill, and read-only Monitor registry leaf are synthetic; no exchange is contacted.
"""

from __future__ import annotations

import hashlib
import json
import copy
import importlib
import importlib.util
import os
import socket
import sqlite3
import sys
import threading
import datetime as dt
import queue
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# These imports are required for this real-host chain. Missing fixed exports or
# SDK packages must fail collection, rather than skip the acceptance node.
for _module_name in (
    "bt_api_base",
    "bt_api_execution",
    "bt_api_gateway",
    "bt_api_monitor",
    "bt_api_py",
    "bt_api_risk",
    "bt_api_transport_zmq",
):
    importlib.import_module(_module_name)
zmq = importlib.import_module("zmq")
pandas = importlib.import_module("pandas")

import backtrader as bt  # noqa: E402
from bt_api_base.account_protocol import (  # noqa: E402
    AccountBalance,
    AccountKey,
    AccountObservation,
    AccountPosition,
    AccountResourceKey,
    AccountValuation,
)
from bt_api_base.market_protocol import (  # noqa: E402
    MarketInstrumentKey,
    MarketSubscriptionKey,
)
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_execution import (  # noqa: E402
    GroupOrderState,
    OrderType,
    SqliteOrderGroupStore,
)
from bt_api_py.service_components import ComponentResources  # noqa: E402
from bt_api_py.service_config import parse_client_config, parse_service_config  # noqa: E402
from bt_api_py.gateway_operator import (  # noqa: E402
    GatewayAccountSessionBinding,
    GatewayOperatorDeployment,
)
from bt_api_py.service_account import ServiceAccountClient  # noqa: E402
from bt_api_py.service_execution_group import (  # noqa: E402
    GroupAccountRoute,
    GroupCoordinatorTarget,
    GroupInstrumentRule,
)
from bt_api_py.service_execution_group_client import GroupOriginRunBindingStore  # noqa: E402
from bt_api_py.service_host import (  # noqa: E402
    ServiceHost,
    TrustedServiceAuthority,
    TrustedServiceClients,
)
from bt_api_py.service_registry import (  # noqa: E402
    PrincipalGrant,
    ResourceGrant,
    ServiceCapability,
    ServiceRegistry,
)
from bt_api_py.service_runtime import (  # noqa: E402
    ClientCurveKeys,
    ServiceClientRuntime,
    ZmqTransportFactory,
)
from bt_api_gateway.event_journal import GatewayEventJournal  # noqa: E402
from bt_api_gateway.router import GatewayCommandKind, GatewayPrincipal  # noqa: E402
from bt_api_gateway.service_component import GatewayServiceAccountScope  # noqa: E402
from bt_api_gateway.session_guard import LocalAccountSessionGuard  # noqa: E402
from bt_api_gateway.session_owner import GatewaySessionOwner  # noqa: E402

from backtrader.stores.btapistore import BtApiStore  # noqa: E402
from backtrader.stores.service_read_proxy import (  # noqa: E402
    ServiceFeedBinding,
    ServiceReadProxy,
)
from backtrader.stores.service_execution_group import (  # noqa: E402
    ServiceStrategyGroupRoute,
)
from backtrader.stores.service_execution_session import (  # noqa: E402
    ServiceExecutionSession,
)
from tests.integration import test_arb06_cerebro_account_monitor as arb06  # noqa: E402
from tests.integration import test_btapi_execution_group_cerebro_v3_host as p5a_host  # noqa: E402

_SDK_TESTS_ROOT_ENV = "BT_API_PY_TESTS_ROOT"
_RISK_FIXTURE_FILENAME = "_dim05_roll_exit_risk_host_fixture.py"
_RISK_FIXTURE_MODULE = "_bt_api_arb06_dim05_roll_exit_risk_fixture"
_RISK_FIXTURE_SHA256 = "5a057674f4e66d2cf9c90bae1d7b9317db6d2135dd6eef088a0808273a995666"
_DIM05_SOURCE_FILENAME = "test_arb03_dim05_group_partial_fill_service.py"
_DIM05_SOURCE_MODULE = "tests.integration.test_arb03_dim05_group_partial_fill_service"
_DIM05_SOURCE_SUPPORT_SHA256 = "d9e516f3b8cbc3cdde4f7e477c3526109603ff0c3a1b01f58be2df9086787887"
_PROVIDER_FIXTURE_MODULE = "tests.unit._service_group_provider_fixtures"
_PROVIDER_FIXTURE_SHA256 = "9bcf021649104243a2b16a93ef159ceca8cacce6ffad9c22afd94eed4ee3b1e2"
_GROUP_HOST_FIXTURE = "integration/test_service_execution_group_local_process.py"
_GROUP_HOST_FIXTURE_SHA256 = "b9f60ce8cf29dcdd798672f4ad501abe6dc2346c7ffedf327376c83d90cd574b"
_SEED_GROUP_FIXTURE_SHA256 = "2f06291dbed35bc56f54d6e502c001fd3316f9408cf4a0fab615acaff03a033e"

_COORDINATOR_LISTENER_REF = "arb06-roll-exit-coordinator-listener-v1"
_COORDINATOR_SECURITY_REF = "arb06-roll-exit-coordinator-server-curve-v1"
_STRATEGY_SECURITY_REF = "arb06-roll-exit-strategy-client-curve-v1"
_STRATEGY_TRANSPORT_REF = "arb06-roll-exit-strategy-connect-v1"
_MONITOR_SECURITY_REF = "arb06-roll-exit-monitor-client-curve-v1"
_MONITOR_TRANSPORT_REF = "arb06-roll-exit-monitor-connect-v1"
_MONITOR_SCOPE_REF = p5a_host._MONITOR_SCOPE_REF
_MONITOR_SERVICE_ID = p5a_host._MONITOR_SERVICE_ID
_MONITOR_INSTANCE_ID = p5a_host._MONITOR_INSTANCE
_MONITOR_PRINCIPAL_REF = p5a_host._MONITOR_PRINCIPAL
_COORDINATOR_REQUEST_TIMEOUT_MS = 5_000
_MAX_MESSAGE_BYTES = 1_000_000
_GROUP_OPERATIONS = frozenset(
    {
        "groups.submit",
        "groups.query",
        "groups.roll_exit",
        "groups.query_roll_exit",
    }
)
_MONITOR_OPERATIONS = frozenset({"monitor.read_after"})
_ORDER_WRITES = frozenset({"orders.submit", "orders.cancel"})
_ORDER_QUERIES = frozenset({"orders.query"})
_ORDINARY_ORDER_SCOPE_REF = "arb06-roll-exit-peer-order-scope"
_ORDINARY_QUERY_SCOPE_REF = "arb06-roll-exit-peer-query-scope"
_RISK_SUBMIT = "orders.submit_group_roll_exit"
_RISK_PREPARE = "orders.prepare_group_roll_exit"
_RISK_QUERY = "orders.query_group_roll_exit"
_COORDINATOR_OPERATIONS = frozenset(
    {"groups.submit", "groups.query", "groups.roll_exit", "groups.query_roll_exit"}
)
_ACCOUNT_READ_OPERATIONS = frozenset({"account.snapshot"})
_ACCOUNT_SERVICE_ID = "arb06-roll-exit-account-service"
_ACCOUNT_INSTANCE_ID = "arb06-roll-exit-account-session"
_ACCOUNT_SERVICE_PRINCIPAL = "arb06-roll-exit-account-principal"
_ACCOUNT_SESSION_REF = "session:arb06-roll-exit-account"
_ACCOUNT_SCOPE_REF = "arb06-roll-exit-account-scope-v1"
_ACCOUNT_TRANSPORT_REF = "arb06-roll-exit-account-listener-v1"
_ACCOUNT_SECURITY_REF = "arb06-roll-exit-account-server-curve-v1"
_ACCOUNT_CLIENT_SECURITY_REF = "arb06-roll-exit-account-client-curve-v1"
_ACCOUNT_CLIENT_TRANSPORT_REF = "arb06-roll-exit-account-connect-v1"
_ACCOUNT_JOURNAL_SCOPE = "journal:arb06-roll-exit-account"
_ACCOUNT_STATE_SCOPE = "state:arb06-roll-exit-account"


class _RegistryTransport:
    """Local registered Monitor/ordinary-order leaf used by this test only."""

    def __init__(self, registry: ServiceRegistry, peer: WireIdentity) -> None:
        self._registry = registry
        self._peer = peer
        self.closed = False

    def request(self, request, *, timeout):
        del timeout
        response = self._registry.handle(request.header.identity.principal_ref, request)
        from dataclasses import replace

        from bt_api_base.service_protocol import WireEnvelope, WireMessageKind

        return WireEnvelope(
            replace(
                request.header,
                kind=WireMessageKind.REPLY,
                message_id=f"reply-{request.header.message_id}",
                correlation_id=request.header.message_id,
                identity=self._peer,
            ),
            response,
        )

    def close(self) -> None:
        self.closed = True


class _RecordingTransport:
    def __init__(
        self, transport, operations: list[str], watched: frozenset[str]
    ) -> None:
        self._transport = transport
        self._operations = operations
        self._watched = watched

    def request(self, request, *, timeout):
        operation = request.header.operation
        if operation in self._watched:
            self._operations.append(operation)
        return self._transport.request(request, timeout=timeout)

    def close(self) -> None:
        self._transport.close()


def _load_fixed_risk_fixture() -> ModuleType:
    """Load the fixed accepted SDK source support and the pinned Risk fixture."""

    root_text = os.environ.get(_SDK_TESTS_ROOT_ENV)
    if type(root_text) is not str or not root_text.strip():
        raise AssertionError(f"{_SDK_TESTS_ROOT_ENV} must name the fixed SDK tests export")
    root = Path(root_text).resolve()
    expected_sources = {
        root / "integration" / _RISK_FIXTURE_FILENAME: _RISK_FIXTURE_SHA256,
        root / "integration" / _DIM05_SOURCE_FILENAME: _DIM05_SOURCE_SUPPORT_SHA256,
        root / "unit" / "_service_group_provider_fixtures.py": _PROVIDER_FIXTURE_SHA256,
        root / _GROUP_HOST_FIXTURE: _GROUP_HOST_FIXTURE_SHA256,
    }
    for source_path, expected_sha256 in expected_sources.items():
        if not source_path.is_file():
            raise AssertionError("fixed DIM05/R249 SDK test support is incomplete")
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != expected_sha256:
            raise AssertionError(f"fixed SDK test source pin changed: {source_path.name}")

    # Reuse the accepted R249 loader for its real spawned account/coordinator
    # seed path. Its exact provider/Host dependencies are checked above.
    p5a_host._load_sdk_host_fixture()
    dim05_source = _load_source_module(
        _DIM05_SOURCE_MODULE,
        root / "integration" / _DIM05_SOURCE_FILENAME,
        _DIM05_SOURCE_SUPPORT_SHA256,
    )
    assert dim05_source._STRATEGY == "strategy-group-partial-fill"

    source_path = root / "integration" / _RISK_FIXTURE_FILENAME
    source_bytes = source_path.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == _RISK_FIXTURE_SHA256

    loaded = sys.modules.get(_RISK_FIXTURE_MODULE)
    if loaded is not None:
        loaded_path = Path(getattr(loaded, "__file__", "")).resolve()
        if loaded_path != source_path:
            raise AssertionError("a different DIM05 Risk fixture is already loaded")
        return loaded
    spec = importlib.util.spec_from_file_location(_RISK_FIXTURE_MODULE, source_path)
    if spec is None or spec.loader is None:
        raise AssertionError("fixed DIM05 roll-exit Risk fixture cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_RISK_FIXTURE_MODULE] = module
    spec.loader.exec_module(module)
    return module


def _load_source_module(module_name: str, source_path: Path, expected_sha256: str) -> ModuleType:
    source_path = source_path.resolve()
    source_bytes = source_path.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != expected_sha256:
        raise AssertionError(f"fixed SDK source pin changed: {source_path.name}")
    existing = sys.modules.get(module_name)
    if existing is not None:
        loaded_path = Path(getattr(existing, "__file__", "")).resolve()
        if loaded_path != source_path:
            raise AssertionError(f"a different fixed source is already loaded: {module_name}")
        return existing
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"fixed SDK module cannot be loaded: {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    parent_name, _, child_name = module_name.rpartition(".")
    if parent_name:
        parent = importlib.import_module(parent_name)
        setattr(parent, child_name, module)
    return module


@contextmanager
def _spawnable_seed_fixture_imports(
    tmp_path: Path,
    *,
    seed_source: Path,
    provider_source: Path,
):
    """Expose byte-identical R249 modules under the names Windows spawn imports."""

    seed_bytes = seed_source.read_bytes()
    provider_bytes = provider_source.read_bytes()
    if hashlib.sha256(seed_bytes).hexdigest() != _SEED_GROUP_FIXTURE_SHA256:
        raise AssertionError("fixed R249 seed source pin changed")
    if hashlib.sha256(provider_bytes).hexdigest() != _PROVIDER_FIXTURE_SHA256:
        raise AssertionError("fixed R249 provider source pin changed")

    support_root = tmp_path / "spawn-imports"
    tests_root = support_root / "tests"
    unit_root = tests_root / "unit"
    unit_root.mkdir(parents=True)
    (support_root / "_bt_api_arb06_fixed_partial_group_fixture.py").write_bytes(
        seed_bytes
    )
    (unit_root / "_service_group_provider_fixtures.py").write_bytes(provider_bytes)
    (unit_root / "__init__.py").write_bytes(b"")
    backtrader_tests = Path(__file__).resolve().parents[1]
    (tests_root / "__init__.py").write_text(
        f"__path__.append({str(backtrader_tests)!r})\n",
        encoding="utf-8",
    )
    support_text = str(support_root.resolve())
    if support_text in sys.path:
        raise AssertionError("spawn support path already exists in sys.path")
    sys.path.insert(0, support_text)
    try:
        yield
    finally:
        sys.path.remove(support_text)


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _group_component(instance_id: str, portfolio_ref: str) -> dict[str, Any]:
    return {
        "config_schema_version": 2,
        "settings": {
            "instance_id": instance_id,
            "bind_ports": ["service.order_group_entry"],
            "options": {"role": "group_coordinator", "portfolio_ref": portfolio_ref},
        },
    }


def _rpc_profile(
    endpoint: str,
    *,
    bind: bool,
    security_ref: str,
    request_timeout_ms: int | None = None,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "high_water_mark": 32,
        "max_message_bytes": _MAX_MESSAGE_BYTES,
    }
    if request_timeout_ms is not None:
        options["request_timeout_ms"] = request_timeout_ms
    return {
        "backend": "zmq",
        "config_schema_version": 1,
        "endpoints": {"rpc_bind" if bind else "rpc_connect": endpoint},
        "security_profile_ref": security_ref,
        "options": options,
    }


class _CoordinatorHostLoop:
    """Own one real Coordinator Host, its upstream runtime and SQLite stores."""

    def __init__(self, factory) -> None:
        self._factory = factory
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.host: ServiceHost | None = None
        self.error: BaseException | None = None
        self.cleanup_errors: list[BaseException] = []
        self._cleanups: list[Any] = []
        self.thread = threading.Thread(
            target=self._run, name="arb06-roll-exit-coordinator-host"
        )

    def _run(self) -> None:
        try:
            self.host = self._factory(self._cleanups)
            self.host.start()
            self.ready.set()
            while not self.stop_event.is_set():
                self.host.serve_once(timeout_ms=15)
        except BaseException as error:
            self.error = error
        finally:
            self.ready.set()
            host = self.host
            if host is not None and host.state not in {"closed", "failed"}:
                try:
                    host.close()
                except BaseException as error:
                    self.cleanup_errors.append(error)
            for close in reversed(self._cleanups):
                try:
                    close()
                except BaseException as error:
                    self.cleanup_errors.append(error)
            self.finished.set()

    def start(self) -> ServiceHost:
        self.thread.start()
        assert self.ready.wait(10), "Coordinator Host did not become ready"
        if self.error is not None:
            host = self.host
            raise AssertionError(
                (
                    type(self.error).__name__,
                    None if host is None else host.summary.get("start_failure"),
                    None if host is None else host.summary.get("component_states"),
                )
            ) from self.error
        assert self.host is not None and self.host.state == "started"
        assert not self.cleanup_errors
        return self.host

    def close(self) -> None:
        self.stop_event.set()
        if self.thread.ident is None:
            return
        assert self.finished.wait(10), "Coordinator Host did not finish normal shutdown"
        self.thread.join(1)
        assert not self.thread.is_alive()
        active_exception = sys.exc_info()[1]
        if self.error is not None:
            if active_exception is None:
                raise AssertionError(
                    ("Coordinator Host thread failed", type(self.error).__name__)
                ) from self.error
            active_exception.add_note(
                f"Coordinator Host thread also failed: {type(self.error).__name__}"
            )
        if self.host is not None and self.host.state != "closed":
            if active_exception is None:
                raise AssertionError(("Coordinator Host did not close", self.host.summary))
            active_exception.add_note("Coordinator Host did not close cleanly")
        if self.cleanup_errors:
            names = tuple(type(error).__name__ for error in self.cleanup_errors)
            if active_exception is None:
                raise AssertionError(("Coordinator Host cleanup failed", names))
            active_exception.add_note(f"Coordinator Host cleanup errors: {names}")


class _AccountHostLoop:
    """Own one real Gateway account Host and serialize worker refreshes."""

    def __init__(self, factory) -> None:
        self._factory = factory
        self._commands: queue.Queue[tuple[Any, threading.Event, dict[str, Any]]] = queue.Queue()
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.deployment: GatewayOperatorDeployment | None = None
        self.error: BaseException | None = None
        self.cleanup_errors: list[BaseException] = []
        self._cleanups: list[Any] = []
        self.thread = threading.Thread(target=self._run, name="arb06-roll-exit-account-host")

    def _run(self) -> None:
        try:
            self.deployment = self._factory(self._cleanups)
            self.deployment.start()
            self.ready.set()
            while not self.stop_event.is_set():
                try:
                    callback, completed, result = self._commands.get(timeout=0.005)
                except queue.Empty:
                    self.deployment.serve_once(timeout_ms=10)
                    continue
                try:
                    result["value"] = callback(self.deployment)
                except BaseException as error:
                    result["error"] = error
                finally:
                    completed.set()
                self.deployment.serve_once(timeout_ms=0)
        except BaseException as error:
            self.error = error
        finally:
            self.ready.set()
            deployment = self.deployment
            if deployment is not None and deployment.state not in {"closed", "failed"}:
                try:
                    deployment.close()
                except BaseException as error:
                    self.cleanup_errors.append(error)
            for cleanup in reversed(self._cleanups):
                try:
                    cleanup()
                except BaseException as error:
                    self.cleanup_errors.append(error)
            self.finished.set()

    def start(self) -> GatewayOperatorDeployment:
        self.thread.start()
        assert self.ready.wait(10), "Gateway account Host did not become ready"
        if self.error is not None:
            deployment = self.deployment
            host = None if deployment is None else deployment.service_host
            raise AssertionError(
                (
                    type(self.error).__name__,
                    None if host is None else host.summary.get("start_failure"),
                    None if host is None else host.summary.get("component_states"),
                )
            ) from self.error
        assert self.deployment is not None and self.deployment.state == "started"
        assert not self.cleanup_errors
        return self.deployment

    def call(self, callback, *, timeout: float = 10.0):
        if self.finished.is_set() or self.error is not None:
            raise AssertionError("Gateway account Host is not serving") from self.error
        completed = threading.Event()
        result: dict[str, Any] = {}
        self._commands.put((callback, completed, result))
        assert completed.wait(timeout), "Gateway account Host owner command timed out"
        if "error" in result:
            raise result["error"]
        if self.error is not None:
            raise AssertionError("Gateway account Host failed during owner command") from self.error
        return result.get("value")

    def close(self) -> None:
        self.stop_event.set()
        if self.thread.ident is None:
            return
        assert self.finished.wait(10), "Gateway account Host did not finish normal shutdown"
        self.thread.join(1)
        assert not self.thread.is_alive()
        active_exception = sys.exc_info()[1]
        if self.error is not None:
            if active_exception is None:
                raise AssertionError(
                    ("Gateway account Host thread failed", type(self.error).__name__)
                ) from self.error
            active_exception.add_note(
                f"Gateway account Host thread also failed: {type(self.error).__name__}"
            )
        if self.deployment is not None and self.deployment.state != "closed":
            if active_exception is None:
                raise AssertionError(
                    ("Gateway account Host did not close", self.deployment.summary)
                )
            active_exception.add_note("Gateway account Host did not close cleanly")
        if self.cleanup_errors:
            names = tuple(type(error).__name__ for error in self.cleanup_errors)
            if active_exception is None:
                raise AssertionError(("Gateway account Host cleanup failed", names))
            active_exception.add_note(f"Gateway account Host cleanup errors: {names}")


class _SyntheticAccountState:
    """Mutable provider snapshot driven only by the accepted synthetic fill."""

    def __init__(self, account_key: AccountKey, resource: AccountResourceKey, instrument):
        self.account_key = account_key
        self.resource = resource
        self.instrument = instrument
        self.cash = Decimal("10000")
        self.quantity = Decimal("2.25")
        self.mark_price = Decimal("100")
        self._lock = threading.Lock()
        self._observation_sequence = 0
        self._applied_fill: tuple[str, Decimal, Decimal, str, str] | None = None
        self.observations: list[AccountObservation] = []

    def apply_close_fill(self, fill: dict[str, Any]) -> None:
        symbol = fill.get("symbol")
        quantity = Decimal(str(fill.get("quantity")))
        price = Decimal(str(fill.get("trade_price")))
        fee = Decimal(str(fill.get("fee_amount")))
        fee_currency = fill.get("fee_currency")
        side = fill.get("side")
        client_order_id = fill.get("client_order_id")
        with self._lock:
            if self._applied_fill is not None:
                raise AssertionError("synthetic account fill was applied more than once")
            if (
                symbol != self.instrument.instrument_id
                or fill.get("account_id") != self.account_key.account_id
                or quantity != Decimal("1.5")
                or price != Decimal("101")
                or side != "sell"
                or fee != Decimal("-0.05")
                or fee_currency != "USD"
                or type(client_order_id) is not str
                or not client_order_id
                or quantity > self.quantity
            ):
                raise AssertionError("Risk provider result is not the expected source close fill")
            # Fees are signed: positive values are charged; negative values
            # are rebates. The account view follows this exact synthetic fill.
            self.cash += quantity * price - fee
            self.quantity -= quantity
            self._applied_fill = (
                symbol,
                quantity,
                price,
                side,
                client_order_id,
            )

    def read_observation(self) -> AccountObservation:
        with self._lock:
            self._observation_sequence += 1
            sequence = self._observation_sequence
            cash = self.cash
            quantity = self.quantity
            mark_price = self.mark_price
        observed_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
        observed_at = observed_at.replace("+00:00", "Z")
        observation = AccountObservation(
            account_key=self.account_key,
            observation_id=f"arb06-account-observation-{sequence}",
            coverage=(self.resource,),
            balances=(
                AccountBalance(
                    resource=self.resource,
                    currency="USD",
                    total=str(cash),
                    available=str(cash),
                    locked="0",
                    observed_at_utc=observed_at,
                ),
            ),
            positions=(
                AccountPosition(
                    resource=self.resource,
                    instrument=self.instrument,
                    side="net",
                    quantity=str(quantity),
                    qty_unit="base",
                    average_price="100",
                    price_currency="USD",
                    observed_at_utc=observed_at,
                ),
            ),
            valuation=AccountValuation(
                currency="USD",
                available_cash=str(cash),
                equity=str(cash + quantity * mark_price),
                observed_at_utc=observed_at,
            ),
            started_at_utc=observed_at,
            completed_at_utc=observed_at,
            consistency="provider_atomic",
            balances_complete=True,
            positions_complete=True,
            open_orders=(),
            open_orders_complete=True,
        )
        with self._lock:
            self.observations.append(observation)
        return observation


class _SyntheticAccountProvider:
    """Gateway provider leaf with no credentials, network, or venue client."""

    def __init__(self, state: _SyntheticAccountState) -> None:
        self._state = state
        self._owner_thread_id: int | None = None
        self._generation: str | None = None
        self.connect_count = 0
        self.read_count = 0
        self.close_count = 0

    def connect(self, *, account_key: AccountKey, generation: str, timeout: float) -> None:
        if self._owner_thread_id is not None and threading.get_ident() != self._owner_thread_id:
            raise AssertionError("synthetic account provider changed owner thread")
        if timeout <= 0 or account_key != self._state.account_key or not generation:
            raise AssertionError("Gateway supplied an invalid account-session binding")
        self._owner_thread_id = threading.get_ident()
        self._generation = generation
        self.connect_count += 1

    def read_account(self, *, generation: str, timeout: float) -> AccountObservation:
        if threading.get_ident() != self._owner_thread_id:
            raise AssertionError("synthetic account read left its Gateway owner thread")
        if generation != self._generation or timeout <= 0:
            raise AssertionError("Gateway read used a different account session")
        self.read_count += 1
        return self._state.read_observation()

    def close(self) -> bool:
        if threading.get_ident() != self._owner_thread_id:
            raise AssertionError("synthetic account provider close left its Gateway owner thread")
        self.close_count += 1
        return True


class _NoMarketClient:
    """Typed unused market facade required by the account-position mapping."""

    def __init__(self, key: MarketSubscriptionKey, stream_scope: WireScope) -> None:
        self.key = key
        self.stream_scope = stream_scope
        self.closed = False

    def start(self) -> None:
        return None

    def history(self, _request):
        return []

    def poll(self):
        return None

    def close(self) -> None:
        self.closed = True


class _AccountStoreFacade:
    """Test-only read adapter; all Store order writes fail closed.

    ServiceReadProxy remains the actual account/position source. The facade
    does not expose its read-only marker because the current managed group
    session rejects that marker; it supplies only account reads and explicit
    write failures while the separate registered group route performs the
    one authorized source-close action.
    """

    def __init__(self, proxy: ServiceReadProxy) -> None:
        self._proxy = proxy
        self.blocked_writes: list[str] = []

    def connect(self) -> None:
        self._proxy.connect()

    def disconnect(self) -> None:
        self._proxy.disconnect()

    def get_balance(self):
        return self._proxy.get_balance()

    def get_positions(self):
        return self._proxy.get_positions()

    def fetch_open_orders(self):
        return self._proxy.fetch_open_orders()

    def supports_position_mode(self, mode: str) -> bool:
        return self._proxy.supports_position_mode(mode)

    def submit_order(self, *_args, **_kwargs):
        self.blocked_writes.append("submit_order")
        raise AssertionError("the account-read facade cannot submit orders")

    def create_order(self, *_args, **_kwargs):
        self.blocked_writes.append("create_order")
        raise AssertionError("the account-read facade cannot create orders")

    def cancel_order(self, *_args, **_kwargs):
        self.blocked_writes.append("cancel_order")
        raise AssertionError("the account-read facade cannot cancel orders")


def _account_service_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _ACCOUNT_SERVICE_ID,
        "scope_ref": _ACCOUNT_SCOPE_REF,
        "transport_ref": _ACCOUNT_TRANSPORT_REF,
        "registration_policy_ref": "arb06-account-registration-v1",
        "service_requirements_ref": "arb06-account-requirements-v1",
        "components": {
            "gateway": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _ACCOUNT_INSTANCE_ID,
                    "bind_ports": ["service.account_read", "service.provider_session"],
                    "options": {
                        "role": "account_session_worker",
                        "account_session_ref": _ACCOUNT_SESSION_REF,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _ACCOUNT_TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _ACCOUNT_SECURITY_REF,
                    "options": {
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _account_client_config(
    endpoint: str, strategy_ref: str, account_ref: str
) -> dict[str, Any]:
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": strategy_ref},
        "clients": {
            "gateway": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "store.account",
                            "service_id": _ACCOUNT_SERVICE_ID,
                            "instance_id": _ACCOUNT_INSTANCE_ID,
                            "scope_ref": _ACCOUNT_SCOPE_REF,
                            "account_ref": account_ref,
                            "transport_ref": _ACCOUNT_CLIENT_TRANSPORT_REF,
                        }
                    ],
                    "options": {
                        "request_timeout_ms": 3_000,
                        "heartbeat_interval_seconds": 5,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _ACCOUNT_CLIENT_TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": _ACCOUNT_CLIENT_SECURITY_REF,
                    "options": {
                        "request_timeout_ms": 3_000,
                        "high_water_mark": 32,
                        "max_message_bytes": _MAX_MESSAGE_BYTES,
                    },
                }
            },
        },
    }


def _start_account_host(
    tmp_path: Path,
    *,
    dim05: ModuleType,
    risk_case,
):
    """Start a real Gateway account Host with only a synthetic provider leaf."""
    account_key = AccountKey(
        provider=risk_case.account_scope.provider,
        venue=risk_case.venue,
        environment=risk_case.account_scope.environment,
        account_id=risk_case.provider_account_id,
    )
    resource = AccountResourceKey("spot", "cash")
    instrument = MarketInstrumentKey(
        provider=account_key.provider,
        venue=account_key.venue,
        environment=account_key.environment,
        product_type=resource.product_type,
        instrument_id=risk_case.source_instrument,
        native_symbol=risk_case.source_instrument,
    )
    state = _SyntheticAccountState(account_key, resource, instrument)
    provider_holder: list[_SyntheticAccountProvider] = []
    endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    owner_strategy = risk_case.source_strategy_ref
    peer_strategy = risk_case.peer_strategy_ref
    account_scope = GatewayServiceAccountScope(
        risk_case.account_ref,
        dim05._DOMAIN,
        _ACCOUNT_JOURNAL_SCOPE,
        account_read_strategy_scope=_ACCOUNT_STATE_SCOPE,
        shared_account_facts_scope=_ACCOUNT_STATE_SCOPE,
        shared_fact_strategy_refs=frozenset({owner_strategy, peer_strategy}),
    )
    gateway_principal = GatewayPrincipal(
        dim05._STRATEGY_PRINCIPAL,
        frozenset({_ACCOUNT_JOURNAL_SCOPE}),
        frozenset({_ACCOUNT_STATE_SCOPE}),
        frozenset({GatewayCommandKind.READ}),
    )
    config = parse_service_config(_account_service_config(endpoint))
    service_identity = WireIdentity(
        WireRole.SERVICE, _ACCOUNT_SERVICE_PRINCIPAL, _ACCOUNT_SERVICE_ID
    )
    strategy_identity = WireIdentity(
        WireRole.STRATEGY_CLIENT, dim05._STRATEGY_PRINCIPAL, owner_strategy
    )
    account_wire_scope = WireScope(
        dim05._DOMAIN,
        account_ref=risk_case.account_ref,
        strategy_ref=owner_strategy,
    )
    authority = TrustedServiceAuthority(
        identity=service_identity,
        scope=WireScope(dim05._DOMAIN),
        scope_ref=_ACCOUNT_SCOPE_REF,
        scope_version="arb06-account-scope-v1",
        security_ref=_ACCOUNT_SECURITY_REF,
        security_version="arb06-account-curve-v1",
        registration_policy_ref=config.registration_policy_ref,
        registration_policy_version="arb06-account-registration-v1",
        service_requirements_ref=config.service_requirements_ref,
        service_requirements_version="arb06-account-requirements-v1",
        curve_public_key=server_public,
        curve_secret_key=server_secret,
        principals={client_public: dim05._STRATEGY_PRINCIPAL},
        grants={
            dim05._STRATEGY_PRINCIPAL: (
                PrincipalGrant(
                    strategy_identity,
                    (
                        ResourceGrant(
                            _ACCOUNT_INSTANCE_ID,
                            "service.account_read",
                            _ACCOUNT_SCOPE_REF,
                            account_wire_scope,
                            _ACCOUNT_READ_OPERATIONS,
                        ),
                    ),
                ),
            )
        },
    )

    def factory(cleanups):
        journal = GatewayEventJournal(
            tmp_path / "arb06-roll-exit-account-journal.sqlite3"
        )
        guard_dir = tmp_path / "arb06-roll-exit-account-guard"
        guard_dir.mkdir(exist_ok=True)
        binding = GatewayAccountSessionBinding(
            account_session_ref=_ACCOUNT_SESSION_REF,
            journal=journal,
            account_key=account_key,
            account_scope=account_scope,
            state_scope=_ACCOUNT_STATE_SCOPE,
            guard=LocalAccountSessionGuard(
                guard_dir,
                account_key.account_key_id,
                "arb06-account-synthetic-owner",
            ),
            required_coverage=(resource,),
            principals={dim05._STRATEGY_PRINCIPAL: gateway_principal},
            require_open_orders=True,
            refresh_interval_seconds=3_600,
            max_staleness_seconds=60,
            request_timeout_seconds=3,
        )

        def provider_factory(_session_ref: str, _credential: object):
            provider = _SyntheticAccountProvider(state)
            provider_holder.append(provider)
            return provider

        owner = GatewaySessionOwner(
            {_ACCOUNT_SESSION_REF: "credential:arb06-synthetic"},
            resolve_credential=lambda _ref: object(),
            provider_factory=provider_factory,
        )
        return GatewayOperatorDeployment(
            config,
            authority,
            tmp_path / "arb06-roll-exit-account-registry.sqlite3",
            resource_provider=lambda *_args: pytest.fail(
                "account_session_worker must use its configured Gateway session owner"
            ),
            session_owner=owner,
            account_session=binding,
        )

    loop = _AccountHostLoop(factory)
    runtime = None
    account_client = None
    try:
        deployment = loop.start()
        if deployment.endpoint != endpoint:
            raise AssertionError("Gateway account Host bound an unexpected endpoint")
        runtime = ServiceClientRuntime(
            parse_client_config(
                _account_client_config(
                    endpoint, owner_strategy, risk_case.account_ref
                )
            ),
            identity=strategy_identity,
            scope_resolver={
                _ACCOUNT_SCOPE_REF: WireScope(
                    dim05._DOMAIN, account_ref=risk_case.account_ref
                )
            }.__getitem__,
            peer_resolver={_ACCOUNT_SERVICE_ID: service_identity}.__getitem__,
            transport_factory=ZmqTransportFactory(
                {
                    _ACCOUNT_CLIENT_SECURITY_REF: ClientCurveKeys(
                        server_key=server_public,
                        public_key=client_public,
                        secret_key=client_secret,
                    )
                }
            ),
            run_id=risk_case.run_id,
            requested_operations={"store.account": _ACCOUNT_READ_OPERATIONS},
        )
        runtime.start()
        monotonic_now = [0.0]
        account_client = ServiceAccountClient(
            runtime,
            "store.account",
            account_ref=risk_case.account_ref,
            expected_account=account_key,
            required_coverage=(resource,),
            require_open_orders=True,
            expected_scope_ref=_ACCOUNT_SCOPE_REF,
            monotonic_clock=lambda: monotonic_now[0],
        )
        market_key = MarketSubscriptionKey(
            "arb06-synthetic-account-bars",
            "arb06-synthetic-account-entitlement",
            instrument,
            "bar",
            timeframe="1m",
        )
        market_client = _NoMarketClient(
            market_key,
            WireScope(
                dim05._DOMAIN,
                account_ref=risk_case.account_ref,
                strategy_ref=owner_strategy,
            ),
        )
        proxy = ServiceReadProxy(
            account_client,
            {
                risk_case.source_instrument: ServiceFeedBinding(
                    market_client=market_client,
                    resource=resource,
                    qty_unit="base",
                    timeframe="1m",
                )
            },
            valuation_currency="USD",
            position_mode="net",
        )
        initial_view = account_client.refresh()
    except BaseException as setup_error:
        if runtime is not None:
            try:
                _close_runtime(runtime)
            except BaseException as cleanup_error:
                setup_error.add_note(
                    f"account client runtime cleanup failed: {type(cleanup_error).__name__}"
                )
        if account_client is not None:
            try:
                account_client.close()
            except BaseException as cleanup_error:
                setup_error.add_note(
                    f"account client facade cleanup failed: {type(cleanup_error).__name__}"
                )
        try:
            loop.close()
        except BaseException as cleanup_error:
            setup_error.add_note(
                f"Gateway account Host cleanup failed: {type(cleanup_error).__name__}"
            )
        raise

    return {
        "loop": loop,
        "deployment": deployment,
        "provider": provider_holder[0],
        "state": state,
        "account_key": account_key,
        "resource": resource,
        "instrument": instrument,
        "runtime": runtime,
        "account_client": account_client,
        "monotonic_now": monotonic_now,
        "proxy": proxy,
        "api": _AccountStoreFacade(proxy),
        "initial_view": initial_view,
    }


def _read_risk_close_fill(risk_case, client_order_id: str) -> dict[str, Any]:
    provider_path = Path(risk_case.account_paths["provider"]).resolve()
    with sqlite3.connect(provider_path.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT fills_json FROM provider_orders WHERE client_order_id=?",
            (client_order_id,),
        ).fetchall()
    if len(rows) != 1:
        raise AssertionError("the synthetic Risk close has no unique persisted provider order")
    fills = json.loads(rows[0][0])
    if type(fills) is not list or len(fills) != 1 or type(fills[0]) is not dict:
        raise AssertionError("the synthetic Risk close must persist exactly one fill")
    return fills[0]


def _new_monitor_registry(tmp_path: Path, *, dim05: ModuleType, risk_case):
    """A registered monitor port that fails on any call; it emits no evidence."""
    scope = WireScope(
        dim05._DOMAIN,
        strategy_ref=risk_case.source_strategy_ref,
        portfolio_ref=dim05._PORTFOLIO,
    )
    identity = WireIdentity(
        WireRole.SERVICE, _MONITOR_PRINCIPAL_REF, _MONITOR_SERVICE_ID
    )
    strategy_identity = WireIdentity(
        WireRole.STRATEGY_CLIENT,
        dim05._STRATEGY_PRINCIPAL,
        risk_case.source_strategy_ref,
    )
    registry = ServiceRegistry(
        tmp_path / "arb06-roll-exit-monitor-registry.sqlite3",
        service_id=_MONITOR_SERVICE_ID,
        capabilities=(
            ServiceCapability(
                _MONITOR_INSTANCE_ID,
                "service.monitor_query",
                _MONITOR_OPERATIONS,
            ),
        ),
        grants={
            dim05._STRATEGY_PRINCIPAL: (
                PrincipalGrant(
                    strategy_identity,
                    (
                        ResourceGrant(
                            _MONITOR_INSTANCE_ID,
                            "service.monitor_query",
                            _MONITOR_SCOPE_REF,
                            scope,
                            _MONITOR_OPERATIONS,
                        ),
                    ),
                ),
            )
        },
        policy_version="arb06-monitor-read-policy-v1",
        requirements_version="arb06-monitor-read-requirements-v1",
        lease_seconds=120,
    )
    calls: list[str] = []

    def fail_if_called(_context, _arguments):
        calls.append("monitor.read_after")
        raise AssertionError("this ARB06 node does not consume Monitor events")

    registry.register_handler(
        _MONITOR_INSTANCE_ID, "monitor.read_after", fail_if_called
    )
    return registry, identity, scope, calls


def _make_primary_writer_runtime(
    tmp_path: Path,
    *,
    api: _AccountStoreFacade,
    execution_domain_ref: str,
    peer_strategy_id: str,
    account_ref: str,
    run_id: str,
):
    """Use a fail-on-write local Registry for the ordinary shared Broker lane."""

    service_id = "arb06-roll-exit-ordinary-order-guard"
    service_principal = "arb06-roll-exit-ordinary-order-principal"
    instance_id = "arb06-roll-exit-ordinary-order-entry"
    order_scope_ref = _ORDINARY_ORDER_SCOPE_REF
    query_scope_ref = _ORDINARY_QUERY_SCOPE_REF
    strategy_principal = "arb06-roll-exit-peer-strategy-principal"
    service_peer = WireIdentity(WireRole.SERVICE, service_principal, service_id)
    strategy_identity = WireIdentity(
        WireRole.STRATEGY_CLIENT, strategy_principal, peer_strategy_id
    )
    order_scope = WireScope(
        execution_domain_ref,
        account_ref=account_ref,
        strategy_ref=peer_strategy_id,
    )
    query_scope = order_scope
    capabilities = (
        ServiceCapability(instance_id, "service.order_entry", _ORDER_WRITES, _ORDER_WRITES),
        ServiceCapability(instance_id, "service.order_query", _ORDER_QUERIES),
    )
    grants = {
        strategy_principal: (
            PrincipalGrant(
                strategy_identity,
                (
                    ResourceGrant(
                        instance_id,
                        "service.order_entry",
                        order_scope_ref,
                        order_scope,
                        _ORDER_WRITES,
                    ),
                    ResourceGrant(
                        instance_id,
                        "service.order_query",
                        query_scope_ref,
                        query_scope,
                        _ORDER_QUERIES,
                    ),
                ),
            ),
        )
    }
    registry = ServiceRegistry(
        tmp_path / "arb06-roll-exit-ordinary-registry.sqlite3",
        service_id=service_id,
        capabilities=capabilities,
        grants=grants,
        policy_version="arb06-roll-exit-ordinary-policy-v1",
        requirements_version="arb06-roll-exit-ordinary-requirements-v1",
        lease_seconds=120,
    )
    ordinary_writes: list[str] = []

    def reject_write(operation: str):
        def handler(_context, _arguments):
            ordinary_writes.append(operation)
            raise AssertionError("group roll-exit must not fall back to an ordinary Broker write")

        return handler

    registry.register_handler(instance_id, "orders.submit", reject_write("orders.submit"))
    registry.register_handler(instance_id, "orders.cancel", reject_write("orders.cancel"))
    registry.register_handler(instance_id, "orders.query", lambda _context, _args: {"found": False})

    client_config = parse_client_config(
        {
            "client_config_schema_version": 1,
            "process_role": "strategy_client",
            "registration": {"strategy_ref": peer_strategy_id},
            "clients": {
                "execution": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "broker.orders",
                                "service_id": service_id,
                                "instance_id": instance_id,
                                "scope_ref": order_scope_ref,
                                "account_ref": account_ref,
                                "transport_ref": "ordinary-registry-rpc",
                            },
                            {
                                "mount": "broker.order_query",
                                "service_id": service_id,
                                "instance_id": instance_id,
                                "scope_ref": query_scope_ref,
                                "account_ref": account_ref,
                                "transport_ref": "ordinary-registry-rpc",
                            },
                        ],
                        "options": {"request_timeout_ms": 500},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "ordinary-registry-rpc": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": "tcp://127.0.0.1:9"},
                        "security_profile_ref": "unused-local-registry-transport",
                    }
                },
            },
        }
    )

    def transport_factory(_profile, expected_peer):
        assert expected_peer == service_peer
        return _RegistryTransport(registry, service_peer)

    runtime = ServiceClientRuntime(
        client_config,
        identity=strategy_identity,
        scope_resolver={order_scope_ref: order_scope, query_scope_ref: query_scope}.__getitem__,
        peer_resolver=lambda _service: service_peer,
        transport_factory=transport_factory,
        run_id=run_id,
        requested_operations={
            "broker.orders": _ORDER_WRITES,
            "broker.order_query": _ORDER_QUERIES,
        },
    )
    store = BtApiStore(
        api=api,
        provider="btapi",
        account_cache_ttl=0,
        positions_cache_ttl=0,
        open_orders_cache_ttl=0,
    )
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=0.0,
        positions_refresh_interval=0.0,
        open_orders_refresh_interval=0.0,
        position_sync_policy="periodic",
        flatten_on_stop=False,
    )
    return registry, runtime, store, broker, ordinary_writes


def _strategy_group_config(
    *,
    strategy_ref: str,
    coordinator_service_id: str,
    coordinator_instance_id: str,
    coordinator_endpoint: str,
    group_scope_ref: str,
    monitor_scope_ref: str,
    monitor_endpoint: str,
    portfolio_ref: str,
):
    return parse_client_config(
        {
            "client_config_schema_version": 1,
            "process_role": "strategy_client",
            "registration": {"strategy_ref": strategy_ref},
            "clients": {
                "execution": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "broker.order_groups",
                                "service_id": coordinator_service_id,
                                "instance_id": coordinator_instance_id,
                                "scope_ref": group_scope_ref,
                                "portfolio_ref": portfolio_ref,
                                "transport_ref": _STRATEGY_TRANSPORT_REF,
                            }
                        ],
                        "options": {
                            "request_timeout_ms": _COORDINATOR_REQUEST_TIMEOUT_MS,
                            "heartbeat_interval_seconds": 5,
                        },
                    },
                },
                "monitor": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "broker.group_monitor",
                                "service_id": _MONITOR_SERVICE_ID,
                                "instance_id": _MONITOR_INSTANCE_ID,
                                "scope_ref": monitor_scope_ref,
                                "portfolio_ref": portfolio_ref,
                                "transport_ref": _MONITOR_TRANSPORT_REF,
                            }
                        ],
                        "options": {"request_timeout_ms": 500},
                    },
                },
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    _STRATEGY_TRANSPORT_REF: _rpc_profile(
                        coordinator_endpoint,
                        bind=False,
                        security_ref=_STRATEGY_SECURITY_REF,
                        request_timeout_ms=_COORDINATOR_REQUEST_TIMEOUT_MS,
                    ),
                    _MONITOR_TRANSPORT_REF: _rpc_profile(
                        monitor_endpoint,
                        bind=False,
                        security_ref=_MONITOR_SECURITY_REF,
                        request_timeout_ms=500,
                    ),
                },
            },
        }
    )


def _coordinator_host_factory(
    tmp_path: Path,
    *,
    dim05: ModuleType,
    risk_case,
    endpoint: str,
    server_public: bytes,
    server_secret: bytes,
    strategy_client_public: bytes,
):
    """Build a normal Coordinator Host using the real Risk Host bindings."""

    raw = copy.deepcopy(dict(risk_case.risk_client_service_config))
    raw.update(
        {
            "service_id": risk_case.coordinator_service_id,
            "scope_ref": "group-coordinator-root",
            "transport_ref": _COORDINATOR_LISTENER_REF,
            "registration_policy_ref": "group-coordinator-registration-v1",
            "service_requirements_ref": "group-coordinator-requirements-v1",
            "components": {
                "execution": _group_component(
                    risk_case.coordinator_instance_id,
                    dim05._PORTFOLIO,
                )
            },
        }
    )
    raw["communication"]["profiles"][_COORDINATOR_LISTENER_REF] = _rpc_profile(
        endpoint,
        bind=True,
        security_ref=_COORDINATOR_SECURITY_REF,
    )
    config = parse_service_config(raw)

    metadata = tuple(
        dim05._metadata(instrument, risk_case.metadata_reference_ns)
        for instrument in (dim05._V2_INSTRUMENT, dim05._PERP_INSTRUMENT)
    )
    route_refs = dim05._route_refs(risk_case.account_ref)
    route = GroupAccountRoute(
        execution_scope=dim05._execution_scope(risk_case.account_ref),
        risk_scope_fingerprint=risk_case.risk_scope_fingerprint,
        reservation_scope_ref=route_refs[0],
        order_scope_ref=route_refs[1],
        query_scope_ref=route_refs[2],
        instruments={
            dim05._V2_INSTRUMENT: GroupInstrumentRule(
                metadata=metadata[0],
                base_units_per_order_unit=Decimal("2"),
                allowed_order_types=frozenset({OrderType.LIMIT}),
            ),
            dim05._PERP_INSTRUMENT: GroupInstrumentRule(
                metadata=metadata[1],
                base_units_per_order_unit=Decimal("1"),
                allowed_order_types=frozenset({OrderType.LIMIT}),
            ),
        },
        roll_exit_order_scope_ref=risk_case.entry_scope_ref,
        roll_exit_query_scope_ref=risk_case.query_scope_ref,
    )
    budget_policy, budget_quote_builder = dim05._budget_binding(metadata)
    stable_scope = dim05._stable_strategy_scope((risk_case.account_ref,))
    target = GroupCoordinatorTarget(
        scope_ref=dim05._COORDINATOR_SCOPE_REF,
        accounts={risk_case.account_ref: route},
        max_group_lifetime_ns=300_000_000_000,
        portfolio_budget_policy=budget_policy,
        budget_quote_builder=budget_quote_builder,
    )

    risk_profiles = raw["communication"]["profiles"]
    entry_transport_ref = risk_case.entry_client_binding["transport_ref"]
    query_transport_ref = risk_case.query_client_binding["transport_ref"]
    if query_transport_ref != entry_transport_ref:
        raise AssertionError("Risk Host entry/query bindings must share the pinned transport")
    risk_security_ref = risk_profiles[entry_transport_ref]["security_profile_ref"]
    peer_identities = {risk_case.risk_identity.actor_ref: risk_case.risk_identity}
    trusted_clients = TrustedServiceClients(
        scope_resolver={
            risk_case.entry_scope_ref: risk_case.owner_scope,
            risk_case.query_scope_ref: risk_case.owner_scope,
        }.__getitem__,
        peer_resolver=peer_identities.__getitem__,
        transport_factory=ZmqTransportFactory(
            {
                risk_security_ref: ClientCurveKeys(
                    server_key=risk_case.server_public_key,
                    public_key=risk_case.client_public_key,
                    secret_key=risk_case.client_secret_key,
                )
            }
        ),
        requested_operations={
            "upstream.group_roll_exit_orders": frozenset({_RISK_SUBMIT}),
            "upstream.group_roll_exit_order_query": frozenset(
                {_RISK_PREPARE, _RISK_QUERY}
            ),
        },
    )

    def factory(cleanups):
        group_store = SqliteOrderGroupStore(risk_case.coordinator_paths["groups"])
        cleanups.append(group_store.close)
        run_bindings = GroupOriginRunBindingStore(
            risk_case.coordinator_paths["run_bindings"]
        )
        cleanups.append(run_bindings.close)

        def resource_provider(component, instance_id, _options, _scope):
            if component != "execution" or instance_id != risk_case.coordinator_instance_id:
                raise AssertionError("unexpected Coordinator resource request")
            return ComponentResources.borrowed(
                {
                    "store": group_store,
                    "targets": {stable_scope: target},
                    "run_bindings": run_bindings,
                },
                ready=lambda: True,
            )

        return ServiceHost(
            config,
            TrustedServiceAuthority(
                identity=risk_case.coordinator_identity,
                scope=WireScope(dim05._DOMAIN),
                scope_ref=config.scope_ref,
                scope_version="coordinator-scope-v1",
                security_ref=_COORDINATOR_SECURITY_REF,
                security_version="coordinator-curve-v1",
                registration_policy_ref=config.registration_policy_ref,
                registration_policy_version="coordinator-registration-v1",
                service_requirements_ref=config.service_requirements_ref,
                service_requirements_version="coordinator-requirements-v1",
                curve_public_key=server_public,
                curve_secret_key=server_secret,
                principals={
                    strategy_client_public: dim05._STRATEGY_PRINCIPAL
                },
                grants={
                    dim05._STRATEGY_PRINCIPAL: (
                        PrincipalGrant(
                            WireIdentity(
                                WireRole.STRATEGY_CLIENT,
                                dim05._STRATEGY_PRINCIPAL,
                                dim05._STRATEGY,
                            ),
                            (
                                ResourceGrant(
                                    risk_case.coordinator_instance_id,
                                    "service.order_group_entry",
                                    dim05._COORDINATOR_SCOPE_REF,
                                    stable_scope,
                                    _COORDINATOR_OPERATIONS,
                                ),
                            ),
                        ),
                    )
                },
            ),
            tmp_path / "arb06-roll-exit-coordinator-registry.sqlite3",
            resource_provider,
            service_directory={
                risk_case.coordinator_service_id: config,
                risk_case.risk_identity.actor_ref: parse_service_config(
                    risk_case.risk_service_config
                ),
            },
            trusted_clients=trusted_clients,
        )

    return factory


class _RollExitStrategy(bt.Strategy):
    params = (
        ("strategy_ref", None),
        ("portfolio_ref", None),
        ("group_id", None),
        ("source_leg_id", None),
        ("after_close", None),
        ("account_view", None),
    )

    def start(self):
        self.bind_service_execution_group()
        self.before = _broker_state(self)
        self.before_account_view = self.p.account_view()

    def next(self):
        self.submitted = self.submit_group_roll_exit(
            self.p.group_id, self.p.source_leg_id, Decimal("101")
        )
        action = self.submitted["result"]["action"]
        self.queried = self.query_group_roll_exit(action["action_id"])
        self.applied_fill = self.p.after_close(action)
        self.after = _broker_state(self)
        self.after_account_view = self.p.account_view()


class _PeerStrategy(bt.Strategy):
    params = (("strategy_ref", None), ("portfolio_ref", None), ("account_view", None))

    def start(self):
        self.before = _broker_state(self)
        self.before_account_view = self.p.account_view()

    def next(self):
        self.after = _broker_state(self)
        self.after_account_view = self.p.account_view()


def _broker_state(strategy) -> tuple[float, float, float]:
    return (
        strategy.broker.getcash(),
        strategy.broker.getvalue(),
        strategy.broker.getposition(strategy.data).size,
    )


def _cerebro(
    broker,
    *,
    instrument: str,
    dim05: ModuleType,
    risk_case,
    after_close,
    account_view,
):
    frame = pandas.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1.0],
            "openinterest": [0.0],
        },
        index=[dt.datetime(2026, 10, 17)],
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.setbroker(broker)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=instrument)
    cerebro.addstrategy(
        _RollExitStrategy,
        strategy_ref=risk_case.source_strategy_ref,
        portfolio_ref=dim05._PORTFOLIO,
        group_id=risk_case.group_id,
        source_leg_id=risk_case.source_leg_id,
        after_close=after_close,
        account_view=account_view,
    )
    cerebro.addstrategy(
        _PeerStrategy,
        strategy_ref=risk_case.peer_strategy_ref,
        portfolio_ref=dim05._PORTFOLIO,
        account_view=account_view,
    )
    return cerebro


@pytest.mark.integration
def test_arb06_two_strategy_cerebro_roll_exit_preserves_peer_account_allocation(
    tmp_path: Path,
) -> None:
    """The real Coordinator/Risk path closes A's source exposure and keeps B's."""

    risk_fixture = _load_fixed_risk_fixture()
    dim05 = importlib.import_module(_DIM05_SOURCE_MODULE)
    source_fixture = arb06._load_fixed_partial_group_fixture()
    seed_path = Path(os.environ[arb06._SDK_PARTIAL_FIXTURE_ENV]).resolve()
    assert Path(source_fixture.__file__).resolve() == seed_path
    assert hashlib.sha256(seed_path.read_bytes()).hexdigest() == _SEED_GROUP_FIXTURE_SHA256
    assert source_fixture._V2_INSTRUMENT == dim05._V2_INSTRUMENT
    assert source_fixture._PERP_INSTRUMENT == dim05._PERP_INSTRUMENT

    group_id = "group-arb06-two-strategy-roll-exit-01"
    source_leg_id = "leg-a"
    accounts = ("account-a",)
    expected_orders = {
        "account-a": (
            (source_fixture._V2_INSTRUMENT, "2", "100", "buy-limit"),
            (source_fixture._PERP_INSTRUMENT, "3", "100", "sell-limit"),
        )
    }
    rule_specs = {
        "account-a": {
            source_fixture._V2_INSTRUMENT: "2",
            source_fixture._PERP_INSTRUMENT: "1",
        }
    }
    provider_source = (
        Path(os.environ[_SDK_TESTS_ROOT_ENV]).resolve()
        / "unit"
        / "_service_group_provider_fixtures.py"
    )
    with _spawnable_seed_fixture_imports(
        tmp_path,
        seed_source=seed_path,
        provider_source=provider_source,
    ), source_fixture._GroupCluster(
        tmp_path,
        accounts=accounts,
        instruments={
            "account-a": (
                source_fixture._V2_INSTRUMENT,
                source_fixture._PERP_INSTRUMENT,
            )
        },
        initial_states={"account-a": ("cancelled:1.5", "filled")},
        expected_orders=expected_orders,
        rule_specs=rule_specs,
    ) as seed_cluster:
        seeded = seed_cluster.submit_group(
            source_fixture._group_request(
                group_id,
                seed_cluster.metadata_reference_ns,
                (
                    (
                        source_leg_id,
                        "account-a",
                        source_fixture.Side.BUY,
                        Decimal("2"),
                        source_fixture._V2_INSTRUMENT,
                    ),
                    (
                        "leg-b",
                        "account-a",
                        source_fixture.Side.SELL,
                        Decimal("4"),
                        source_fixture._PERP_INSTRUMENT,
                    ),
                ),
            )
        )
        assert seeded.state is GroupOrderState.PAIRED
        metadata_reference_ns = seed_cluster.metadata_reference_ns
        account_paths = {
            account_ref: dict(paths)
            for account_ref, paths in seed_cluster.account_paths.items()
        }
        coordinator_paths = dict(seed_cluster.coordinator_paths)

    with risk_fixture.dim05_roll_exit_risk_host(
        tmp_path,
        account_paths=account_paths,
        coordinator_paths=coordinator_paths,
        metadata_reference_ns=metadata_reference_ns,
        group_id=group_id,
        source_leg_id=source_leg_id,
    ) as risk_case:
        assert risk_case.source_strategy_ref == dim05._STRATEGY
        assert risk_case.source_filled_quantity == Decimal("1.5")
        assert risk_case.peer_strategy_ref != risk_case.source_strategy_ref
        assert risk_case.available(risk_case.source_strategy_ref) == Decimal("1.5")
        assert risk_case.available(risk_case.peer_strategy_ref) == Decimal("0.75")
        assert risk_case.provider_calls() == ()

        account_bundle = None
        account_runtime = None
        monitor_registry = None
        coordinator_loop = None
        primary_registry = None
        primary_runtime = None
        store = None
        group_runtime = None
        try:
            account_bundle = _start_account_host(
                tmp_path,
                dim05=dim05,
                risk_case=risk_case,
            )
            account_runtime = account_bundle["runtime"]
            monitor_registry, monitor_identity, monitor_scope, monitor_calls = (
                _new_monitor_registry(
                    tmp_path,
                    dim05=dim05,
                    risk_case=risk_case,
                )
            )
            coordinator_endpoint = _endpoint()
            coordinator_server_public, coordinator_server_secret = zmq.curve_keypair()
            strategy_client_public, strategy_client_secret = zmq.curve_keypair()
            coordinator_loop = _CoordinatorHostLoop(
                _coordinator_host_factory(
                    tmp_path,
                    dim05=dim05,
                    risk_case=risk_case,
                    endpoint=coordinator_endpoint,
                    server_public=coordinator_server_public,
                    server_secret=coordinator_server_secret,
                    strategy_client_public=strategy_client_public,
                )
            )
            coordinator_host = coordinator_loop.start()
            (
                primary_registry,
                primary_runtime,
                store,
                broker,
                ordinary_writes,
            ) = _make_primary_writer_runtime(
                tmp_path,
                api=account_bundle["api"],
                execution_domain_ref=dim05._DOMAIN,
                peer_strategy_id=risk_case.source_strategy_ref,
                account_ref=risk_case.account_ref,
                run_id=risk_case.run_id,
            )
            client_config = _strategy_group_config(
                strategy_ref=risk_case.source_strategy_ref,
                coordinator_service_id=risk_case.coordinator_service_id,
                coordinator_instance_id=risk_case.coordinator_instance_id,
                coordinator_endpoint=coordinator_host.endpoint,
                group_scope_ref=dim05._COORDINATOR_SCOPE_REF,
                monitor_scope_ref=_MONITOR_SCOPE_REF,
                monitor_endpoint=_endpoint(),
                portfolio_ref=dim05._PORTFOLIO,
            )
            group_scope = dim05._stable_strategy_scope((risk_case.account_ref,))
            transport_factory = ZmqTransportFactory(
                {
                    _STRATEGY_SECURITY_REF: ClientCurveKeys(
                        server_key=coordinator_server_public,
                        public_key=strategy_client_public,
                        secret_key=strategy_client_secret,
                    ),
                }
            )
            coordinator_operations: list[str] = []
            monitor_operations: list[str] = []

            def group_transport(profile, expected_peer):
                if profile["security_profile_ref"] == _STRATEGY_SECURITY_REF:
                    transport = transport_factory(profile, expected_peer)
                    return _RecordingTransport(
                        transport,
                        coordinator_operations,
                        frozenset({"groups.roll_exit", "groups.query_roll_exit"}),
                    )
                if profile["security_profile_ref"] == _MONITOR_SECURITY_REF:
                    if expected_peer != monitor_identity:
                        raise AssertionError("Monitor registry peer identity changed")
                    transport = _RegistryTransport(monitor_registry, monitor_identity)
                    return _RecordingTransport(
                        transport, monitor_operations, _MONITOR_OPERATIONS
                    )
                raise AssertionError("strategy runtime requested an unbound transport")

            coordinator_identity = risk_case.coordinator_identity
            group_runtime = ServiceClientRuntime(
                client_config,
                identity=WireIdentity(
                    WireRole.STRATEGY_CLIENT,
                    dim05._STRATEGY_PRINCIPAL,
                    risk_case.source_strategy_ref,
                ),
                scope_resolver={
                    dim05._COORDINATOR_SCOPE_REF: group_scope,
                    _MONITOR_SCOPE_REF: monitor_scope,
                }.__getitem__,
                peer_resolver={
                    risk_case.coordinator_service_id: coordinator_identity,
                    _MONITOR_SERVICE_ID: monitor_identity,
                }.__getitem__,
                transport_factory=group_transport,
                run_id=risk_case.run_id,
                requested_operations={
                    "broker.order_groups": _GROUP_OPERATIONS,
                    "broker.group_monitor": _MONITOR_OPERATIONS,
                },
            )
            route = ServiceStrategyGroupRoute(
                strategy_ref=risk_case.source_strategy_ref,
                portfolio_ref=dim05._PORTFOLIO,
                account_refs=(risk_case.account_ref,),
                runtime=group_runtime,
                group_scope_ref=dim05._COORDINATOR_SCOPE_REF,
                monitor_scope_ref=_MONITOR_SCOPE_REF,
                owned=True,
            )
            session = ServiceExecutionSession(
                primary_runtime,
                mount="broker.orders",
                scope_ref=_ORDINARY_ORDER_SCOPE_REF,
                query_mount="broker.order_query",
                query_scope_ref=_ORDINARY_QUERY_SCOPE_REF,
                strategy_group_routes=(route,),
            )

            def account_view():
                return account_bundle["account_client"].snapshot()

            def after_close(_action):
                calls = risk_case.provider_calls()
                if len(calls) != 1:
                    raise AssertionError("one synthetic Risk close provider call is required")
                fill = _read_risk_close_fill(risk_case, calls[0][4])
                account_bundle["state"].apply_close_fill(fill)
                refreshed = account_bundle["loop"].call(
                    lambda deployment: deployment.account_session_worker.refresh()
                )
                if refreshed is None:
                    raise AssertionError("Gateway account worker did not return its refresh receipt")
                previous_view = account_bundle["account_client"].last_view
                if previous_view is None:
                    raise AssertionError("account client lost its initial accepted snapshot")
                account_bundle["monotonic_now"][0] = (
                    previous_view.fresh_until_monotonic + 1.0
                )
                return fill

            strategies = session.run(
                _cerebro(
                    broker,
                    instrument=risk_case.source_instrument,
                    dim05=dim05,
                    risk_case=risk_case,
                    after_close=after_close,
                    account_view=account_view,
                )
            )

            assert session.state == "closed"
            assert session.cleanup_report.errors == ()
            assert session.cleanup_report.store_connected is False
            assert session.cleanup_report.runtime_state == "closed"
            assert session.cleanup_report.unregister_uncertainties == 0
            assert session.cleanup_report.cleanup_failures == 0
            assert primary_runtime.state == "closed"
            assert group_runtime.state == "closed"
            assert group_runtime.unregister_uncertainties == 0
            assert group_runtime.cleanup_failures == 0
            assert len(strategies) == 2
            by_strategy = {strategy.p.strategy_ref: strategy for strategy in strategies}
            owner = by_strategy[risk_case.source_strategy_ref]
            peer = by_strategy[risk_case.peer_strategy_ref]

            action = owner.submitted["result"]["action"]
            assert owner.submitted["ok"] is True
            assert owner.submitted["code"] == "OK"
            assert action["group_id"] == group_id
            assert action["source_leg_id"] == source_leg_id
            assert action["phase"] == "RESOLVED"
            assert action["close_state"] == "FILLED"
            assert Decimal(action["requested_quantity"]) == Decimal("1.5")
            assert Decimal(action["filled_quantity"]) == Decimal("1.5")
            assert owner.queried["result"]["found"] is True
            assert owner.queried["result"]["action"] == action
            assert coordinator_operations == [
                "groups.roll_exit",
                "groups.query_roll_exit",
            ]
            assert monitor_operations == []
            assert monitor_calls == []
            assert ordinary_writes == []

            close_calls = risk_case.provider_calls()
            assert len(close_calls) == 1
            assert close_calls[0][0] == risk_case.source_instrument
            assert close_calls[0][1] == Decimal("1.5")
            assert close_calls[0][2] == Decimal("101")
            assert close_calls[0][3] == "sell-limit"
            assert close_calls[0][4]
            assert risk_case.available(risk_case.source_strategy_ref) == Decimal("0")
            assert risk_case.available(risk_case.peer_strategy_ref) == Decimal("0.75")

            fill = owner.applied_fill
            assert fill == _read_risk_close_fill(risk_case, close_calls[0][4])
            assert fill["symbol"] == risk_case.source_instrument
            assert Decimal(fill["quantity"]) == Decimal("1.5")
            assert Decimal(fill["trade_price"]) == Decimal("101")
            assert Decimal(fill["fee_amount"]) == Decimal("-0.05")
            assert fill["fee_currency"] == "USD"
            assert owner.before == (10_000.0, 10_225.0, 2.25)
            assert owner.after == (10_151.55, 10_226.55, 0.75)
            assert peer.before == owner.before
            assert peer.after == owner.after
            assert owner.before_account_view.cursor < owner.after_account_view.cursor
            assert owner.before_account_view.snapshot_id != owner.after_account_view.snapshot_id
            assert peer.before_account_view is owner.before_account_view
            assert peer.after_account_view is owner.after_account_view
            assert owner.after_account_view.observation.to_dict() == (
                account_bundle["state"].observations[-1].to_dict()
            )
            assert owner.after_account_view.observation.positions[0].quantity == "0.75"
            assert owner.after_account_view.observation.valuation.available_cash == "10151.55"
            assert owner.after_account_view.observation.valuation.equity == "10226.55"
            assert len(account_bundle["state"].observations) >= 2
            assert account_bundle["provider"].connect_count == 1
            assert account_bundle["provider"].read_count >= 2
            assert account_bundle["api"].blocked_writes == []
            assert owner.before == peer.before
            assert store.is_connected is False
        finally:
            _close_test_resources(
                (
                    ("group runtime", lambda: _close_runtime(group_runtime)),
                    ("ordinary runtime", lambda: _close_runtime(primary_runtime)),
                    ("Backtrader store", lambda: _stop_store(store)),
                    (
                        "account Store facade",
                        lambda: _close_account_facade(account_bundle),
                    ),
                    ("account facade runtime", lambda: _close_account_runtime(account_runtime)),
                    ("ordinary registry", lambda: _close_registry(primary_registry)),
                    ("Coordinator Host", lambda: _close_host_loop(coordinator_loop)),
                    ("Monitor registration registry", lambda: _close_registry(monitor_registry)),
                    (
                        "Gateway account Host",
                        lambda: _close_account_host(account_bundle),
                    ),
                )
            )


def _close_runtime(runtime) -> None:
    if runtime is None or runtime.state == "closed":
        return
    runtime.close()
    if runtime.state != "closed":
        raise AssertionError(
            ("ServiceClientRuntime did not close normally", runtime.state)
        )


def _stop_store(store) -> None:
    if store is not None and store.is_connected:
        store.stop()


def _close_registry(registry) -> None:
    if registry is not None:
        registry.close()


def _close_host_loop(loop) -> None:
    if loop is not None:
        loop.close()


def _close_account_runtime(runtime) -> None:
    if runtime is None:
        return
    _close_runtime(runtime)
    if runtime.state != "closed" or runtime.cleanup_failures or runtime.unregister_uncertainties:
        raise AssertionError(
            (
                "account client runtime did not close normally",
                runtime.state,
                runtime.cleanup_failures,
                runtime.unregister_uncertainties,
            )
        )


def _close_account_facade(bundle) -> None:
    if bundle is None:
        return
    bundle["api"].disconnect()
    if bundle["proxy"].is_connected:
        raise AssertionError("ServiceReadProxy did not disconnect normally")
    if bundle["account_client"].healthy:
        raise AssertionError("ServiceAccountClient retained a live snapshot after close")


def _close_account_host(bundle) -> None:
    if bundle is None:
        return
    _close_host_loop(bundle["loop"])
    if bundle["deployment"].state != "closed":
        raise AssertionError("Gateway account Host did not close normally")
    if bundle["provider"].close_count != 1:
        raise AssertionError("synthetic Gateway provider did not close exactly once")
    if bundle["loop"].cleanup_errors:
        raise AssertionError(
            tuple(type(error).__name__ for error in bundle["loop"].cleanup_errors)
        )


def _close_test_resources(resources) -> None:
    """Attempt every owned cleanup and preserve the test's first exception."""

    active_error = sys.exc_info()[1]
    failures = []
    for label, cleanup in resources:
        try:
            cleanup()
        except BaseException as error:
            failures.append((label, error))

    if not failures:
        return
    descriptions = tuple(
        (label, type(error).__name__) for label, error in failures
    )
    if active_error is not None:
        for label, error in failures:
            active_error.add_note(
                f"{label} cleanup also failed: {type(error).__name__}"
            )
        return

    cleanup_error = AssertionError(("test resource cleanup failed", descriptions))
    for label, error in failures[1:]:
        cleanup_error.add_note(f"{label} cleanup also failed: {type(error).__name__}")
    raise cleanup_error from failures[0][1]


@pytest.mark.parametrize("initial_state", ("failed", "close_failed"))
def test_close_runtime_retries_failed_state_and_verifies_closed(initial_state: str) -> None:
    class RuntimeProbe:
        def __init__(self) -> None:
            self.state = initial_state
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            self.state = "closed"

    runtime = RuntimeProbe()
    _close_runtime(runtime)

    assert runtime.close_calls == 1
    assert runtime.state == "closed"


def test_runtime_cleanup_failure_keeps_primary_error_and_adds_cleanup_note() -> None:
    class RuntimeProbe:
        state = "failed"

        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("synthetic runtime close failure")

    runtime = RuntimeProbe()
    primary = ValueError("synthetic setup failure")
    try:
        try:
            raise primary
        finally:
            _close_test_resources(
                (("account runtime", lambda: _close_runtime(runtime)),)
            )
    except ValueError as error:
        assert error is primary
        assert any(
            "account runtime cleanup also failed: RuntimeError" in note
            for note in getattr(error, "__notes__", ())
        )
    else:
        raise AssertionError("primary setup failure was not preserved")
    assert runtime.close_calls == 1
