"""Backtrader Store bridge for optional managed execution and groups.

The Store owns attachment and lifecycle; SDK services own provider dispatch,
durable state and authorization. This bridge starts no service on its own.
"""
from __future__ import annotations

from typing import Any

from ..execution.managed_execution import ManagedExecutionAdapter, require_managed_execution_adapter
from ..stores._btapi_errors import BtApiStoreError


class StoreManagedExecutionBridgeMixin:
    """Bind optional managed adapters to the Store's framework lifecycle."""

    @property
    def managed_execution_active(self) -> bool:
        """Return whether this Store has an explicitly attached managed route.

        The value describes the Store attachment only.  It does not certify
        live approval, provider capability, or a successful account session;
        those remain the responsibility of the validated runtime composition.
        """

        return self._managed_execution_adapter is not None

    @property
    def service_execution_group_active(self) -> bool:
        """Return whether an explicit Strategy group route is attached."""

        return self._service_execution_group_adapter is not None

    def attach_service_execution_group_adapter(self, adapter: Any) -> None:
        """Attach the validated optional Strategy group bridge before startup."""

        if self._started or self._connected:
            raise BtApiStoreError("service group adapter must attach before Store startup")
        if self._service_execution_group_adapter is not None:
            raise BtApiStoreError("service group adapter is already attached")
        try:
            from backtrader.service.service_execution_group import (
                require_service_execution_group_adapter,
            )

            self._service_execution_group_adapter = require_service_execution_group_adapter(adapter)
        except Exception as error:
            raise BtApiStoreError("invalid service group adapter") from error

    def bind_strategy_execution_group(self, strategy: Any, broker: Any) -> None:
        """Bind one actual Strategy object to its registered group route."""

        adapter = self._service_execution_group_adapter
        if adapter is None:
            raise BtApiStoreError("strategy group route is unavailable")
        adapter.bind_strategy(strategy, broker)

    def submit_group_order(self, strategy: Any, broker: Any, intent: Any) -> Any:
        """Submit one typed P5A group through the registered coordinator route."""

        adapter = self._service_execution_group_adapter
        if adapter is None:
            raise BtApiStoreError("strategy group route is unavailable")
        return adapter.submit(strategy, broker, intent)

    def query_group_order(self, strategy: Any, broker: Any, group_id: str) -> Any:
        """Query one existing group ID through the registered coordinator route."""

        adapter = self._service_execution_group_adapter
        if adapter is None:
            raise BtApiStoreError("strategy group route is unavailable")
        return adapter.query(strategy, broker, group_id)

    def submit_group_roll_exit(
        self,
        strategy: Any,
        broker: Any,
        group_id: str,
        source_leg_id: str,
        limit_price: Any,
    ) -> Any:
        """Request one source-bound group CLOSE through the coordinator adapter."""

        adapter = self._service_execution_group_adapter
        if adapter is None:
            raise BtApiStoreError("strategy group roll-exit route is unavailable")
        return adapter.roll_exit(strategy, broker, group_id, source_leg_id, limit_price)

    def query_group_roll_exit(self, strategy: Any, broker: Any, action_id: str) -> Any:
        """Read roll-exit status through its registered read capability."""

        adapter = self._service_execution_group_adapter
        if adapter is None:
            raise BtApiStoreError("strategy group roll-exit route is unavailable")
        return adapter.query_roll_exit(strategy, broker, action_id)

    def recover_group_order(
        self,
        strategy: Any,
        broker: Any,
        group_id: str,
        cursor: Any = None,
        *,
        limit: int = 32,
    ) -> Any:
        """Read the original group ID and resume its caller-owned monitor cursor."""

        adapter = self._service_execution_group_adapter
        if adapter is None:
            raise BtApiStoreError("strategy group route is unavailable")
        return adapter.recover(strategy, broker, group_id, cursor, limit=limit)

    def read_group_residuals(
        self,
        strategy: Any,
        broker: Any,
        cursor: Any = None,
        *,
        limit: int = 32,
    ) -> Any:
        """Read a repeatable, durable Monitor residual page without acknowledging it."""

        adapter = self._service_execution_group_adapter
        if adapter is None:
            raise BtApiStoreError("strategy group route is unavailable")
        return adapter.read_residuals(strategy, broker, cursor, limit=limit)

    def attach_managed_execution_adapter(self, adapter: ManagedExecutionAdapter) -> None:
        """Attach one already-composed managed route before Store startup.

        Runtime composition may build the Store before all code-owned adapter
        dependencies are ready.  This method keeps that setup explicit and
        rejects route replacement after startup or after another adapter has
        been attached; it never accepts a configuration dict or module name.
        """

        if self._started or self._connected:
            raise BtApiStoreError("managed execution adapter must attach before Store startup")
        if self._managed_execution_adapter is not None:
            raise BtApiStoreError("managed execution adapter is already attached")
        validated = require_managed_execution_adapter(adapter)

        self._managed_execution_adapter = validated

    def get_strategy_allocation(self, strategy_id: str):
        """Read an attached managed adapter's allocation without starting the SDK.

        The immutable SDK snapshot describes local reserved risk units. It
        supplies sizing advice only; the writer must still reserve atomically.
        """

        reader = getattr(self._managed_execution_adapter, "get_strategy_allocation", None)
        if not callable(reader):
            raise BtApiStoreError("managed strategy allocation reader is unavailable")
        return reader(strategy_id)

    def validate_managed_framework_projection(self, response, order) -> bool:
        """Ask the attached bridge whether a fill response owns a live receipt.

        The Broker must not trust a response flag from a legacy/provider payload
        as permission to replay a durable managed fill.  This narrow port stays
        false for every historic adapter and becomes true only when the
        configuration-bound bridge has retained the private receipt claim.
        """

        adapter = self._managed_execution_adapter
        validate = getattr(adapter, "validate_framework_projection", None)
        if not callable(validate):
            return False
        try:
            return validate(response, order) is True
        except Exception as exc:
            from ..stores.btapistore import _safe_log

            _safe_log("warning", "btapistore:managed framework projection receipt invalid")
            self.sanitize_exception(exc)
            return False

    def complete_managed_framework_projection(self, response, order) -> None:
        """Commit a bridge receipt after normal Broker fill accounting succeeds."""

        adapter = self._managed_execution_adapter
        complete = getattr(adapter, "complete_framework_projection", None)
        if not callable(complete):
            raise BtApiStoreError("managed framework projection completion is unavailable")
        complete(response, order)

    def fail_managed_framework_projection(self, response, reason) -> None:
        """Fence the attached bridge after a post-accounting receipt failure."""

        fail = getattr(self._managed_execution_adapter, "fail_framework_projection", None)
        if callable(fail):
            try:
                fail(response, reason)
            except Exception as exc:
                self.sanitize_exception(exc)

    @property
    def managed_provider_projection_enabled(self) -> bool:
        """True only for a bridge with an explicitly injected source normalizer."""

        return bool(
            getattr(self._managed_execution_adapter, "managed_provider_projection_enabled", False)
        )

    @property
    def managed_provider_projection_blocked(self) -> bool:
        """Expose only the bridge's process-local fail-closed session latch."""

        return bool(getattr(self._managed_execution_adapter, "_source_projection_blocked", False))

    def prepare_managed_provider_projection(self, update, order):
        """Durably persist and claim a provider event before Broker mutation."""

        adapter = self._managed_execution_adapter
        prepare = getattr(adapter, "prepare_managed_provider_projection", None)
        if not callable(prepare):
            raise BtApiStoreError("managed provider event preparation is unavailable")
        try:
            return prepare(update, order)
        except Exception as exc:
            self.sanitize_exception(exc)
            raise

    def validate_managed_provider_projection(self, update, order) -> bool:
        """Validate the private receipt for an immutable source event."""

        validate = getattr(
            self._managed_execution_adapter, "validate_managed_provider_projection", None
        )
        if not callable(validate):
            return False
        try:
            return validate(update, order) is True
        except Exception as exc:
            self.sanitize_exception(exc)
            return False

    def complete_managed_provider_projection(self, update, order) -> None:
        """Persist the session high-water after the Broker applied a source event."""

        complete = getattr(
            self._managed_execution_adapter, "complete_managed_provider_projection", None
        )
        if not callable(complete):
            raise BtApiStoreError("managed provider event completion is unavailable")
        complete(update, order)

    def fail_managed_provider_projection(self, update, reason) -> None:
        """Fence the managed bridge session after uncertain Broker application."""

        fail = getattr(self._managed_execution_adapter, "fail_managed_provider_projection", None)
        if callable(fail):
            try:
                fail(update, reason)
            except Exception as exc:
                self.sanitize_exception(exc)

