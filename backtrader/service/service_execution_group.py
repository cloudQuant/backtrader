"""Backtrader identity and lifecycle bridge for the SDK service-group RPC client.

The SDK owns service-group routes, wire contracts, response validation, RPC
outcome classification, and residual pagination. This module keeps only the
Backtrader Strategy/Broker bindings and session/thread lifecycle checks.
SDK imports stay lazy so ordinary Backtrader imports do not require bt_api_py.
Group routes, results and errors are imported from
``bt_api_py.service_group_rpc_client`` by their consumers.
"""

from __future__ import annotations

import threading
from typing import Any, Optional


__all__ = [
    "ServiceExecutionGroupAdapter",
    "require_service_execution_group_adapter",
]


def _group_error(code: str, *, group_id: Optional[str] = None) -> Exception:
    from bt_api_py.service_group_rpc_client import ServiceGroupError

    return ServiceGroupError(code, group_id=group_id)


class ServiceExecutionGroupAdapter:
    """Bind Backtrader Strategies to one SDK-owned group RPC client."""

    def __init__(self, session: Any, rpc_client: Any) -> None:
        from bt_api_py.service_group_rpc_client import ServiceGroupRpcClient

        if type(rpc_client) is not ServiceGroupRpcClient:
            raise _group_error("INVALID_GROUP_CLIENT")
        self._session = session
        self._rpc_client = rpc_client
        self._owners: dict[tuple[str, str], Any] = {}
        self._bound_by_object: dict[int, tuple[Any, tuple[str, str]]] = {}
        self._registered = False
        self._owner_thread_id = threading.get_ident()

    def validate_registered_routes(self) -> None:
        """Validate SDK route registrations on the Backtrader owner thread."""

        self._assert_owner_thread()
        self._rpc_client.validate_registered_routes()
        self._registered = True

    def deactivate(self) -> None:
        """Fence both the framework bridge and SDK client before cleanup."""

        self._registered = False
        self._rpc_client.deactivate()

    def bind_strategy(self, strategy: Any, broker: Any) -> None:
        self._assert_active()
        try:
            from backtrader.strategy import Strategy
        except Exception:
            raise _group_error("STRATEGY_TYPE_UNAVAILABLE") from None
        if not isinstance(strategy, Strategy):
            raise _group_error("INVALID_STRATEGY_INSTANCE")
        if (
            getattr(strategy, "broker", None) is not broker
            or broker is not self._session._broker
        ):
            raise _group_error("STRATEGY_BROKER_MISMATCH")
        params = getattr(strategy, "p", None)
        strategy_ref = getattr(params, "strategy_ref", None)
        portfolio_ref = getattr(params, "portfolio_ref", None)
        key = (strategy_ref, portfolio_ref)

        # The SDK client owns exact route validation and lookup.
        self._rpc_client.route_for(strategy_ref, portfolio_ref)

        object_key = id(strategy)
        previous = self._bound_by_object.get(object_key)
        if previous is not None:
            previous_strategy, previous_key = previous
            if previous_strategy is strategy and previous_key == key:
                return
            raise _group_error("STRATEGY_GROUP_ALREADY_BOUND")
        route_owner = self._owners.get(key)
        if route_owner is not None and route_owner is not strategy:
            raise _group_error("STRATEGY_GROUP_ROUTE_ALREADY_BOUND")
        self._owners[key] = strategy
        self._bound_by_object[object_key] = (strategy, key)

    def submit(self, strategy: Any, broker: Any, intent: Any) -> Any:
        route = self._route_for(strategy, broker)
        return self._rpc_client.submit(route, intent)

    def query(self, strategy: Any, broker: Any, group_id: str) -> Any:
        route = self._route_for(strategy, broker)
        return self._rpc_client.query(route, group_id)

    def roll_exit(
        self,
        strategy: Any,
        broker: Any,
        group_id: str,
        source_leg_id: str,
        limit_price: Any,
    ) -> Any:
        route = self._route_for(strategy, broker)
        return self._rpc_client.roll_exit(
            route, group_id, source_leg_id, limit_price
        )

    def query_roll_exit(
        self, strategy: Any, broker: Any, action_id: str
    ) -> Any:
        route = self._route_for(strategy, broker)
        return self._rpc_client.query_roll_exit(route, action_id)

    def read_residuals(
        self,
        strategy: Any,
        broker: Any,
        cursor: Any = None,
        *,
        limit: int = 32,
    ) -> Any:
        route = self._route_for(strategy, broker)
        return self._rpc_client.read_residuals(route, cursor, limit=limit)

    def recover(
        self,
        strategy: Any,
        broker: Any,
        group_id: str,
        cursor: Any = None,
        *,
        limit: int = 32,
    ) -> Any:
        route = self._route_for(strategy, broker)
        return self._rpc_client.recover(
            route, group_id, cursor, limit=limit
        )

    def _route_for(self, strategy: Any, broker: Any) -> Any:
        self._assert_active()
        object_key = id(strategy)
        bound = self._bound_by_object.get(object_key)
        if bound is None or bound[0] is not strategy:
            raise _group_error("STRATEGY_GROUP_NOT_BOUND")
        _, key = bound
        if self._owners.get(key) is not strategy:
            raise _group_error("STRATEGY_GROUP_ROUTE_MISMATCH")
        if (
            getattr(strategy, "broker", None) is not broker
            or broker is not self._session._broker
        ):
            raise _group_error("STRATEGY_BROKER_MISMATCH")
        params = getattr(strategy, "p", None)
        if (
            getattr(params, "strategy_ref", None) != key[0]
            or getattr(params, "portfolio_ref", None) != key[1]
        ):
            raise _group_error("STRATEGY_GROUP_IDENTITY_CHANGED")
        return self._rpc_client.route_for(*key)

    def _assert_owner_thread(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise _group_error("WRONG_RUNTIME_THREAD")

    def _assert_active(self) -> None:
        self._assert_owner_thread()
        if (
            not self._registered
            or getattr(self._session, "_state", None) != "running"
            or getattr(self._session, "_broker", None) is None
        ):
            raise _group_error("GROUP_SESSION_NOT_ACTIVE")


def require_service_execution_group_adapter(adapter: Any) -> ServiceExecutionGroupAdapter:
    if type(adapter) is not ServiceExecutionGroupAdapter:
        raise _group_error("INVALID_GROUP_ADAPTER")
    return adapter
