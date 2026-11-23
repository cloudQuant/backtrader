"""Thin shared base Feed for Direct and Gateway bt_api_py live feeds (T-025).

Inherits ``(LiveBarCohortFeedMixin, LiveFeedBase)`` cleanly with zero metaclass
conflict and provides:
- Immutable ``LiveRunBinding`` storage and verification against its Store.
- Mode-specific ``MarketSourcePort`` and ``CalendarQueryPort`` attachment.
- Unbound helper classmethods (``historical_warmup_active``,
  ``gateway_trade_qualification``) so internal callers can safely check
  ``isinstance(feed, BaseBtApiFeed)`` across ``BtApiFeed``,
  ``DirectBtApiFeed``, and ``GatewayBtApiFeed``.
"""

from __future__ import annotations

from typing import Any, Optional

from ..stores._btapi_errors import LiveCompositionError
from ..stores.btapi_composition import LiveRunBinding, verify_run_binding
from ._btapi_cohort import LiveBarCohortFeedMixin
from ._calendar_query_port import CalendarQueryPort
from ._market_source_port import MarketSourcePort
from .livefeed import LiveFeedBase

__all__ = ["BaseBtApiFeed"]


class BaseBtApiFeed(LiveBarCohortFeedMixin, LiveFeedBase):
    """Shared base class for ``BtApiFeed``, ``DirectBtApiFeed``, and ``GatewayBtApiFeed``."""

    _run_binding: Optional[LiveRunBinding] = None
    _market_source_port: Optional[MarketSourcePort] = None
    _calendar_query_port: Optional[CalendarQueryPort] = None

    @property
    def run_binding(self) -> Optional[LiveRunBinding]:
        return self._run_binding

    @property
    def live_mode(self) -> Optional[str]:
        if self._run_binding is not None:
            return self._run_binding.mode
        if self._market_source_port is not None:
            return self._market_source_port.mode
        store = getattr(self, "store", None)
        if store is not None:
            return getattr(store, "live_mode", None)
        return None

    @property
    def market_source_port(self) -> Optional[MarketSourcePort]:
        return self._market_source_port

    @property
    def calendar_query_port(self) -> Optional[CalendarQueryPort]:
        return self._calendar_query_port

    def verify_run_binding_for(self, expected: LiveRunBinding) -> None:
        verify_run_binding(expected, self._run_binding)

    @staticmethod
    def check_historical_warmup_active(feed: "BaseBtApiFeed") -> bool:
        """Non-overridable helper mirroring ``BtApiFeed.historical_warmup_active``."""
        from .btapifeed import BtApiFeed

        if not isinstance(feed, BtApiFeed):
            raise LiveCompositionError("MODE_CONFLICT", detail="feed_not_btapi")
        return bool(BtApiFeed.historical_warmup_active(feed))

    @staticmethod
    def check_gateway_trade_qualification(
        feed: "BaseBtApiFeed",
        *,
        expected_store: Any,
        expected_instrument: Any,
    ) -> Any:
        """Non-overridable helper mirroring ``BtApiFeed.gateway_trade_qualification``."""
        from .btapifeed import BtApiFeed

        if not isinstance(feed, BtApiFeed):
            raise LiveCompositionError("MODE_CONFLICT", detail="feed_not_btapi")
        return BtApiFeed.gateway_trade_qualification(
            feed,
            expected_store=expected_store,
            expected_instrument=expected_instrument,
        )
