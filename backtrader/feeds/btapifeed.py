#!/usr/bin/env python
"""Unified bt_api_py-backed live data feed."""

from __future__ import annotations

import collections
import datetime as _dt

from ..channel import Event, EventPriority
from ..dataseries import TimeFrame
from ..events import BarEvent
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
        self._bar_builder = None

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

        if hasattr(self.store, "has_pending_tick") and self.store.has_pending_tick(self._dataname):
            return True

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

        self._drain_live_ticks()

        if self._live:
            bar = self._live.popleft()
        elif self.store is not None:
            bar = self.store.poll_live(self._dataname)
        else:
            bar = None

        if bar is None:
            if (
                self.store is not None
                and hasattr(self.store, "supports_live_ticks")
                and self.store.supports_live_ticks(self._dataname)
            ):
                return None
            return False

        if not self._live_notified:
            self.put_notification(self.LIVE)
            self._live_notified = True

        return self._load_bar(bar)

    def _check(self, forcedata=None):
        """Drain live ticks while waiting for the next completed bar."""
        super()._check(forcedata=forcedata)
        self._drain_live_ticks()

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

    def _drain_live_ticks(self):
        """Drain queued live ticks and aggregate them into completed bars."""
        if self.store is None or not hasattr(self.store, "poll_tick"):
            return

        while True:
            tick = self.store.poll_tick(self._dataname)
            if tick is None:
                break

            self._dispatch_event(
                channel_type="tick",
                priority=EventPriority.TICK,
                event_data=tick,
            )
            self._ingest_tick(tick)

    def _ingest_tick(self, tick):
        """Update the current bar builder from a live tick."""
        tick_dt = getattr(tick, "datetime", None)
        if tick_dt is None:
            tick_dt = _dt.datetime.fromtimestamp(float(tick.timestamp))

        price = float(getattr(tick, "price", 0.0) or 0.0)
        if price <= 0:
            return

        volume = float(getattr(tick, "volume", 0.0) or 0.0)
        openinterest = float(getattr(tick, "openinterest", 0.0) or 0.0)

        if self._timeframe == TimeFrame.Ticks:
            self._enqueue_bar_event(
                BarEvent(
                    timestamp=float(tick.timestamp),
                    symbol=self._dataname,
                    exchange=getattr(tick, "exchange", ""),
                    asset_type=getattr(tick, "asset_type", "futures"),
                    local_time=getattr(tick, "local_time", None),
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=volume,
                    openinterest=openinterest,
                ),
                tick_dt,
            )
            return

        bucket_start = self._get_bucket_start(tick_dt)
        current = self._bar_builder
        if current is None:
            self._bar_builder = self._new_bar_builder(bucket_start, tick, price, volume, openinterest)
            return

        if bucket_start == current["bucket_start"]:
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price
            current["volume"] += volume
            current["openinterest"] = openinterest
            current["last_timestamp"] = float(tick.timestamp)
            return

        completed = BarEvent(
            timestamp=current["last_timestamp"],
            symbol=self._dataname,
            exchange=getattr(tick, "exchange", ""),
            asset_type=getattr(tick, "asset_type", "futures"),
            local_time=getattr(tick, "local_time", None),
            open=current["open"],
            high=current["high"],
            low=current["low"],
            close=current["close"],
            volume=current["volume"],
            openinterest=current["openinterest"],
        )
        self._enqueue_bar_event(completed, current["bucket_start"])
        self._bar_builder = self._new_bar_builder(bucket_start, tick, price, volume, openinterest)

    def _new_bar_builder(self, bucket_start, tick, price, volume, openinterest):
        """Create the mutable state for an in-progress aggregated bar."""
        return {
            "bucket_start": bucket_start,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
            "openinterest": openinterest,
            "last_timestamp": float(tick.timestamp),
        }

    def _enqueue_bar_event(self, bar_event, bar_datetime):
        """Queue a completed bar for both notify_bar and line delivery."""
        bar_event.datetime = bar_datetime
        self._dispatch_event(
            channel_type="bar",
            priority=EventPriority.BAR,
            event_data=bar_event,
        )
        self._live.append(
            {
                "datetime": bar_datetime,
                "open": bar_event.open,
                "high": bar_event.high,
                "low": bar_event.low,
                "close": bar_event.close,
                "volume": bar_event.volume,
                "openinterest": bar_event.openinterest,
            }
        )

    def _dispatch_event(self, channel_type, priority, event_data):
        """Dispatch a tick/bar event into Cerebro's channel callback surface."""
        env = getattr(self, "_env", None)
        if env is None or not hasattr(env, "dispatch_channel_event"):
            return

        env.dispatch_channel_event(
            Event(
                timestamp=float(getattr(event_data, "timestamp", 0.0) or 0.0),
                priority=priority,
                channel_type=channel_type,
                channel_name=self._dataname,
                data=event_data,
            )
        )

    def _get_bucket_start(self, dt_value):
        """Round a tick timestamp down to the current feed timeframe bucket."""
        dt_value = dt_value.replace(microsecond=0)

        if self._timeframe == TimeFrame.Seconds:
            second = (dt_value.second // self._compression) * self._compression
            return dt_value.replace(second=second)

        if self._timeframe == TimeFrame.Minutes:
            minute = (dt_value.minute // self._compression) * self._compression
            return dt_value.replace(minute=minute, second=0)

        if self._timeframe == TimeFrame.Days:
            return dt_value.replace(hour=0, minute=0, second=0)

        # Fall back to minute-style bucketing for other sub-day frames.
        return dt_value.replace(second=0)
