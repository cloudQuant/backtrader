"""Thin shared Broker base class and unified shutdown summary normalization (T-030/T-031).

Owns ONLY shared broker parameters (never Direct-only parameters from
``direct_params()``), immutable ``LiveRunBinding`` enforcement, and canonical
``get_shutdown_summary()`` normalization aligned with
:mod:`backtrader.live_trading.run_status`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, FrozenSet, Optional, Tuple

from ..broker import BrokerBase
from ..stores.btapi_composition import LiveRunBinding, verify_run_binding
from ._btapi_direct_mode import direct_params

__all__ = [
    "CANONICAL_SHUTDOWN_OUTCOMES",
    "DIRECT_ONLY_BROKER_PARAM_NAMES",
    "SHARED_BTAPI_BROKER_PARAMS",
    "BaseBtApiBroker",
    "normalize_shutdown_summary",
]

SHARED_BTAPI_BROKER_PARAMS: Tuple[Tuple[str, Any], ...] = (
    ("store", None),
    ("cash", 0.0),
    ("value", None),
    ("account_refresh_interval", 1.0),
    ("positions_refresh_interval", 1.0),
    ("position_sync_policy", "periodic"),
    ("position_audit_interval", 0.0),
    ("open_orders_refresh_interval", 1.0),
    ("cancel_wait_remote", False),
    ("cancel_confirmation_timeout", 1.0),
    ("cancel_retry_max_attempts", 3),
    ("reconcile_retry_max_attempts", 3),
    ("reconcile_retry_backoff", 0.05),
    ("force_refresh_queries", True),
    ("max_order_size", 0),
    ("pending_trade_update_limit", 256),
    ("position_mode", "net"),
    ("sdk_preflight", True),
    ("shutdown_timeout", 2.0),
    ("flatten_on_stop", True),
    ("market_data_only", False),
    ("startup_account_state", None),
    ("approval_expires_at_utc", None),
    ("approval_max_order_count", None),
    ("execution_recovery", None),
)

DIRECT_ONLY_BROKER_PARAM_NAMES: FrozenSet[str] = frozenset(name for name, _ in direct_params())

CANONICAL_SHUTDOWN_OUTCOMES: FrozenSet[str] = frozenset(
    {
        "STOPPED",
        "STOPPED_WITH_WORKING_ORDERS",
        "STOPPED_WITH_WRITE_IN_FLIGHT",
        "UNKNOWN",
        "BLOCKED",
        "CRASHED",
        "KILLED",
    }
)


def normalize_shutdown_summary(summary: Any, *, mode: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Normalize a Direct or Gateway broker shutdown summary into canonical run_status vocabulary.

    Lifts and supersedes the example-local ``gateway_client_runner.contract_broker_summary``
    bridge (T-031 / R62S-10). Never upgrades an unproven or incomplete stop to ``STOPPED``.
    """
    if not isinstance(summary, Mapping):
        return None
    translated: Dict[str, Any] = dict(summary)
    if mode is not None:
        translated.setdefault("mode", mode)

    status = translated.get("status")
    has_gateway_fields = (
        mode == "gateway"
        or "gateway_status" in translated
        or "gateway_working_orders" in translated
    )

    if has_gateway_fields:
        working = translated.get("gateway_working_orders")
        working_map = working if isinstance(working, Mapping) else None
        unresolved = (
            working_map.get("unresolved_working_orders") if working_map is not None else None
        )
        gateway_status = translated.get("gateway_status", status)
        translated["gateway_status"] = gateway_status
        market_data_only = translated.get("market_data_only") is True

        if type(unresolved) is int and unresolved > 0:
            translated["status"] = "STOPPED_WITH_WORKING_ORDERS"
            translated["unresolved_working_orders"] = unresolved
            return translated
        if translated.get("write_in_flight") is True or status == "STOPPED_WITH_WRITE_IN_FLIGHT":
            translated["status"] = "STOPPED_WITH_WRITE_IN_FLIGHT"
            return translated
        if gateway_status == "PASS" and unresolved == 0:
            translated["status"] = "STOPPED"
            return translated
        if (
            market_data_only
            and gateway_status == "OBSERVATION_ONLY"
            and not unresolved
            and translated.get("active_order_count") == 0
        ):
            translated["status"] = "STOPPED"
            return translated
        if status in CANONICAL_SHUTDOWN_OUTCOMES and gateway_status in (None, status):
            return translated
        translated["status"] = "UNKNOWN"
        return translated

    # Direct / generic path
    if status == "NOT_STARTED":
        return translated
    if status in CANONICAL_SHUTDOWN_OUTCOMES:
        return translated
    if translated.get("write_in_flight") is True:
        translated["status"] = "STOPPED_WITH_WRITE_IN_FLIGHT"
        return translated
    unresolved_direct = translated.get("unresolved_working_orders")
    if type(unresolved_direct) is int and unresolved_direct > 0:
        translated["status"] = "STOPPED_WITH_WORKING_ORDERS"
        return translated
    if status in ("PASS", "OK", "CLEAN") and unresolved_direct in (0, None):
        translated["status"] = "STOPPED"
        return translated
    translated["status"] = "UNKNOWN"
    return translated


class BaseBtApiBroker(BrokerBase):
    """Thin shared base for ``BtApiBroker``, ``DirectBtApiBroker``, and ``GatewayBtApiBroker``."""

    _run_binding: Optional[LiveRunBinding] = None

    @property
    def run_binding(self) -> Optional[LiveRunBinding]:
        return self._run_binding

    @property
    def live_mode(self) -> Optional[str]:
        if self._run_binding is not None:
            return self._run_binding.mode
        store = getattr(self, "store", None)
        if store is not None:
            return getattr(store, "live_mode", None)
        return None

    @property
    def is_direct_mode(self) -> bool:
        return self.live_mode == "direct"

    @property
    def is_gateway_mode(self) -> bool:
        return self.live_mode == "gateway"

    def verify_run_binding_for(self, expected: LiveRunBinding) -> None:
        verify_run_binding(expected, self._run_binding)
