"""Strict Direct-mode bt_api_py Broker implementation (T-032).

Owns Direct mode execution parameters (``direct_params()`` including
``waiting_orders``, ``direct_facts_timeout``, ``strategy_dir``), enforces
immutable ``LiveRunBinding(mode='direct', ...)``, rejects Gateway Stores,
and emits canonical :mod:`backtrader.live_trading.run_status` shutdown summaries.
"""

from __future__ import annotations

from typing import Any, Optional

from ..stores._btapi_errors import LiveCompositionError
from ..stores.btapi_composition import LiveRunBinding, verify_run_binding
from .base_btapi_broker import (
    SHARED_BTAPI_BROKER_PARAMS,
    normalize_shutdown_summary,
)
from ._btapi_direct_mode import direct_params
from .btapibroker import BtApiBroker

__all__ = ["DirectBtApiBroker"]


class DirectBtApiBroker(BtApiBroker):
    """Concrete Direct-mode live Broker."""

    params = SHARED_BTAPI_BROKER_PARAMS + direct_params()

    def __init__(self, **kwargs: Any) -> None:
        explicit_binding: Optional[LiveRunBinding] = kwargs.pop("run_binding", None)
        store = kwargs.get("store")
        from ..stores.gateway_btapi_store import GatewayBtApiStore

        if isinstance(store, GatewayBtApiStore) or getattr(store, "_gateway_mode", False):
            raise LiveCompositionError(
                "RUN_BINDING_MISMATCH", detail="gateway_store_on_direct_broker"
            )

        store_binding = getattr(store, "run_binding", None) if store is not None else None
        if explicit_binding is not None:
            if not isinstance(explicit_binding, LiveRunBinding) or explicit_binding.mode != "direct":
                raise LiveCompositionError(
                    "RUN_BINDING_MISMATCH", detail="direct_broker_binding_mode"
                )
            if store_binding is not None:
                verify_run_binding(store_binding, explicit_binding)
            resolved_binding = explicit_binding
        elif store_binding is not None:
            if store_binding.mode != "direct":
                raise LiveCompositionError(
                    "RUN_BINDING_MISMATCH", detail="direct_broker_store_mode"
                )
            resolved_binding = store_binding
        else:
            resolved_binding = LiveRunBinding(
                mode="direct",
                position_mode=str(kwargs.get("position_mode", "net")),
                market_data_only=bool(kwargs.get("market_data_only", False)),
            )

        if resolved_binding.market_data_only:
            kwargs["market_data_only"] = True

        super().__init__(run_binding=resolved_binding, **kwargs)
        self._strict_gateway_no_direct_path = False

    def get_shutdown_summary(self) -> Any:
        raw = super().get_shutdown_summary()
        return normalize_shutdown_summary(raw, mode="direct")
