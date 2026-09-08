#!/usr/bin/env python
"""Unified bt_api_py-backed live data feed."""

from __future__ import annotations

import collections
import datetime as _dt
import math
import time as _time

from ..channel import Event, EventPriority
from ..dataseries import TimeFrame
from ..events import BarEvent
from ..feed import DataBase
from ..stores.btapistore import _normalize_bar, _redact_diagnostic
from ..utils import date2num
from ..utils.log_message import get_logger
from .livefeed import LiveFeedBase

logger = get_logger(__name__)
_LOGGING_HEALTH = collections.Counter()


def _safe_log(level, message, *args):
    """Keep a failing log sink outside feed control flow."""
    try:
        getattr(logger, level)(_redact_diagnostic(message), *map(_redact_diagnostic, args))
    except Exception:
        _LOGGING_HEALTH["logging_errors"] += 1


_UTC = _dt.timezone.utc


def _coerce_epoch_seconds(value):
    ts = float(value)
    if ts > 10_000_000_000:
        ts /= 1000.0
    return ts


def _datetime_to_utc_naive(value):
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(_UTC).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def _datetime_to_timestamp(value):
    return _datetime_to_utc_naive(value).replace(tzinfo=_UTC).timestamp()


def _tick_value(tick, *names, default=None):
    if isinstance(tick, dict):
        for name in names:
            if name in tick and tick[name] is not None:
                return tick[name]
        return default

    for name in names:
        value = getattr(tick, name, None)
        if value is not None:
            return value
    return default


def _tick_timestamp(tick):
    value = _tick_value(tick, "timestamp", "Timestamp", default=None)
    if value is not None:
        return _coerce_epoch_seconds(value)

    dt_value = _tick_value(tick, "datetime", "dt", default=None)
    if isinstance(dt_value, _dt.datetime):
        return _datetime_to_timestamp(dt_value)
    if isinstance(dt_value, str) and dt_value:
        try:
            return _datetime_to_timestamp(
                _dt.datetime.fromisoformat(dt_value.replace("Z", "+00:00"))
            )
        except ValueError:
            pass

    return _coerce_epoch_seconds(_tick_value(tick, "local_time", "LocalTime", default=0.0) or 0.0)


def _tick_datetime(tick):
    timestamp_value = _tick_value(tick, "timestamp", "Timestamp", default=None)
    if timestamp_value not in (None, ""):
        try:
            ts = _coerce_epoch_seconds(timestamp_value)
        except (TypeError, ValueError):
            pass
        else:
            if ts > 0:
                return _dt.datetime.fromtimestamp(ts, _UTC).replace(tzinfo=None)

    value = _tick_value(tick, "datetime", "dt", default=None)
    if isinstance(value, _dt.datetime):
        return _datetime_to_utc_naive(value)
    if isinstance(value, str) and value:
        try:
            return _datetime_to_utc_naive(_dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
    return _dt.datetime.fromtimestamp(_tick_timestamp(tick), _UTC).replace(tzinfo=None)


def _causal_event_kwargs(event):
    """Copy standard timing and identity fields into derived events."""
    return {
        key: _tick_value(event, key, default=None)
        for key in (
            "exchange_time",
            "received_wall_time",
            "received_monotonic_ns",
            "clock_domain_id",
            "sequence",
            "previous_sequence",
            "snapshot_or_delta",
            "continuity_status",
            "stale",
            "stale_reason",
            "source",
            "event_id",
            "coalesced_count",
        )
        if _tick_value(event, key, default=None) is not None
    }


class BtApiFeed(DataBase, LiveFeedBase):
    """Data feed that backfills and streams bars through BtApiStore.

    ``orderbook_as_ticks=True`` exposes each depth snapshot as a zero-volume
    midpoint tick bar before calling ``notify_orderbook``. This gives native
    broker orders a valid feed price and clock even without trade/bar streams.
    It requires ``timeframe=TimeFrame.Ticks``.
    """

    params = (
        ("store", None),
        ("provider", "btapi"),
        ("historical_bars", None),
        ("live_bars", None),
        ("backfill_start", True),
        ("dispatch_ticks", True),
        ("dispatch_orderbooks", True),
        ("dispatch_bars", True),
        ("orderbook_as_ticks", False),
    )

    def __init__(self, *args, **kwargs):
        """Initialize the feed, normalize inputs, and prepare internal state.

        The constructor performs three pieces of work:

        1. Resolves the :class:`BtApiStore` instance and the data provider
           tag from the parsed parameters and stashes them on the instance
           for quick access during :meth:`start` / :meth:`_load`.
        2. Normalizes the optional pre-supplied ``historical_bars`` and
           ``live_bars`` parameters into :class:`collections.deque`
           instances so that :meth:`_load` can ``popleft`` from them in O(1).
        3. Initializes the runtime flags that govern backfill behavior
           (``_history_backfilled``) and bar aggregation
           (``_bar_builder``).

        Args:
            *args: Positional arguments forwarded to the
                :class:`backtrader.feed.DataBase` constructor. Typically
                this is just the ``dataname`` (symbol/contract identifier).
            **kwargs: Parameter overrides. Any key matching a name in
                :attr:`params` overrides the corresponding default; unknown
                keys are forwarded to the base class unchanged.
        """
        super().__init__(*args, **kwargs)
        self.store = self.p.store
        self.provider = self.p.provider
        self._history = collections.deque(
            _normalize_bar(bar) for bar in (self.p.historical_bars or [])
        )
        self._live = collections.deque(_normalize_bar(bar) for bar in (self.p.live_bars or []))
        self._live_notified = False
        self._bar_builder = None
        self._history_backfilled = bool(self._history)
        self._continuity_degraded = False
        self._session_active = False

    def start(self):
        """Start the feed, register it, and backfill if configured."""
        new_session = not self._session_active
        if new_session:
            self._live_notified = False
            self._continuity_degraded = False
        try:
            super().start()
            if self.p.orderbook_as_ticks and self._timeframe != TimeFrame.Ticks:
                raise ValueError("orderbook_as_ticks requires timeframe=TimeFrame.Ticks")

            if self.store is None:
                self.store = getattr(self, "_store", None)

            if self.store is None:
                self._session_active = True
                return

            self.store.start(data=self)
            self.store.register(self)

            if self.p.backfill_start and not self._history and not self._history_backfilled:
                try:
                    bars = self.store.fetch_history(
                        self._dataname,
                        timeframe=self._timeframe,
                        compression=self._compression,
                    )
                    self._history.extend(bars)
                    self._history_backfilled = True
                except Exception as e:
                    _safe_log("debug", "Failed to backfill history: %s", e)

            self.store.subscribe(self._dataname)
            self._session_active = True
        except Exception:
            if new_session:
                self._session_active = False
            raise

    def stop(self):
        """Stop the feed."""
        try:
            super().stop()
        finally:
            self._session_active = False

    def islive(self) -> bool:
        """Return whether this feed has a configured live data source."""
        dataname = getattr(self, "_dataname", None)

        if self._live:
            return True

        store = self.store or getattr(self, "_store", None)
        if store is None:
            return bool(self.p.live_bars)

        # Cerebro queries islive before Store.start. A public BtApi event
        # source is live without the legacy supports_live_* duck protocol.
        if getattr(store, "_sdk_mode", False):
            return True

        live_cache = getattr(store, "_live_bars", {})
        if dataname is not None and live_cache.get(dataname):
            return True

        api = getattr(store, "_api", None)
        if api is not None and dataname is not None:
            api_live = self._api_indicates_live(api, dataname)
            if api_live is not None:
                return api_live

        if getattr(store, "_api_cls", None) is not None:
            return True

        if api is None:
            return True

        return False

    @staticmethod
    def _api_indicates_live(api, dataname):
        """Whether the store API reports a live source for ``dataname``.

        Returns True/False when the API gives a definitive answer, or None when
        it has no opinion (caller falls through to other heuristics). Extracted
        from islive() to flatten the repeated supports_live_* probes.
        """
        for capability in (
            "supports_live_streaming",
            "supports_live_ticks",
            "supports_live_orderbook",
        ):
            if hasattr(api, capability):
                try:
                    if bool(getattr(api, capability)(dataname)):
                        return True
                except Exception as e:
                    _safe_log("debug", "%s check failed: %s", capability, e)

        live_ticks = getattr(api, "live_ticks", None)
        if live_ticks is not None:
            return dataname in live_ticks

        live_orderbooks = getattr(api, "live_orderbooks", None)
        if live_orderbooks is not None:
            return dataname in live_orderbooks

        live_bars = getattr(api, "live", None)
        if live_bars is not None:
            return dataname in live_bars

        return None

    def haslivedata(self) -> bool:
        """Return whether a completed live bar is immediately available.

        Pending raw ticks/orderbooks are realtime traffic, but they do not
        advance the strategy clock until they aggregate into a completed bar.
        Treating them as live data here makes Cerebro skip qcheck and spin while
        repeatedly draining ticks that produce no bar.
        """
        if self._live:
            return True

        store = self.store or getattr(self, "_store", None)
        if store is None:
            return False

        live_cache = getattr(store, "_live_bars", {})
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

        if self.p.orderbook_as_ticks:
            if self._load_orderbook_tick():
                return True
            if self._qcheck > 0:
                _time.sleep(self._qcheck)
            return None

        drained_ticks = self._drain_live_ticks()
        drained_orderbooks = self._drain_live_orderbooks()

        if self._live:
            bar = self._live.popleft()
        elif self.store is not None:
            bar = self.store.poll_live(self._dataname)
        else:
            bar = None

        if bar is None:
            if drained_ticks or drained_orderbooks:
                self._mark_live()
            if self._qcheck > 0:
                _time.sleep(self._qcheck)
            return None

        self._mark_live()

        return self._load_bar(bar)

    def _check(self, forcedata=None):
        """Drain live ticks while waiting for the next completed bar."""
        super()._check(forcedata=forcedata)
        if self.p.orderbook_as_ticks:
            return  # _load must establish the feed clock before the callback.
        drained_ticks = self._drain_live_ticks()
        drained_orderbooks = self._drain_live_orderbooks()
        if not self._history and (drained_ticks or drained_orderbooks):
            self._mark_live()

    def _load_orderbook_tick(self):
        """Load one snapshot per turn so neither another venue nor the broker starves."""
        if self.store is None:
            return False
        orderbook = self.store.poll_orderbook(self._dataname)
        if orderbook is None:
            return False
        if self._handle_event_health(orderbook):
            if self.p.dispatch_orderbooks:
                self._dispatch_event("orderbook", EventPriority.ORDERBOOK, orderbook)
            else:
                self._mark_event_dropped(orderbook, "orderbook_dispatch_disabled")
            return False
        bids = _tick_value(orderbook, "bids", default=[]) or []
        asks = _tick_value(orderbook, "asks", default=[]) or []
        if not bids or not asks:
            self._mark_event_dropped(orderbook, "orderbook_missing_top_of_book")
            return False
        bid, ask = float(bids[0][0]), float(asks[0][0])
        if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask < bid:
            self._mark_event_dropped(orderbook, "orderbook_invalid_top_of_book")
            return False
        midpoint = (bid + ask) / 2.0
        stamp = _tick_timestamp(orderbook)
        bar = BarEvent(
            timestamp=stamp,
            symbol=self._dataname,
            exchange=_tick_value(orderbook, "exchange", default=""),
            asset_type=_tick_value(orderbook, "asset_type", default="futures"),
            local_time=_tick_value(orderbook, "local_time", default=stamp),
            **_causal_event_kwargs(orderbook),
            open=midpoint,
            high=midpoint,
            low=midpoint,
            close=midpoint,
            volume=0.0,
        )
        self._load_bar(
            {
                "datetime": _tick_datetime(orderbook),
                "open": midpoint,
                "high": midpoint,
                "low": midpoint,
                "close": midpoint,
                "volume": 0.0,
                "openinterest": 0.0,
            }
        )
        self._mark_live()
        if self.p.dispatch_orderbooks:
            self._dispatch_event("orderbook", EventPriority.ORDERBOOK, orderbook)
        else:
            self._mark_event_dropped(orderbook, "orderbook_dispatch_disabled")
        if self.p.dispatch_bars:
            self._dispatch_event("bar", EventPriority.BAR, bar)
        return True

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
            return False

        drained = False

        while True:
            tick = self.store.poll_tick(self._dataname)
            if tick is None:
                break
            drained = True

            if self._handle_event_health(tick):
                if self.p.dispatch_ticks:
                    self._dispatch_event(
                        channel_type="tick",
                        priority=EventPriority.TICK,
                        event_data=tick,
                    )
                else:
                    self._mark_event_dropped(tick, "tick_dispatch_disabled")
                continue

            if self.p.dispatch_ticks:
                self._dispatch_event(
                    channel_type="tick",
                    priority=EventPriority.TICK,
                    event_data=tick,
                )
            else:
                self._mark_event_dropped(tick, "tick_dispatch_disabled")
            self._ingest_tick(tick)
        return drained

    def _drain_live_orderbooks(self):
        if self.store is None or not hasattr(self.store, "poll_orderbook"):
            return False

        drained = False

        while True:
            orderbook = self.store.poll_orderbook(self._dataname)
            if orderbook is None:
                break
            drained = True

            self._handle_event_health(orderbook)

            if self.p.dispatch_orderbooks:
                self._dispatch_event(
                    channel_type="orderbook",
                    priority=EventPriority.ORDERBOOK,
                    event_data=orderbook,
                )
            else:
                self._mark_event_dropped(orderbook, "orderbook_dispatch_disabled")
        return drained

    def _ingest_tick(self, tick):
        """Update the current bar builder from a live tick."""
        tick_dt = _tick_datetime(tick)
        tick_ts = _tick_timestamp(tick)

        price = float(_tick_value(tick, "price", "last_price", "LastPrice", default=0.0) or 0.0)
        if price <= 0:
            return

        volume = float(_tick_value(tick, "volume", "Volume", default=0.0) or 0.0)
        openinterest = float(
            _tick_value(tick, "openinterest", "open_interest", "OpenInterest", default=0.0) or 0.0
        )

        if self._timeframe == TimeFrame.Ticks:
            self._enqueue_bar_event(
                BarEvent(
                    timestamp=tick_ts,
                    symbol=self._dataname,
                    exchange=_tick_value(tick, "exchange", "exchange_id", "ExchangeID", default=""),
                    asset_type=_tick_value(tick, "asset_type", "assetType", default="futures"),
                    local_time=_tick_value(tick, "local_time", "LocalTime", default=None),
                    **_causal_event_kwargs(tick),
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
            self._bar_builder = self._new_bar_builder(
                bucket_start, tick, price, volume, openinterest
            )
            return

        if bucket_start == current["bucket_start"]:
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price
            current["volume"] += volume
            current["openinterest"] = openinterest
            current["last_timestamp"] = tick_ts
            return

        completed = BarEvent(
            timestamp=current["last_timestamp"],
            symbol=self._dataname,
            exchange=_tick_value(tick, "exchange", "exchange_id", "ExchangeID", default=""),
            asset_type=_tick_value(tick, "asset_type", "assetType", default="futures"),
            local_time=_tick_value(tick, "local_time", "LocalTime", default=None),
            **current["causal"],
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
            "last_timestamp": _tick_timestamp(tick),
            "causal": _causal_event_kwargs(tick),
        }

    def _enqueue_bar_event(self, bar_event, bar_datetime):
        """Queue a completed bar for both notify_bar and line delivery."""
        bar_event.datetime = bar_datetime
        if self.p.dispatch_bars:
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
            self._mark_event_dropped(event_data, "strategy_dispatch_unavailable")
            return False

        event = Event(
            timestamp=_tick_timestamp(event_data),
            priority=priority,
            channel_type=channel_type,
            channel_name=self._dataname,
            data=event_data,
        )
        # Only feed-origin events carry this private reference. Channel queues
        # already drive the matching broker in their own event loop.
        event._source_feed = self
        try:
            env.dispatch_channel_event(event)
        except Exception:
            self._mark_event_dropped(event_data, "strategy_dispatch_failed")
            raise
        if self.store is not None and hasattr(self.store, "mark_strategy_delivered"):
            self.store.mark_strategy_delivered(event_data)
        return True

    def _mark_event_dropped(self, event_data, reason):
        """Close Store conservation accounting for an undispatched feed event."""
        marker = getattr(self.store, "mark_feed_dropped", None)
        if callable(marker):
            marker(event_data, reason)

    def _handle_event_health(self, event_data):
        """Emit feed status transitions and tell callers whether data is unsafe."""
        stale = bool(_tick_value(event_data, "stale", default=False))
        continuity = str(
            _tick_value(event_data, "continuity_status", "continuity", default="unknown")
            or "unknown"
        ).lower()
        unhealthy = stale or continuity in {
            "gap",
            "stale",
            "disconnected",
            "checksum_failed",
            "out_of_order",
        }
        if unhealthy:
            if not self._continuity_degraded:
                self.put_notification(
                    self.DELAYED,
                    stale_reason=_tick_value(
                        event_data, "stale_reason", default=continuity or "stale"
                    ),
                    event_id=_tick_value(event_data, "event_id", default=""),
                )
                # A later verified recovery is a fresh LIVE transition.
                self._live_notified = False
            self._continuity_degraded = True
            return True
        if self._continuity_degraded and continuity in {
            "ok",
            "continuous",
            "recovered",
            "snapshot",
        }:
            self._continuity_degraded = False
            self._mark_live()
        return False

    def get_logging_health(self):
        """Return the number of feed log-sink failures observed in this process."""
        return dict(_LOGGING_HEALTH)

    def _mark_live(self):
        """Emit the LIVE status exactly once when real-time traffic begins."""
        if self._continuity_degraded:
            return
        if not self._live_notified:
            self.put_notification(self.LIVE)
            self._live_notified = True

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
