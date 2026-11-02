"""Backtrader Store bindings for SDK reconciliation requests and results.

Store instance state and BT order references remain framework-owned; the SDK
owns its reconciliation contracts, handle issuance and result verification.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict

from .reconciliation_projection import (
    project_store_reconciliation_result as _project_store_reconciliation_result,
)

_UTC = _dt.timezone.utc


class StoreReconciliationBridgeMixin:
    """Bind Store lifecycle and local orders to neutral SDK reconciliation."""

    @staticmethod
    def _incomplete_reconciliation_snapshot(reason: str) -> Dict[str, Any]:
        """Return a neutral, non-authoritative snapshot with no projected rows."""
        safe_reason = (
            reason
            if type(reason) is str
            and reason
            and reason == reason.strip()
            and re.fullmatch(r"[a-z0-9_]{1,96}", reason)
            else "reconciliation_unavailable"
        )
        return {
            "schema_version": "backtrader.execution.reconciliation.v1",
            "complete": False,
            "safe_to_resume": False,
            "evidence_complete": False,
            "consistency_digest": None,
            "snapshot_id": None,
            "orders": None,
            "fills": None,
            "positions": None,
            "open_orders": None,
            "reason": safe_reason,
            "error_code": safe_reason,
        }

    @staticmethod
    def _reconciliation_timeout(timeout: Any) -> float:
        """Validate a finite timeout before it crosses into the SDK."""
        from bt_api_py.reconciliation import validate_reconciliation_timeout

        return validate_reconciliation_timeout(timeout, maximum_seconds=60.0)

    def _active_sdk_reconciliation_api(self):
        """Require an already active SDK session without lazy construction."""
        from ..stores._btapi_errors import BtApiStoreError

        if not self._sdk_mode or self._service_read_only:
            raise BtApiStoreError("SDK reconciliation requires the unified execution facade")
        api = self._api
        if api is None or not self._started or not self._connected:
            raise BtApiStoreError("SDK reconciliation requires an active Store session")
        return api

    def _select_reconciliation_route(self, api, exchange_name=None):
        """Select an exact route-name key; never infer or merge route scopes."""
        from ..stores._btapi_errors import BtApiStoreError

        if api is not self._api:
            raise BtApiStoreError("SDK reconciliation API binding changed")
        from bt_api_py.route_identity_projection import select_exact_reconciliation_route

        return select_exact_reconciliation_route(
            self._facade_exchange_names(api),
            list(self._sdk_exchanges),
            exchange_name,
            error_type=BtApiStoreError,
        )

    def _reconciliation_facade(self, api, route):
        """Delegate exact neutral reconciliation-port selection to the adapter."""
        return self._sdk_reconciliation_adapter.select_facade(api, route)

    def _prepare_reconciliation_handle(self, facade, *, correlation=None):
        """Delegate SDK handle issuance while Store owns BT scope references."""
        return self._sdk_reconciliation_adapter.prepare_handle(
            facade,
            correlation=correlation,
        )

    def _queue_reconciliation_command(
        self,
        operation,
        *,
        api,
        route,
        facade,
        handle,
        timeout,
        local_ref=None,
        client_order_id=None,
        correlation=None,
    ):
        if not self.uses_async_commands:
            return {
                "kind": "command_receipt",
                "command": operation,
                "queued": False,
                "status": "rejected",
                "error_code": "reconciliation_worker_unavailable",
            }
        if self._api is not api or not self._connected or not self._started:
            return {
                "kind": "command_receipt",
                "command": operation,
                "queued": False,
                "status": "rejected",
                "error_code": "reconciliation_session_unavailable",
            }
        command = {
            "operation": operation,
            "venue": route,
            "symbol": (
                correlation.symbol
                if correlation is not None
                else None
            ),
            "bt_order_ref": local_ref,
            "client_order_id": client_order_id,
            "correlation": correlation,
            "reconciliation_api": api,
            "reconciliation_facade": facade,
            "reconciliation_handle": handle,
            "reconciliation_timeout": timeout,
        }
        return self._enqueue_sdk_command(command, priority_name="reconcile")

    def enqueue_order_reconciliation(self, local_ref, *, timeout=5.0) -> Dict[str, Any]:
        """Queue an SDK-issued order reconciliation using a BT-local reference."""
        from ..stores._btapi_errors import BtApiStoreError

        if type(local_ref) is not int or local_ref <= 0:
            return {
                "kind": "command_receipt",
                "command": "reconciliation",
                "queued": False,
                "status": "rejected",
                "error_code": "order_reconciliation_reference_invalid",
            }
        try:
            timeout = self._reconciliation_timeout(timeout)
            api = self._active_sdk_reconciliation_api()
            binding = self._sdk_execution_bindings.by_local_ref(local_ref)
            if binding is None or binding.get("api") is not api:
                raise BtApiStoreError("Store-local order correlation is unavailable")
            correlation = binding.get("correlation")
            route = binding.get("exchange_name")
            symbol = binding.get("symbol")
            client_order_id = binding.get("client_order_id")
            if (
                type(route) is not str
                or type(symbol) is not str
                or type(client_order_id) is not str
                or correlation is None
                or correlation.client_order_id != client_order_id
                or correlation.exchange_name != route
                or correlation.symbol != symbol
                or not self._sdk_execution_bindings.binding_matches(
                    binding,
                    correlation=correlation,
                    api=api,
                    exchange_name=route,
                    symbol=symbol,
                    require_all_indexes=True,
                )
            ):
                raise BtApiStoreError("Store-local order correlation is stale")
            route = self._select_reconciliation_route(api, route)
            facade = self._reconciliation_facade(api, route)
            handle = self._prepare_reconciliation_handle(
                facade, correlation=correlation
            )
            return self._queue_reconciliation_command(
                "order_reconciliation",
                api=api,
                route=route,
                facade=facade,
                handle=handle,
                timeout=timeout,
                local_ref=local_ref,
                client_order_id=client_order_id,
                correlation=correlation,
            )
        except Exception as exc:
            self.sanitize_exception(exc)
            return {
                "kind": "command_receipt",
                "command": "reconciliation",
                "queued": False,
                "status": "rejected",
                "error_code": self._safe_exception_code(
                    exc, "order_reconciliation_unavailable"
                ),
            }

    def enqueue_reconciliation(self, correlation=None, *, timeout=5.0) -> Dict[str, Any]:
        """Queue an SDK-authorized account snapshot for the exact single route."""
        if correlation is not None:
            if type(correlation) is not str or not correlation or correlation != correlation.strip():
                return {
                    "kind": "command_receipt",
                    "command": "reconciliation",
                    "queued": False,
                    "status": "rejected",
                    "error_code": "reconciliation_correlation_invalid",
                }
            matches = tuple(
                binding
                for binding in self._sdk_execution_bindings.find_client_id(
                    correlation, api=self._api
                )
                if self._sdk_execution_bindings.binding_matches(
                    binding, api=self._api, require_all_indexes=True
                )
            )
            if len(matches) != 1 or type(matches[0].get("bt_order_ref")) is not int:
                return {
                    "kind": "command_receipt",
                    "command": "reconciliation",
                    "queued": False,
                    "status": "rejected",
                    "error_code": "reconciliation_correlation_unbound",
                }
            return self.enqueue_order_reconciliation(
                matches[0]["bt_order_ref"], timeout=timeout
            )
        try:
            timeout = self._reconciliation_timeout(timeout)
            api = self._active_sdk_reconciliation_api()
            route = self._select_reconciliation_route(api)
            facade = self._reconciliation_facade(api, route)
            handle = self._prepare_reconciliation_handle(facade)
            return self._queue_reconciliation_command(
                "reconciliation",
                api=api,
                route=route,
                facade=facade,
                handle=handle,
                timeout=timeout,
            )
        except Exception as exc:
            self.sanitize_exception(exc)
            return {
                "kind": "command_receipt",
                "command": "reconciliation",
                "queued": False,
                "status": "rejected",
                "error_code": self._safe_exception_code(
                    exc, "reconciliation_unavailable"
                ),
            }

    def enqueue_reconcile(self) -> Dict[str, Any]:
        """Queue a typed SDK snapshot for the active single-route account scope."""
        try:
            api = self._active_sdk_reconciliation_api()
            route = self._select_reconciliation_route(api)
            facade = self._reconciliation_facade(api, route)
            handle = self._prepare_reconciliation_handle(facade)
            return self._queue_reconciliation_command(
                "reconcile",
                api=api,
                route=route,
                facade=facade,
                handle=handle,
                timeout=5.0,
            )
        except Exception as exc:
            self.sanitize_exception(exc)
            return {
                "kind": "command_receipt",
                "command": "reconcile",
                "queued": False,
                "status": "rejected",
                "error_code": self._safe_exception_code(
                    exc, "reconciliation_unavailable"
                ),
            }

    def reconciliation_snapshot(self, *, timeout=5.0) -> Dict[str, Any]:
        """Read and adapt one exact SDK-verified account reconciliation result."""
        try:
            timeout = self._reconciliation_timeout(timeout)
            api = self._active_sdk_reconciliation_api()
            route = self._select_reconciliation_route(api)
            facade = self._reconciliation_facade(api, route)
            handle = self._prepare_reconciliation_handle(facade)
            result = self._sdk_reconciliation_adapter.snapshot(
                facade,
                handle,
                timeout=timeout,
            )
            return self._project_reconciliation_result(
                api,
                route,
                facade,
                handle,
                result,
            )
        except Exception as exc:
            self.sanitize_exception(exc)
            return self._incomplete_reconciliation_snapshot(
                self._safe_exception_code(exc, "reconciliation_unavailable")
            )

    async def _invoke_sdk_reconciliation(self, command):
        """Run one retained SDK handle and require its exact current verifier."""
        from ..stores._btapi_errors import BtApiMissingDependencyError
        from ..stores.btapistore import _run_in_thread
        api = command.get("reconciliation_api")
        route = command.get("venue")
        facade = command.get("reconciliation_facade")
        handle = command.get("reconciliation_handle")
        correlation = command.get("correlation")
        timeout = command.get("reconciliation_timeout")
        try:
            timeout = self._reconciliation_timeout(timeout)
            if api is not self._api or not self._connected or not self._started:
                return self._incomplete_reconciliation_snapshot(
                    "reconciliation_session_changed"
                )
            selected_route = self._select_reconciliation_route(api, route)
            if selected_route != route:
                return self._incomplete_reconciliation_snapshot(
                    "reconciliation_route_changed"
                )
            current_facade = self._reconciliation_facade(api, route)
            if current_facade is not facade:
                return self._incomplete_reconciliation_snapshot(
                    "reconciliation_facade_changed"
                )
            if correlation is not None:
                entry = self._sdk_execution_bindings.by_correlation(correlation)
                if entry is None or not self._sdk_execution_bindings.binding_matches(
                    entry,
                    correlation=correlation,
                    api=api,
                    exchange_name=route,
                    states={"prepared", "queued", "completed", "unknown"},
                    require_all_indexes=True,
                ):
                    return self._incomplete_reconciliation_snapshot(
                        "order_reconciliation_binding_changed"
                    )
            try:
                exact_handle = self._sdk_reconciliation_adapter.is_request_handle(handle)
            except BtApiMissingDependencyError:
                return self._incomplete_reconciliation_snapshot(
                    "reconciliation_contract_unavailable"
                )
            if exact_handle is not True:
                return self._incomplete_reconciliation_snapshot(
                    "reconciliation_handle_invalid"
                )
            result = await _run_in_thread(
                self._sdk_reconciliation_adapter.snapshot,
                facade,
                handle,
                timeout=timeout,
            )
            return await self._project_reconciliation_result_async(
                api,
                route,
                facade,
                handle,
                result,
                command=command,
            )
        except Exception as exc:
            self.sanitize_exception(exc)
            return self._incomplete_reconciliation_snapshot(
                self._safe_exception_code(exc, "reconciliation_provider_unavailable")
            )

    async def _project_reconciliation_result_async(
        self, api, route, facade, handle, result, *, command
    ):
        """Verify a worker result on a thread before neutral projection."""
        from ..stores.btapistore import _run_in_thread
        try:
            valid = await _run_in_thread(
                self._sdk_reconciliation_adapter.validate_snapshot,
                facade,
                handle,
                result,
                now=_dt.datetime.now(_UTC),
            )
        except Exception:
            valid = False
        return self._project_reconciliation_result(
            api,
            route,
            facade,
            handle,
            result,
            verified=valid,
            retain_for_apply=command.get("operation") in {"reconcile", "reconciliation"},
            order_specific=command.get("operation") == "order_reconciliation",
            retain_for_order=command.get("operation") == "order_reconciliation",
            order_local_ref=(
                command.get("bt_order_ref")
                if command.get("operation") == "order_reconciliation"
                else None
            ),
            expected_correlation=(
                command.get("correlation")
                if command.get("operation") == "order_reconciliation"
                else None
            ),
        )

    def _project_reconciliation_result(
        self, api, route, facade, handle, result, *, verified=None,
        retain_for_apply=False, order_specific=False, retain_for_order=False,
        order_local_ref=None, expected_correlation=None,
    ):
        """Project SDK reconciliation through the framework execution adapter."""
        return _project_store_reconciliation_result(
            self, api, route, facade, handle, result, verified=verified,
            retain_for_apply=retain_for_apply, order_specific=order_specific,
            retain_for_order=retain_for_order, order_local_ref=order_local_ref,
            expected_correlation=expected_correlation,
        )
