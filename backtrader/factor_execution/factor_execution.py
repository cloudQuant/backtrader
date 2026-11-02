"""Backtrader consumer boundary for neutral provider execution and queries.

The Strategy and Broker own local order/position lifecycle. Provider requests,
authorization, queries, and outcome classification belong to bt_api_py and its
injected provider authority. This module delegates neutral operations to the SDK; it never discovers a venue, reads a Store API/cache, or
translates provider outcomes into Backtrader terminal states.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator, Optional, Tuple


class FactorExecutionError(RuntimeError):
    """Finite failure at the Backtrader execution boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionPositionSnapshot:
    """No-I/O copy of one public Backtrader Broker position."""

    quantity: Decimal
    average_price: Optional[Decimal]


@dataclass(frozen=True)
class ExecutionOrderSnapshot:
    """No-I/O copy of one local Broker order without provider identity guesses."""

    order_ref: int
    client_order_id: Optional[str]
    side: str
    status: str
    quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    execution_unknown: bool


def execution_position_snapshot(broker: Any, data: Any) -> ExecutionPositionSnapshot:
    """Read the Broker's cached public position API without Store calls."""

    if broker is None or data is None:
        raise FactorExecutionError("POSITION_DATA_REQUIRED")
    getposition = getattr(broker, "getposition", None)
    if not callable(getposition):
        raise FactorExecutionError("BROKER_POSITION_SNAPSHOT_UNAVAILABLE")
    try:
        position = getposition(data)
        quantity = _finite_decimal(getattr(position, "size", None))
        average = _optional_decimal(getattr(position, "price", None))
    except Exception as error:
        raise FactorExecutionError("BROKER_POSITION_SNAPSHOT_UNAVAILABLE") from error
    if quantity is None:
        raise FactorExecutionError("BROKER_POSITION_VALUE_INVALID")
    return ExecutionPositionSnapshot(quantity=quantity, average_price=average)


def execution_order_snapshot(
    broker: Any, *, owner: Any = None
) -> Tuple[ExecutionOrderSnapshot, ...]:
    """Copy alive orders through the Broker's public safe snapshot method."""

    if broker is None:
        raise FactorExecutionError("BROKER_REQUIRED")
    get_orders_open = getattr(broker, "get_orders_open", None)
    if not callable(get_orders_open):
        raise FactorExecutionError("BROKER_ORDER_SNAPSHOT_UNAVAILABLE")
    try:
        orders = get_orders_open(safe=True)
    except Exception as error:
        raise FactorExecutionError("BROKER_ORDER_SNAPSHOT_UNAVAILABLE") from error
    if type(orders) not in (tuple, list):
        raise FactorExecutionError("BROKER_ORDER_SNAPSHOT_INVALID")
    result = []
    seen_refs = set()
    for order in tuple(orders):
        if owner is not None and getattr(order, "owner", None) is not owner:
            continue
        alive = getattr(order, "alive", None)
        if not callable(alive) or alive() is not True:
            continue
        order_ref = getattr(order, "ref", None)
        if type(order_ref) is not int or order_ref <= 0 or order_ref in seen_refs:
            raise FactorExecutionError("BROKER_ORDER_IDENTITY_INVALID")
        seen_refs.add(order_ref)
        info = getattr(order, "info", None)
        getter = getattr(info, "get", None)
        if not callable(getter):
            raise FactorExecutionError("BROKER_ORDER_INFO_UNAVAILABLE")
        client_order_id = getter("client_order_id")
        if client_order_id is not None and (
            type(client_order_id) is not str
            or not client_order_id
            or client_order_id != client_order_id.strip()
        ):
            raise FactorExecutionError("BROKER_CLIENT_ORDER_ID_INVALID")
        created = getattr(order, "created", None)
        executed = getattr(order, "executed", None)
        quantity = _finite_decimal(getattr(created, "size", None))
        filled = _finite_decimal(getattr(executed, "size", None))
        side_getter = getattr(order, "isbuy", None)
        status_getter = getattr(order, "getstatusname", None)
        if quantity is None or filled is None or not callable(side_getter) or not callable(status_getter):
            raise FactorExecutionError("BROKER_ORDER_STATE_UNAVAILABLE")
        quantity = abs(quantity)
        filled = abs(filled)
        side_value = side_getter()
        status = status_getter()
        if (
            quantity <= 0
            or filled < 0
            or filled > quantity
            or type(side_value) is not bool
            or type(status) is not str
            or not status
        ):
            raise FactorExecutionError("BROKER_ORDER_STATE_INVALID")
        result.append(
            ExecutionOrderSnapshot(
                order_ref=order_ref,
                client_order_id=client_order_id,
                side="buy" if side_value else "sell",
                status=status,
                quantity=quantity,
                filled_quantity=filled,
                remaining_quantity=quantity - filled,
                execution_unknown=getter("execution_unknown") is True,
            )
        )
    return tuple(result)


class FactorExecutionCoordinator:
    """Bind a Strategy's local Broker lifecycle to the SDK facades.

    The SDK facade owns claims, provider calls, and outcome classification.
    This coordinator does not treat a mode name, Broker callback, provider
    order id, or local Store flag as write permission.
    """

    def __init__(
        self,
        broker: Any,
        *,
        query_facade: Any = None,
        managed_execution_facade: Any = None,
        targets: Tuple[Any, ...] = (),
    ) -> None:
        if broker is None:
            raise FactorExecutionError("BROKER_REQUIRED")
        self.broker = broker
        self.query_facade = query_facade
        self.managed_execution_facade = managed_execution_facade
        self.targets = tuple(targets)
        self._active_scope: ContextVar[Optional["FactorExecutionDecisionScope"]] = ContextVar(
            "factor_execution_scope_{}".format(id(self)), default=None
        )
        current = getattr(broker, "factor_execution_coordinator", None)
        if current is not None and current is not self:
            raise FactorExecutionError("BROKER_COORDINATOR_ALREADY_BOUND")
        broker.factor_execution_coordinator = self

    def collect_facts(
        self,
        *,
        strategy: Any,
        receipt: Any,
        lease: Any,
        account_session_snapshot: Any,
        now: datetime,
    ):
        """Collect neutral provider snapshots and local BT facts."""

        try:
            from .factor_execution_facts import (
                FactorExecutionFactsError,
                collect_local_bt_facts,
            )

            return collect_local_bt_facts(
                broker=self.broker,
                strategy=strategy,
                query_facade=self._require_query_facade(),
                receipt=receipt,
                lease=lease,
                account_session_snapshot=account_session_snapshot,
                now=now,
                targets=self.targets,
            )
        except FactorExecutionFactsError as error:
            raise FactorExecutionError(error.code) from error

    def _sdk_client(self):
        from bt_api_py.managed_execution_client import ManagedExecutionClient

        return ManagedExecutionClient(
            query_facade=self.query_facade,
            managed_execution_facade=self.managed_execution_facade,
            error_type=FactorExecutionError,
        )

    def query(self, requests, *, deadline: datetime):
        return self._sdk_client().query(requests, deadline=deadline)

    def snapshot(self, receipt: Any, request_ref: str):
        return self._sdk_client().snapshot(receipt, request_ref)

    def acquire_snapshot_lease(self, receipt: Any, *, purpose: str, expires_at: datetime):
        return self._sdk_client().acquire_snapshot_lease(
            receipt, purpose=purpose, expires_at=expires_at
        )

    def validate_snapshot_lease(self, lease: Any, receipt: Any, *, now: datetime) -> bool:
        return self._sdk_client().validate_snapshot_lease(lease, receipt, now=now)

    def claim(self, operation: str, request: Any, *, authorization: Any):
        return self._sdk_client().claim(operation, request, authorization=authorization)

    def submit(self, request: Any, *, claim: Any, authorization: Any):
        return self._sdk_client().submit(request, claim=claim, authorization=authorization)

    def cancel(self, request: Any, *, claim: Any, authorization: Any):
        return self._sdk_client().cancel(request, claim=claim, authorization=authorization)

    def resolve_unknown(
        self, request: Any, *, receipt: Any, lease: Any, now: datetime, authorization: Any
    ):
        return self._sdk_client().resolve_unknown(
            request, receipt=receipt, lease=lease, now=now, authorization=authorization
        )

    @contextmanager
    def decision_scope(
        self,
        *,
        owner: Any,
        execution_facts: Any,
        now: datetime,
    ) -> Iterator["FactorExecutionDecisionScope"]:
        """Bind one Strategy and freshly revalidated facts for local dispatch."""

        scope = FactorExecutionDecisionScope(self, owner, execution_facts, now=now)
        with scope:
            yield scope

    def active_scope(self, owner: Any) -> "FactorExecutionDecisionScope":
        scope = self._active_scope.get()
        if scope is None or scope.owner is not owner or not scope.active:
            raise FactorExecutionError("ACTIVE_DECISION_SCOPE_REQUIRED")
        return scope

    def active_scope_for_order(self, order: Any) -> "FactorExecutionDecisionScope":
        owner = getattr(order, "owner", None)
        if owner is None:
            raise FactorExecutionError("ORDER_OWNER_UNAVAILABLE")
        return self.active_scope(owner)

    def _require_query_facade(self):
        return self._sdk_client().require_query_facade()


class FactorExecutionDecisionScope:
    """Temporary Strategy binding for current query evidence.

    The scope only proves that the exact neutral receipt lease is current. It
    does not evaluate trading policy or grant dispatch authority; each SDK
    operation still requires its own opaque authorization.
    """

    def __init__(
        self,
        coordinator: FactorExecutionCoordinator,
        owner: Any,
        execution_facts: Any,
        *,
        now: datetime,
    ) -> None:
        self.coordinator = coordinator
        self.owner = owner
        self.execution_facts = execution_facts
        self.now = now
        self.active = False
        self._token = None

    def __enter__(self) -> "FactorExecutionDecisionScope":
        if self.owner is None or getattr(self.owner, "broker", None) is not self.coordinator.broker:
            raise FactorExecutionError("STRATEGY_BROKER_MISMATCH")
        if self.coordinator._active_scope.get() is not None:
            raise FactorExecutionError("NESTED_DECISION_SCOPE")
        from .factor_execution_facts import FactorExecutionFacts

        if type(self.execution_facts) is not FactorExecutionFacts:
            raise FactorExecutionError("EXECUTION_FACTS_REQUIRED")
        validate = getattr(self.execution_facts, "validate_current", None)
        if not callable(validate) or validate(
            query_facade=self.coordinator._require_query_facade(),
            now=self.now,
        ) is not True:
            raise FactorExecutionError("QUERY_SNAPSHOT_LEASE_STALE")
        self._token = self.coordinator._active_scope.set(self)
        self.active = True
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if self._token is not None:
            self.coordinator._active_scope.reset(self._token)
            self._token = None
        self.active = False
        return False






def _finite_decimal(value: Any) -> Optional[Decimal]:
    if type(value) is bool or value is None:
        return None
    try:
        result = value if type(value) is Decimal else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _optional_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    return _finite_decimal(value)




__all__ = [
    "ExecutionOrderSnapshot",
    "ExecutionPositionSnapshot",
    "FactorExecutionCoordinator",
    "FactorExecutionDecisionScope",
    "FactorExecutionError",
    "execution_order_snapshot",
    "execution_position_snapshot",
]
