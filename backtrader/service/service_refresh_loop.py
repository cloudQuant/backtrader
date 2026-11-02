"""Backtrader Broker binding for SDK managed-order refresh scheduling."""

from __future__ import annotations

from .service_execution_adapter import ServiceExecutionReadError

__all__ = ["ManagedOrderRefreshLoop"]


def _partial_refs(error):
    return tuple(error.applied_refs) if isinstance(error, ServiceExecutionReadError) else ()


class ManagedOrderRefreshLoop:
    """Bind the SDK scheduler to the selected Backtrader Broker."""

    def __init__(self, broker, **settings):
        from bt_api_py.managed_order_refresh import ManagedOrderRefreshLoop as SdkRefreshLoop

        self._delegate = SdkRefreshLoop(
            getattr(broker, "refresh_managed_orders", None),
            partial_refs_from_error=_partial_refs,
            unavailable_code="BROKER_CANNOT_REFRESH",
            **settings,
        )

    def due(self):
        return self._delegate.due()

    def next_delay(self):
        return self._delegate.next_delay()

    def run_once(self):
        return self._delegate.run_once()

    @property
    def stats(self):
        return self._delegate.stats
