"""Standalone non-live Replay Feed decoupled from live Store/Broker paths (D62S-08a).

Intentionally inherits :class:`LiveFeedBase` directly (NOT :class:`BaseBtApiFeed`
or :class:`BtApiFeed`) so live Broker qualification and live Store composition
never treat a replay feed as a live tradable feed.
"""

from __future__ import annotations

from typing import Any, Optional

from ..stores._btapi_errors import LiveCompositionError
from ..utils import date2num
from .livefeed import LiveFeedBase
from .replay_market_adapter import ReplayMarketTickAdapter

__all__ = ["ReplayBtApiFeed"]


class ReplayBtApiFeed(LiveFeedBase):
    """Standalone non-live replay feed backed strictly by a ReplayMarketTickPort."""

    read_only = True

    params = (
        ("store", None),
        ("provider", "local_replay"),
        ("replay_market_tick_port", None),
        ("backfill_start", False),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.p.store is not None:
            raise LiveCompositionError(
                "NON_LIVE_TOOL_CONFLICT", detail="replay_feed_forbids_store"
            )
        if self.p.provider != "local_replay":
            raise LiveCompositionError(
                "NON_LIVE_TOOL_CONFLICT", detail="replay_feed_requires_local_replay_provider"
            )
        if self.p.backfill_start is not False:
            raise ValueError("replay market input requires backfill_start=False")
        if self.p.replay_market_tick_port is None:
            raise ValueError("ReplayBtApiFeed requires replay_market_tick_port")
        self.store = None
        self.provider = "local_replay"
        self._replay_tick_adapter = ReplayMarketTickAdapter(
            self.p.replay_market_tick_port,
            self._dataname,
        )
        self._started = False
        self._last_tick: Optional[Any] = None

    def islive(self) -> bool:
        return False

    @property
    def replay_exhausted(self) -> bool:
        return bool(self._replay_tick_adapter.exhausted)

    def start(self) -> None:
        if self.store is not None or getattr(self, "_store", None) is not None:
            raise LiveCompositionError(
                "NON_LIVE_TOOL_CONFLICT", detail="replay_feed_forbids_store"
            )
        super().start()
        self._replay_tick_adapter.start()
        self._started = True

    def stop(self) -> None:
        try:
            super().stop()
        finally:
            self._started = False
            self._replay_tick_adapter.close()

    def _load(self) -> bool:
        if not self._started:
            return False
        poll = self._replay_tick_adapter.poll_tick()
        if poll is None:
            return False
        status = getattr(poll, "status", None)
        if status == "exhausted" or self._replay_tick_adapter.exhausted:
            return False
        tick = getattr(poll, "tick", None)
        if tick is None:
            return False
        self._last_tick = tick
        price = float(getattr(tick, "price", getattr(tick, "last_price", 0.0)))
        volume = float(getattr(tick, "volume", 0.0) or 0.0)
        ts = getattr(tick, "event_time_utc", None) or getattr(tick, "timestamp", None)
        if ts is not None:
            self.lines.datetime[0] = date2num(ts)
        self.lines.open[0] = price
        self.lines.high[0] = price
        self.lines.low[0] = price
        self.lines.close[0] = price
        self.lines.volume[0] = volume
        self.lines.openinterest[0] = float(getattr(tick, "open_interest", 0.0) or 0.0)
        return True
