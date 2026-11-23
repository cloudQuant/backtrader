"""Strict Direct-mode bt_api_py Feed implementation (T-027)."""

from __future__ import annotations

from typing import Any, Optional

from ..stores._btapi_errors import LiveCompositionError
from ..stores.btapi_composition import LiveRunBinding, verify_run_binding
from ._calendar_query_port import LocalCalendarQueryPort
from ._market_source_port import DirectMarketSourcePort
from .btapifeed import BtApiFeed

__all__ = ["DirectBtApiFeed"]


class DirectBtApiFeed(BtApiFeed):
    """Concrete Direct-mode live Feed (forbids Gateway store/options and local_replay)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        explicit_binding: Optional[LiveRunBinding] = kwargs.pop("run_binding", None)
        super().__init__(*args, **kwargs)

        if self.provider == "local_replay" or self.p.replay_market_tick_port is not None:
            raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="local_replay_on_direct_feed")

        from ..stores.gateway_btapi_store import GatewayBtApiStore

        if isinstance(self.store, GatewayBtApiStore) or getattr(
            self.store, "_gateway_mode", False
        ):
            raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="gateway_store_on_direct_feed")

        store_binding = getattr(self.store, "run_binding", None) if self.store is not None else None
        if explicit_binding is not None:
            if not isinstance(explicit_binding, LiveRunBinding) or explicit_binding.mode != "direct":
                raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="direct_feed_binding_mode")
            if store_binding is not None:
                verify_run_binding(store_binding, explicit_binding)
            self._run_binding = explicit_binding
        elif store_binding is not None:
            if store_binding.mode != "direct":
                raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="direct_feed_store_mode")
            self._run_binding = store_binding
        else:
            self._run_binding = LiveRunBinding(mode="direct")

        self._market_source_port = DirectMarketSourcePort()
        self._calendar_query_port = LocalCalendarQueryPort()
        self._market_source_port.validate_feed_capabilities(self)
        self._calendar_query_port.validate_feed_scope(self._calendar_scope)

    def instrument_status_observation(self, *, timeout_seconds: float = 5.0) -> Any:
        """Gateway instrument status queries are unavailable on DirectBtApiFeed."""
        raise LiveCompositionError(
            "MODE_CONFLICT", detail="gateway_instrument_status_on_direct_feed"
        )
