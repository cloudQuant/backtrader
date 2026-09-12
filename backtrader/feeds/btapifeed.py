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
from .ctpcohort import CtpCohortNow
from .livefeed import LiveFeedBase

logger = get_logger(__name__)
_LOGGING_HEALTH: "collections.Counter[str]" = collections.Counter()


def _safe_log(level, message, *args):
    """Keep a failing log sink outside feed control flow."""
    try:
        getattr(logger, level)(_redact_diagnostic(message), *map(_redact_diagnostic, args))
    except Exception:
        _LOGGING_HEALTH["logging_errors"] += 1


_UTC = _dt.timezone.utc
_CTP_INVALID_ABS = 1.0e50


def _set_tick_value(tick, name, value):
    """Set one normalized field on mapping and object event shapes."""
    if isinstance(tick, dict):
        tick[name] = value
    else:
        setattr(tick, name, value)


def _finite_market_number(value):
    """Return a finite market number, rejecting CTP's DBL_MAX-style sentinels."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or abs(number) >= _CTP_INVALID_ABS:
        return None
    return number


def _as_utc_datetime(value):
    """Parse an event-time field without silently replacing invalid source time."""
    if isinstance(value, _dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=_UTC)
        return value.astimezone(_UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return _dt.datetime.fromtimestamp(_coerce_epoch_seconds(value), _UTC)
        except (OSError, OverflowError, TypeError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        try:
            parsed = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=_UTC)
        return parsed.astimezone(_UTC)
    return None


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
    event_time = _as_utc_datetime(_tick_value(tick, "event_time_utc", default=None))
    if event_time is not None:
        return event_time.timestamp()

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
    event_time = _as_utc_datetime(_tick_value(tick, "event_time_utc", default=None))
    if event_time is not None:
        return event_time.replace(tzinfo=None)

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
        ("bar_watermark_ms", 500),
        ("event_time_max_age", 2.0),
        ("receive_time_max_age", 2.0),
        ("price_tick", None),
        ("clock", None),
        # A caller-owned, calibrated provider invoked at the synchronous
        # strategy-dispatch boundary for strict ctp.quote.v2 ticks.  It must
        # return CtpCohortNow in the event's exact monotonic clock domain.
        # There is deliberately no process-clock fallback here.
        ("ctp_decision_now_provider", None),
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
        self._bar_builders = collections.OrderedDict()
        self._bar_quality_overrides = collections.defaultdict(set)
        self._max_event_timestamp = None
        self._last_ingest_monotonic_ns = None
        self._last_closed_bucket_end = None
        self._last_connection_generation = None
        self._last_ctp_scope = None
        self._highest_ctp_scope = None
        self._bar_sequence = 0
        self._tick_consumer_claimed = False
        self._history_backfilled = bool(self._history)
        self._continuity_degraded = False
        self._session_active = False

    def start(self):
        """Start the feed, register it, and backfill if configured."""
        new_session = not self._session_active
        if new_session:
            self._live_notified = False
            self._continuity_degraded = False
        claimed_this_start = False
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

            claim = getattr(self.store, "claim_tick_consumer", None)
            if (
                callable(claim)
                and not self.p.orderbook_as_ticks
                and not self._tick_consumer_claimed
            ):
                claim(self._dataname, self)
                self._tick_consumer_claimed = True
                claimed_this_start = True
            self.store.subscribe(self._dataname)
            self._session_active = True
        except Exception:
            if claimed_this_start and self.store is not None:
                release = getattr(self.store, "release_tick_consumer", None)
                if callable(release):
                    release(self._dataname, self)
                self._tick_consumer_claimed = False
            if new_session:
                self._session_active = False
            raise

    def stop(self):
        """Stop the feed."""
        try:
            super().stop()
        finally:
            if self._tick_consumer_claimed and self.store is not None:
                release = getattr(self.store, "release_tick_consumer", None)
                if callable(release):
                    release(self._dataname, self)
            # A live partial bucket is not a completed market bar.  Clear it
            # during teardown without dispatching a synthetic notify_bar after
            # Cerebro has already stopped the strategy.
            self._bar_builders.clear()
            self._bar_builder = None
            self._bar_quality_overrides.clear()
            self._max_event_timestamp = None
            self._last_ingest_monotonic_ns = None
            self._last_closed_bucket_end = None
            self._last_connection_generation = None
            self._last_ctp_scope = None
            self._highest_ctp_scope = None
            self._tick_consumer_claimed = False
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

        # Preserve the causal pair between a completed bar callback and the
        # matching data-line advance.  Do not consume newer ticks while an
        # already completed bar is waiting for Strategy.next().
        if self._live:
            self._mark_live()
            return self._load_bar(self._live.popleft())

        if self.p.orderbook_as_ticks:
            if self._load_orderbook_tick():
                return True
            if self._qcheck > 0:
                _time.sleep(self._qcheck)
            return None

        drained_ticks = self._drain_live_ticks()
        drained_orderbooks = self._drain_live_orderbooks()
        self._flush_ready_bars(reason="load")
        # If this turn already produced a line bar, deliver it before an EOF
        # watermark is allowed to close the following bucket.
        source_exhausted = False if self._live else self._handle_source_exhaustion()

        if self._live:
            bar = self._live.popleft()
        elif self.store is not None:
            bar = self.store.poll_live(self._dataname)
        else:
            bar = None

        if bar is None:
            if source_exhausted and not self._bar_builders:
                return False
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
        if self._live:
            return  # _load must pair the queued callback with its line bar.
        drained_ticks = self._drain_live_ticks()
        drained_orderbooks = self._drain_live_orderbooks()
        self._flush_ready_bars(reason="idle")
        self._handle_source_exhaustion()
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
        """Consume ticks only until the next completed bar boundary.

        A single ``_load`` turn may inspect many ticks inside one bucket, but
        it must stop as soon as any bar event closes.  Otherwise callbacks for
        several future bars can run before the first matching data-line/next
        turn, which makes the strategy observe the final callback repeatedly.
        """
        if self.store is None or not hasattr(self.store, "poll_tick"):
            return False

        drained = False

        while True:
            bar_sequence_before = self._bar_sequence
            tick = self.store.poll_tick(self._dataname)
            if tick is None:
                break
            drained = True

            self._prepare_tick(tick)

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
            self._flush_ready_bars(reason="tick")
            if self._bar_sequence != bar_sequence_before:
                break
        return drained

    def _handle_source_exhaustion(self):
        """Finalize an explicitly finite source and report natural EOF.

        Live transports do not expose this contract and therefore continue to
        return ``None`` while idle.  Deterministic replay sources may declare
        both exhaustion and their final event-time watermark.  A missing or
        insufficient watermark invalidates any residual bucket rather than
        promoting a partial bar to executable data.
        """

        store = self.store
        exhausted = getattr(store, "is_source_exhausted", None) if store is not None else None
        if not callable(exhausted) or not exhausted(self._dataname):
            return False

        watermark_reader = getattr(store, "get_source_event_time_watermark", None)
        watermark = watermark_reader(self._dataname) if callable(watermark_reader) else None
        watermark_dt = _as_utc_datetime(watermark)
        if watermark_dt is not None:
            watermark_ts = watermark_dt.timestamp()
            if self._max_event_timestamp is None or watermark_ts > self._max_event_timestamp:
                self._max_event_timestamp = watermark_ts
                self._last_ingest_monotonic_ns = self._now_monotonic_ns()
            self._flush_ready_bars(reason="source_exhausted")

        if self._bar_builders:
            self._flush_ready_bars(reason="source_exhausted_incomplete", force_invalid=True)
        return True

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

        price = _finite_market_number(
            _tick_value(tick, "price", "last_price", "LastPrice", default=None)
        )
        if price is None or price <= 0 or not bool(_tick_value(tick, "bar_eligible", default=True)):
            return

        volume = _finite_market_number(
            _tick_value(tick, "delta_volume", "volume", "Volume", default=0.0)
        )
        if volume is None or volume <= 0:
            return
        openinterest = _finite_market_number(
            _tick_value(tick, "openinterest", "open_interest", "OpenInterest", default=0.0)
        )
        openinterest = max(openinterest or 0.0, 0.0)

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
        current = self._bar_builders.get(bucket_start)
        if current is None:
            current = self._new_bar_builder(bucket_start, tick, price, volume, openinterest)
            self._bar_builders[bucket_start] = current
            self._bar_builders.move_to_end(bucket_start)
            self._bar_builder = current
            return

        if bucket_start == current["bucket_start"]:
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price
            current["volume"] += volume
            current["openinterest"] = openinterest
            current["last_timestamp"] = tick_ts
            current["last_ingest_seq"] = _tick_value(
                tick, "ingest_seq", "sequence", default=current["last_ingest_seq"]
            )
            current["quality_flags"].update(_tick_value(tick, "quality_flags", default=()) or ())
            return

    def _new_bar_builder(self, bucket_start, tick, price, volume, openinterest):
        """Create the mutable state for an in-progress aggregated bar."""
        ingest_seq = _tick_value(tick, "ingest_seq", "sequence", default=0)
        return {
            "bucket_start": bucket_start,
            "bucket_end": self._get_bucket_end(bucket_start),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
            "openinterest": openinterest,
            "last_timestamp": _tick_timestamp(tick),
            "causal": _causal_event_kwargs(tick),
            "exchange": _tick_value(tick, "exchange", "exchange_id", "ExchangeID", default=""),
            "asset_type": _tick_value(tick, "asset_type", "assetType", default="futures"),
            "trading_day": _tick_value(tick, "trading_day", "TradingDay", default=""),
            "action_day": _tick_value(tick, "action_day", "ActionDay", default=""),
            "connection_generation": _tick_value(
                tick, "connection_generation", "stream_generation", default=None
            ),
            "first_ingest_seq": ingest_seq,
            "last_ingest_seq": ingest_seq,
            "volume_complete": bool(_tick_value(tick, "volume_complete", default=True)),
            "quality_flags": set(_tick_value(tick, "quality_flags", default=()) or ()),
        }

    def _enqueue_bar_event(self, bar_event, bar_datetime, *, deliver_lines=True):
        """Queue a completed bar for both notify_bar and line delivery."""
        bar_event.datetime = bar_datetime
        if self.p.dispatch_bars:
            self._dispatch_event(
                channel_type="bar",
                priority=EventPriority.BAR,
                event_data=bar_event,
            )
        if deliver_lines:
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

    def _now_monotonic_ns(self):
        clock = self.p.clock
        method = getattr(clock, "monotonic_ns", None) if clock is not None else None
        if callable(method):
            return int(method())
        method = getattr(clock, "monotonic_now", None) if clock is not None else None
        if callable(method):
            return int(float(method()) * 1_000_000_000)
        method = getattr(clock, "monotonic", None) if clock is not None else None
        if callable(method):
            return int(float(method()) * 1_000_000_000)
        return _time.monotonic_ns()

    def _event_time_watermark(self):
        if self._max_event_timestamp is None:
            return None
        elapsed = 0.0
        if self._last_ingest_monotonic_ns is not None:
            elapsed = (
                max(
                    self._now_monotonic_ns() - self._last_ingest_monotonic_ns,
                    0,
                )
                / 1_000_000_000.0
            )
        return self._max_event_timestamp + elapsed

    def _cached_price_tick(self):
        configured = _finite_market_number(self.p.price_tick)
        if configured is not None and configured > 0:
            return configured
        store = self.store
        metadata = getattr(store, "contract_metadata", {}) if store is not None else {}
        candidates = [self._dataname]
        text = str(self._dataname or "")
        for separator in (".", ":", "/"):
            candidates.extend(part for part in text.split(separator) if part)
        for key in candidates:
            row = metadata.get(key) if isinstance(metadata, dict) else None
            if not isinstance(row, dict):
                continue
            value = _finite_market_number(
                row.get("price_tick") or row.get("tick_size") or row.get("min_price_tick")
            )
            if value is not None and value > 0:
                return value
        return None

    @staticmethod
    def _on_price_grid(value, price_tick):
        if value is None or price_tick is None:
            return True
        scaled = value / price_tick
        return math.isfinite(scaled) and abs(scaled - round(scaled)) <= 1e-8

    def _add_bar_quality_override(self, bucket_start, *flags):
        """Retain blocking evidence only while its minute can still be built."""
        if bucket_start is None:
            return
        bucket_end = self._get_bucket_end(bucket_start)
        if self._last_closed_bucket_end is not None and bucket_end <= self._last_closed_bucket_end:
            return
        self._bar_quality_overrides[bucket_start].update(flag for flag in flags if flag)

    def _prune_bar_quality_overrides(self, watermark=None):
        """Discard override-only buckets after their watermark can no longer admit data."""
        if not self._bar_quality_overrides:
            return
        watermark = self._event_time_watermark() if watermark is None else watermark
        watermark_delay = max(float(self.p.bar_watermark_ms or 0.0), 0.0) / 1000.0
        for bucket_start in list(self._bar_quality_overrides):
            if bucket_start in self._bar_builders:
                continue
            bucket_end = self._get_bucket_end(bucket_start)
            already_closed = (
                self._last_closed_bucket_end is not None
                and bucket_end <= self._last_closed_bucket_end
            )
            deadline = bucket_end.replace(tzinfo=_UTC).timestamp() + watermark_delay
            if already_closed or (watermark is not None and deadline <= watermark):
                self._bar_quality_overrides.pop(bucket_start, None)

    def _prepare_tick(self, tick):
        """Normalize one tick's schema, quality, ordering and volume semantics."""
        schema = str(_tick_value(tick, "schema_version", default="") or "").strip()
        if not schema:
            schema = "backtrader.tick.v1"
            _set_tick_value(tick, "schema_version", schema)
            semantics = "delta"
            _set_tick_value(tick, "volume_semantics", semantics)
            legacy = True
        else:
            semantics = str(_tick_value(tick, "volume_semantics", default="") or "").strip().lower()
            legacy = False

        strict_ctp_v2 = schema == "ctp.quote.v2"
        raw_quality_flags = _tick_value(tick, "quality_flags", default=None)
        valid_quality_container = isinstance(raw_quality_flags, (list, tuple, set, frozenset))
        try:
            quality_items = tuple(raw_quality_flags or ()) if valid_quality_container else ()
        except TypeError:
            # A custom collection is allowed by the broad runtime protocol,
            # but a broken iterator must never turn into an uncaught dispatch
            # failure or a clean quote.
            quality_items = ()
            valid_quality_container = False
        valid_quality_items = all(
            isinstance(flag, str) and bool(flag) and flag.strip() == flag for flag in quality_items
        )
        if strict_ctp_v2 and (not valid_quality_container or not valid_quality_items):
            # A V2 producer must make both the evidence container and every
            # flag explicit. Do not coerce malformed input into apparently
            # clean evidence or let an unhashable/non-string item crash the
            # strategy dispatch path.
            flags = {"QUOTE_QUALITY_FLAGS_INVALID"}
        elif not valid_quality_items:
            flags = {"QUOTE_QUALITY_FLAGS_INVALID"}
        else:
            flags = set(quality_items)
        if legacy:
            flags.add("LEGACY_SCHEMA")

        if semantics in {"delta", "incremental"}:
            delta = _finite_market_number(
                _tick_value(tick, "delta_volume", "volume", "Volume", default=None)
            )
            semantics = "delta"
        elif semantics in {"cumulative", "cum", "total"}:
            # Conversion is owned by the SDK/Store. Feed never differences a
            # declared cumulative value because doing so can double-difference.
            delta = _finite_market_number(_tick_value(tick, "delta_volume", default=None))
            semantics = "cumulative"
            if delta is None:
                flags.add("DELTA_VOLUME_MISSING")
        else:
            delta = None
            flags.add("VOLUME_SEMANTICS_UNKNOWN")
        if delta is None or delta < 0:
            flags.add("DELTA_VOLUME_INVALID")
            delta = 0.0
        _set_tick_value(tick, "volume_semantics", semantics)
        _set_tick_value(tick, "delta_volume", delta)

        cumulative = _finite_market_number(
            _tick_value(tick, "cum_volume", "cumulative_volume", default=None)
        )
        if cumulative is not None:
            _set_tick_value(tick, "cum_volume", cumulative)
            _set_tick_value(tick, "cumulative_volume", cumulative)

        price = _finite_market_number(
            _tick_value(tick, "price", "last_price", "LastPrice", default=None)
        )
        bid = _finite_market_number(_tick_value(tick, "bid_price", "BidPrice1", default=None))
        ask = _finite_market_number(_tick_value(tick, "ask_price", "AskPrice1", default=None))
        bid_size = _finite_market_number(
            _tick_value(tick, "bid_volume", "bid_size", "BidVolume1", default=None)
        )
        ask_size = _finite_market_number(
            _tick_value(tick, "ask_volume", "ask_size", "AskVolume1", default=None)
        )
        ctp_schema = schema.startswith("ctp.")
        if price is None or price <= 0:
            flags.add("LAST_PRICE_INVALID")
        if ctp_schema:
            if bid is None or bid <= 0:
                flags.add("BID_PRICE_INVALID")
            if ask is None or ask <= 0:
                flags.add("ASK_PRICE_INVALID")
            if bid_size is None or bid_size < 0:
                flags.add("BID_SIZE_INVALID")
            elif bid_size == 0:
                flags.add("BID_DEPTH_ZERO")
            if ask_size is None or ask_size < 0:
                flags.add("ASK_SIZE_INVALID")
            elif ask_size == 0:
                flags.add("ASK_DEPTH_ZERO")
            if bid is not None and ask is not None and bid > ask:
                flags.add("CROSSED_BOOK")

        price_tick = self._cached_price_tick()
        if ctp_schema and price_tick is None:
            flags.add("PRICE_TICK_UNKNOWN")
        elif price_tick is not None:
            for name, value in (("LAST", price), ("BID", bid), ("ASK", ask)):
                if value is not None and value > 0 and not self._on_price_grid(value, price_tick):
                    flags.add(f"{name}_PRICE_OFF_GRID")

        upstream_execution_eligible = _tick_value(
            tick,
            "execution_eligible",
            default=None,
        )
        if strict_ctp_v2:
            # ``BtApiFeed`` is a consumer-side quality boundary, not an
            # authority that may promote a hand-built or incomplete V2 quote.
            # The SDK/Store must explicitly attest the upstream decision; this
            # Feed only keeps it false when any local gate also fails.
            if upstream_execution_eligible is not True:
                flags.add("UPSTREAM_EXECUTION_INELIGIBLE")
            if _tick_value(tick, "source_clock_quality", default="") != "verified":
                flags.add("SOURCE_CLOCK_UNVERIFIED")
            if _tick_value(tick, "receive_clock_quality", default="") != "verified":
                flags.add("RECEIVE_CLOCK_UNVERIFIED")
            if _tick_value(tick, "freshness_verified", default=False) is not True:
                flags.add("FRESHNESS_UNVERIFIED")
            if _tick_value(tick, "stale", default=None) is not False:
                flags.add("STREAM_UNREADY")
            if _tick_value(tick, "stale_reason", default=None) != "":
                flags.add("STREAM_UNREADY")
        raw_event_time = _tick_value(tick, "event_time_utc", default=None)
        if strict_ctp_v2 and raw_event_time in (None, ""):
            flags.add("EVENT_TIME_MISSING")
        event_dt = _as_utc_datetime(
            raw_event_time
            if raw_event_time not in (None, "")
            else _tick_value(tick, "timestamp", "datetime", default=None)
        )
        if event_dt is None:
            flags.add("EVENT_TIME_INVALID")
        raw_recv_time = _tick_value(tick, "recv_time_utc", default=None)
        if strict_ctp_v2 and raw_recv_time in (None, ""):
            flags.add("RECV_TIME_MISSING")
        received_wall = _as_utc_datetime(
            raw_recv_time
            if raw_recv_time not in (None, "")
            else _tick_value(tick, "received_wall_time", "local_time", default=None)
        )
        if strict_ctp_v2 and received_wall is None:
            flags.add("RECV_TIME_INVALID")
        if received_wall is not None and event_dt is not None:
            event_age = (received_wall - event_dt).total_seconds()
            _set_tick_value(tick, "event_age_seconds", event_age)
            maximum = max(float(self.p.event_time_max_age or 0.0), 0.0)
            if ctp_schema and (event_age < -0.5 or (maximum and event_age > maximum)):
                flags.add("EVENT_TIME_STALE")

        raw_recv_mono = _tick_value(tick, "recv_monotonic_ns", default=None)
        if strict_ctp_v2 and raw_recv_mono in (None, ""):
            flags.add("RECV_MONOTONIC_MISSING")
        recv_mono = (
            raw_recv_mono
            if raw_recv_mono not in (None, "")
            else _tick_value(tick, "received_monotonic_ns", default=None)
        )
        if isinstance(recv_mono, int) and recv_mono > 0:
            recv_age = max(self._now_monotonic_ns() - recv_mono, 0) / 1_000_000_000.0
            _set_tick_value(tick, "recv_age_seconds", recv_age)
            maximum = max(float(self.p.receive_time_max_age or 0.0), 0.0)
            if ctp_schema and maximum and recv_age > maximum:
                flags.add("RECEIVE_TIME_STALE")
        elif strict_ctp_v2:
            flags.add("RECV_MONOTONIC_INVALID")

        tick_ts = event_dt.timestamp() if event_dt is not None else None
        raw_timestamp = _finite_market_number(
            _tick_value(tick, "timestamp", "Timestamp", default=None)
        )
        if strict_ctp_v2 and event_dt is not None and raw_timestamp is not None:
            raw_timestamp = _coerce_epoch_seconds(raw_timestamp)
            if abs(raw_timestamp - tick_ts) > 1.0e-6:
                flags.add("EVENT_TIME_CONFLICT")
        prior_watermark = self._event_time_watermark()
        bucket_start = (
            self._get_bucket_start(event_dt.replace(tzinfo=None)) if event_dt is not None else None
        )
        bucket_end = self._get_bucket_end(bucket_start) if bucket_start is not None else None
        bucket_end_ts = (
            bucket_end.replace(tzinfo=_UTC).timestamp() if bucket_end is not None else None
        )
        watermark_delay = max(float(self.p.bar_watermark_ms or 0.0), 0.0) / 1000.0
        if (
            self._timeframe != TimeFrame.Ticks
            and prior_watermark is not None
            and bucket_end_ts is not None
            and bucket_end_ts + watermark_delay <= prior_watermark
        ):
            flags.add("LATE_AFTER_WATERMARK")
        elif (
            self._max_event_timestamp is not None
            and tick_ts is not None
            and tick_ts < self._max_event_timestamp
        ):
            flags.add("OUT_OF_ORDER_EVENT_TIME")
            if delta > 0:
                flags.add("ORDERING_VOLUME_GAP")
                if bucket_start is not None:
                    self._add_bar_quality_override(bucket_start, "ORDERING_VOLUME_GAP")
                current_start = self._get_bucket_start(
                    _dt.datetime.fromtimestamp(self._max_event_timestamp, _UTC).replace(tzinfo=None)
                )
                self._add_bar_quality_override(current_start, "ORDERING_VOLUME_GAP")

        generation = _tick_value(tick, "connection_generation", "stream_generation", default=None)
        subscription_epoch = _tick_value(tick, "subscription_epoch", default=None)
        retired_ctp_scope = False
        if strict_ctp_v2:
            scope_is_valid = (
                type(generation) is int
                and generation > 0
                and type(subscription_epoch) is int
                and subscription_epoch > 0
            )
            if not scope_is_valid:
                flags.add("CTP_SCOPE_INVALID")
            else:
                scope = (generation, subscription_epoch)
                if self._highest_ctp_scope is not None and scope < self._highest_ctp_scope:
                    # A delayed callback from an old connection/subscribe
                    # scope must not reopen a retired stream after a newer
                    # scope has been observed. In particular, `(8, 1)` is
                    # newer than `(7, 99)` because generation dominates.
                    flags.add("RETIRED_CONNECTION_SCOPE")
                    retired_ctp_scope = True
                elif self._highest_ctp_scope is not None and scope != self._highest_ctp_scope:
                    for builder in self._bar_builders.values():
                        builder["quality_flags"].add(
                            (
                                "CONNECTION_GENERATION_CHANGED"
                                if generation != self._highest_ctp_scope[0]
                                else "SUBSCRIPTION_EPOCH_CHANGED"
                            )
                        )
                    self._flush_ready_bars(
                        reason=(
                            "generation"
                            if generation != self._highest_ctp_scope[0]
                            else "subscription_epoch"
                        ),
                        force_invalid=True,
                    )
                    self._max_event_timestamp = None
                    flags.add(
                        (
                            "CONNECTION_GENERATION_CHANGED"
                            if generation != self._highest_ctp_scope[0]
                            else "SUBSCRIPTION_EPOCH_CHANGED"
                        )
                    )
                    self._add_bar_quality_override(
                        bucket_start,
                        (
                            "CONNECTION_GENERATION_CHANGED"
                            if generation != self._highest_ctp_scope[0]
                            else "SUBSCRIPTION_EPOCH_CHANGED"
                        ),
                    )
                if not retired_ctp_scope:
                    self._highest_ctp_scope = scope
                    self._last_ctp_scope = scope
                    self._last_connection_generation = generation
        elif generation not in (None, ""):
            if (
                self._last_connection_generation is not None
                and generation != self._last_connection_generation
            ):
                for builder in self._bar_builders.values():
                    builder["quality_flags"].add("CONNECTION_GENERATION_CHANGED")
                self._flush_ready_bars(reason="generation", force_invalid=True)
                self._max_event_timestamp = None
                flags.add("CONNECTION_GENERATION_CHANGED")
                self._add_bar_quality_override(bucket_start, "CONNECTION_GENERATION_CHANGED")
            self._last_connection_generation = generation

        if (
            self._timeframe != TimeFrame.Ticks
            and bucket_end is not None
            and self._last_closed_bucket_end is not None
            and bucket_end <= self._last_closed_bucket_end
        ):
            flags.add("BUCKET_ALREADY_CLOSED")

        if tick_ts is not None and "EVENT_TIME_CONFLICT" not in flags and not retired_ctp_scope:
            if self._max_event_timestamp is None or tick_ts >= self._max_event_timestamp:
                self._max_event_timestamp = tick_ts
            self._last_ingest_monotonic_ns = self._now_monotonic_ns()

        blocking = {
            flag
            for flag in flags
            if flag
            not in {
                "LEGACY_SCHEMA",
                "NO_TRADE",
                "VOLUME_BASELINE",
            }
        }
        volume_complete = bool(_tick_value(tick, "volume_complete", default=not ctp_schema))
        if ctp_schema and not volume_complete and delta > 0:
            blocking.add("VOLUME_INCOMPLETE")
            flags.add("VOLUME_INCOMPLETE")
        # A rejected snapshot can still prove that an already-open bucket is
        # incomplete. Preserve that evidence before _ingest_tick declines to
        # mutate OHLCV. Otherwise a later watermark could publish the earlier
        # trades as a deceptively complete bar after a volume/order/time gap.
        if bucket_start is not None and blocking:
            already_closed = (
                self._last_closed_bucket_end is not None
                and bucket_end is not None
                and bucket_end <= self._last_closed_bucket_end
            )
            if not already_closed:
                self._add_bar_quality_override(bucket_start, *blocking)
        execution_eligible = (
            (not strict_ctp_v2 or upstream_execution_eligible is True)
            and not blocking
            and all(value is not None and value > 0 for value in (bid, ask, bid_size, ask_size))
        )
        bar_eligible = not blocking and price is not None and price > 0 and delta > 0
        _set_tick_value(tick, "quality_flags", tuple(sorted(flags)))
        _set_tick_value(tick, "quality", "GOOD" if not blocking else "INVALID")
        _set_tick_value(tick, "execution_eligible", execution_eligible)
        _set_tick_value(tick, "bar_eligible", bar_eligible)
        self._prune_bar_quality_overrides()

    def _flush_ready_bars(self, *, reason, force_invalid=False):
        """Close trade-backed buckets once the event-time watermark has passed."""
        watermark = self._event_time_watermark()
        if not self._bar_builders:
            self._prune_bar_quality_overrides(watermark)
            return 0
        watermark_delay = max(float(self.p.bar_watermark_ms or 0.0), 0.0) / 1000.0
        closed = 0
        for bucket_start in sorted(self._bar_builders):
            current = self._bar_builders[bucket_start]
            bucket_end = current["bucket_end"]
            deadline = bucket_end.replace(tzinfo=_UTC).timestamp() + watermark_delay
            if not force_invalid and (watermark is None or watermark < deadline):
                continue
            flags = set(current["quality_flags"])
            flags.update(self._bar_quality_overrides.pop(bucket_start, set()))
            if force_invalid:
                flags.add("FORCED_INVALIDATION")
            complete = bool(current["volume_complete"] and not flags.difference({"LEGACY_SCHEMA"}))
            available_ts = max(deadline, watermark or deadline)
            available_at = _dt.datetime.fromtimestamp(available_ts, _UTC)
            self._bar_sequence += 1
            first_seq = current["first_ingest_seq"]
            last_seq = current["last_ingest_seq"]
            generation = current["connection_generation"]
            bar_id = (
                f"{self._dataname}:{bucket_start.isoformat()}:{generation}:"
                f"{first_seq}-{last_seq}"
            )
            completed = BarEvent(
                timestamp=bucket_end.replace(tzinfo=_UTC).timestamp(),
                symbol=self._dataname,
                exchange=current["exchange"],
                asset_type=current["asset_type"],
                local_time=available_ts,
                **current["causal"],
                open=current["open"],
                high=current["high"],
                low=current["low"],
                close=current["close"],
                volume=current["volume"],
                openinterest=current["openinterest"],
            )
            extensions = {
                "bucket_start": bucket_start.replace(tzinfo=_UTC),
                "bucket_end": bucket_end.replace(tzinfo=_UTC),
                "closed_at": available_at,
                "available_at": available_at,
                "bar_available_at": available_at,
                "complete": complete,
                "quality": "GOOD" if complete else "INVALID",
                "quality_flags": tuple(sorted(flags)),
                "volume_complete": bool(current["volume_complete"]),
                "first_ingest_seq": first_seq,
                "last_ingest_seq": last_seq,
                "trading_day": current["trading_day"],
                "action_day": current["action_day"],
                "connection_generation": generation,
                "bar_id": bar_id,
                "decision_version": bar_id,
                "closure_reason": reason,
                "bar_sequence": self._bar_sequence,
            }
            for name, value in extensions.items():
                setattr(completed, name, value)
            self._enqueue_bar_event(completed, bucket_start, deliver_lines=complete)
            del self._bar_builders[bucket_start]
            self._last_closed_bucket_end = bucket_end
            closed += 1
        self._bar_builder = next(reversed(self._bar_builders.values()), None)
        self._prune_bar_quality_overrides(watermark)
        return closed

    def _dispatch_event(self, channel_type, priority, event_data):
        """Dispatch a tick/bar event into Cerebro's channel callback surface."""
        env = getattr(self, "_env", None)
        if env is None or not hasattr(env, "dispatch_channel_event"):
            self._mark_event_dropped(event_data, "strategy_dispatch_unavailable")
            return False

        if channel_type == "tick":
            self._attach_ctp_decision_now(event_data)

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

    def _attach_ctp_decision_now(self, tick):
        """Attach caller-owned decision-boundary time to a strict CTP V2 tick.

        Parent receipt time is useful evidence but cannot measure time spent
        in the Store/Feed path.  A live caller must explicitly provide a
        calibrated same-domain provider; raw tick fields never supply this
        boundary.  Replay code can provide its own deterministic evidence
        without involving this Feed.
        """

        if _tick_value(tick, "schema_version", default=None) != "ctp.quote.v2":
            return
        decision_fields = (
            "cohort_decision_now_monotonic_ns",
            "cohort_decision_now_epoch",
            "cohort_decision_now_clock_domain_id",
            "cohort_decision_now_receive_clock_error_ms",
            "cohort_decision_now_receive_clock_quality",
            "cohort_decision_now_freshness_verified",
        )
        # These fields belong to this dispatch boundary.  A raw transport
        # payload must never pre-populate them and masquerade as a later local
        # decision timestamp.
        for name in decision_fields:
            _set_tick_value(tick, name, None)
        provider = self.p.ctp_decision_now_provider
        if not callable(provider):
            return
        try:
            now = provider(tick)
        except Exception:
            return
        if not isinstance(now, CtpCohortNow):
            return
        if now.clock_domain_id != _tick_value(tick, "clock_domain_id", default=None):
            return
        for name, value in (
            ("cohort_decision_now_monotonic_ns", now.now_monotonic_ns),
            ("cohort_decision_now_epoch", now.now_epoch),
            ("cohort_decision_now_clock_domain_id", now.clock_domain_id),
            ("cohort_decision_now_receive_clock_error_ms", now.receive_clock_error_ms),
            ("cohort_decision_now_receive_clock_quality", now.receive_clock_quality),
            ("cohort_decision_now_freshness_verified", now.freshness_verified),
        ):
            _set_tick_value(tick, name, value)

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
            "invalid",
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

    def _get_bucket_end(self, bucket_start):
        """Return the exclusive right edge for a feed bucket."""
        if self._timeframe == TimeFrame.Ticks:
            return bucket_start
        if self._timeframe == TimeFrame.Seconds:
            return bucket_start + _dt.timedelta(seconds=self._compression)
        if self._timeframe == TimeFrame.Minutes:
            return bucket_start + _dt.timedelta(minutes=self._compression)
        if self._timeframe == TimeFrame.Days:
            return bucket_start + _dt.timedelta(days=self._compression)
        return bucket_start + _dt.timedelta(minutes=self._compression)
