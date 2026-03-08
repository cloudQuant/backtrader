#!/usr/bin/env python
"""Unified bt_api_py-backed live data feed."""

from __future__ import annotations

import collections

from .livefeed import LiveFeedBase
from ..feed import DataBase
from ..utils import date2num
from ..stores.btapistore import _normalize_bar


class BtApiFeed(DataBase, LiveFeedBase):
    """Data feed that backfills and streams bars through BtApiStore."""

    params = (
        ("store", None),
        ("provider", "btapi"),
        ("historical_bars", None),
        ("live_bars", None),
        ("backfill_start", True),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.store = self.p.store
        self.provider = self.p.provider
        self._history = collections.deque(
            _normalize_bar(bar) for bar in (self.p.historical_bars or [])
        )
        self._live = collections.deque(_normalize_bar(bar) for bar in (self.p.live_bars or []))
        self._live_notified = False

    def start(self):
        """Start the feed, register it, and backfill if configured."""
        super().start()

        if self.store is None:
            self.store = getattr(self, "_store", None)

        if self.store is None:
            return

        self.store.start(data=self)
        self.store.register(self)

        if self.p.backfill_start and not self._history:
            bars = self.store.fetch_history(
                self._dataname,
                timeframe=self._timeframe,
                compression=self._compression,
            )
            self._history.extend(bars)

        self.store.subscribe(self._dataname)

    def stop(self):
        """Stop the feed."""
        super().stop()

    def islive(self) -> bool:
        """Mark this feed as live."""
        return True

    def haslivedata(self) -> bool:
        """Return whether live bars are immediately available."""
        if self._live:
            return True

        if self.store is None:
            return False

        live_cache = getattr(self.store, "_live_bars", {})
        return bool(live_cache.get(self._dataname))

    def _load_history(self) -> bool:
        """Load one historical bar if available."""
        if not self._history:
            return False

        return self._load_bar(self._history.popleft())

    def _load(self) -> bool:
        """Load the next historical or live bar."""
        if self._history:
            return self._load_history()

        if self._live:
            bar = self._live.popleft()
        elif self.store is not None:
            bar = self.store.poll_live(self._dataname)
        else:
            bar = None

        if bar is None:
            return False

        if not self._live_notified:
            self.put_notification(self.LIVE)
            self._live_notified = True

        return self._load_bar(bar)

    def _load_bar(self, bar) -> bool:
        """Write a normalized bar into line buffers."""
        bar = _normalize_bar(bar)
        self.lines.datetime[0] = date2num(bar["datetime"])
        self.lines.open[0] = bar["open"]
        self.lines.high[0] = bar["high"]
        self.lines.low[0] = bar["low"]
        self.lines.close[0] = bar["close"]
        self.lines.volume[0] = bar["volume"]
        self.lines.openinterest[0] = bar["openinterest"]
        return True
