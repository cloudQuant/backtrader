"""Normal Cerebro wiring for one strategy-bound P5A group route.

The public SDK runtime and Registry are real. A synthetic registered
coordinator handler returns a typed partial-group snapshot, with a synthetic
provider leaf; Monitor's read-only service and durable outbox are real. This
integration checks that a group residual remains a Strategy-scoped fact and
never books Broker cash or positions for another Strategy sharing the same
account.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

import backtrader as bt
import pandas
from bt_api_base.service_protocol import (
    WireEnvelope,
    WireIdentity,
    WireMessageKind,
    WireRole,
    WireScope,
)
from bt_api_execution import (
    ExecutionScope,
    GroupAccountReservationSnapshot,
    GroupLegPhase,
    GroupLegProgress,
    GroupOrderIntent,
    GroupOrderLegPlan,
    GroupOrderSnapshot,
    GroupOrderState,
    GroupReservationPhase,
    OrderIntent,
    PositionEffect,
    Side,
    TimeInForce,
    group_leg_intent_id,
)
from bt_api_monitor.durable import DurableOutbox, OutboxEvent
from bt_api_monitor.service_component import MonitorReadService, MonitorReadTarget
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_registry import (
    PrincipalGrant,
    ResourceGrant,
    ServiceCapability,
    ServiceRegistry,
)
from bt_api_py.service_runtime import (
    ServiceCallOutcomeUnknownError,
    ServiceClientRuntime,
)

from backtrader.stores.service_execution_group import (
    ServiceExecutionGroupAdapter,
    ServiceExecutionGroupError,
    ServiceExecutionGroupUnknownOutcomeError,
    ServiceGroupResidualCursor,
    ServiceStrategyGroupRoute,
)
from backtrader.stores.service_execution_session import (
    ServiceExecutionSession,
    ServiceExecutionSessionConfigError,
    _coerce_strategy_group_routes,
)
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store


_SERVICE_ID = "p5a-cerebro-service"
_SERVICE_PEER = WireIdentity(WireRole.SERVICE, "p5a-service-principal", _SERVICE_ID)
_STRATEGY_A = "p5a-strategy-a"
_STRATEGY_B = "p5a-strategy-b"
_PRINCIPAL_A = "p5a-principal-a"
_PRINCIPAL_B = "p5a-principal-b"
_ACCOUNT = "shared-account"
_PORTFOLIO = "shared-portfolio"
_DOMAIN = "p5a-paper-domain"
_INSTRUMENT = "BTC/USDT"
_GROUP_ID = "p5a-group-a-001"
_GROUP_INSTANCE = "p5a-coordinator"
_MONITOR_INSTANCE = "p5a-monitor"
_BROKER_INSTANCE = "p5a-broker"
_GROUP_SCOPE_REF = "p5a-group-scope-a"
_MONITOR_SCOPE_REF = "p5a-monitor-scope-a"
_ORDER_SCOPE_REF = "p5a-order-scope-b"
_QUERY_SCOPE_REF = "p5a-query-scope-b"
_WRITER_OPERATIONS = frozenset({"orders.submit", "orders.cancel"})
_QUERY_OPERATIONS = frozenset({"orders.query"})
_GROUP_OPERATIONS = frozenset({"groups.submit", "groups.query"})
_MONITOR_OPERATIONS = frozenset({"monitor.read_after"})
_RESIDUAL_SCOPE = "p5a-group-residuals"
_JOURNAL_GENERATION = "a" * 64
_RESIDUAL_EVENT_SHA256 = "b" * 64
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))


class _RegistryTransport:
    """In-process transport that keeps the SDK Registry on the request path."""

    def __init__(self, registry: ServiceRegistry, dispatch_facts=None) -> None:
        self._registry = registry
        self._dispatch_facts = dispatch_facts if dispatch_facts is not None else []
        self.requests = []
        self.closed = False

    def request(self, request, *, timeout):
        del timeout
        self.requests.append(request)
        identity = request.header.identity
        response = self._registry.handle(identity.principal_ref, request)
        operation = request.header.operation
        if operation in {"groups.submit", "groups.query", "monitor.read_after"}:
            result = response.get("result") if isinstance(response, Mapping) else None
            fact = {
                "operation": operation,
                "ok": response.get("ok") if isinstance(response, Mapping) else None,
                "code": response.get("code") if isinstance(response, Mapping) else None,
                "result_keys": tuple(sorted(result)) if isinstance(result, Mapping) else (),
            }
            if operation == "monitor.read_after" and isinstance(result, Mapping):
                page_events = result.get("events")
                fact["requested_cursor"] = result.get("requested_cursor")
                fact["next_cursor"] = result.get("next_cursor")
                fact["event_ids"] = (
                    tuple(
                        event.get("event_id")
                        for event in page_events
                        if isinstance(event, Mapping)
                    )
                    if isinstance(page_events, (tuple, list))
                    else ()
                )
            self._dispatch_facts.append(fact)
        if request.header.operation == "groups.submit":
            # Simulate a lost reply only after the synthetic coordinator has
            # returned success. Rejections and handler failures remain visible
            # to the caller instead of masquerading as a successful unknown.
            if isinstance(response, Mapping) and response.get("ok") is True:
                raise ServiceCallOutcomeUnknownError(request.header.message_id, operation)
        return WireEnvelope(
            replace(
                request.header,
                kind=WireMessageKind.REPLY,
                message_id=f"reply-{request.header.message_id}",
                correlation_id=request.header.message_id,
                identity=_SERVICE_PEER,
            ),
            response,
        )

    def close(self) -> None:
        self.closed = True


class _SyntheticProviderLeaf:
    """Final synthetic execution edge; it never mutates BtApiBroker state."""

    def __init__(self) -> None:
        self.calls = []

    def dispatch_partial_group(self, intent: GroupOrderIntent):
        self.calls.append((intent.group_id, tuple(leg.leg_id for leg in intent.legs)))
        return {
            "first_filled_quantity": "0.10",
            "second_filled_quantity": "0.04",
            "residual_base_units": "0.06",
        }


class _SyntheticCoordinator:
    """Registered group service boundary backed by typed SDK snapshots."""

    def __init__(self, intent, provider, outbox) -> None:
        self.intent = intent
        self.provider = provider
        self.outbox = outbox
        self.snapshot = None
        self.submit_calls = 0
        self.submit_stage = "not_called"
        self.submit_failure_type = None
        self.submit_request_mismatch = None
        self.query_calls = 0
        self.received_submit_bodies = []

    def submit(self, context, arguments):
        self.submit_calls += 1
        self.submit_stage = "entered"
        try:
            return self._submit(context, arguments)
        except Exception as error:
            self.submit_failure_type = type(error).__name__
            raise

    def _submit(self, context, arguments):
        self.received_submit_bodies.append(dict(arguments))
        _assert_strategy_context(context, _STRATEGY_A, ("groups.submit",))
        self.submit_stage = "context_validated"
        self.submit_stage = "request_validation"
        self.submit_request_mismatch = _wire_json_mismatch(
            arguments, _submit_body(self.intent)
        )
        assert self.submit_request_mismatch is None, (
            f"wire submit body mismatch at {self.submit_request_mismatch}"
        )
        self.submit_stage = "request_validated"
        if self.snapshot is not None:
            # The coordinator is idempotent by the original group ID. This
            # branch returns the existing durable result without dispatching.
            return {"found": True, "snapshot": self.snapshot.to_payload()}

        fill = self.provider.dispatch_partial_group(self.intent)
        self.submit_stage = "provider_dispatched"
        timestamp_ns = self.intent.received_at_ns + 1
        reservations = tuple(
            GroupAccountReservationSnapshot(
                group_id=self.intent.group_id,
                account_ref=account_ref,
                scope_fingerprint=hashlib.sha256(
                    f"{self.intent.strategy_id}:{account_ref}".encode("utf-8")
                ).hexdigest(),
                phase=GroupReservationPhase.ACTIVE,
            )
            for account_ref in self.intent.account_refs
        )
        legs = tuple(
            GroupLegProgress(leg_id=leg.leg_id, phase=GroupLegPhase.UNKNOWN)
            for leg in self.intent.legs
        )
        self.snapshot = GroupOrderSnapshot(
            request=self.intent,
            state=GroupOrderState.RECOVERY_REQUIRED,
            revision=1,
            reservations=reservations,
            legs=legs,
            residual_base_units=Decimal(fill["residual_base_units"]),
            error_code="SYNTHETIC_PARTIAL_FILL",
            created_at_ns=timestamp_ns,
            updated_at_ns=timestamp_ns,
        )
        self.submit_stage = "snapshot_created"
        self.outbox.append(
            OutboxEvent(
                event_id="p5a-residual-event-a-001",
                scope=_RESIDUAL_SCOPE,
                event_type="group.residual",
                data={
                    "schema": "sdk.group_monitor_projection.v1",
                    "journal_generation": _JOURNAL_GENERATION,
                    # The source journal cursor is deliberately independent
                    # from the Monitor outbox cursor returned to the client.
                    "source_sequence": 41,
                    "source_event_sha256": _RESIDUAL_EVENT_SHA256,
                    "source_revision": self.snapshot.revision,
                    "source_created_at_ns": timestamp_ns,
                    "portfolio_ref": self.intent.portfolio_ref,
                    "group_id": self.intent.group_id,
                    "strategy_id": self.intent.strategy_id,
                    "account_refs": list(self.intent.account_refs),
                    "state": "RECOVERY_REQUIRED",
                    "reason": "hedge_residual_unresolved",
                    "residual_base_units": fill["residual_base_units"],
                    "first_leg_id": self.intent.first_leg_id,
                    "second_leg_id": next(
                        leg.leg_id for leg in self.intent.legs
                        if leg.leg_id != self.intent.first_leg_id
                    ),
                    "first_filled_quantity": fill["first_filled_quantity"],
                    "second_filled_quantity": fill["second_filled_quantity"],
                },
                occurred_at=timestamp_ns / 1_000_000_000,
            )
        )
        self.submit_stage = "outbox_appended"
        return {"found": True, "snapshot": self.snapshot.to_payload()}

    def query(self, context, arguments):
        self.query_calls += 1
        _assert_strategy_context(context, _STRATEGY_A, ("groups.query",))
        assert set(arguments) == {"group_id"}
        if arguments["group_id"] != self.intent.group_id or self.snapshot is None:
            return {"found": False, "snapshot": None}
        return {"found": True, "snapshot": self.snapshot.to_payload()}


def _assert_strategy_context(context, strategy_ref, operations):
    assert context.identity.role is WireRole.STRATEGY_CLIENT
    assert context.identity.actor_ref == strategy_ref
    assert context.scope.strategy_ref == strategy_ref
    assert context.scope.run_id
    assert context.scope.execution_domain_ref == _DOMAIN
    if "groups.submit" in operations or "groups.query" in operations:
        assert context.scope.account_refs == (_ACCOUNT,)
        assert context.scope.portfolio_ref == _PORTFOLIO
    if "monitor.read_after" in operations:
        assert context.scope.account_refs == ()
        assert context.scope.portfolio_ref == _PORTFOLIO


def _submit_body(intent):
    return {
        "group_id": intent.group_id,
        "deadline_ns": intent.deadline_ns,
        "first_leg_id": intent.first_leg_id,
        "legs": [
            {
                "leg_id": leg.leg_id,
                "account_ref": leg.account_ref,
                "intent": leg.maximum_intent.to_payload(),
            }
            for leg in intent.legs
        ],
    }


def _wire_json_mismatch(actual, expected, path="$"):
    """Compare a mutable JSON fixture with the SDK's frozen wire tree."""

    if isinstance(expected, Mapping):
        if type(actual) is not _MAPPING_PROXY_TYPE:
            return f"{path}:mapping_type"
        if set(actual) != set(expected):
            return f"{path}:mapping_keys"
        for key in sorted(expected):
            mismatch = _wire_json_mismatch(actual[key], expected[key], f"{path}.{key}")
            if mismatch is not None:
                return mismatch
        return None
    if type(expected) in (list, tuple):
        if type(actual) is not tuple:
            return f"{path}:sequence_type"
        if len(actual) != len(expected):
            return f"{path}:sequence_length"
        for index, (actual_item, expected_item) in enumerate(zip(actual, expected)):
            mismatch = _wire_json_mismatch(
                actual_item, expected_item, f"{path}[{index}]"
            )
            if mismatch is not None:
                return mismatch
        return None
    if type(actual) is not type(expected) or actual != expected:
        return f"{path}:scalar"
    return None


def _intent() -> GroupOrderIntent:
    received_at_ns = 1_800_000_000_000_000_000
    deadline_ns = received_at_ns + 30_000_000_000

    def leg(leg_id, side):
        scope = ExecutionScope(
            provider="btapi",
            environment="paper",
            account_ref=_ACCOUNT,
            strategy_id=_STRATEGY_A,
        )
        maximum_intent = OrderIntent.limit(
            intent_id=group_leg_intent_id(_GROUP_ID, leg_id),
            scope=scope,
            signal_id=f"signal-{leg_id}",
            instrument=_INSTRUMENT,
            side=side,
            quantity=Decimal("0.10"),
            price=Decimal("100"),
            position_effect=PositionEffect.OPEN,
            time_in_force=TimeInForce.IOC,
            reduce_only=False,
            metadata_version="p5a-cerebro-v1",
            deadline_ns=deadline_ns,
            tags={"instrument_metadata_digest": "c" * 64},
        )
        return GroupOrderLegPlan(
            leg_id=leg_id,
            account_ref=_ACCOUNT,
            maximum_intent=maximum_intent,
            base_units_per_order_unit=Decimal("1"),
            quantity_step=Decimal("0.01"),
            metadata_valid_until_ns=deadline_ns + 1,
        )

    return GroupOrderIntent(
        group_id=_GROUP_ID,
        portfolio_ref=_PORTFOLIO,
        strategy_id=_STRATEGY_A,
        coordinator_principal_ref="p5a-coordinator-principal",
        received_at_ns=received_at_ns,
        deadline_ns=deadline_ns,
        first_leg_id="entry-leg",
        legs=(leg("entry-leg", Side.BUY), leg("hedge-leg", Side.SELL)),
    )


def _runtime_config(strategy_ref, bindings):
    clients = {}
    aliases_by_mount = {
        "broker.orders": "execution",
        "broker.order_query": "execution",
        "broker.order_groups": "execution",
        "broker.group_monitor": "monitor",
    }
    for binding in bindings:
        alias = aliases_by_mount[binding["mount"]]
        client = clients.setdefault(
            alias,
            {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [],
                    "options": {"request_timeout_ms": 500},
                },
            },
        )
        # parse_client_config consumes plain JSON trees: bindings must be a
        # list, and each mount must live under its schema-defined alias.
        client["settings"]["bindings"].append(dict(binding))

    return parse_client_config(
        {
            "client_config_schema_version": 1,
            "process_role": "strategy_client",
            "registration": {"strategy_ref": strategy_ref},
            "clients": clients,
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
    )


def _client_runtime(
    registry,
    *,
    strategy_ref,
    principal_ref,
    bindings,
    scopes,
    requested,
    dispatch_facts=None,
):
    identity = WireIdentity(WireRole.STRATEGY_CLIENT, principal_ref, strategy_ref)
    return ServiceClientRuntime(
        _runtime_config(strategy_ref, bindings),
        identity=identity,
        scope_resolver=scopes.__getitem__,
        peer_resolver=lambda _service_id: _SERVICE_PEER,
        transport_factory=lambda _profile, _peer: _RegistryTransport(
            registry, dispatch_facts
        ),
        run_id=f"p5a-cerebro-{strategy_ref}-run",
        requested_operations=requested,
    )


def _registry(tmp_path, intent, provider, outbox, monitor):
    a_group_scope = WireScope(
        _DOMAIN,
        account_refs=(_ACCOUNT,),
        strategy_ref=_STRATEGY_A,
        portfolio_ref=_PORTFOLIO,
    )
    a_monitor_scope = WireScope(
        _DOMAIN,
        strategy_ref=_STRATEGY_A,
        portfolio_ref=_PORTFOLIO,
    )
    b_order_scope = WireScope(
        _DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY_B
    )
    b_query_scope = WireScope(
        _DOMAIN, account_ref=_ACCOUNT, strategy_ref=_STRATEGY_B
    )

    capabilities = (
        ServiceCapability(
            _BROKER_INSTANCE,
            "service.order_entry",
            _WRITER_OPERATIONS,
            _WRITER_OPERATIONS,
        ),
        ServiceCapability(_BROKER_INSTANCE, "service.order_query", _QUERY_OPERATIONS),
        ServiceCapability(
            _GROUP_INSTANCE,
            "service.order_group_entry",
            _GROUP_OPERATIONS,
            frozenset({"groups.submit"}),
        ),
        ServiceCapability(_MONITOR_INSTANCE, "service.monitor_query", _MONITOR_OPERATIONS),
    )
    grants = {
        _PRINCIPAL_A: (
            PrincipalGrant(
                WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL_A, _STRATEGY_A),
                (
                    ResourceGrant(
                        _GROUP_INSTANCE,
                        "service.order_group_entry",
                        _GROUP_SCOPE_REF,
                        a_group_scope,
                        _GROUP_OPERATIONS,
                    ),
                    ResourceGrant(
                        _MONITOR_INSTANCE,
                        "service.monitor_query",
                        _MONITOR_SCOPE_REF,
                        a_monitor_scope,
                        _MONITOR_OPERATIONS,
                    ),
                ),
            ),
        ),
        _PRINCIPAL_B: (
            PrincipalGrant(
                WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL_B, _STRATEGY_B),
                (
                    ResourceGrant(
                        _BROKER_INSTANCE,
                        "service.order_entry",
                        _ORDER_SCOPE_REF,
                        b_order_scope,
                        _WRITER_OPERATIONS,
                    ),
                    ResourceGrant(
                        _BROKER_INSTANCE,
                        "service.order_query",
                        _QUERY_SCOPE_REF,
                        b_query_scope,
                        _QUERY_OPERATIONS,
                    ),
                ),
            ),
        ),
    }
    registry = ServiceRegistry(
        tmp_path / "p5a-registry.sqlite3",
        service_id=_SERVICE_ID,
        capabilities=capabilities,
        grants=grants,
        policy_version="p5a-access-v1",
        requirements_version="p5a-ready-v1",
        lease_seconds=120,
    )
    coordinator = _SyntheticCoordinator(intent, provider, outbox)
    ordinary_write_calls = []

    def reject_ordinary_write(operation):
        def handler(_context, _arguments):
            ordinary_write_calls.append(operation)
            raise AssertionError("ordinary order writes are outside this group test")

        return handler

    registry.register_handler(_GROUP_INSTANCE, "groups.submit", coordinator.submit)
    registry.register_handler(_GROUP_INSTANCE, "groups.query", coordinator.query)

    def read_monitor(context, arguments):
        _assert_strategy_context(context, _STRATEGY_A, ("monitor.read_after",))
        return monitor.handle(
            "monitor.read_after",
            principal_ref=context.principal_ref,
            scope=context.scope,
            arguments=arguments,
        )

    registry.register_handler(_MONITOR_INSTANCE, "monitor.read_after", read_monitor)
    registry.register_handler(
        _BROKER_INSTANCE,
        "orders.submit",
        reject_ordinary_write("orders.submit"),
    )
    registry.register_handler(
        _BROKER_INSTANCE,
        "orders.cancel",
        reject_ordinary_write("orders.cancel"),
    )
    registry.register_handler(
        _BROKER_INSTANCE,
        "orders.query",
        lambda _context, _arguments: {"found": False},
    )
    return (
        registry,
        coordinator,
        ordinary_write_calls,
        a_group_scope,
        a_monitor_scope,
        b_order_scope,
        b_query_scope,
    )


def _broker_state(strategy):
    position = strategy.broker.getposition(strategy.data)
    return (
        strategy.broker.getcash(),
        strategy.broker.getvalue(),
        position.size,
        position.price,
    )


class _GroupStrategy(bt.Strategy):
    params = (("strategy_ref", _STRATEGY_A), ("portfolio_ref", _PORTFOLIO), ("intent", None))

    def start(self):
        self.bind_service_execution_group()
        self.group_route_bound = True
        self.before_group = _broker_state(self)

    def next(self):
        self.submit_error = None
        try:
            self.submit_snapshot = self.submit_group_order(self.p.intent)
        except ServiceExecutionGroupUnknownOutcomeError as error:
            self.submit_error = error.code
        except ServiceExecutionGroupError as error:
            self.submit_error = error.code
        self.first_page = self.read_group_residuals()
        self.replay_page = self.read_group_residuals()
        persisted_cursor = ServiceGroupResidualCursor.from_payload(
            self.first_page.cursor.to_payload()
        )
        self.recovery = self.recover_group_order(
            self.p.intent.group_id, persisted_cursor
        )
        self.after_group = _broker_state(self)


class _SharedAccountObserver(bt.Strategy):
    params = (("strategy_ref", _STRATEGY_B), ("portfolio_ref", _PORTFOLIO))

    def start(self):
        try:
            self.bind_service_execution_group()
        except ServiceExecutionGroupError as error:
            self.group_route_error = error.code
        else:  # pragma: no cover - this runtime has no Strategy A group grant
            self.group_route_error = "UNEXPECTED_GROUP_ROUTE"
        self.before_group = _broker_state(self)

    def next(self):
        self.after_group = _broker_state(self)


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
    cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=_INSTRUMENT)
    cerebro.addstrategy(_GroupStrategy, intent=intent)
    cerebro.addstrategy(_SharedAccountObserver)
    return cerebro


def test_group_residual_stays_strategy_scoped_in_shared_account_cerebro(tmp_path):
    intent = _intent()
    provider = _SyntheticProviderLeaf()
    outbox_path = tmp_path / "p5a-monitor-outbox.sqlite3"
    outbox = DurableOutbox(outbox_path)
    read_only_outbox = DurableOutbox(outbox_path, read_only=True)
    monitor = MonitorReadService(
        read_only_outbox,
        {
            WireScope(
                _DOMAIN,
                strategy_ref=_STRATEGY_A,
                portfolio_ref=_PORTFOLIO,
            ): MonitorReadTarget(_RESIDUAL_SCOPE, ("group.residual",))
        },
    )
    (
        registry,
        coordinator,
        ordinary_write_calls,
        group_scope,
        monitor_scope,
        order_scope,
        query_scope,
    ) = _registry(tmp_path, intent, provider, outbox, monitor)
    group_dispatch_facts = []

    group_runtime = _client_runtime(
        registry,
        strategy_ref=_STRATEGY_A,
        principal_ref=_PRINCIPAL_A,
        bindings=(
            {
                "mount": "broker.order_groups",
                "service_id": _SERVICE_ID,
                "instance_id": _GROUP_INSTANCE,
                "scope_ref": _GROUP_SCOPE_REF,
                "portfolio_ref": _PORTFOLIO,
                "transport_ref": "execution-rpc",
            },
            {
                "mount": "broker.group_monitor",
                "service_id": _SERVICE_ID,
                "instance_id": _MONITOR_INSTANCE,
                "scope_ref": _MONITOR_SCOPE_REF,
                "portfolio_ref": _PORTFOLIO,
                "transport_ref": "execution-rpc",
            },
        ),
        scopes={_GROUP_SCOPE_REF: group_scope, _MONITOR_SCOPE_REF: monitor_scope},
        requested={
            "broker.order_groups": _GROUP_OPERATIONS,
            "broker.group_monitor": _MONITOR_OPERATIONS,
        },
        dispatch_facts=group_dispatch_facts,
    )
    primary_runtime = _client_runtime(
        registry,
        strategy_ref=_STRATEGY_B,
        principal_ref=_PRINCIPAL_B,
        bindings=(
            {
                "mount": "broker.orders",
                "service_id": _SERVICE_ID,
                "instance_id": _BROKER_INSTANCE,
                "scope_ref": _ORDER_SCOPE_REF,
                "account_ref": _ACCOUNT,
                "transport_ref": "execution-rpc",
            },
            {
                "mount": "broker.order_query",
                "service_id": _SERVICE_ID,
                "instance_id": _BROKER_INSTANCE,
                "scope_ref": _QUERY_SCOPE_REF,
                "account_ref": _ACCOUNT,
                "transport_ref": "execution-rpc",
            },
        ),
        scopes={_ORDER_SCOPE_REF: order_scope, _QUERY_SCOPE_REF: query_scope},
        requested={
            "broker.orders": _WRITER_OPERATIONS,
            "broker.order_query": _QUERY_OPERATIONS,
        },
    )

    store = make_store(
        api=FakeBtApiClient(
            balance={"cash": 10_000.0, "value": 10_200.0},
            positions=[{"instrument": _INSTRUMENT, "volume": 2.0, "price": 100.0}],
            open_orders=[],
        ),
        provider="btapi",
    )
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=3600.0,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    session = ServiceExecutionSession(
        primary_runtime,
        mount="broker.orders",
        scope_ref=_ORDER_SCOPE_REF,
        query_mount="broker.order_query",
        query_scope_ref=_QUERY_SCOPE_REF,
        strategy_group_routes=(
            ServiceStrategyGroupRoute(
                strategy_ref=_STRATEGY_A,
                portfolio_ref=_PORTFOLIO,
                account_refs=(_ACCOUNT,),
                runtime=group_runtime,
                group_scope_ref=_GROUP_SCOPE_REF,
                monitor_scope_ref=_MONITOR_SCOPE_REF,
                owned=True,
            ),
        ),
    )
    try:
        strategies = session.run(_cerebro(broker, intent))
        assert session.state == "closed"
        assert session.cleanup_report.errors == ()
        assert session.cleanup_report.store_connected is False
        assert session.cleanup_report.runtime_state == "closed"
        assert group_runtime.state == "closed"
        assert primary_runtime.state == "closed"
        assert len(strategies) == 2

        group_strategy, observer = strategies
        assert group_strategy.group_route_bound is True
        submit_facts = tuple(
            fact
            for fact in group_dispatch_facts
            if fact["operation"] == "groups.submit"
        )
        outbox_rows, _ = read_only_outbox.read_page_types(
            _RESIDUAL_SCOPE, ("group.residual",), 0, 32
        )
        outbox_facts = tuple(
            (
                row.sequence,
                row.event.event_id,
                row.event.scope,
                row.event.event_type,
                row.event.data.get("first_filled_quantity"),
                row.event.data.get("second_filled_quantity"),
                row.event.data.get("residual_base_units"),
            )
            for row in outbox_rows
        )
        assert len(submit_facts) == 1, (
            "expected one Registry groups.submit dispatch; "
            f"dispatch={submit_facts!r}, coordinator_calls={coordinator.submit_calls}, "
            f"coordinator_stage={coordinator.submit_stage!r}, provider_calls={provider.calls!r}, "
            f"coordinator_failure={coordinator.submit_failure_type!r}, "
            f"request_mismatch={coordinator.submit_request_mismatch!r}, "
            f"durable_outbox={outbox_facts!r}"
        )
        assert (
            submit_facts[0]["ok"] is True
            and submit_facts[0]["code"] == "OK"
            and submit_facts[0]["result_keys"] == ("found", "snapshot")
            and coordinator.submit_stage == "outbox_appended"
        ), (
            "group submit did not durably complete before simulated reply loss; "
            f"dispatch={submit_facts[0]!r}, coordinator_calls={coordinator.submit_calls}, "
            f"coordinator_stage={coordinator.submit_stage!r}, provider_calls={provider.calls!r}, "
            f"coordinator_failure={coordinator.submit_failure_type!r}, "
            f"request_mismatch={coordinator.submit_request_mismatch!r}, "
            f"durable_outbox={outbox_facts!r}"
        )
        assert group_strategy.submit_error == "REQUEST_OUTCOME_UNKNOWN"
        assert not hasattr(group_strategy, "submit_snapshot")
        monitor_dispatch = tuple(
            fact
            for fact in group_dispatch_facts
            if fact["operation"] == "monitor.read_after"
        )
        assert len(group_strategy.first_page.events) == 1, (
            "Monitor did not return the one durable residual event; "
            f"page={group_strategy.first_page!r}, durable_outbox={outbox_facts!r}, "
            f"monitor_dispatch={monitor_dispatch!r}"
        )
        residual = group_strategy.first_page.events[0]
        assert residual.group_id == _GROUP_ID
        assert residual.strategy_ref == _STRATEGY_A
        assert residual.sequence == 1
        assert residual.source_created_at_ns > 0
        assert residual.first_filled_quantity == "0.10"
        assert residual.second_filled_quantity == "0.04"
        assert residual.residual_base_units == "0.06"
        assert residual.state == "RECOVERY_REQUIRED"
        assert residual.reason == "hedge_residual_unresolved"
        assert group_strategy.first_page.cursor.sequence == 1
        assert group_strategy.first_page.cursor.event_id == "p5a-residual-event-a-001"
        assert group_strategy.first_page.cursor.journal_generation == _JOURNAL_GENERATION
        assert len(group_strategy.replay_page.events) == 1
        assert group_strategy.replay_page.events[0].event_id == residual.event_id
        assert group_strategy.recovery.snapshot.request.group_id == _GROUP_ID
        assert group_strategy.recovery.snapshot.request.strategy_id == _STRATEGY_A
        assert group_strategy.recovery.snapshot.state is GroupOrderState.RECOVERY_REQUIRED
        assert group_strategy.recovery.residual_page.events == ()
        assert group_strategy.recovery.residual_page.cursor == group_strategy.first_page.cursor

        assert observer.group_route_error == "GROUP_ROUTE_UNAVAILABLE"
        assert group_strategy.before_group == group_strategy.after_group
        assert observer.before_group == observer.after_group
        assert group_strategy.before_group == observer.before_group
        assert provider.calls == [(_GROUP_ID, ("entry-leg", "hedge-leg"))]
        assert coordinator.submit_calls == 1
        assert len(coordinator.received_submit_bodies) == 1
        assert set(coordinator.received_submit_bodies[0]) == {
            "group_id",
            "deadline_ns",
            "first_leg_id",
            "legs",
        }
        assert coordinator.query_calls == 1
        assert ordinary_write_calls == []
    finally:
        # ServiceExecutionSession owns Store shutdown once run begins; do not
        # retry an uncertain shutdown from this test teardown.
        for runtime in (group_runtime, primary_runtime):
            if runtime.state not in {"closed", "failed", "close_failed"}:
                runtime.close()
        registry.close()


class _GroupRouteRuntime(ServiceClientRuntime):
    """Small same-thread runtime double for route-coercion boundaries."""

    def __init__(self, strategy_ref, *, state="registered"):
        self.identity = WireIdentity(
            WireRole.STRATEGY_CLIENT,
            f"principal-{strategy_ref}",
            strategy_ref,
        )
        self._test_state = state
        self.maintenance_checks = 0

    @property
    def state(self):
        return self._test_state

    def next_maintenance_delay(self):
        self.maintenance_checks += 1
        return 1.0


def _group_route(runtime, *, strategy_ref="borrowed-strategy", owned=False):
    return ServiceStrategyGroupRoute(
        strategy_ref=strategy_ref,
        portfolio_ref="borrowed-portfolio",
        account_refs=("borrowed-account",),
        runtime=runtime,
        group_scope_ref="borrowed-group-scope",
        monitor_scope_ref="borrowed-monitor-scope",
        owned=owned,
    )


def test_strategy_group_route_rejects_runtime_owned_by_another_session():
    owner_session = object.__new__(ServiceExecutionSession)
    owner_session._state = "running"
    runtime = _GroupRouteRuntime("borrowed-strategy")
    runtime._backtrader_service_execution_session_owner = owner_session
    route = _group_route(runtime)

    try:
        _coerce_strategy_group_routes(object(), (route,), ServiceClientRuntime)
    except ServiceExecutionSessionConfigError as error:
        assert error.code == "GROUP_RUNTIME_ALREADY_OWNED"
    else:  # pragma: no cover - the ownership marker must fail closed
        raise AssertionError("a borrowed route reused another session's runtime")

    assert runtime.state == "registered"
    assert runtime._backtrader_service_execution_session_owner is owner_session
    assert owner_session.state == "running"
    assert runtime.maintenance_checks == 0


def test_strategy_group_route_allows_unowned_registered_runtime_borrow():
    runtime = _GroupRouteRuntime("borrowed-strategy")
    route = _group_route(runtime)

    routes = _coerce_strategy_group_routes(object(), (route,), ServiceClientRuntime)

    assert routes == (route,)
    assert runtime.state == "registered"
    assert not hasattr(runtime, "_backtrader_service_execution_session_owner")
    assert runtime.maintenance_checks == 1


class _BooleanRequestedCursorRuntime:
    def __init__(self):
        self.calls = []

    def call(self, mount, operation, arguments, **kwargs):
        self.calls.append((mount, operation, dict(arguments), dict(kwargs)))
        return {
            "requested_cursor": True,
            "next_cursor": 1,
            "has_more": False,
            "events": (),
        }


def test_group_monitor_page_rejects_boolean_requested_cursor():
    runtime = _BooleanRequestedCursorRuntime()
    route = ServiceStrategyGroupRoute(
        strategy_ref=_STRATEGY_A,
        portfolio_ref=_PORTFOLIO,
        account_refs=(_ACCOUNT,),
        runtime=runtime,
        group_scope_ref=_GROUP_SCOPE_REF,
        monitor_scope_ref=_MONITOR_SCOPE_REF,
        owned=False,
    )
    adapter = object.__new__(ServiceExecutionGroupAdapter)

    try:
        adapter._read_monitor_page(route, 1, 32, include_page=True)
    except ServiceExecutionGroupError as error:
        assert error.code == "RESIDUAL_MONITOR_PAGE_INVALID"
    else:  # pragma: no cover - bool must not satisfy the exact-int cursor schema
        raise AssertionError("boolean requested_cursor was accepted as integer 1")

    assert runtime.calls == [
        (
            "broker.group_monitor",
            "monitor.read_after",
            {"after_sequence": 1, "limit": 32},
            {"portfolio_ref": _PORTFOLIO, "scope_ref": _MONITOR_SCOPE_REF},
        )
    ]
