"""Explicit Backtrader bridge for registered SDK group-order routes.

The bridge stays optional: importing it does not import an SDK package or
construct a runtime. A :class:`ServiceExecutionSession` validates and owns the
registered routes; this adapter only makes bounded calls through the public
``ServiceClientRuntime.call`` API.
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

__all__ = [
    "ServiceExecutionGroupAdapter",
    "ServiceExecutionGroupError",
    "ServiceExecutionGroupNotSentError",
    "ServiceExecutionGroupRecovery",
    "ServiceExecutionGroupUnknownOutcomeError",
    "ServiceGroupResidual",
    "ServiceGroupResidualCursor",
    "ServiceGroupResidualPage",
    "ServiceStrategyGroupRoute",
    "require_service_execution_group_adapter",
]

_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_TEXT = re.compile(r"^[-+]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_GROUP_MOUNT = "broker.order_groups"
_GROUP_OPERATIONS = frozenset({"groups.submit", "groups.query"})
_MONITOR_MOUNT = "broker.group_monitor"
_MONITOR_OPERATIONS = frozenset({"monitor.read_after"})
_RESIDUAL_EVENT_TYPE = "group.residual"
_RESIDUAL_SCHEMA = "sdk.group_monitor_projection.v1"
_RESIDUAL_STATE = "RECOVERY_REQUIRED"
_PAIR_RESIDUAL_REASON = "hedge_residual_unresolved"
_CURSOR_SCHEMA = "backtrader.service_group_residual_cursor.v1"
_MAX_RESIDUAL_PAGE_SIZE = 100
_RESIDUAL_DATA_FIELDS = frozenset(
    {
        "schema",
        "journal_generation",
        "source_sequence",
        "source_event_sha256",
        "source_revision",
        "source_created_at_ns",
        "portfolio_ref",
        "group_id",
        "strategy_id",
        "account_refs",
        "state",
        "reason",
        "residual_base_units",
        "first_leg_id",
        "second_leg_id",
        "first_filled_quantity",
        "second_filled_quantity",
    }
)


@dataclass(frozen=True)
class ServiceStrategyGroupRoute:
    """One strategy's exact P5A coordinator and read-only Monitor scopes.

    The group scope carries the ordered account set required by the
    coordinator. Monitor has its own strategy/portfolio scope because its
    public read contract does not accept ``account_refs``. Both bindings may
    live on one registered runtime.
    """

    strategy_ref: str
    portfolio_ref: str
    account_refs: tuple[str, ...]
    runtime: Any
    group_scope_ref: str
    monitor_scope_ref: str
    owned: bool = True


class ServiceExecutionGroupError(RuntimeError):
    """Finite diagnostics for a rejected group call or residual page."""

    def __init__(self, code: str, *, group_id: Optional[str] = None) -> None:
        self.code = code
        self.group_id = group_id
        super().__init__(code)


class ServiceExecutionGroupNotSentError(ServiceExecutionGroupError):
    """The runtime proved that a group submit was not sent."""

    def __init__(self, *, group_id: str) -> None:
        super().__init__("REQUEST_NOT_SENT", group_id=group_id)


class ServiceExecutionGroupUnknownOutcomeError(ServiceExecutionGroupError):
    """The submit may have reached the coordinator and must be queried by ID."""

    def __init__(self, *, group_id: str) -> None:
        super().__init__("REQUEST_OUTCOME_UNKNOWN", group_id=group_id)


@dataclass(frozen=True)
class ServiceGroupResidualCursor:
    """Caller-persistable Monitor cursor bound to one Strategy and portfolio."""

    strategy_ref: str
    portfolio_ref: str
    sequence: int = 0
    event_id: Optional[str] = None
    journal_generation: Optional[str] = None

    def __post_init__(self) -> None:
        _require_reference(self.strategy_ref, "INVALID_RESIDUAL_CURSOR")
        _require_reference(self.portfolio_ref, "INVALID_RESIDUAL_CURSOR")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ServiceExecutionGroupError("INVALID_RESIDUAL_CURSOR")
        if self.sequence == 0:
            if self.event_id is not None or self.journal_generation is not None:
                raise ServiceExecutionGroupError("INVALID_RESIDUAL_CURSOR")
        elif (
            not _valid_text(self.event_id)
            or type(self.journal_generation) is not str
            or _SHA256.fullmatch(self.journal_generation) is None
        ):
            raise ServiceExecutionGroupError("INVALID_RESIDUAL_CURSOR")

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema": _CURSOR_SCHEMA,
            "strategy_ref": self.strategy_ref,
            "portfolio_ref": self.portfolio_ref,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "journal_generation": self.journal_generation,
        }

    @classmethod
    def from_payload(cls, value: object) -> "ServiceGroupResidualCursor":
        if not isinstance(value, Mapping) or frozenset(value) != frozenset(
            {
                "schema",
                "strategy_ref",
                "portfolio_ref",
                "sequence",
                "event_id",
                "journal_generation",
            }
        ) or value.get("schema") != _CURSOR_SCHEMA:
            raise ServiceExecutionGroupError("INVALID_RESIDUAL_CURSOR")
        return cls(
            strategy_ref=value["strategy_ref"],
            portfolio_ref=value["portfolio_ref"],
            sequence=value["sequence"],
            event_id=value["event_id"],
            journal_generation=value["journal_generation"],
        )


@dataclass(frozen=True)
class ServiceGroupResidual:
    """One validated, immutable durable group residual fact."""

    sequence: int
    event_id: str
    journal_generation: str
    portfolio_ref: str
    group_id: str
    strategy_ref: str
    account_refs: tuple[str, ...]
    state: str
    reason: str
    residual_base_units: Optional[str]
    first_leg_id: Optional[str]
    second_leg_id: Optional[str]
    first_filled_quantity: Optional[str]
    second_filled_quantity: Optional[str]
    source_event_sha256: str
    source_revision: int
    source_created_at_ns: int


@dataclass(frozen=True)
class ServiceGroupResidualPage:
    """One repeatable Monitor page and the cursor the caller may persist."""

    events: tuple[ServiceGroupResidual, ...]
    cursor: ServiceGroupResidualCursor
    has_more: bool


@dataclass(frozen=True)
class ServiceExecutionGroupRecovery:
    """Read-only recovery projection for one original group ID."""

    snapshot: Any
    residual_page: ServiceGroupResidualPage


class ServiceExecutionGroupAdapter:
    """Bind real Strategies to exact registered group and Monitor operations."""

    def __init__(self, session: Any, routes: tuple[ServiceStrategyGroupRoute, ...]) -> None:
        if type(routes) is not tuple or any(
            type(route) is not ServiceStrategyGroupRoute for route in routes
        ):
            raise ServiceExecutionGroupError("INVALID_GROUP_ROUTES")
        self._session = session
        self._routes = routes
        self._route_by_key = {
            (route.strategy_ref, route.portfolio_ref): route for route in routes
        }
        self._owners: dict[tuple[str, str], Any] = {}
        self._bound_by_object: dict[int, tuple[Any, tuple[str, str]]] = {}
        self._registered = False
        self._owner_thread_id = threading.get_ident()

    def validate_registered_routes(self) -> None:
        """Fail closed unless each configured runtime has exact read/write grants."""

        from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
        from bt_api_py.service_runtime import RegisteredBinding

        resolved = set()
        runtime_owner: dict[int, str] = {}
        for route in self._routes:
            runtime = route.runtime
            if getattr(runtime, "state", None) != "registered":
                raise ServiceExecutionGroupError("GROUP_RUNTIME_NOT_REGISTERED")
            identity = getattr(runtime, "identity", None)
            if (
                type(identity) is not WireIdentity
                or identity.role is not WireRole.STRATEGY_CLIENT
                or identity.actor_ref != route.strategy_ref
                or not _valid_text(identity.principal_ref)
            ):
                raise ServiceExecutionGroupError("GROUP_STRATEGY_IDENTITY_MISMATCH")
            prior_strategy = runtime_owner.get(id(runtime))
            if prior_strategy is not None and prior_strategy != route.strategy_ref:
                raise ServiceExecutionGroupError("GROUP_RUNTIME_STRATEGY_AMBIGUOUS")
            runtime_owner[id(runtime)] = route.strategy_ref
            try:
                bindings = runtime.bindings
            except Exception:
                raise ServiceExecutionGroupError("GROUP_RUNTIME_BINDINGS_UNAVAILABLE") from None
            if type(bindings) is not tuple or any(
                type(binding) is not RegisteredBinding for binding in bindings
            ):
                raise ServiceExecutionGroupError("GROUP_RUNTIME_BINDINGS_INVALID")
            group_binding = _unique_binding(
                bindings, _GROUP_MOUNT, route.group_scope_ref, _GROUP_OPERATIONS
            )
            monitor_binding = _unique_binding(
                bindings, _MONITOR_MOUNT, route.monitor_scope_ref, _MONITOR_OPERATIONS
            )
            group_scope = getattr(group_binding, "scope", None)
            monitor_scope = getattr(monitor_binding, "scope", None)
            if type(group_scope) is not WireScope or type(monitor_scope) is not WireScope:
                raise ServiceExecutionGroupError("GROUP_RUNTIME_SCOPE_INVALID")
            if not _valid_group_scope(route, runtime, group_scope):
                raise ServiceExecutionGroupError("GROUP_SCOPE_MISMATCH")
            if not _valid_monitor_scope(route, runtime, group_scope, monitor_scope):
                raise ServiceExecutionGroupError("GROUP_MONITOR_SCOPE_MISMATCH")
            key = (route.strategy_ref, route.portfolio_ref)
            if key in resolved:
                raise ServiceExecutionGroupError("GROUP_ROUTE_AMBIGUOUS")
            resolved.add(key)
        self._registered = True

    def deactivate(self) -> None:
        """Fence new calls before the session begins Broker/runtime cleanup."""

        self._registered = False

    def bind_strategy(self, strategy: Any, broker: Any) -> None:
        self._assert_active()
        try:
            from backtrader.strategy import Strategy
        except Exception:
            raise ServiceExecutionGroupError("STRATEGY_TYPE_UNAVAILABLE") from None
        if not isinstance(strategy, Strategy):
            raise ServiceExecutionGroupError("INVALID_STRATEGY_INSTANCE")
        if getattr(strategy, "broker", None) is not broker or broker is not self._session._broker:
            raise ServiceExecutionGroupError("STRATEGY_BROKER_MISMATCH")
        params = getattr(strategy, "p", None)
        strategy_ref = getattr(params, "strategy_ref", None)
        portfolio_ref = getattr(params, "portfolio_ref", None)
        if not _valid_reference(strategy_ref) or not _valid_reference(portfolio_ref):
            raise ServiceExecutionGroupError("STRATEGY_GROUP_IDENTITY_INCOMPLETE")
        key = (strategy_ref, portfolio_ref)
        if key not in self._route_by_key:
            raise ServiceExecutionGroupError("GROUP_ROUTE_UNAVAILABLE")
        object_key = id(strategy)
        previous = self._bound_by_object.get(object_key)
        if previous is not None:
            previous_strategy, previous_key = previous
            if previous_strategy is strategy and previous_key == key:
                return
            raise ServiceExecutionGroupError("STRATEGY_GROUP_ALREADY_BOUND")
        route_owner = self._owners.get(key)
        if route_owner is not None and route_owner is not strategy:
            raise ServiceExecutionGroupError("STRATEGY_GROUP_ROUTE_ALREADY_BOUND")
        self._owners[key] = strategy
        self._bound_by_object[object_key] = (strategy, key)

    def submit(self, strategy: Any, broker: Any, intent: Any) -> Any:
        route = self._route_for(strategy, broker)
        from bt_api_execution.group_order_contracts import GroupOrderIntent

        if type(intent) is not GroupOrderIntent:
            raise ServiceExecutionGroupError("GROUP_INTENT_TYPE_INVALID")
        if (
            intent.version != 1
            or intent.budget_quote is not None
            or intent.strategy_id != route.strategy_ref
            or intent.portfolio_ref != route.portfolio_ref
            or intent.account_refs != route.account_refs
        ):
            raise ServiceExecutionGroupError("P5A_GROUP_SCOPE_MISMATCH", group_id=intent.group_id)
        arguments = {
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
        runtime = route.runtime
        try:
            result = runtime.call(
                _GROUP_MOUNT,
                "groups.submit",
                arguments,
                portfolio_ref=route.portfolio_ref,
                scope_ref=route.group_scope_ref,
            )
        except Exception as error:
            _raise_submit_error(error, intent.group_id)
        try:
            snapshot = _snapshot_from_reply(result, expected_intent=intent)
        except Exception:
            raise ServiceExecutionGroupUnknownOutcomeError(group_id=intent.group_id) from None
        return snapshot

    def query(self, strategy: Any, broker: Any, group_id: str) -> Any:
        route = self._route_for(strategy, broker)
        _require_reference(group_id, "INVALID_GROUP_ID")
        try:
            result = route.runtime.call(
                _GROUP_MOUNT,
                "groups.query",
                {"group_id": group_id},
                portfolio_ref=route.portfolio_ref,
                scope_ref=route.group_scope_ref,
            )
        except Exception:
            raise ServiceExecutionGroupError("GROUP_QUERY_FAILED", group_id=group_id) from None
        try:
            if not isinstance(result, Mapping) or frozenset(result) != frozenset(
                {"found", "snapshot"}
            ) or type(result["found"]) is not bool:
                raise ValueError
            if result["found"] is False:
                if result["snapshot"] is not None:
                    raise ValueError
                return None
            return _snapshot_from_reply(result, expected_identity=route, group_id=group_id)
        except Exception:
            raise ServiceExecutionGroupError("GROUP_QUERY_RESPONSE_INVALID", group_id=group_id) from None

    def read_residuals(
        self,
        strategy: Any,
        broker: Any,
        cursor: Optional[ServiceGroupResidualCursor] = None,
        *,
        limit: int = 32,
    ) -> ServiceGroupResidualPage:
        route = self._route_for(strategy, broker)
        if type(limit) is not int or not 1 <= limit <= _MAX_RESIDUAL_PAGE_SIZE:
            raise ServiceExecutionGroupError("INVALID_RESIDUAL_LIMIT")
        if cursor is not None and type(cursor) is not ServiceGroupResidualCursor:
            raise ServiceExecutionGroupError("INVALID_RESIDUAL_CURSOR")
        if cursor is not None and (
            cursor.strategy_ref != route.strategy_ref
            or cursor.portfolio_ref != route.portfolio_ref
        ):
            raise ServiceExecutionGroupError("RESIDUAL_CURSOR_SCOPE_MISMATCH")
        after_sequence = 0 if cursor is None else cursor.sequence
        if cursor is not None and cursor.sequence:
            anchor = self._read_monitor_page(route, cursor.sequence - 1, 1)
            if (
                len(anchor) != 1
                or anchor[0].sequence != cursor.sequence
                or anchor[0].event_id != cursor.event_id
                or anchor[0].journal_generation != cursor.journal_generation
            ):
                raise ServiceExecutionGroupError("RESIDUAL_CURSOR_ANCHOR_MISMATCH")
        events, has_more, returned_cursor = self._read_monitor_page(
            route, after_sequence, limit, include_page=True
        )
        if cursor is not None and cursor.journal_generation is not None and any(
            item.journal_generation != cursor.journal_generation for item in events
        ):
            raise ServiceExecutionGroupError("RESIDUAL_JOURNAL_GENERATION_CHANGED")
        if events:
            last = events[-1]
            next_cursor = ServiceGroupResidualCursor(
                strategy_ref=route.strategy_ref,
                portfolio_ref=route.portfolio_ref,
                sequence=last.sequence,
                event_id=last.event_id,
                journal_generation=last.journal_generation,
            )
        elif cursor is not None:
            next_cursor = cursor
        else:
            next_cursor = ServiceGroupResidualCursor(route.strategy_ref, route.portfolio_ref)
        if returned_cursor != (events[-1].sequence if events else after_sequence):
            raise ServiceExecutionGroupError("RESIDUAL_MONITOR_CURSOR_INVALID")
        return ServiceGroupResidualPage(tuple(events), next_cursor, has_more)

    def recover(
        self,
        strategy: Any,
        broker: Any,
        group_id: str,
        cursor: Optional[ServiceGroupResidualCursor] = None,
        *,
        limit: int = 32,
    ) -> ServiceExecutionGroupRecovery:
        """Recover by querying the original ID, then resuming the durable cursor."""

        snapshot = self.query(strategy, broker, group_id)
        residual_page = self.read_residuals(strategy, broker, cursor, limit=limit)
        return ServiceExecutionGroupRecovery(snapshot, residual_page)

    def _read_monitor_page(
        self,
        route: ServiceStrategyGroupRoute,
        after_sequence: int,
        limit: int,
        *,
        include_page: bool = False,
    ) -> Any:
        try:
            result = route.runtime.call(
                _MONITOR_MOUNT,
                "monitor.read_after",
                {"after_sequence": after_sequence, "limit": limit},
                portfolio_ref=route.portfolio_ref,
                scope_ref=route.monitor_scope_ref,
            )
        except Exception:
            raise ServiceExecutionGroupError("RESIDUAL_MONITOR_READ_FAILED") from None
        try:
            if not isinstance(result, Mapping) or frozenset(result) != frozenset(
                {"requested_cursor", "next_cursor", "has_more", "events"}
            ):
                raise ValueError
            if (
                type(result["requested_cursor"]) is not int
                or result["requested_cursor"] != after_sequence
                or type(result["next_cursor"]) is not int
                or type(result["has_more"]) is not bool
                or not isinstance(result["events"], (list, tuple))
                or (result["has_more"] and len(result["events"]) != limit)
            ):
                raise ValueError
            events = tuple(
                _parse_residual_event(event, route) for event in result["events"]
            )
            sequences = tuple(item.sequence for item in events)
            if any(value <= after_sequence for value in sequences) or any(
                left >= right for left, right in zip(sequences, sequences[1:])
            ):
                raise ValueError
            if len(events) > limit:
                raise ValueError
            expected_next = events[-1].sequence if events else after_sequence
            if result["next_cursor"] != expected_next:
                raise ValueError
            if include_page:
                return events, result["has_more"], result["next_cursor"]
            return events
        except ServiceExecutionGroupError:
            raise
        except Exception:
            raise ServiceExecutionGroupError("RESIDUAL_MONITOR_PAGE_INVALID") from None

    def _route_for(self, strategy: Any, broker: Any) -> ServiceStrategyGroupRoute:
        self._assert_active()
        object_key = id(strategy)
        bound = self._bound_by_object.get(object_key)
        if bound is None or bound[0] is not strategy:
            raise ServiceExecutionGroupError("STRATEGY_GROUP_NOT_BOUND")
        _, key = bound
        if self._owners.get(key) is not strategy:
            raise ServiceExecutionGroupError("STRATEGY_GROUP_ROUTE_MISMATCH")
        if getattr(strategy, "broker", None) is not broker or broker is not self._session._broker:
            raise ServiceExecutionGroupError("STRATEGY_BROKER_MISMATCH")
        params = getattr(strategy, "p", None)
        if (
            getattr(params, "strategy_ref", None) != key[0]
            or getattr(params, "portfolio_ref", None) != key[1]
        ):
            raise ServiceExecutionGroupError("STRATEGY_GROUP_IDENTITY_CHANGED")
        return self._route_by_key[key]

    def _assert_active(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise ServiceExecutionGroupError("WRONG_RUNTIME_THREAD")
        if (
            not self._registered
            or getattr(self._session, "_state", None) != "running"
            or getattr(self._session, "_broker", None) is None
        ):
            raise ServiceExecutionGroupError("GROUP_SESSION_NOT_ACTIVE")


def require_service_execution_group_adapter(adapter: Any) -> ServiceExecutionGroupAdapter:
    if type(adapter) is not ServiceExecutionGroupAdapter:
        raise ServiceExecutionGroupError("INVALID_GROUP_ADAPTER")
    return adapter


def _unique_binding(
    bindings: tuple[Any, ...], mount: str, scope_ref: str, operations: frozenset[str]
) -> Any:
    matches = tuple(
        binding
        for binding in bindings
        if binding.active is True
        and binding.mount == mount
        and binding.scope_ref == scope_ref
        and binding.operations == operations
    )
    if len(matches) != 1:
        raise ServiceExecutionGroupError("GROUP_ROUTE_MISSING_OR_AMBIGUOUS")
    return matches[0]


def _valid_group_scope(
    route: ServiceStrategyGroupRoute, runtime: Any, scope: Any
) -> bool:
    return (
        scope.account_ref is None
        and scope.account_refs == route.account_refs
        and scope.strategy_ref == route.strategy_ref
        and scope.portfolio_ref == route.portfolio_ref
        and scope.run_id == runtime.run_id
        and _valid_reference(scope.execution_domain_ref)
        and scope.manual_book_ref is None
        and scope.group_id is None
        and scope.leg_id is None
    )


def _valid_monitor_scope(
    route: ServiceStrategyGroupRoute, runtime: Any, group_scope: Any, monitor_scope: Any
) -> bool:
    return (
        monitor_scope.account_ref is None
        and monitor_scope.account_refs == ()
        and monitor_scope.strategy_ref == route.strategy_ref
        and monitor_scope.portfolio_ref == route.portfolio_ref
        and monitor_scope.run_id == runtime.run_id
        and monitor_scope.execution_domain_ref == group_scope.execution_domain_ref
        and monitor_scope.manual_book_ref is None
        and monitor_scope.group_id is None
        and monitor_scope.leg_id is None
    )


def _snapshot_from_reply(
    value: object,
    *,
    expected_intent: Any = None,
    expected_identity: Any = None,
    group_id: Optional[str] = None,
) -> Any:
    from bt_api_execution import GroupOrderSnapshot

    if not isinstance(value, Mapping) or frozenset(value) != frozenset({"found", "snapshot"}):
        raise ValueError
    if value["found"] is not True or not isinstance(value["snapshot"], Mapping):
        raise ValueError
    snapshot_payload = _thaw_json_tree(value["snapshot"])
    snapshot = GroupOrderSnapshot.from_payload(snapshot_payload)
    request = snapshot.request
    if expected_intent is not None:
        if (
            request.group_id != expected_intent.group_id
            or request.strategy_id != expected_intent.strategy_id
            or request.portfolio_ref != expected_intent.portfolio_ref
            or request.deadline_ns != expected_intent.deadline_ns
            or request.first_leg_id != expected_intent.first_leg_id
            or request.version != 1
            or tuple(
                (
                    item.leg_id,
                    item.account_ref,
                    item.maximum_intent.to_payload(),
                )
                for item in request.legs
            )
            != tuple(
                (
                    item.leg_id,
                    item.account_ref,
                    item.maximum_intent.to_payload(),
                )
                for item in expected_intent.legs
            )
        ):
            raise ValueError
    if expected_identity is not None and (
        request.strategy_id != expected_identity.strategy_ref
        or request.portfolio_ref != expected_identity.portfolio_ref
        or request.account_refs != expected_identity.account_refs
    ):
        raise ValueError
    if group_id is not None and request.group_id != group_id:
        raise ValueError
    return snapshot


def _parse_residual_event(value: object, route: ServiceStrategyGroupRoute) -> ServiceGroupResidual:
    if not isinstance(value, Mapping) or frozenset(value) != frozenset(
        {"sequence", "event_id", "event_type", "occurred_at", "data"}
    ):
        raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID")
    data = value["data"]
    if (
        value["event_type"] != _RESIDUAL_EVENT_TYPE
        or type(value["sequence"]) is not int
        or value["sequence"] <= 0
        or not _valid_text(value["event_id"])
        or not isinstance(value["occurred_at"], (int, float))
        or isinstance(value["occurred_at"], bool)
        or not math.isfinite(float(value["occurred_at"]))
        or not isinstance(data, Mapping)
        or frozenset(data) != _RESIDUAL_DATA_FIELDS
        or data.get("schema") != _RESIDUAL_SCHEMA
        or type(data.get("source_sequence")) is not int
        or data["source_sequence"] <= 0
        or type(data.get("source_revision")) is not int
        or data["source_revision"] < 0
        or type(data.get("source_created_at_ns")) is not int
        or data["source_created_at_ns"] <= 0
        or data.get("strategy_id") != route.strategy_ref
        or data.get("portfolio_ref") != route.portfolio_ref
        or data.get("state") != _RESIDUAL_STATE
    ):
        raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID")
    generation = data.get("journal_generation")
    group_id = data.get("group_id")
    reason = data.get("reason")
    source_digest = data.get("source_event_sha256")
    account_refs = data.get("account_refs")
    if (
        not isinstance(generation, str)
        or _SHA256.fullmatch(generation) is None
        or not _valid_reference(group_id)
        or not _valid_text(reason)
        or type(source_digest) is not str
        or _SHA256.fullmatch(source_digest) is None
        or type(account_refs) not in (list, tuple)
        or not account_refs
        or any(not _valid_reference(item) for item in account_refs)
        or tuple(sorted(set(account_refs))) != tuple(account_refs)
        or not set(account_refs).issubset(route.account_refs)
    ):
        raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID")
    residual_base_units = _optional_decimal_text(data.get("residual_base_units"))
    first_leg_id = _optional_reference(data.get("first_leg_id"))
    second_leg_id = _optional_reference(data.get("second_leg_id"))
    first_filled_quantity = _optional_decimal_text(data.get("first_filled_quantity"))
    second_filled_quantity = _optional_decimal_text(data.get("second_filled_quantity"))
    pair_values = (
        first_leg_id,
        second_leg_id,
        first_filled_quantity,
        second_filled_quantity,
    )
    if residual_base_units is None:
        if any(value is not None for value in pair_values) or reason == _PAIR_RESIDUAL_REASON:
            raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID")
    elif (
        any(value is None for value in pair_values)
        or reason != _PAIR_RESIDUAL_REASON
    ):
        raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID")
    return ServiceGroupResidual(
        sequence=value["sequence"],
        event_id=value["event_id"],
        journal_generation=generation,
        portfolio_ref=route.portfolio_ref,
        group_id=group_id,
        strategy_ref=route.strategy_ref,
        account_refs=tuple(account_refs),
        state=_RESIDUAL_STATE,
        reason=reason,
        residual_base_units=residual_base_units,
        first_leg_id=first_leg_id,
        second_leg_id=second_leg_id,
        first_filled_quantity=first_filled_quantity,
        second_filled_quantity=second_filled_quantity,
        source_event_sha256=source_digest,
        source_revision=data["source_revision"],
        source_created_at_ns=data["source_created_at_ns"],
    )


def _raise_submit_error(error: BaseException, group_id: str) -> None:
    try:
        from bt_api_py.service_runtime import (
            ServiceCallOutcomeUnknownError,
            ServiceRuntimeError,
            ServiceRuntimeRequestNotSentError,
        )
    except ImportError:
        raise ServiceExecutionGroupUnknownOutcomeError(group_id=group_id) from None
    if isinstance(error, ServiceRuntimeRequestNotSentError):
        raise ServiceExecutionGroupNotSentError(group_id=group_id) from None
    if isinstance(error, ServiceCallOutcomeUnknownError):
        raise ServiceExecutionGroupUnknownOutcomeError(group_id=group_id) from None
    if isinstance(error, ServiceRuntimeError):
        raise ServiceExecutionGroupError(
            "GROUP_REQUEST_REJECTED", group_id=group_id
        ) from None
    raise ServiceExecutionGroupUnknownOutcomeError(group_id=group_id) from None


def _thaw_json_tree(value: object) -> Any:
    """Convert the SDK's immutable wire JSON tree for strict DTO parsers.

    ``ServiceClientRuntime.call`` returns the validated ``WireEnvelope`` result:
    mappings are read-only proxies and arrays are tuples. The typed execution
    DTO parsers consume ordinary JSON-shaped dictionaries and lists, so thaw
    only those wire containers and reject every non-JSON value.
    """

    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("wire object keys must be strings")
        return {key: _thaw_json_tree(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [_thaw_json_tree(item) for item in value]
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("unsupported value in wire JSON tree")


def _optional_decimal_text(value: object) -> Optional[str]:
    if value is None:
        return None
    if type(value) is not str or _DECIMAL_TEXT.fullmatch(value) is None:
        raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID") from None
    if not parsed.is_finite():
        raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID")
    return value


def _optional_reference(value: object) -> Optional[str]:
    if value is None:
        return None
    if not _valid_reference(value):
        raise ServiceExecutionGroupError("RESIDUAL_EVENT_INVALID")
    return value


def _require_reference(value: object, code: str) -> str:
    if not _valid_reference(value):
        raise ServiceExecutionGroupError(code)
    return value


def _valid_reference(value: object) -> bool:
    return type(value) is str and _REFERENCE.fullmatch(value) is not None


def _valid_text(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )
