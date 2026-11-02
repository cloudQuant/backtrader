"""Generic Store shutdown observation for the Alpha003 example.

Backtrader stops its public Store and inspects the Store's public lifecycle
health. The current neutral contract has no separate typed provider-close
receipt, so this module reports that field as unavailable rather than inferring
provider resource release.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class DiscoveryStoreCloseResult:
    """Finite, provider-neutral Store shutdown projection."""

    status: str
    reason_code: str
    complete: bool
    store_stop_attempted: bool
    store_stop_returned: Optional[bool]
    shutdown_state: Optional[str]
    workers_quiescent: Optional[bool]
    provider_close_receipt_present: Optional[bool]


class _Custody:
    """Keep the exact supplied Store referenced while closure is uncertain."""

    __slots__ = ("store",)

    def __init__(self, store: Any) -> None:
        self.store = store

    def __repr__(self) -> str:
        return "<DiscoveryStoreCloseCustody: reference retained; details redacted>"


class DiscoveryStoreCloseError(RuntimeError):
    """Store shutdown was incomplete or its public health was unavailable."""

    def __init__(
        self, result: DiscoveryStoreCloseResult, custody: Optional[_Custody]
    ) -> None:
        super().__init__(result.reason_code)
        self.result = result
        self.custody = custody


def _result(
    *,
    status: str,
    reason_code: str,
    attempted: bool,
    returned: Optional[bool],
    shutdown_state: Optional[str] = None,
    workers_quiescent: Optional[bool] = None,
) -> DiscoveryStoreCloseResult:
    return DiscoveryStoreCloseResult(
        status=status,
        reason_code=reason_code,
        complete=False,
        store_stop_attempted=attempted,
        store_stop_returned=returned,
        shutdown_state=shutdown_state,
        workers_quiescent=workers_quiescent,
        provider_close_receipt_present=None,
    )


def _workers_quiescent(health: Mapping[str, Any]) -> Optional[bool]:
    required = {
        "queue_depth": int,
        "inflight": int,
        "publications_pending": int,
        "worker_alive": bool,
        "close_thread_alive": bool,
        "broker_update_queue_depth": int,
        "funding_worker_alive": bool,
        "funding_queue_depth": int,
        "funding_inflight": bool,
        "funding_pending": int,
        "read_only_metadata_probe_active": bool,
    }
    if any(type(health.get(name)) is not value_type for name, value_type in required.items()):
        return None
    projector_close_failures = health.get("market_tick_projector_close_failures", 0)
    if type(projector_close_failures) is not int or projector_close_failures < 0:
        return None
    counters = (
        "queue_depth",
        "inflight",
        "publications_pending",
        "broker_update_queue_depth",
        "funding_queue_depth",
        "funding_pending",
    )
    return (
        projector_close_failures == 0
        and all(health[name] == 0 for name in counters)
        and all(
            health[name] is False
            for name in (
                "worker_alive",
                "close_thread_alive",
                "funding_worker_alive",
                "funding_inflight",
                "read_only_metadata_probe_active",
            )
        )
    )


def close_discovery_store(
    store: Any, timeout: float = 5.0
) -> DiscoveryStoreCloseResult:
    """Stop the selected SDK-backed Store and require its full health result.

    The Store owns the SDK facade and its selected market-tick projectors; its
    terminal health result covers those close operations. There is no separate
    provider-close receipt in the current neutral contract, so this reports
    only Store lifecycle completion and leaves that field unset.
    """

    if type(timeout) not in (int, float) or not math.isfinite(float(timeout)) or timeout <= 0:
        result = _result(
            status="UNAVAILABLE",
            reason_code="STORE_CLOSE_TIMEOUT_INVALID",
            attempted=False,
            returned=None,
        )
        raise DiscoveryStoreCloseError(result, _Custody(store)) from None
    stop = getattr(store, "stop", None)
    if not callable(stop):
        result = _result(
            status="UNAVAILABLE",
            reason_code="STORE_STOP_CAPABILITY_UNAVAILABLE",
            attempted=False,
            returned=None,
        )
        raise DiscoveryStoreCloseError(result, _Custody(store)) from None
    try:
        health = stop(timeout=float(timeout))
    except Exception:
        result = _result(
            status="INCOMPLETE",
            reason_code="STORE_STOP_FAILED",
            attempted=True,
            returned=False,
        )
        raise DiscoveryStoreCloseError(result, _Custody(store)) from None
    if not isinstance(health, Mapping):
        result = _result(
            status="INCOMPLETE",
            reason_code="STORE_SHUTDOWN_HEALTH_INVALID",
            attempted=True,
            returned=True,
        )
        raise DiscoveryStoreCloseError(result, _Custody(store)) from None
    shutdown_state = health.get("shutdown_state")
    if type(shutdown_state) is not str or shutdown_state not in {"PASS", "INCOMPLETE", "FAIL"}:
        result = _result(
            status="INCOMPLETE",
            reason_code="STORE_SHUTDOWN_HEALTH_INVALID",
            attempted=True,
            returned=True,
        )
        raise DiscoveryStoreCloseError(result, _Custody(store)) from None
    quiescent = _workers_quiescent(health)
    if shutdown_state != "PASS" or quiescent is not True:
        result = _result(
            status="INCOMPLETE",
            reason_code="STORE_STOP_INCOMPLETE",
            attempted=True,
            returned=True,
            shutdown_state=shutdown_state,
            workers_quiescent=quiescent,
        )
        raise DiscoveryStoreCloseError(result, _Custody(store)) from None
    return DiscoveryStoreCloseResult(
        status="STOPPED",
        reason_code="STORE_SHUTDOWN_CONFIRMED",
        complete=True,
        store_stop_attempted=True,
        store_stop_returned=True,
        shutdown_state=shutdown_state,
        workers_quiescent=True,
        provider_close_receipt_present=None,
    )


__all__ = [
    "DiscoveryStoreCloseError",
    "DiscoveryStoreCloseResult",
    "close_discovery_store",
]
