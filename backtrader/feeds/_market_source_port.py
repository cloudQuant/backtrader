"""Mode-specific market source ports for Direct and Gateway live feeds (T-025).

Decouples :class:`BaseBtApiFeed` from mode-dependent polling, idle backoff, and
capability checks while preserving:
- Direct mode: Store-backed tick/bar/orderbook polling + optional backfill +
  optional research cohort mode.
- Gateway mode: ``GatewayMarketAdapter`` subscription only, explicit capability
  refusals (``GATEWAY_MARKET_FEED_CONFIGURATION_UNSUPPORTED``), and the
  ``0.02s`` idle poll backoff preventing CPU spin when ``qcheck`` is unset.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple
from typing_extensions import Protocol, runtime_checkable

__all__ = [
    "GATEWAY_IDLE_POLL_SECONDS",
    "DirectMarketSourcePort",
    "GatewayMarketSourcePort",
    "MarketSourcePort",
]

GATEWAY_IDLE_POLL_SECONDS: float = 0.02


@runtime_checkable
class MarketSourcePort(Protocol):
    """Minimal neutral contract for a live feed's market data source."""

    @property
    def mode(self) -> str: ...

    @property
    def idle_poll_seconds(self) -> float: ...

    @property
    def supports_backfill(self) -> bool: ...

    @property
    def supports_orderbook_as_ticks(self) -> bool: ...

    @property
    def supports_cohort_mode(self) -> bool: ...

    def validate_feed_capabilities(self, feed: Any) -> None: ...

    def poll_live_bar(self, store: Any, dataname: str) -> Any: ...

    def recovery_reason(self, feed: Any) -> Optional[str]: ...


class DirectMarketSourcePort:
    """Market source port for :class:`DirectBtApiFeed`."""

    mode: str = "direct"
    idle_poll_seconds: float = 0.0
    supports_backfill: bool = True
    supports_orderbook_as_ticks: bool = True
    supports_cohort_mode: bool = True

    def validate_feed_capabilities(self, feed: Any) -> None:
        from ..stores._btapi_errors import LiveCompositionError

        if getattr(feed.p, "gateway_clock_verification", None) is not None:
            raise LiveCompositionError(
                "MODE_CONFLICT", detail="gateway_clock_verification_on_direct_feed"
            )
        if getattr(feed.p, "allow_stale_market_feed", False) is True:
            raise LiveCompositionError(
                "MODE_CONFLICT", detail="allow_stale_market_feed_on_direct_feed"
            )

    def poll_live_bar(self, store: Any, dataname: str) -> Any:
        if store is None:
            return None
        poller = getattr(store, "poll_live", None)
        return poller(dataname) if callable(poller) else None

    def recovery_reason(self, feed: Any) -> Optional[str]:
        reader = getattr(feed, "_stream_recovery_reader", None)
        return reader() if callable(reader) else None


class GatewayMarketSourcePort:
    """Market source port for :class:`GatewayBtApiFeed`."""

    mode: str = "gateway"
    idle_poll_seconds: float = GATEWAY_IDLE_POLL_SECONDS
    supports_backfill: bool = False
    supports_orderbook_as_ticks: bool = False
    supports_cohort_mode: bool = False

    _UNSUPPORTED_TRUTHY_PARAMS: Tuple[str, ...] = (
        "backfill_start",
        "orderbook_as_ticks",
        "cohort_source_mode",
        "market_factor_source_binding",
        "closed_bar_evidence_provider",
        "market_decision_now_provider",
        "closed_bar_quote_capture",
    )

    def validate_feed_capabilities(self, feed: Any) -> None:
        for param_name in self._UNSUPPORTED_TRUTHY_PARAMS:
            if getattr(feed.p, param_name, None):
                raise ValueError("GATEWAY_MARKET_FEED_CONFIGURATION_UNSUPPORTED")
        if getattr(feed.p, "historical_bars", None) or getattr(feed.p, "live_bars", None):
            raise ValueError("GATEWAY_MARKET_FEED_CONFIGURATION_UNSUPPORTED")

    def poll_live_bar(self, store: Any, dataname: str) -> Any:
        # Gateway feeds deliver exclusively through GatewayMarketAdapter ticks.
        return None

    def recovery_reason(self, feed: Any) -> Optional[str]:
        adapter = feed.__dict__.get("_gateway_market_adapter")
        if adapter is not None:
            reader = getattr(adapter, "recovery_reason", None)
            if callable(reader):
                return reader()
        return None
