"""Strict Gateway-mode bt_api_py Feed implementation (T-027)."""

from __future__ import annotations

from typing import Any, Optional

from ..stores._btapi_errors import LiveCompositionError
from ..stores.btapi_composition import LiveRunBinding, verify_run_binding
from ._calendar_query_port import GatewayCalendarQueryPort
from ._market_source_port import GatewayMarketSourcePort
from .btapifeed import BtApiFeed

__all__ = ["GatewayBtApiFeed"]


class GatewayBtApiFeed(BtApiFeed):
    """Concrete Gateway-mode live Feed (strict Gateway capability & calendar contract)."""

    params = (("backfill_start", False),)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        explicit_binding: Optional[LiveRunBinding] = kwargs.pop("run_binding", None)
        super().__init__(*args, **kwargs)

        if self.provider == "local_replay" or self.p.replay_market_tick_port is not None:
            raise LiveCompositionError("NON_LIVE_TOOL_CONFLICT", detail="local_replay_on_gateway_feed")

        from ..stores.direct_btapi_store import DirectBtApiStore

        if isinstance(self.store, DirectBtApiStore) or (
            self.store is not None
            and not getattr(self.store, "_gateway_mode", False)
            and getattr(self.store, "live_mode", None) == "direct"
        ):
            raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="direct_store_on_gateway_feed")

        store_binding = getattr(self.store, "run_binding", None) if self.store is not None else None
        if explicit_binding is not None:
            if not isinstance(explicit_binding, LiveRunBinding) or explicit_binding.mode != "gateway":
                raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="gateway_feed_binding_mode")
            if store_binding is not None:
                verify_run_binding(store_binding, explicit_binding)
            self._run_binding = explicit_binding
        elif store_binding is not None:
            if store_binding.mode != "gateway":
                raise LiveCompositionError("RUN_BINDING_MISMATCH", detail="gateway_feed_store_mode")
            self._run_binding = store_binding
        else:
            self._run_binding = LiveRunBinding(mode="gateway")

        self._market_source_port = GatewayMarketSourcePort()
        self._calendar_query_port = GatewayCalendarQueryPort()
        self._market_source_port.validate_feed_capabilities(self)
        store_cfg = getattr(self.store, "_config", None) if self.store is not None else None
        self._calendar_query_port.validate_feed_scope(self._calendar_scope, config=store_cfg)

    def start(self) -> None:
        if self._market_source_port is not None:
            self._market_source_port.validate_feed_capabilities(self)
        super().start()
