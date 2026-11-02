"""Translate SDK reconciliation client errors at the Backtrader boundary."""

from __future__ import annotations

from typing import Any, Type


class SdkReconciliationAdapter:
    """Keep BT error types while SDK owns the neutral reconciliation workflow."""

    _MESSAGES = {
        "reconciliation_selector_unavailable": "SDK reconciliation selector is unavailable",
        "reconciliation_route_port_unavailable": "SDK route-bound reconciliation port is unavailable",
        "reconciliation_correlation_invalid": "order reconciliation requires an exact SDK correlation",
        "reconciliation_handle_async_invalid": "SDK reconciliation handle preparation must be synchronous",
        "reconciliation_handle_invalid": "SDK did not issue an exact opaque reconciliation handle",
    }

    def __init__(
        self,
        *,
        error_type: Type[Exception],
        missing_dependency_error_type: Type[Exception],
    ) -> None:
        self._error_type = error_type
        self._missing_dependency_error_type = missing_dependency_error_type

    def _call(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        try:
            from bt_api_py.facade_protocol import (
                OrderCorrelation,
                ReconciliationFacadePort,
                ReconciliationFacadeSelector,
                ReconciliationRequestHandle,
            )
            from bt_api_py.reconciliation import ReconciliationClient, ReconciliationError
            if not all(
                isinstance(contract, type)
                for contract in (
                    OrderCorrelation,
                    ReconciliationFacadePort,
                    ReconciliationFacadeSelector,
                    ReconciliationRequestHandle,
                )
            ):
                raise ImportError("reconciliation contract unavailable")
        except ImportError as exc:
            raise self._missing_dependency_error_type(
                "bt_api_py reconciliation client contracts are required"
            ) from exc
        try:
            return getattr(ReconciliationClient, operation)(*args, **kwargs)
        except ReconciliationError as exc:
            if operation in {"snapshot", "validate_snapshot"}:
                raise
            raise self._error_type(
                self._MESSAGES.get(exc.code, "SDK reconciliation request failed")
            ) from None

    def select_facade(self, api: Any, route: Any) -> Any:
        return self._call("select_facade", api, route)

    def prepare_handle(self, facade: Any, *, correlation: Any = None) -> Any:
        return self._call("prepare_handle", facade, correlation=correlation)

    def is_request_handle(self, handle: Any) -> bool:
        return self._call("is_request_handle", handle)

    def snapshot(self, facade: Any, handle: Any, *, timeout: float) -> Any:
        return self._call("snapshot", facade, handle, timeout=timeout)

    def validate_snapshot(self, facade: Any, handle: Any, result: Any, *, now: Any) -> Any:
        return self._call("validate_snapshot", facade, handle, result, now=now)


__all__ = ("SdkReconciliationAdapter",)
