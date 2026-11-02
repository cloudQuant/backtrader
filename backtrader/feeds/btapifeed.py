#!/usr/bin/env python
"""Unified bt_api_py-backed live data feed."""

from __future__ import annotations

import collections
from collections.abc import Mapping
import copy
import datetime as _dt
import math
import time as _time
from types import MappingProxyType, SimpleNamespace

from ..channel import Event, EventPriority
from ..dataseries import TimeFrame
from ..events import BarEvent
from ..feed import DataBase
from ..utils.bar_projection import normalize_bar as _normalize_bar
from ..utils.redaction import redact_diagnostic as _redact_diagnostic
from ..utils import date2num
from ..utils.log_message import get_logger
from .barrier import BarEvidence
from .market_cohort import MarketCohortNow
from .livefeed import LiveFeedBase
from .market_tick_adapter import (
    MarketTickAdapterError,
    adapt_market_tick_event,
)
from .service_recovery_quotes import ServiceRecoveryQuoteBindingMixin
from ._btapi_cohort import (
    LiveBarCohortFeedMixin,
    _COHORT_MISSING,
    _LIVE_COHORT_EXTRA_LINES,
    _tick_value,
)

logger = get_logger(__name__)
_LOGGING_HEALTH: "collections.Counter[str]" = collections.Counter()


def _safe_log(level, message, *args):
    """Keep a failing log sink outside feed control flow."""
    try:
        getattr(logger, level)(_redact_diagnostic(message), *map(_redact_diagnostic, args))
    except Exception:
        # The sink itself failed. Calling it again would escape this guard
        # before its health counter is incremented and disrupt feed callbacks.
        _LOGGING_HEALTH["logging_errors"] += 1


_UTC = _dt.timezone.utc
_TICK_PRICE_FIELDS = ("price", "last_price")
_MAX_DIAGNOSTIC_TEXT = 128


def _bounded_context_value(value):
    """Keep diagnostic identifiers finite without retaining arbitrary objects."""
    if type(value) is str:
        return value[:_MAX_DIAGNOSTIC_TEXT]
    if type(value) is int and -(2**63) <= value < 2**63:
        return value
    return None


def _set_tick_value(tick, name, value):
    """Set one normalized field on mapping and object event shapes."""
    if isinstance(tick, dict):
        tick[name] = value
    else:
        setattr(tick, name, value)


def _finite_market_number(value):
    """Delegate neutral number normalization to the SDK market contract."""
    from bt_api_py.market_tick_contracts import finite_market_number

    return finite_market_number(value)


def _as_utc_datetime(value):
    """Parse an event-time field without silently replacing invalid source time."""
    from bt_api_py.market_tick_contracts import parse_market_event_datetime

    return parse_market_event_datetime(value)


def _tick_timestamp(tick):
    from bt_api_py.market_tick_contracts import market_event_timestamp

    return market_event_timestamp(tick, on_invalid_datetime=_log_invalid_market_datetime)


def _tick_datetime(tick):
    from bt_api_py.market_tick_contracts import market_event_utc_naive_datetime

    return market_event_utc_naive_datetime(tick, on_invalid_datetime=_log_invalid_market_datetime)


def _log_invalid_market_datetime(reason):
    messages = {
        "timestamp_datetime": "btapifeed:132 ignored ValueError",
        "datetime_timestamp": "btapifeed:147 ignored TypeError,ValueError",
        "datetime_datetime": "btapifeed:159 ignored ValueError",
    }
    _safe_log("debug", messages[reason])


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


class BtApiFeed(LiveBarCohortFeedMixin, ServiceRecoveryQuoteBindingMixin, DataBase, LiveFeedBase):
    """Data feed that backfills and streams bars through BtApiStore.

    ``orderbook_as_ticks=True`` exposes each depth snapshot as a zero-volume
    midpoint tick bar before calling ``notify_orderbook``. This gives native
    broker orders a valid feed price and clock even without trade/bar streams.
    It requires ``timeframe=TimeFrame.Ticks`` for legacy non-SDK adapters.
    SDK order-book events retain their unknown clock/freshness and are delivered
    only to notification callbacks; they never create midpoint bars.
    """

    # These fixed numeric slots are used by the opt-in research cohort path.
    # They remain NaN unless the exact registered member maps each field to a
    # validated raw numeric field. Ordinary feeds keep their historical loader.
    lines = _LIVE_COHORT_EXTRA_LINES

    params = (
        ("store", None),
        ("provider", "btapi"),
        ("replay_market_tick_port", None),
        ("historical_bars", None),
        ("live_bars", None),
        # Explicit cohort mode keeps saved source events raw until the cohort
        # validates them. Ordinary feeds retain their historical tolerant
        # normalization path.
        ("cohort_source_mode", False),
        # Optional SDK-resolved factor source binding. Kept out of ordinary
        # imports and behavior unless the caller explicitly supplies it.
        ("market_factor_source_binding", None),
        # Adapter-authored origin claim; cohort matching does not prove exchange completeness.
        ("cohort_source_origin", None),
        ("backfill_start", True),
        ("dispatch_ticks", True),
        ("dispatch_orderbooks", True),
        ("dispatch_bars", True),
        ("orderbook_as_ticks", False),
        ("market_channels", None),
        ("orderbook_depth", None),
        ("bar_watermark_ms", 500),
        ("event_time_max_age", 2.0),
        ("receive_time_max_age", 2.0),
        ("price_tick", None),
        ("clock", None),
        # Optional bounded per-bucket quote capture for the strict options
        # adapters: each prepared tick inside a bucket is frozen (with its
        # stamped provenance) onto the sealed bar event's ``quote_events`` so
        # examples can build minute quote windows without inventing them.
        # Default off; overflow drops the oldest record and flags the bucket.
        ("closed_bar_quote_capture", False),
        ("closed_bar_quote_limit", 240),
        # Opt-in trusted quote-to-bar binding for managed-paper recovery V2.
        # When enabled, every bar delivery freezes the latest trusted quote
        # observation noted from this feed's own tick stream, and the recovery
        # Broker reads it through ``service_execution_recovery_quote_binding``.
        # ``service_recovery_quote_source_ref`` names that quote stream and is
        # required whenever the binding is enabled.  Default off: the method
        # then fails closed instead of exposing an unbound revision.
        ("service_recovery_quote_binding", False),
        ("service_recovery_quote_source_ref", None),
        # A caller-owned, calibrated provider invoked at the synchronous
        # strategy-dispatch boundary for SDK-qualified market ticks. It must
        # return MarketCohortNow in the event's exact monotonic clock domain.
        # There is deliberately no process-clock fallback here.
        ("market_decision_now_provider", None),
        # A caller-owned adapter from a Feed-owned, immutable closed BarEvent
        # to the public BarEvidence hand-off.  The Feed only attaches a
        # successfully validated object; it never invents a clock mapping or
        # candidate scope from process-local state.
        ("closed_bar_evidence_provider", None),
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
        if self.p.closed_bar_evidence_provider is not None and not callable(
            self.p.closed_bar_evidence_provider
        ):
            raise ValueError("closed_bar_evidence_provider must be callable")
        if bool(self.p.service_recovery_quote_binding):
            source_ref = self.p.service_recovery_quote_source_ref
            if type(source_ref) is not str or not source_ref:
                raise ValueError(
                    "service_recovery_quote_binding requires an explicit "
                    "service_recovery_quote_source_ref"
                )
        self.store = self.p.store
        self.provider = self.p.provider
        self._replay_tick_adapter = None
        replay_port = self.p.replay_market_tick_port
        if replay_port is not None or self.provider == "local_replay":
            if (
                replay_port is None
                or self.provider != "local_replay"
                or self.store is not None
            ):
                raise ValueError(
                    "local_replay requires replay_market_tick_port and store=None"
                )
            if (
                self.p.cohort_source_mode is True
                or self.p.market_factor_source_binding is not None
                or bool(self.p.service_recovery_quote_binding)
                or self.p.closed_bar_evidence_provider is not None
                or self.p.market_decision_now_provider is not None
                or bool(self.p.closed_bar_quote_capture)
                or bool(self.p.orderbook_as_ticks)
            ):
                raise ValueError("replay market input cannot use live-only feed bindings")
            if self.p.backfill_start is not False:
                raise ValueError("replay market input requires backfill_start=False")
            for name, rows in (
                ("historical_bars", self.p.historical_bars),
                ("live_bars", self.p.live_bars),
            ):
                if rows is not None and (
                    type(rows) not in (tuple, list, collections.deque) or rows
                ):
                    raise ValueError(f"replay market input rejects preloaded {name}")
            from .replay_market_adapter import ReplayMarketTickAdapter

            self._replay_tick_adapter = ReplayMarketTickAdapter(replay_port, self._dataname)
        history_source = self.p.historical_bars
        live_source = self.p.live_bars
        if history_source is None:
            history_source = ()
        if live_source is None:
            live_source = ()
        cohort_source_mode = self.p.cohort_source_mode
        if type(cohort_source_mode) is not bool:
            raise ValueError("cohort_source_mode must be an exact bool")
        source_binding = self.p.market_factor_source_binding
        if source_binding is None:
            self._market_factor_source_binding = None
            self._market_factor_source_projector = None
            self._market_factor_source_error_type = None
        else:
            # Import only for this explicit live-source mode so a normal
            # BtApiFeed import remains compatible with Python 3.8 and does
            # not load the futures-session implementation.
            from .market_factor_source import (
                MarketFactorSourceBinding,
                MarketFactorSourceError,
                project_market_factor_tick,
            )

            if not isinstance(source_binding, MarketFactorSourceBinding):
                raise ValueError("market_factor_source_binding has an unsupported type")
            if not cohort_source_mode:
                raise ValueError("market factor source binding requires cohort_source_mode=True")
            self._market_factor_source_binding = source_binding
            self._market_factor_source_projector = project_market_factor_tick
            self._market_factor_source_error_type = MarketFactorSourceError
        self._market_factor_source_last_cursor_sequence = 0
        if cohort_source_mode:
            if type(history_source) is not tuple or type(live_source) is not tuple:
                raise ValueError("cohort_source_mode requires immutable tuple bar sources")
            if self.p.backfill_start:
                raise ValueError(
                    "cohort_source_mode requires backfill_start=False and explicit source tuples"
                )
        # Keep the caller's raw event objects available for the opt-in cohort
        # path without materializing an arbitrary iterator. Cohort mode accepts
        # replayable finite sequences here; live stores remain polled directly.
        self._cohort_history_source = (
            history_source if isinstance(history_source, (tuple, list)) else None
        )
        self._cohort_live_source = live_source if isinstance(live_source, (tuple, list)) else None
        self._live_bar_cohort = None
        self._cohort_clock = None
        self._cohort_history_iter = None
        self._cohort_live_iter = None
        self._cohort_history_exhausted = False
        self._cohort_live_exhausted = False
        self._cohort_history_lookahead = _COHORT_MISSING
        self._cohort_live_lookahead = _COHORT_MISSING
        self._cohort_store_lookahead = _COHORT_MISSING
        self._cohort_completed_lookahead = _COHORT_MISSING
        self._cohort_slot_index_by_close = {}
        self._cohort_last_delivered_slot_index = -1
        self._cohort_armed_envelope = None
        self._cohort_staged_delivery = None
        self._cohort_delivery_failed = False
        self._cohort_stream_health_baseline = None
        if cohort_source_mode:
            # The sealed cohort owns the strict validation boundary. Preserve
            # exact raw tuples and leave the legacy normalized queues empty so
            # malformed numbers cannot be silently coerced before capture.
            self._history = collections.deque()
            self._live = collections.deque()
        else:
            self._history = collections.deque(
                _normalize_bar(dict(bar) if isinstance(bar, Mapping) else bar)
                for bar in history_source
            )
            self._live = collections.deque(
                _normalize_bar(dict(bar) if isinstance(bar, Mapping) else bar)
                for bar in live_source
            )
        self._live_notified = False
        self._bar_builder = None
        self._bar_builders = collections.OrderedDict()
        self._initial_volume_baseline_scope = None
        self._initial_volume_baseline_start = None
        self._bar_quality_overrides = collections.defaultdict(set)
        self._max_event_timestamp = None
        self._last_ingest_monotonic_ns = None
        self._replay_started = False
        self._last_closed_bucket_end = None
        self._last_connection_generation = None
        self._last_market_scope = None
        self._highest_market_scope = None
        self._bar_sequence = 0
        # Per-feed opaque marker proves that a strategy callback received the
        # sealed event from this exact Feed instance, rather than a caller
        # constructing a look-alike object around a BarEvidence value.
        self._closed_bar_evidence_dispatch_token = object()
        # This short-lived identity binding is populated immediately before
        # synchronous strategy dispatch and cleared immediately afterward.
        # It prevents a callback hook from retaining the event marker while
        # replacing the immutable evidence object with a different one.
        self._sealed_closed_bar_evidence_by_event_id = {}
        self._tick_consumer_claimed = False
        self._history_backfilled = bool(self._cohort_history_source) or bool(self._history)
        self._continuity_degraded = False
        self._session_active = False

    @property
    def live_bar_cohort(self):
        """Return the exact cohort installed by Cerebro for this feed, if any."""
        return self._live_bar_cohort

    def start(self):
        """Start the feed, register it, and backfill if configured."""
        new_session = not self._session_active
        if new_session:
            self._live_notified = False
            self._continuity_degraded = False
        claimed_this_start = False
        try:
            super().start()
            if self.p.cohort_source_mode and self._live_bar_cohort is None:
                raise ValueError("cohort_source_mode requires Cerebro live cohort activation")
            if self.p.orderbook_as_ticks and self._timeframe != TimeFrame.Ticks:
                raise ValueError("orderbook_as_ticks requires timeframe=TimeFrame.Ticks")

            if self._replay_tick_adapter is not None:
                if self.store is not None or getattr(self, "_store", None) is not None:
                    raise ValueError("replay feed cannot bind a Store")
                if self._history or self._live or self.p.backfill_start:
                    raise ValueError("replay feed cannot mix Store or preloaded bar sources")
                self._replay_tick_adapter.start()
                self._replay_started = True
                self._session_active = True
                return

            if self.store is None:
                self.store = getattr(self, "_store", None)

            if self.p.cohort_source_mode:
                self._validate_cohort_store_raw_mode(self.store)

            if self.store is None:
                self._session_active = True
                return

            self.store.start(data=self)
            if self._live_bar_cohort is not None:
                try:
                    baseline = self._read_cohort_stream_health()
                except Exception:
                    self._freeze_cohort_source(
                        "store_stream_health_invalid",
                        "cohort Store stream health is invalid at startup",
                    )
                if baseline is not None and (
                    baseline[1] not in (None, 0) or baseline[2] not in (None, 0) or baseline[3]
                ):
                    self._freeze_cohort_source(
                        "store_stream_degraded_before_cohort_start",
                        "cohort Store stream was already degraded at startup",
                    )
                self._cohort_stream_health_baseline = baseline
            self.store.register(self)

            service_read_only = bool(getattr(self.store, "_service_read_only", False))
            if service_read_only:
                # Establish the bounded live cursor before history so bars
                # published during backfill can be replayed and deduplicated.
                self.store.subscribe(
                    self._dataname,
                    channels=self.p.market_channels,
                    orderbook_depth=self.p.orderbook_depth,
                )

            if self.p.backfill_start and not self._history and not self._history_backfilled:
                if service_read_only:
                    bars = self.store.fetch_history(
                        self._dataname,
                        timeframe=self._timeframe,
                        compression=self._compression,
                    )
                    if self._live_bar_cohort is not None:
                        self._cohort_history_iter = iter(bars)
                        self._cohort_history_exhausted = False
                    else:
                        self._history.extend(bars)
                    self._history_backfilled = True
                else:
                    try:
                        bars = self.store.fetch_history(
                            self._dataname,
                            timeframe=self._timeframe,
                            compression=self._compression,
                        )
                        if self._live_bar_cohort is not None:
                            self._cohort_history_iter = iter(bars)
                            self._cohort_history_exhausted = False
                        else:
                            self._history.extend(bars)
                        self._history_backfilled = True
                    except Exception as e:
                        _safe_log("warning", "btapifeed:312 fallback on Exception")
                        _safe_log("debug", "Failed to backfill history: %s", e)

            if not service_read_only:
                if self._uses_sdk_market_streams():
                    self.store.subscribe(
                        self._dataname,
                        channels=self.p.market_channels,
                        orderbook_depth=self.p.orderbook_depth,
                    )
                    claim = getattr(self.store, "claim_tick_consumer", None)
                    supports_ticks = getattr(self.store, "supports_live_ticks", None)
                    if (
                        callable(claim)
                        and callable(supports_ticks)
                        and supports_ticks(self._dataname)
                        and not self._tick_consumer_claimed
                    ):
                        claim(self._dataname, self)
                        self._tick_consumer_claimed = True
                        claimed_this_start = True
                else:
                    claim = getattr(self.store, "claim_tick_consumer", None)
                    if (
                        callable(claim)
                        and not self.p.orderbook_as_ticks
                        and not self._tick_consumer_claimed
                    ):
                        claim(self._dataname, self)
                        self._tick_consumer_claimed = True
                        claimed_this_start = True
                    self.store.subscribe(
                        self._dataname,
                        channels=self.p.market_channels,
                        orderbook_depth=self.p.orderbook_depth,
                    )
            self._session_active = True
        except Exception:
            _safe_log("error", "btapifeed:326 exception before re-raise (Exception)")
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
            self._initial_volume_baseline_scope = None
            self._initial_volume_baseline_start = None
            self._last_market_scope = None
            self._highest_market_scope = None
            self._tick_consumer_claimed = False
            self._session_active = False
            if self._replay_started:
                self._replay_tick_adapter.close()
                self._replay_started = False

    def islive(self) -> bool:
        """Return whether this feed has a configured live data source."""
        if self._replay_tick_adapter is not None:
            # Cerebro must poll this finite source, but replay never emits a
            # LIVE readiness notification or a live market-clock assertion.
            return True
        if self._live_bar_cohort is not None:
            return True
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

        has_pending_live_bar = getattr(store, "has_pending_live_bar", None)
        if dataname is not None and callable(has_pending_live_bar) and has_pending_live_bar(dataname):
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
                    _safe_log("warning", "btapifeed:411 fallback on Exception")
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
        if self._live_bar_cohort is not None:
            return False
        if self._live:
            return True

        store = self.store or getattr(self, "_store", None)
        if store is None:
            return False

        has_pending_live_bar = getattr(store, "has_pending_live_bar", None)
        return bool(has_pending_live_bar(self._dataname)) if callable(has_pending_live_bar) else False

    def _load_history(self) -> bool:
        """Load one historical bar if available."""
        if not self._history:
            return False

        return self._load_bar(self._history.popleft())

    def _load(self) -> bool:
        """Load the next historical or live bar."""
        if self._live_bar_cohort is not None:
            # Only Cerebro may arm the exact envelope after every member has
            # passed preflight.  In particular, do not consume a side queue or
            # sleep from this path while another cohort member is pending.
            return self._load_live_bar_cohort_envelope()

        if self._history:
            return self._load_history()

        # Preserve the causal pair between a completed bar callback and the
        # matching data-line advance.  Do not consume newer ticks while an
        # already completed bar is waiting for Strategy.next().
        if self._live:
            self._mark_live()
            return self._load_bar(self._live.popleft())

        if self.p.orderbook_as_ticks and not self._uses_sdk_market_streams():
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
        if self._live_bar_cohort is not None:
            # The cohort runner owns bounded collection and the one shared
            # wait.  Feed._check must not consume events or sleep per member.
            return
        super()._check(forcedata=forcedata)
        if self.p.orderbook_as_ticks and not self._uses_sdk_market_streams():
            return  # _load must establish the feed clock before the callback.
        if self._live:
            return  # _load must pair the queued callback with its line bar.
        # The historical Tick-timeframe check path drains every currently
        # available tick. Keep that behavior for ordinary feeds, while an
        # explicit quote binding retains the per-bar freeze boundary.
        stop_after_queued_bar = self._timeframe != TimeFrame.Ticks or bool(
            self.p.service_recovery_quote_binding
        )
        drained_ticks = self._drain_live_ticks(stop_after_queued_bar=stop_after_queued_bar)
        drained_orderbooks = self._drain_live_orderbooks()
        self._flush_ready_bars(reason="idle")
        self._handle_source_exhaustion()
        if not self._history and (drained_ticks or drained_orderbooks):
            self._mark_live()

    def _load_orderbook_tick(self):
        """Load one snapshot per turn so neither another venue nor the broker starves."""
        if self.store is None:
            return False
        orderbook = self.store.poll_orderbook(
            self._dataname, depth=self.p.orderbook_depth
        )
        if orderbook is None:
            return False
        if getattr(orderbook, "execution_eligible", None) is False:
            self._handle_event_health(orderbook)
            if self.p.dispatch_orderbooks:
                self._dispatch_event("orderbook", EventPriority.ORDERBOOK, orderbook)
            else:
                self._mark_event_dropped(orderbook, "orderbook_dispatch_disabled")
            return False
        if self._handle_event_health(orderbook):
            if self.p.dispatch_orderbooks:
                self._dispatch_event("orderbook", EventPriority.ORDERBOOK, orderbook)
            else:
                self._mark_event_dropped(orderbook, "orderbook_dispatch_disabled")
            return False
        bids = _tick_value(orderbook, "bids", default=[]) or []
        asks = _tick_value(orderbook, "asks", default=[]) or []
        from bt_api_py.market_stream_contracts import orderbook_midpoint

        midpoint, error = orderbook_midpoint(bids, asks)
        if error is not None:
            self._mark_event_dropped(orderbook, f"orderbook_{error}")
            return False
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

    def _uses_sdk_market_streams(self) -> bool:
        """Read the Store's explicit stream-mode contract without API probing."""
        return getattr(self.store, "uses_sdk_market_streams", False) is True

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
        for name in _LIVE_COHORT_EXTRA_LINES:
            getattr(self.lines, name)[0] = math.nan
        if bool(self.p.service_recovery_quote_binding):
            # The trusted recovery binding is frozen at the exact delivery
            # boundary of this bar: the bar index the strategy will observe
            # and the datetime written into the line.  Recovery never
            # re-derives either fact later.
            self._record_service_recovery_quote_bar(
                bar_index=len(self),
                datetime_hex=float(self.lines.datetime[0]).hex(),
            )
        return True

    def _drain_live_ticks(
        self,
        limit=None,
        *,
        stop_after_queued_bar=True,
        deadline_ns=None,
        quote_only=False,
    ):
        """Drain available ticks subject to the caller's count and bar bounds.

        Normal load and cohort collection stop after the next queued bar so
        its callback stays paired with the matching line turn.  The legacy
        Tick-timeframe ``_check`` path may opt out of that queued-bar stop.
        Completed aggregate bars still end a drain on every path.  The private
        quote-only mode is reserved for a bounded, already-armed cohort
        winddown: it uses the same source validation and tick dispatch but
        never mutates or closes a bar builder.  Its integer return is the
        number of source ticks consumed; the ordinary path keeps its historic
        boolean return contract.
        """
        if quote_only and self._live_bar_cohort is None:
            raise RuntimeError("quote-only tick drain requires an active live bar cohort")
        if self._replay_tick_adapter is None and (
            self.store is None or not hasattr(self.store, "poll_tick")
        ):
            return 0 if quote_only else False

        drained = False

        drained_count = 0
        while limit is None or drained_count < limit:
            if self._cohort_prepare_deadline_expired(deadline_ns):
                break
            bar_sequence_before = self._bar_sequence
            queued_bars_before = len(self._live)
            try:
                if self._replay_tick_adapter is not None:
                    tick = self._replay_tick_adapter.poll()
                else:
                    tick = self.store.poll_tick(self._dataname)
            except Exception:
                if quote_only:
                    # The cohort cannot be trusted after its bounded quote
                    # source failed. Mark it frozen while preserving the
                    # provider exception and traceback for the caller.
                    self._freeze_cohort_source_state("winddown_quote_poll_failed")
                raise
            self._check_cohort_stream_health()
            if tick is None:
                break
            if self._replay_tick_adapter is None:
                try:
                    tick = adapt_market_tick_event(tick)
                except MarketTickAdapterError as error:
                    self._freeze_cohort_source_state(error.code)
                    raise
            expired_after_poll = self._cohort_prepare_deadline_expired(deadline_ns)
            drained = True
            drained_count += 1
            market_factor_planned_minute = True

            if self._market_factor_source_binding is not None:
                try:
                    projection = self._market_factor_source_projector(
                        self._market_factor_source_binding, tick
                    )
                    cursor_sequence = projection.cursor_sequence
                    if (
                        type(cursor_sequence) is not int
                        or cursor_sequence <= self._market_factor_source_last_cursor_sequence
                    ):
                        raise self._market_factor_source_error_type(
                            "MARKET_FACTOR_SOURCE_SEQUENCE_INVALID"
                        )
                    self._market_factor_source_last_cursor_sequence = cursor_sequence
                except self._market_factor_source_error_type:
                    self._freeze_cohort_source_state("market_factor_source_invalid")
                    raise
                market_factor_planned_minute = projection.planned_close_time is not None
                tick.event_time_utc = projection.event_time_utc
                tick.clock_domain_id = projection.clock_domain_id
                tick.market_factor_calendar_digest = projection.calendar_digest
                tick.market_factor_target_id = self._market_factor_source_binding.target_id
                tick.market_factor_product = (
                    self._market_factor_source_binding.product.exchange_id,
                    self._market_factor_source_binding.product.product_id,
                )
                tick.market_factor_trading_date = projection.trading_date.isoformat()
                tick.market_factor_session_date = projection.session_date.isoformat()
                tick.market_factor_event_session_date = projection.event_session_date.isoformat()
                tick.exchange_id = projection.venue
                tick.exchange_id_source = projection.identity_source
                tick.session_segment = projection.session_segment

            if self._validate_raw_cohort_tick_price(tick) is False:
                self._mark_event_dropped(tick, "invalid_market_tick")
                continue
            self._prepare_tick(
                tick,
                quote_only=quote_only or not market_factor_planned_minute,
            )
            expired_after_normalize = self._cohort_prepare_deadline_expired(deadline_ns)

            if self._handle_event_health(tick):
                if self._live_bar_cohort is not None:
                    self._freeze_cohort_source(
                        "unhealthy_source_tick", "unhealthy tick cannot continue a live cohort"
                    )
                if self.p.dispatch_ticks:
                    self._dispatch_event(
                        channel_type="tick",
                        priority=EventPriority.TICK,
                        event_data=tick,
                    )
                else:
                    self._mark_event_dropped(tick, "tick_dispatch_disabled")
                if (
                    expired_after_poll
                    or expired_after_normalize
                    or self._cohort_prepare_deadline_expired(deadline_ns)
                ):
                    break
                continue

            if not quote_only:
                self._record_initial_volume_baseline(tick)

            if self.p.dispatch_ticks:
                self._dispatch_event(
                    channel_type="tick",
                    priority=EventPriority.TICK,
                    event_data=tick,
                )
            else:
                self._mark_event_dropped(tick, "tick_dispatch_disabled")
            if quote_only or not market_factor_planned_minute:
                if (
                    expired_after_poll
                    or expired_after_normalize
                    or self._cohort_prepare_deadline_expired(deadline_ns)
                ):
                    break
                continue
            self._ingest_tick(tick)
            self._flush_ready_bars(reason="tick")
            # _bar_sequence tracks completed aggregate bars. Tick-timeframe
            # bars instead use the queue length; only ordinary _check may
            # preserve its historical all-available-ticks behavior.
            if (
                expired_after_poll
                or expired_after_normalize
                or self._cohort_prepare_deadline_expired(deadline_ns)
            ):
                break
            if self._bar_sequence != bar_sequence_before or (
                stop_after_queued_bar and len(self._live) > queued_bars_before
            ):
                break
        return drained_count if quote_only else drained

    def _record_initial_volume_baseline(self, tick):
        """Remember the first incomplete-volume bucket from neutral tick facts."""
        event = getattr(tick, "market_tick_event", None)
        if event is None or self._timeframe == TimeFrame.Ticks:
            return False
        data = event.data
        if data.volume_complete or data.cumulative_volume is None:
            return False
        trading_date = data.trading_date
        if type(trading_date) is not str or not trading_date:
            return False
        scope = (
            data.provider_connection_generation,
            data.provider_subscription_epoch,
            trading_date,
        )
        moment = getattr(tick, "event_time_utc", None)
        if not isinstance(moment, _dt.datetime) or moment.tzinfo is None:
            return False
        bucket_start = self._get_bucket_start(moment.astimezone(_UTC).replace(tzinfo=None))
        if self._initial_volume_baseline_scope != scope:
            self._initial_volume_baseline_scope = scope
            self._initial_volume_baseline_start = bucket_start
        elif self._initial_volume_baseline_start is None:
            self._initial_volume_baseline_start = bucket_start
        return True

    def _cohort_drain_winddown_quotes(self, *, limit, deadline_ns):
        """Consume a bounded source-backed quote prefix without bar work."""
        if self._live_bar_cohort is None:
            return 0
        if self._live_bar_cohort.frozen or self._cohort_delivery_failed:
            return 0
        return self._drain_live_ticks(
            limit=limit,
            stop_after_queued_bar=False,
            deadline_ns=deadline_ns,
            quote_only=True,
        )

    def _validate_raw_cohort_tick_price(self, tick):
        """Reject an invalid neutral quote before tolerant line conversion."""
        cohort = self._live_bar_cohort
        if cohort is None:
            return True

        raw_price = _tick_value(tick, "price", "last_price", default=None)
        price = _finite_market_number(raw_price)
        if price is not None and price > 0:
            return True

        member = cohort.member_for_feed(self)
        instrument = member.instrument if member is not None else self._dataname
        report = {
            "source": "BtApiFeed.tick",
            "instrument": _bounded_context_value(instrument),
            "field": "price",
            "category": "missing_or_invalid",
            "generation": _bounded_context_value(
                _tick_value(tick, "connection_generation", default=None)
            ),
            "sequence": _bounded_context_value(
                _tick_value(tick, "sequence", default=None)
            ),
            "reason": "LAST_PRICE_INVALID",
        }
        cohort._freeze("invalid_source_tick_price")
        self._cohort_delivery_failed = True
        from ..research.live_cohort import LiveCohortValidationError

        error = LiveCohortValidationError("tick price rejected: LAST_PRICE_INVALID")
        error.code = "LAST_PRICE_INVALID"
        error.report = MappingProxyType(report)
        raise error

    def _handle_source_exhaustion(self):
        """Finalize an explicitly finite source and report natural EOF.

        Live transports do not expose this contract and therefore continue to
        return ``None`` while idle.  Deterministic replay sources may declare
        both exhaustion and their final event-time watermark.  A missing or
        insufficient watermark invalidates any residual bucket rather than
        promoting a partial bar to executable data.
        """

        store = self.store
        if self._replay_tick_adapter is not None:
            if not self._replay_tick_adapter.exhausted:
                return False
            watermark_dt = self._replay_tick_adapter.final_event_time_watermark_utc
        else:
            exhausted = getattr(store, "is_source_exhausted", None) if store is not None else None
            if not callable(exhausted) or not exhausted(self._dataname):
                return False

            watermark_reader = (
                getattr(store, "get_source_event_time_watermark", None)
                if store is not None
                else None
            )
            watermark = watermark_reader(self._dataname) if callable(watermark_reader) else None
            watermark_dt = _as_utc_datetime(watermark)
        if watermark_dt is not None:
            watermark_ts = watermark_dt.timestamp()
            if self._max_event_timestamp is None or watermark_ts > self._max_event_timestamp:
                self._max_event_timestamp = watermark_ts
                if self._replay_tick_adapter is None:
                    self._last_ingest_monotonic_ns = self._now_monotonic_ns()
            self._flush_ready_bars(reason="source_exhausted")

        if self._bar_builders:
            self._flush_ready_bars(reason="source_exhausted_incomplete", force_invalid=True)
        return True

    def _drain_live_orderbooks(self, limit=None, *, deadline_ns=None):
        if self.store is None or not hasattr(self.store, "poll_orderbook"):
            return False

        drained = False

        drained_count = 0
        while limit is None or drained_count < limit:
            if self._cohort_prepare_deadline_expired(deadline_ns):
                break
            orderbook = self.store.poll_orderbook(
                self._dataname, depth=self.p.orderbook_depth
            )
            if orderbook is None:
                break
            expired_after_poll = self._cohort_prepare_deadline_expired(deadline_ns)
            observer_only = getattr(orderbook, "execution_eligible", None) is False
            drained = drained or not observer_only
            drained_count += 1

            self._handle_event_health(orderbook)

            if self.p.dispatch_orderbooks:
                self._dispatch_event(
                    channel_type="orderbook",
                    priority=EventPriority.ORDERBOOK,
                    event_data=orderbook,
                )
            else:
                self._mark_event_dropped(orderbook, "orderbook_dispatch_disabled")
            if expired_after_poll or self._cohort_prepare_deadline_expired(deadline_ns):
                break
        return drained

    def _ingest_tick(self, tick):
        """Update the current bar builder from a live tick."""
        tick_dt = _tick_datetime(tick)
        tick_ts = _tick_timestamp(tick)

        market_tick_event = getattr(tick, "market_tick_event", None)
        if market_tick_event is not None and self._timeframe != TimeFrame.Ticks:
            data = market_tick_event.data
            scope = (
                data.provider_connection_generation,
                data.provider_subscription_epoch,
                data.trading_date,
            )
            bucket_start = self._get_bucket_start(tick_dt)
            if (
                scope == self._initial_volume_baseline_scope
                and bucket_start == self._initial_volume_baseline_start
            ):
                # The SDK's neutral volume contract marks an incomplete
                # baseline explicitly. Skip only that partially observed
                # bucket; do not re-difference cumulative volume in Backtrader.
                cohort = self._live_bar_cohort
                if cohort is not None:
                    bucket_end = self._get_bucket_end(bucket_start)
                    if isinstance(bucket_end, _dt.datetime):
                        cohort.note_cold_start_skipped_slot(
                            bucket_end.replace(tzinfo=_UTC)
                        )
                return

        price = _finite_market_number(
            _tick_value(tick, "price", "last_price", default=None)
        )
        if price is None or price <= 0 or not bool(_tick_value(tick, "bar_eligible", default=True)):
            return

        volume = _finite_market_number(
            _tick_value(tick, "delta_volume", "volume", default=0.0)
        )
        if volume is None or volume <= 0:
            return
        openinterest = _finite_market_number(
            _tick_value(tick, "openinterest", "open_interest", default=0.0)
        )
        openinterest = max(openinterest or 0.0, 0.0)

        if self._timeframe == TimeFrame.Ticks:
            self._enqueue_bar_event(
                BarEvent(
                    timestamp=tick_ts,
                    symbol=self._dataname,
                    exchange=_tick_value(tick, "exchange", "exchange_id", default=""),
                    asset_type=_tick_value(tick, "asset_type", default="futures"),
                    local_time=_tick_value(tick, "local_time", default=None),
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
            self._note_service_recovery_quote_from_tick(tick, tick_ts)
            return

        bucket_start = self._get_bucket_start(tick_dt)
        current = self._bar_builders.get(bucket_start)
        if current is None:
            current = self._new_bar_builder(bucket_start, tick, price, volume, openinterest)
            self._capture_quote(current, tick)
            self._bar_builders[bucket_start] = current
            self._bar_builders.move_to_end(bucket_start)
            self._bar_builder = current
            self._note_service_recovery_quote_from_tick(tick, tick_ts)
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
            if current.get("source_mode") in {"replay", "synthetic"}:
                current["last_replay_sequence"] = _tick_value(
                    tick, "replay_sequence", default=current["last_replay_sequence"]
                )
            current["trade_count"] += 1
            for field, aliases, mismatch_flag in (
                ("rules_hash", ("rules_hash",), "RULES_HASH_CHANGED"),
                ("session_segment", ("session_segment",), "SESSION_SEGMENT_CHANGED"),
                ("trading_day", ("trading_day", "trading_date"), "TRADING_DAY_CHANGED"),
            ):
                value = _tick_value(tick, *aliases, default=current[field])
                if value != current[field]:
                    current["quality_flags"].add(mismatch_flag)
            resolved_event_session_date = _tick_value(
                tick, "market_factor_event_session_date", default=None
            )
            if (
                current["event_session_date"] is not None
                and resolved_event_session_date != current["event_session_date"]
            ):
                # A bar spanning distinct or unresolved event dates has no
                # single resolver-backed session date.
                current["event_session_date"] = None
                current["market_factor_event_session_date"] = None
                current["quality_flags"].add("EVENT_SESSION_DATE_NOT_UNIFORM")
            current["quality_flags"].update(_tick_value(tick, "quality_flags", default=()) or ())
            self._capture_quote(current, tick)
            self._note_service_recovery_quote_from_tick(tick, tick_ts)
            return

    def _new_bar_builder(self, bucket_start, tick, price, volume, openinterest):
        """Create the mutable state for an in-progress aggregated bar."""
        ingest_seq = _tick_value(tick, "ingest_seq", "sequence", default=0)
        replay_mode = _tick_value(tick, "source_mode", default=None)
        replay_sequence = _tick_value(tick, "replay_sequence", default=None)
        replay = replay_mode in {"replay", "synthetic"}
        builder = {
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
            "exchange": _tick_value(tick, "exchange", "exchange_id", default=""),
            "asset_type": _tick_value(tick, "asset_type", default="futures"),
            "trading_day": _tick_value(tick, "trading_day", "trading_date", default=""),
            "quote_events": [],
            "action_day": _tick_value(tick, "action_day", "event_session_date", default=""),
            # This is populated only by the exact-event SDK session resolver
            # projection above; provider event-date claims alone are not enough.
            "event_session_date": _tick_value(
                tick, "market_factor_event_session_date", default=None
            ),
            "rules_hash": _tick_value(tick, "quality_contract_ref", default=None),
            "session_segment": _tick_value(tick, "session_segment", default=None),
            "clock_domain_id": _tick_value(tick, "clock_domain_id", default=None),
            "market_factor_calendar_digest": _tick_value(
                tick, "market_factor_calendar_digest", default=None
            ),
            "market_factor_target_id": _tick_value(
                tick, "market_factor_target_id", default=None
            ),
            "market_factor_product": _tick_value(
                tick, "market_factor_product", default=None
            ),
            "market_factor_trading_date": _tick_value(
                tick, "market_factor_trading_date", default=None
            ),
            "market_factor_session_date": _tick_value(
                tick, "market_factor_session_date", default=None
            ),
            "market_factor_event_session_date": _tick_value(
                tick, "market_factor_event_session_date", default=None
            ),
            "exchange_id_source": _tick_value(tick, "exchange_id_source", default=None),
            "connection_generation": _tick_value(
                tick, "connection_generation", default=None
            ),
            "first_ingest_seq": ingest_seq,
            "last_ingest_seq": ingest_seq,
            "trade_count": 1,
            "volume_complete": bool(_tick_value(tick, "volume_complete", default=True)),
            "quality_flags": set(_tick_value(tick, "quality_flags", default=()) or ()),
        }
        if replay:
            # Replay-local identity is intentionally disjoint from live stream
            # generation and provider ingress sequence fields.
            builder.update(
                {
                    "source_mode": replay_mode,
                    "replay_source_ref": _tick_value(tick, "replay_source_ref", default=""),
                    "replay_epoch": _tick_value(tick, "replay_epoch", default=""),
                    "first_replay_sequence": replay_sequence,
                    "last_replay_sequence": replay_sequence,
                    "connection_generation": None,
                    "first_ingest_seq": None,
                    "last_ingest_seq": None,
                }
            )
        return builder

    def _note_service_recovery_quote_from_tick(self, tick, tick_ts):
        """Ingest one accepted tick as a trusted recovery quote observation.

        The recovery quote revision of this feed *is* its own ingested tick
        stream: the configured source reference names the stream, the tick's
        connection generation and ingest sequence are its generation and
        cursor, and the tick event time is its as-of time.  Malformed, stale
        or duplicated observations are dropped here; the per-bar reader then
        fails closed instead of inventing a revision.
        """

        if not bool(self.p.service_recovery_quote_binding):
            return False
        try:
            as_of_ns = int(round(float(tick_ts) * 1_000_000_000))
        except (TypeError, ValueError, OverflowError):
            return False
        return self.try_note_service_recovery_quote(
            source_ref=self.p.service_recovery_quote_source_ref,
            generation=_tick_value(
                tick, "connection_generation", default=None
            ),
            cursor=_tick_value(tick, "ingest_seq", "sequence", default=None),
            instrument=self._dataname,
            as_of_ns=as_of_ns,
        )

    def _capture_quote(self, builder, tick):
        """Freeze one prepared tick into the bucket's bounded quote window."""
        if not bool(self.p.closed_bar_quote_capture):
            return
        mapping = self._quote_capture_mapping(tick)
        if mapping is None:
            return
        events = builder.get("quote_events")
        if events is None:
            events = builder["quote_events"] = []
        limit = int(self.p.closed_bar_quote_limit or 0)
        if limit > 0 and len(events) >= limit:
            builder["quality_flags"].add("QUOTE_CAPTURE_OVERFLOW")
            events.pop(0)
        events.append(mapping)

    def _evidence_symbol(self):
        """Return the display identity used by legacy bars and quote evidence.

        ``dataname`` remains the provider subscription key.  Cerebro's
        explicit feed name is preserved for ordinary display and quote-window
        records when present.  Cohort bars use the exact source route instead.
        """
        name = getattr(self, "_name", None)
        return name if isinstance(name, str) and name else self._dataname

    def _completed_bar_symbol(self):
        """Use the exact provider route for cohort bars, display name otherwise."""
        if self._live_bar_cohort is not None:
            return self._dataname
        return self._evidence_symbol()

    def _quote_capture_mapping(self, tick):
        """Project the tick with this Feed's configured display identity."""
        from bt_api_py.market_tick_contracts import quote_capture_mapping

        return quote_capture_mapping(tick, symbol=self._evidence_symbol())

    def _attach_closed_bar_evidence(self, bar_event):
        """Attach only a scope-consistent caller-produced BarEvidence object.

        The adapter receives a detached snapshot after the Feed has frozen
        its closed-bar metadata but before the channel callback.  Validation
        remains against the Feed-owned event, so a provider cannot mutate its
        input and make a forged result appear scope-consistent.  The hand-off
        stays narrow: unlike a strategy it cannot reconstruct evidence from
        mutable line buffers, and unlike the Feed it cannot invent a clock
        mapping or candidate identity.
        """

        provider = self.p.closed_bar_evidence_provider
        if provider is None:
            return
        provider_input = SimpleNamespace(**copy.deepcopy(vars(bar_event)))
        evidence = provider(provider_input)
        if not isinstance(evidence, BarEvidence):
            raise ValueError("closed_bar_evidence_provider must return BarEvidence")
        if evidence.symbol != bar_event.symbol or evidence.exchange != bar_event.exchange:
            raise ValueError("closed BarEvidence identity does not match BarEvent")
        for name in (
            "bucket_start",
            "bucket_end",
            "available_at",
            "trading_day",
            "connection_generation",
            "rules_hash",
            "session_segment",
            "first_ingest_seq",
            "last_ingest_seq",
            "quote_cutoff_seq",
            "bar_id",
            "bar_sequence",
            "complete",
        ):
            event_name = "generation" if name == "connection_generation" else name
            if getattr(evidence, event_name) != getattr(bar_event, name):
                raise ValueError(f"closed BarEvidence {event_name} does not match BarEvent")
        for name in ("quality", "volume_complete", "closure_reason", "trade_count", "watermark"):
            if getattr(evidence, name) != getattr(bar_event, name):
                raise ValueError(f"closed BarEvidence {name} does not match BarEvent")
        if evidence.max_event_time != getattr(bar_event, "max_event_time"):
            raise ValueError("closed BarEvidence max_event_time does not match BarEvent")
        for name in ("open", "high", "low", "close", "volume", "openinterest"):
            if getattr(evidence, name) != float(getattr(bar_event, name)):
                raise ValueError(f"closed BarEvidence {name} does not match BarEvent")
        if evidence.clock_domain != getattr(bar_event, "clock_domain_id", None):
            raise ValueError("closed BarEvidence clock domain does not match BarEvent")
        setattr(bar_event, "closed_bar_evidence", evidence)

    def _has_sealed_closed_bar_evidence(self, bar_event, evidence):
        """Return whether this exact event/evidence pair is still in dispatch."""

        return self._sealed_closed_bar_evidence_by_event_id.get(id(bar_event)) is evidence

    def _enqueue_bar_event(self, bar_event, bar_datetime, *, deliver_lines=True):
        """Queue a completed bar for both notify_bar and line delivery."""
        if self._live_bar_cohort is not None:
            if self._cohort_completed_lookahead is not _COHORT_MISSING:
                self._live_bar_cohort._freeze("feed_completed_bar_queue_overflow")
                self._cohort_delivery_failed = True
                raise RuntimeError("BtApiFeed completed-bar lookahead is full")
            # Preserve the provider/feed-produced event intact.  Validation,
            # line delivery, and notify_bar are deferred to the batch barrier.
            self._cohort_completed_lookahead = bar_event
            return
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
        if self._replay_tick_adapter is not None:
            # Replay advances only from the next recorded event or the source's
            # explicit final watermark. Host idle time must not move its clock.
            return self._max_event_timestamp
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
        from bt_api_py.instrument_metadata_aliases import configured_metadata_price_tick

        return configured_metadata_price_tick(
            metadata, self._dataname, finite_number=_finite_market_number,
        )

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

    def _prepare_tick(self, tick, *, quote_only=False):
        """Normalize one tick's schema, quality, ordering and volume semantics."""
        from bt_api_py.market_tick_contracts import (
            classify_market_scope,
            prepare_market_tick_fields,
            prepare_market_tick_timing,
        )

        (
            typed_market_tick, replay_market_tick, replay_binding_invalid, flags, delta,
            price, bid, ask, bid_size, ask_size,
        ) = prepare_market_tick_fields(
            tick, replay_adapter_available=self._replay_tick_adapter is not None,
            legacy_schema="backtrader.tick.v1",
        )

        price_tick = self._cached_price_tick()
        if typed_market_tick and price_tick is None:
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
        if typed_market_tick:
            # ``BtApiFeed`` is a consumer-side quality boundary, not an
            # authority that may promote a hand-built or incomplete V2 quote.
            # The SDK/Store must explicitly attest the upstream decision; this
            # Feed only keeps it false when any local gate also fails.
            from bt_api_py.market_tick_contracts import market_execution_evidence_flags

            flags.update(market_execution_evidence_flags(
                execution_eligible=upstream_execution_eligible,
                source_clock_quality=_tick_value(tick, "source_clock_quality", default=""),
                receive_clock_quality=_tick_value(tick, "receive_clock_quality", default=""),
                freshness_verified=_tick_value(tick, "freshness_verified", default=False),
                stale=_tick_value(tick, "stale", default=None),
                stale_reason=_tick_value(tick, "stale_reason", default=None),
            ))
        event_dt, tick_ts, timing_flags = prepare_market_tick_timing(
            tick,
            typed_market_tick=typed_market_tick,
            now_monotonic_ns=self._now_monotonic_ns,
            event_time_max_age=lambda: self.p.event_time_max_age,
            receive_time_max_age=lambda: self.p.receive_time_max_age,
        )
        flags.update(timing_flags)
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
                if bucket_start is not None and not quote_only:
                    self._add_bar_quality_override(bucket_start, "ORDERING_VOLUME_GAP")
                current_start = self._get_bucket_start(
                    _dt.datetime.fromtimestamp(self._max_event_timestamp, _UTC).replace(tzinfo=None)
                )
                if not quote_only:
                    self._add_bar_quality_override(current_start, "ORDERING_VOLUME_GAP")

        generation = _tick_value(tick, "connection_generation", default=None)
        subscription_epoch = _tick_value(tick, "subscription_epoch", default=None)
        scope, retired_market_scope, scope_flag, advance_generation = classify_market_scope(
            typed_market_tick=typed_market_tick,
            generation=generation,
            subscription_epoch=subscription_epoch,
            highest_scope=self._highest_market_scope,
            last_generation=self._last_connection_generation,
        )
        if scope_flag in {"MARKET_SCOPE_INVALID", "RETIRED_CONNECTION_SCOPE"}:
            flags.add(scope_flag)
        elif scope_flag is not None:
            if not quote_only:
                for builder in self._bar_builders.values():
                    builder["quality_flags"].add(scope_flag)
                self._flush_ready_bars(
                    reason=(
                        "generation"
                        if scope_flag == "CONNECTION_GENERATION_CHANGED"
                        else "subscription_epoch"
                    ),
                    force_invalid=True,
                )
            self._max_event_timestamp = None
            flags.add(scope_flag)
            if not quote_only:
                self._add_bar_quality_override(bucket_start, scope_flag)
        if advance_generation:
            if typed_market_tick:
                self._highest_market_scope = scope
                self._last_market_scope = scope
            self._last_connection_generation = generation

        if (
            self._timeframe != TimeFrame.Ticks
            and bucket_end is not None
            and self._last_closed_bucket_end is not None
            and bucket_end <= self._last_closed_bucket_end
        ):
            flags.add("BUCKET_ALREADY_CLOSED")

        if tick_ts is not None and "EVENT_TIME_CONFLICT" not in flags and not retired_market_scope:
            if self._max_event_timestamp is None or tick_ts >= self._max_event_timestamp:
                self._max_event_timestamp = tick_ts
            if not replay_market_tick:
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
        volume_complete = bool(_tick_value(tick, "volume_complete", default=not typed_market_tick))
        if typed_market_tick and not volume_complete and delta == 0:
            flags.add("VOLUME_BASELINE")
        if typed_market_tick and not volume_complete and delta > 0:
            blocking.add("VOLUME_INCOMPLETE")
            flags.add("VOLUME_INCOMPLETE")
        # A rejected snapshot can still prove that an already-open bucket is
        # incomplete. Preserve that evidence before _ingest_tick declines to
        # mutate OHLCV. Otherwise a later watermark could publish the earlier
        # trades as a deceptively complete bar after a volume/order/time gap.
        if bucket_start is not None and blocking and not quote_only:
            already_closed = (
                self._last_closed_bucket_end is not None
                and bucket_end is not None
                and bucket_end <= self._last_closed_bucket_end
            )
            if not already_closed:
                self._add_bar_quality_override(bucket_start, *blocking)
        execution_eligible = (
            (
                not replay_market_tick
                and (not typed_market_tick or upstream_execution_eligible is True)
            )
            and not blocking
            and all(value is not None and value > 0 for value in (bid, ask, bid_size, ask_size))
        )
        bar_eligible = not blocking and price is not None and price > 0 and delta > 0
        _set_tick_value(tick, "quality_flags", tuple(sorted(flags)))
        _set_tick_value(
            tick,
            "quality",
            "REPLAY_ONLY" if replay_market_tick else ("GOOD" if not blocking else "INVALID"),
        )
        _set_tick_value(tick, "execution_eligible", execution_eligible)
        _set_tick_value(tick, "bar_eligible", bar_eligible and not replay_binding_invalid)
        if not quote_only:
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
            replay = current.get("source_mode") in {"replay", "synthetic"}
            if replay:
                from .replay_market_adapter import ReplayBarEvent

                replay_first = current["first_replay_sequence"]
                replay_last = current["last_replay_sequence"]
                replay_source_ref = current["replay_source_ref"]
                replay_epoch = current["replay_epoch"]
                completed = ReplayBarEvent(
                    timestamp=bucket_end.replace(tzinfo=_UTC).timestamp(),
                    symbol=self._completed_bar_symbol(),
                    exchange=current["exchange"],
                    venue=current["exchange"],
                    asset_type=current["asset_type"],
                    source_mode=current["source_mode"],
                    replay_source_ref=replay_source_ref,
                    replay_epoch=replay_epoch,
                    replay_bar_sequence=self._bar_sequence,
                    first_replay_sequence=replay_first,
                    last_replay_sequence=replay_last,
                    replay_bucket_start=bucket_start.replace(tzinfo=_UTC),
                    replay_bucket_end=bucket_end.replace(tzinfo=_UTC),
                    replay_available_at=available_at,
                    replay_bar_status=(
                        "fixture_projection" if complete else "incomplete_projection"
                    ),
                    replay_close_reason=(
                        "event_time_watermark" if reason in {"tick", "load", "idle"} else reason
                    ),
                    trading_day=str(current["trading_day"] or ""),
                    event_session_date=str(current["action_day"] or ""),
                    open=current["open"],
                    high=current["high"],
                    low=current["low"],
                    close=current["close"],
                    volume=current["volume"],
                    openinterest=current["openinterest"],
                    replay_volume_complete=bool(current["volume_complete"]),
                    replay_quality_flags=tuple(sorted(flags)),
                    replay_bar_id=(
                        f"{replay_source_ref}:{replay_epoch}:{self._dataname}:"
                        f"{bucket_start.isoformat()}:{replay_first}-{replay_last}"
                    ),
                )
            else:
                bar_id = (
                    f"{self._dataname}:{bucket_start.isoformat()}:{generation}:"
                    f"{first_seq}-{last_seq}"
                )
                completed = BarEvent(
                    timestamp=bucket_end.replace(tzinfo=_UTC).timestamp(),
                    symbol=self._completed_bar_symbol(),
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
                    "quote_cutoff_seq": last_seq,
                    "trading_day": current["trading_day"],
                    "action_day": current["action_day"],
                    "event_session_date": current["event_session_date"],
                    "rules_hash": current["rules_hash"],
                    "session_segment": current["session_segment"],
                    "connection_generation": generation,
                    "bar_id": bar_id,
                    "decision_version": bar_id,
                    "closure_reason": reason,
                    "bar_sequence": self._bar_sequence,
                    "trade_count": current["trade_count"],
                    "watermark": _dt.datetime.fromtimestamp(watermark or available_ts, _UTC),
                    "max_event_time": _dt.datetime.fromtimestamp(current["last_timestamp"], _UTC),
                }
                if bool(self.p.closed_bar_quote_capture):
                    extensions["quote_events"] = tuple(current.get("quote_events") or ())
                for name in (
                    "clock_domain_id",
                    "market_factor_calendar_digest",
                    "market_factor_target_id",
                    "market_factor_product",
                    "market_factor_trading_date",
                    "market_factor_session_date",
                    "market_factor_event_session_date",
                    "exchange_id_source",
                ):
                    value = current.get(name)
                    if value is not None:
                        extensions[name] = value
                for name, value in extensions.items():
                    setattr(completed, name, value)
                self._attach_closed_bar_evidence(completed)
                if getattr(completed, "closed_bar_evidence", None) is not None:
                    setattr(
                        completed,
                        "_closed_bar_evidence_dispatch_token",
                        self._closed_bar_evidence_dispatch_token,
                    )
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
            self._attach_market_decision_now(event_data)

        event_timestamp = _tick_timestamp(event_data)
        if (
            getattr(event_data, "execution_eligible", None) is False
            and getattr(event_data, "event_time_utc", None) is None
        ):
            event_timestamp = None
        event = Event(
            timestamp=event_timestamp,
            priority=priority,
            channel_type=channel_type,
            channel_name=self._dataname,
            data=event_data,
        )
        # Only feed-origin events carry this private reference. Channel queues
        # already drive the matching broker in their own event loop.
        event._source_feed = (
            None
            if getattr(event_data, "execution_eligible", None) is False
            else self
        )
        sealed_evidence = (
            getattr(event_data, "closed_bar_evidence", None) if channel_type == "bar" else None
        )
        if sealed_evidence is not None:
            self._sealed_closed_bar_evidence_by_event_id[id(event_data)] = sealed_evidence
        try:
            env.dispatch_channel_event(event)
        except Exception:
            _safe_log("error", "btapifeed:1390 exception before re-raise (Exception)")
            self._mark_event_dropped(event_data, "strategy_dispatch_failed")
            raise
        finally:
            # Native callbacks are synchronous.  Do not retain evidence
            # identity after their dispatch window has closed.
            self._sealed_closed_bar_evidence_by_event_id.pop(id(event_data), None)
        if self.store is not None and hasattr(self.store, "mark_strategy_delivered"):
            self.store.mark_strategy_delivered(event_data)
        return True

    def _attach_market_decision_now(self, tick):
        """Attach caller-owned decision-boundary time to a qualified SDK tick.

        Parent receipt time is useful evidence but cannot measure time spent
        in the Store/Feed path.  A live caller must explicitly provide a
        calibrated same-domain provider; raw tick fields never supply this
        boundary.  Replay code can provide its own deterministic evidence
        without involving this Feed.
        """

        if _tick_value(tick, "schema_version", default=None) != "sdk.market.tick.v1":
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
        provider = self.p.market_decision_now_provider
        if not callable(provider):
            return
        try:
            now = provider(tick)
        except Exception:
            _safe_log("warning", "btapifeed:1431 fallback on Exception")
            return
        if not isinstance(now, MarketCohortNow):
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
        execution_unavailable = getattr(event_data, "execution_eligible", None) is False
        observer_only_orderbook = execution_unavailable and (
            getattr(event_data, "event_type", None) == "orderbook"
            or getattr(getattr(event_data, "key", None), "channel", None) == "orderbook"
        )
        if observer_only_orderbook:
            # Keep unknown book clock/freshness on this event without
            # degrading the Feed's independent tick/bar continuity state.
            return True
        unhealthy = execution_unavailable or stale or continuity in {
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
        if self._replay_tick_adapter is not None or self._continuity_degraded:
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
