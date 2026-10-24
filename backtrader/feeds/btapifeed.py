#!/usr/bin/env python
"""Unified bt_api_py-backed live data feed."""

from __future__ import annotations

import collections
from collections.abc import Mapping
import copy
import datetime as _dt
import math
import numbers
import time as _time
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace

from ..channel import Event, EventPriority
from ..dataseries import TimeFrame
from ..events import BarEvent
from ..feed import DataBase
from ..stores.btapistore import _build_ctp_tick_datetime, _normalize_bar, _redact_diagnostic
from ..utils import date2num
from ..utils.log_message import get_logger
from .barrier import BarEvidence
from .ctpcohort import CtpCohortNow
from .livefeed import LiveFeedBase
from .service_recovery_quotes import ServiceRecoveryQuoteBindingMixin

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
_CTP_INVALID_ABS = 1.0e50
_COHORT_MISSING = object()
_TICK_PRICE_FIELDS = ("price", "last_price", "LastPrice")
_MAX_DIAGNOSTIC_TEXT = 128
_MAPPING_PROXY_TYPE = type(MappingProxyType({}))
_LIVE_COHORT_EXTRA_LINES = (
    "vwap",
    "cap",
    "sector",
    "industry",
    "subindustry",
    "dollar_volume",
)


@dataclass(frozen=True)
class _PreparedLiveBarCohortActivation:
    """Validated, side-effect-free feed state staged by Cerebro."""

    feed_ref: object
    cohort: object
    clock: object
    history_iter: object
    live_iter: object
    slot_index_by_close: object


@dataclass(frozen=True)
class _PreparedLiveBarCohortDelivery:
    """Read-only, validated values staged before any batch member advances."""

    feed_ref: object
    envelope: object
    raw_values: object
    close_time: object
    datetime_value: float


def _raw_tick_field(tick, names):
    """Read the first explicitly present raw tick alias without normalizing it."""
    first_null = None
    for name in names:
        if isinstance(tick, Mapping):
            if name in tick:
                value = tick[name]
                if value is not None:
                    return name, value, True
                if first_null is None:
                    first_null = (name, value)
            continue
        value = getattr(tick, name, _COHORT_MISSING)
        if value is not _COHORT_MISSING:
            if value is not None:
                return name, value, True
            if first_null is None:
                first_null = (name, value)
    if first_null is not None:
        return first_null[0], first_null[1], True
    return names[0], _COHORT_MISSING, False


def _tick_price_category(value, present):
    """Classify a raw price before the tolerant numeric conversion path runs."""
    if not present or value is None or (isinstance(value, str) and value == ""):
        return "missing"
    if isinstance(value, bool) or not isinstance(value, (numbers.Real, Decimal)):
        return "wrong_type"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "non_finite"
    if math.isnan(number):
        return "nan"
    if not math.isfinite(number):
        return "non_finite"
    if abs(number) >= _CTP_INVALID_ABS:
        return "sentinel"
    if number <= 0:
        return "non_positive"
    return None


def _bounded_context_value(value):
    """Keep diagnostic identifiers finite without retaining arbitrary objects."""
    if type(value) is str:
        return value[:_MAX_DIAGNOSTIC_TEXT]
    if type(value) is int and -(2**63) <= value < 2**63:
        return value
    return None


def _live_tick_validation_error(report, code="LAST_PRICE_INVALID"):
    """Build a structured cohort error without importing research on Feed import."""
    from ..research.live_cohort import LiveCohortValidationError

    message = (
        "raw tick price rejected: LAST_PRICE_INVALID"
        if code == "LAST_PRICE_INVALID"
        else "raw CTP tick rejected: {}".format(code)
    )
    error = LiveCohortValidationError(message)
    error.code = code
    error.report = MappingProxyType(dict(report))
    return error


def _raw_ctp_volume_category(value, present):
    """Classify cumulative volume before Store/Feed tolerant conversions."""
    if not present or value is None or (isinstance(value, str) and value == ""):
        return "missing"
    if isinstance(value, bool) or not isinstance(value, (numbers.Real, Decimal)):
        return "wrong_type"
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return "non_finite"
    if math.isnan(number):
        return "nan"
    if not math.isfinite(number):
        return "non_finite"
    if abs(number) >= _CTP_INVALID_ABS:
        return "sentinel"
    if number < 0:
        return "negative"
    return None


def _raw_ctp_tick_problem(raw_tick, *, strict_action_day=False):
    """Return the first unsafe direct-CTP source field, without coercion."""
    if not isinstance(raw_tick, Mapping):
        return "SOURCE_TICK_INVALID", "ctp_raw_tick", "wrong_type", "invalid_source_ctp_tick"

    field, value, present = _raw_tick_field(raw_tick, ("LastPrice",))
    category = _tick_price_category(value, present)
    if category is not None:
        return "LAST_PRICE_INVALID", field, category, "invalid_source_tick_price"

    if strict_action_day:
        trading_day = raw_tick.get("TradingDay")
        if type(trading_day) is not str or len(trading_day) != 8 or not trading_day.isdigit():
            return (
                "TRADING_DAY_INVALID",
                "TradingDay",
                "missing_or_invalid",
                "invalid_source_trading_day",
            )
        try:
            _dt.datetime.strptime(trading_day, "%Y%m%d")
        except ValueError:
            return "TRADING_DAY_INVALID", "TradingDay", "invalid_date", "invalid_source_trading_day"

        action_day = raw_tick.get("ActionDay")
        if isinstance(action_day, Mapping) and action_day.get("read_error") is True:
            return "ACTION_DAY_INVALID", "ActionDay", "read_error", "invalid_source_action_day"
        if action_day is None or action_day == "":
            # TradingDay is not an event-date proof for night or after-midnight
            # CTP ticks, so strict cohort input cannot infer ActionDay from it.
            return "ACTION_DAY_INVALID", "ActionDay", "missing", "invalid_source_action_day"
        if type(action_day) is not str or len(action_day) != 8 or not action_day.isdigit():
            return (
                "ACTION_DAY_INVALID",
                "ActionDay",
                "missing_or_invalid",
                "invalid_source_action_day",
            )
        try:
            _dt.datetime.strptime(action_day, "%Y%m%d")
        except ValueError:
            return "ACTION_DAY_INVALID", "ActionDay", "invalid_date", "invalid_source_action_day"
        if _build_ctp_tick_datetime(raw_tick) is None:
            return (
                "SOURCE_TIME_INVALID",
                "source_time",
                "missing_or_invalid",
                "invalid_source_tick_time",
            )
    else:
        if _build_ctp_tick_datetime(raw_tick) is None:
            return (
                "SOURCE_TIME_INVALID",
                "source_time",
                "missing_or_invalid",
                "invalid_source_tick_time",
            )
        trading_day = raw_tick.get("TradingDay")
        if type(trading_day) is not str or len(trading_day) != 8 or not trading_day.isdigit():
            return (
                "TRADING_DAY_INVALID",
                "TradingDay",
                "missing_or_invalid",
                "invalid_source_trading_day",
            )
        try:
            _dt.datetime.strptime(trading_day, "%Y%m%d")
        except ValueError:
            return "TRADING_DAY_INVALID", "TradingDay", "invalid_date", "invalid_source_trading_day"

    field, value, present = _raw_tick_field(raw_tick, ("Volume",))
    category = _raw_ctp_volume_category(value, present)
    if category is not None:
        return "CUMULATIVE_VOLUME_INVALID", field, category, "invalid_source_cumulative_volume"

    generation = raw_tick.get("connection_generation")
    if type(generation) is not int or generation <= 0:
        return (
            "CTP_CONNECTION_GENERATION_INVALID",
            "connection_generation",
            "missing_or_invalid",
            "invalid_source_ctp_scope",
        )

    issue = raw_tick.get("volume_issue")
    if issue:
        return "VOLUME_DISCONTINUITY", "Volume", str(issue), "invalid_source_cumulative_volume"
    return None


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
    if isinstance(tick, Mapping):
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
            _safe_log("debug", "btapifeed:132 ignored ValueError")

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
            _safe_log("debug", "btapifeed:147 ignored TypeError,ValueError")
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
            _safe_log("debug", "btapifeed:159 ignored ValueError")
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


class BtApiFeed(ServiceRecoveryQuoteBindingMixin, DataBase, LiveFeedBase):
    """Data feed that backfills and streams bars through BtApiStore.

    ``orderbook_as_ticks=True`` exposes each depth snapshot as a zero-volume
    midpoint tick bar before calling ``notify_orderbook``. This gives native
    broker orders a valid feed price and clock even without trade/bar streams.
    It requires ``timeframe=TimeFrame.Ticks``.
    """

    # These fixed numeric slots are used by the opt-in research cohort path.
    # They remain NaN unless the exact registered member maps each field to a
    # validated raw numeric field. Ordinary feeds keep their historical loader.
    lines = _LIVE_COHORT_EXTRA_LINES

    params = (
        ("store", None),
        ("provider", "btapi"),
        ("historical_bars", None),
        ("live_bars", None),
        # Explicit cohort mode keeps saved source events raw until the cohort
        # validates them. Ordinary feeds retain their historical tolerant
        # normalization path.
        ("cohort_source_mode", False),
        # Adapter-authored origin claim; cohort matching does not prove exchange completeness.
        ("cohort_source_origin", None),
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
        # strategy-dispatch boundary for strict ctp.quote.v2 ticks.  It must
        # return CtpCohortNow in the event's exact monotonic clock domain.
        # There is deliberately no process-clock fallback here.
        ("ctp_decision_now_provider", None),
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
        history_source = self.p.historical_bars
        live_source = self.p.live_bars
        if history_source is None:
            history_source = ()
        if live_source is None:
            live_source = ()
        cohort_source_mode = self.p.cohort_source_mode
        if type(cohort_source_mode) is not bool:
            raise ValueError("cohort_source_mode must be an exact bool")
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
        self._ctp_first_bucket_scope = None
        self._ctp_first_bucket_start = None
        self._bar_quality_overrides = collections.defaultdict(set)
        self._max_event_timestamp = None
        self._last_ingest_monotonic_ns = None
        self._last_closed_bucket_end = None
        self._last_connection_generation = None
        self._last_ctp_scope = None
        self._highest_ctp_scope = None
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

    def _prepare_live_bar_cohort_activation(self, cohort, clock):
        """Validate and stage cohort state without changing this feed."""
        if self.p.cohort_source_mode is not True:
            raise ValueError("live cohort requires cohort_source_mode=True")
        if self.p.backfill_start:
            raise ValueError("live cohort raw source mode requires backfill_start=False")
        self._validate_cohort_store_raw_mode(self.store)
        if self._live_bar_cohort is not None:
            raise ValueError("BtApiFeed is already bound to a live bar cohort")
        member = cohort.member_for_feed(self)
        if member is None or member.feed_ref is not self:
            raise ValueError("live bar cohort does not own this exact BtApiFeed")
        if self.p.cohort_source_origin is not member.source_origin:
            raise ValueError("feed and cohort do not share the exact source-origin declaration")
        feed_lines = set(self.getlinealiases())
        unsupported_lines = tuple(name for name in member.line_fields if name not in feed_lines)
        if unsupported_lines:
            raise ValueError(
                "live cohort member declares unsupported BtApiFeed line fields: {!r}".format(
                    unsupported_lines
                )
            )
        if self._cohort_history_source is None or self._cohort_live_source is None:
            raise ValueError(
                "live cohort explicit bar sources must be replayable tuple/list values"
            )
        if (
            type(self._cohort_history_source) is not tuple
            or type(self._cohort_live_source) is not tuple
        ):
            raise ValueError("live cohort explicit bar sources must use immutable tuples")
        if any(
            type(event) is not _MAPPING_PROXY_TYPE
            for source in (self._cohort_history_source, self._cohort_live_source)
            for event in source
        ):
            raise ValueError(
                "live cohort saved bar events must be immutable MappingProxyType mappings"
            )
        calendar_slots = cohort._calendar.slots
        if len(self._cohort_history_source) + len(self._cohort_live_source) > (
            len(calendar_slots) + cohort.max_pending_slots
        ):
            raise ValueError("live cohort saved source exceeds the finite calendar bound")
        # Creating iterators is side-effect-free.  Cerebro stages every exact
        # member before asking any feed to publish this state or clear its
        # legacy, provenance-free queues.
        return _PreparedLiveBarCohortActivation(
            feed_ref=self,
            cohort=cohort,
            clock=clock,
            history_iter=iter(self._cohort_history_source),
            live_iter=iter(self._cohort_live_source),
            # Cohort owns this immutable-after-construction lookup. Reuse it
            # rather than building another calendar-sized dictionary/feed.
            slot_index_by_close=cohort._slot_indices_by_close,
        )

    @staticmethod
    def _validate_cohort_store_raw_mode(store):
        """Require Store bars to remain raw until cohort capture."""
        if store is None or not callable(getattr(store, "poll_live", None)):
            return
        if getattr(store, "preserve_raw_bars", None) is not True:
            raise ValueError("live cohort Store polling requires preserve_raw_bars=True")

    def _live_bar_cohort_activation_snapshot(self):
        """Capture mutable feed state so Cerebro can roll back a failed commit."""
        return (
            self._live_bar_cohort,
            self._cohort_clock,
            self._cohort_history_iter,
            self._cohort_live_iter,
            self._cohort_history_exhausted,
            self._cohort_live_exhausted,
            self._cohort_history_lookahead,
            self._cohort_live_lookahead,
            self._cohort_store_lookahead,
            self._cohort_completed_lookahead,
            self._cohort_slot_index_by_close,
            self._cohort_last_delivered_slot_index,
            self._cohort_armed_envelope,
            self._cohort_staged_delivery,
            self._cohort_delivery_failed,
            self._history,
            self._live,
        )

    def _commit_live_bar_cohort_activation(self, prepared):
        """Publish previously validated state; Cerebro calls this in phase two."""
        self._live_bar_cohort = prepared.cohort
        self._cohort_clock = prepared.clock
        self._cohort_history_iter = prepared.history_iter
        self._cohort_live_iter = prepared.live_iter
        self._cohort_slot_index_by_close = prepared.slot_index_by_close
        # Swap in empty queues only after every feed was validated. Keeping the
        # prior deque objects in Cerebro's rollback snapshot avoids copying up
        # to a full finite history merely to make activation reversible.
        self._history = collections.deque()
        self._live = collections.deque()

    def _restore_live_bar_cohort_activation(self, snapshot):
        """Restore the exact pre-activation feed state after a commit failure."""
        (
            self._live_bar_cohort,
            self._cohort_clock,
            self._cohort_history_iter,
            self._cohort_live_iter,
            self._cohort_history_exhausted,
            self._cohort_live_exhausted,
            self._cohort_history_lookahead,
            self._cohort_live_lookahead,
            self._cohort_store_lookahead,
            self._cohort_completed_lookahead,
            self._cohort_slot_index_by_close,
            self._cohort_last_delivered_slot_index,
            self._cohort_armed_envelope,
            self._cohort_staged_delivery,
            self._cohort_delivery_failed,
            self._history,
            self._live,
        ) = snapshot

    def _cohort_source_is_exhausted(self):
        """Report EOF only for finite sources with an explicit end contract."""
        if self._live_bar_cohort is None:
            return False
        if not self._cohort_history_exhausted or not self._cohort_live_exhausted:
            return False
        if self._cohort_history_lookahead is not _COHORT_MISSING:
            return False
        if self._cohort_live_lookahead is not _COHORT_MISSING:
            return False
        if self._cohort_store_lookahead is not _COHORT_MISSING:
            return False
        if self._cohort_completed_lookahead is not _COHORT_MISSING:
            return False
        if self._bar_builders:
            return False

        store = self.store
        if store is None:
            return True
        source_exhausted = getattr(store, "is_source_exhausted", None)
        if callable(source_exhausted):
            try:
                return bool(source_exhausted(self._dataname))
            except TypeError:
                return bool(source_exhausted())
        # A store with a polling API is live unless it explicitly declares
        # exhaustion.  A store used only for startup/backfill is finite.
        return not any(
            callable(getattr(store, name, None))
            for name in ("poll_live", "poll_tick", "poll_orderbook")
        )

    def _cohort_event_slot_index(self, event):
        close_time = _tick_value(event, "bucket_end", default=None)
        if not isinstance(close_time, _dt.datetime):
            return None
        if close_time.tzinfo is None or close_time.utcoffset() is None:
            return None
        return self._cohort_slot_index_by_close.get(close_time.astimezone(_UTC))

    def _cohort_max_collect_slot(self):
        next_slot = self._cohort_last_delivered_slot_index + 1
        return next_slot + self._live_bar_cohort.max_pending_slots - 1

    def _cohort_capture_source(self, event, source_role, received_monotonic_ns, max_slot):
        slot_index = self._cohort_event_slot_index(event)
        if slot_index is not None and slot_index > max_slot:
            return False
        self._live_bar_cohort.capture_bar(
            self,
            event,
            source_role=source_role,
            received_monotonic_ns=received_monotonic_ns,
        )
        return True

    def _cohort_prepare_deadline_expired(self, deadline_ns):
        if deadline_ns is None:
            return False
        clock = self._cohort_clock
        monotonic_ns = getattr(clock, "monotonic_ns", None)
        if not callable(monotonic_ns):
            raise RuntimeError("live cohort feed has no monotonic clock")
        now_ns = monotonic_ns()
        if type(now_ns) is not int or now_ns <= 0:
            raise ValueError("live cohort clock returned an invalid monotonic sample")
        return now_ns >= deadline_ns

    def _cohort_next_source_item(self, role):
        if role == "history":
            lookahead_name = "_cohort_history_lookahead"
            iterator_name = "_cohort_history_iter"
            exhausted_name = "_cohort_history_exhausted"
        else:
            lookahead_name = "_cohort_live_lookahead"
            iterator_name = "_cohort_live_iter"
            exhausted_name = "_cohort_live_exhausted"
        lookahead = getattr(self, lookahead_name)
        if lookahead is not _COHORT_MISSING:
            setattr(self, lookahead_name, _COHORT_MISSING)
            return lookahead
        if getattr(self, exhausted_name):
            return _COHORT_MISSING
        try:
            return next(getattr(self, iterator_name))
        except StopIteration:
            setattr(self, exhausted_name, True)
            return _COHORT_MISSING

    def _cohort_collect_source(self, now_monotonic_ns, *, deadline_ns=None):
        """Capture a bounded prefix without advancing lines.

        The deadline is cooperative: one provider poll/normalization call cannot
        be preempted, but consumed events finish validation/capture before this
        method yields so they are never silently dropped.
        """
        cohort = self._live_bar_cohort
        if cohort is None:
            return 0
        if self._cohort_delivery_failed or cohort.frozen:
            return 0

        max_slot = self._cohort_max_collect_slot()
        budget = cohort.max_pending_slots
        collected = 0

        # Preserve history-before-live ordering so overlap deduplication can
        # only move from history to live, never back across the cutover.
        for source_role in ("history", "live"):
            while collected < budget:
                if self._cohort_prepare_deadline_expired(deadline_ns):
                    return collected
                event = self._cohort_next_source_item(source_role)
                if event is _COHORT_MISSING:
                    break
                expired_after_read = self._cohort_prepare_deadline_expired(deadline_ns)
                slot_index = self._cohort_event_slot_index(event)
                if slot_index is not None and slot_index > max_slot:
                    lookahead_name = (
                        "_cohort_history_lookahead"
                        if source_role == "history"
                        else "_cohort_live_lookahead"
                    )
                    setattr(self, lookahead_name, event)
                    if expired_after_read:
                        return collected
                    break
                self._cohort_capture_source(event, source_role, now_monotonic_ns, max_slot)
                collected += 1
                if expired_after_read or self._cohort_prepare_deadline_expired(deadline_ns):
                    return collected
            if collected >= budget:
                return collected
            if source_role == "history" and not self._cohort_history_exhausted:
                # Do not let live ticks overtake historical prewarm rows.
                return collected

        # Aggregated bar events are captured in _enqueue_bar_event. Keep that
        # queue bounded to one lookahead when the calendar window is full.
        if self._cohort_completed_lookahead is not _COHORT_MISSING:
            if self._cohort_prepare_deadline_expired(deadline_ns):
                return collected
            event = self._cohort_completed_lookahead
            slot_index = self._cohort_event_slot_index(event)
            if slot_index is not None and slot_index > max_slot:
                return collected
            self._cohort_completed_lookahead = _COHORT_MISSING
            self._cohort_capture_source(event, "live", now_monotonic_ns, max_slot)
            collected += 1
            if self._cohort_prepare_deadline_expired(deadline_ns):
                return collected

        if collected >= budget:
            return collected

        # Drain a fixed amount per engine round. Feed._check remains a strict
        # no-consumption path, and no per-feed sleep occurs here.
        drained = self._drain_live_ticks(limit=64, deadline_ns=deadline_ns)
        expired_after_ticks = self._cohort_prepare_deadline_expired(deadline_ns)
        if not expired_after_ticks:
            self._drain_live_orderbooks(limit=64, deadline_ns=deadline_ns)
        if not self._cohort_prepare_deadline_expired(deadline_ns):
            self._flush_ready_bars(reason="cohort")
        if len(self._bar_builders) > cohort.max_pending_slots:
            cohort._freeze("feed_bar_builder_capacity_exceeded")
            self._cohort_delivery_failed = True
            raise RuntimeError("BtApiFeed cohort bar-builder capacity exceeded")
        if self._bar_builders and not self._cohort_prepare_deadline_expired(deadline_ns):
            self._handle_source_exhaustion()
        if drained:
            self._mark_live()
        if self._cohort_completed_lookahead is not _COHORT_MISSING:
            # Tick aggregation can finish a bar during this collection pass.
            # Capture that exact event now, before the engine starts a shared
            # missing-member wait; otherwise the next pass may arrive only at
            # the deadline and lose to the cohort's timeout check. Preserve
            # the same collection budget and calendar lookahead bound used by
            # the source queues above.
            event = self._cohort_completed_lookahead
            slot_index = self._cohort_event_slot_index(event)
            if slot_index is not None and slot_index > max_slot:
                return collected
            self._cohort_completed_lookahead = _COHORT_MISSING
            self._cohort_capture_source(event, "live", now_monotonic_ns, max_slot)
            collected += 1
        if collected >= budget or self._cohort_prepare_deadline_expired(deadline_ns):
            return collected

        # Direct completed-bar sources retain their original event schema.
        while collected < budget and self.store is not None:
            if self._cohort_prepare_deadline_expired(deadline_ns):
                return collected
            if self._cohort_store_lookahead is not _COHORT_MISSING:
                event = self._cohort_store_lookahead
                self._cohort_store_lookahead = _COHORT_MISSING
            else:
                poll_live = getattr(self.store, "poll_live", None)
                if not callable(poll_live):
                    break
                event = poll_live(self._dataname)
            if event is None:
                break
            expired_after_poll = self._cohort_prepare_deadline_expired(deadline_ns)
            slot_index = self._cohort_event_slot_index(event)
            if slot_index is not None and slot_index > max_slot:
                self._cohort_store_lookahead = event
                if expired_after_poll:
                    return collected
                break
            self._cohort_capture_source(event, "live", now_monotonic_ns, max_slot)
            collected += 1
            self._mark_live()
            if expired_after_poll or self._cohort_prepare_deadline_expired(deadline_ns):
                return collected
        return collected

    def _prepare_live_bar_cohort_delivery(self, envelope):
        """Preflight one exact envelope without mutating feed or line state."""
        cohort = self._live_bar_cohort
        if cohort is None or self._cohort_delivery_failed:
            raise RuntimeError("BtApiFeed is not ready for cohort delivery")
        if cohort.prepared_envelope(self) is not envelope:
            raise ValueError("Cerebro supplied a non-prepared cohort envelope")
        raw_values = cohort.preflight_delivery(self, envelope)
        close_time = envelope.close_time
        datetime_value = date2num(close_time.replace(tzinfo=None))
        return _PreparedLiveBarCohortDelivery(
            feed_ref=self,
            envelope=envelope,
            raw_values=raw_values,
            close_time=close_time,
            datetime_value=datetime_value,
        )

    def _arm_live_bar_cohort_envelope(self, envelope, prepared):
        """Bind an exact preflight result for the following normal feed load."""
        if (
            type(prepared) is not _PreparedLiveBarCohortDelivery
            or prepared.feed_ref is not self
            or prepared.envelope is not envelope
        ):
            raise ValueError("Cerebro supplied a mismatched prepared cohort delivery")
        if self._cohort_armed_envelope is not None or self._cohort_staged_delivery is not None:
            raise RuntimeError("BtApiFeed already has an armed cohort delivery")
        cohort = self._live_bar_cohort
        if cohort is None or self._cohort_delivery_failed:
            raise RuntimeError("BtApiFeed is not ready for cohort delivery")
        if cohort.prepared_envelope(self) is not envelope:
            raise ValueError("Cerebro supplied a non-prepared cohort envelope")
        self._cohort_armed_envelope = envelope
        self._cohort_staged_delivery = prepared

    def _preflight_live_bar_cohort_delivery_commit(self, envelope, prepared):
        """Validate staged line state before the cohort commits receipts atomically."""
        cohort = self._live_bar_cohort
        if (
            cohort is None
            or self._cohort_delivery_failed
            or self._cohort_armed_envelope is not envelope
            or self._cohort_staged_delivery is not prepared
            or type(prepared) is not _PreparedLiveBarCohortDelivery
            or prepared.feed_ref is not self
            or prepared.envelope is not envelope
        ):
            self._cohort_delivery_failed = True
            raise ValueError("BtApiFeed cohort delivery stage changed before commit")
        if cohort.prepared_envelope(self) is not envelope:
            self._cohort_delivery_failed = True
            raise ValueError("BtApiFeed cohort envelope changed before commit")
        line_values = (
            ("datetime", self.lines.datetime[0], prepared.datetime_value),
            ("open", self.lines.open[0], prepared.raw_values["open"]),
            ("high", self.lines.high[0], prepared.raw_values["high"]),
            ("low", self.lines.low[0], prepared.raw_values["low"]),
            ("close", self.lines.close[0], prepared.raw_values["close"]),
            ("volume", self.lines.volume[0], prepared.raw_values["volume"]),
            (
                "openinterest",
                self.lines.openinterest[0],
                prepared.raw_values.get("openinterest", 0.0),
            ),
        )
        member = cohort.member_for_feed(self)
        if member is None or member.feed_ref is not self:
            self._cohort_delivery_failed = True
            raise ValueError("BtApiFeed is no longer the exact live cohort member")
        declared_lines = set(member.line_fields)
        line_values += tuple(
            (
                name,
                getattr(self.lines, name)[0],
                prepared.raw_values[name] if name in declared_lines else math.nan,
            )
            for name in _LIVE_COHORT_EXTRA_LINES
        )

        def values_match(actual, expected):
            if actual == expected:
                return True
            try:
                return math.isnan(float(actual)) and math.isnan(float(expected))
            except (TypeError, ValueError, OverflowError):
                return False

        if any(not values_match(actual, expected) for _name, actual, expected in line_values):
            self._cohort_delivery_failed = True
            raise ValueError("BtApiFeed line values differ from staged cohort delivery")
        return True

    def _commit_live_bar_cohort_delivery(self, envelope, prepared):
        """Publish local feed metadata after the cohort atomically records receipts."""
        # Cerebro preflights every feed and calls LiveBarCohort's batch commit
        # before entering this assignment-only phase. Keeping receipt mutation
        # out of this method prevents a failure on one feed from publishing a
        # partial cohort batch.
        self._cohort_last_delivered_slot_index = envelope.slot_index
        self._cohort_armed_envelope = None
        self._cohort_staged_delivery = None
        return True

    def _abort_live_bar_cohort_delivery(self):
        """Discard staged state after Cerebro rolls back a failed batch write."""
        self._cohort_armed_envelope = None
        self._cohort_staged_delivery = None
        self._cohort_delivery_failed = True

    def _load_live_bar_cohort_envelope(self):
        cohort = self._live_bar_cohort
        envelope = self._cohort_armed_envelope
        prepared = self._cohort_staged_delivery
        if self._cohort_delivery_failed:
            return None
        if envelope is None or prepared is None:
            return None
        if (
            cohort.prepared_envelope(self) is not envelope
            or prepared.feed_ref is not self
            or prepared.envelope is not envelope
        ):
            self._cohort_delivery_failed = True
            raise ValueError("armed cohort delivery is no longer the prepared object")
        try:
            raw_values = prepared.raw_values
            self.lines.datetime[0] = prepared.datetime_value
            self.lines.open[0] = raw_values["open"]
            self.lines.high[0] = raw_values["high"]
            self.lines.low[0] = raw_values["low"]
            self.lines.close[0] = raw_values["close"]
            self.lines.volume[0] = raw_values["volume"]
            self.lines.openinterest[0] = raw_values.get("openinterest", 0.0)
            member = cohort.member_for_feed(self)
            if member is None or member.feed_ref is not self:
                self._cohort_delivery_failed = True
                raise ValueError("BtApiFeed is no longer the exact live cohort member")
            declared_lines = set(member.line_fields)
            for name in _LIVE_COHORT_EXTRA_LINES:
                value = raw_values[name] if name in declared_lines else math.nan
                getattr(self.lines, name)[0] = value
            return True
        except Exception:
            self._cohort_delivery_failed = True
            raise

    def _dispatch_live_bar_cohort_envelope(self, envelope):
        """Dispatch notify_bar only after Cerebro verifies a complete batch."""
        if envelope.feed_ref is not self:
            return False
        if envelope.source_role == "live":
            # Status notification can append to a user-visible notification
            # queue and therefore may fail. Run it only after Cerebro has
            # committed every member's lines and local delivery metadata.
            self._mark_live()
        if envelope.source_role != "live":
            return False
        if not self.p.dispatch_bars:
            return False
        event = envelope.event_ref
        if event is None:
            raise ValueError("live cohort envelope lost its source event")
        if isinstance(event, Mapping):
            event = dict(event)
            event.update(dict(envelope.raw_values))
            event.update(
                {
                    "datetime": envelope.close_time,
                    "timestamp": envelope.close_time.timestamp(),
                    "bucket_start": envelope.bucket_start,
                    "bucket_end": envelope.close_time,
                    "available_at": envelope.available_at,
                    "trading_day": envelope.trading_day,
                    "session_segment": envelope.session_segment,
                    "connection_generation": envelope.connection_generation,
                    "bar_sequence": envelope.feed_sequence,
                    "bar_id": envelope.bar_id,
                    "complete": envelope.complete,
                    "quality": envelope.quality,
                    "quality_flags": envelope.quality_flags,
                }
            )
        else:
            event = copy.copy(event)
            for name, value in envelope.raw_values.items():
                setattr(event, name, value)
            for name, value in (
                ("datetime", envelope.close_time),
                ("timestamp", envelope.close_time.timestamp()),
                ("bucket_start", envelope.bucket_start),
                ("bucket_end", envelope.close_time),
                ("available_at", envelope.available_at),
                ("trading_day", envelope.trading_day),
                ("session_segment", envelope.session_segment),
                ("connection_generation", envelope.connection_generation),
                ("bar_sequence", envelope.feed_sequence),
                ("bar_id", envelope.bar_id),
                ("complete", envelope.complete),
                ("quality", envelope.quality),
                ("quality_flags", envelope.quality_flags),
            ):
                setattr(event, name, value)
        self._dispatch_event(
            channel_type="bar",
            priority=EventPriority.BAR,
            event_data=event,
        )
        return True

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

            if self.store is None:
                self.store = getattr(self, "_store", None)

            if self.p.cohort_source_mode:
                self._validate_cohort_store_raw_mode(self.store)

            if self.store is None:
                self._session_active = True
                return

            self.store.start(data=self)
            self.store.register(self)

            service_read_only = bool(getattr(self.store, "_service_read_only", False))
            if service_read_only:
                # Establish the bounded live cursor before history so bars
                # published during backfill can be replayed and deduplicated.
                self.store.subscribe(self._dataname)

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
            self._ctp_first_bucket_scope = None
            self._ctp_first_bucket_start = None
            self._last_ctp_scope = None
            self._highest_ctp_scope = None
            self._tick_consumer_claimed = False
            self._session_active = False

    def islive(self) -> bool:
        """Return whether this feed has a configured live data source."""
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

        live_cache = getattr(store, "_live_bars", {})
        return bool(live_cache.get(self._dataname))

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
        if self._live_bar_cohort is not None:
            # The cohort runner owns bounded collection and the one shared
            # wait.  Feed._check must not consume events or sleep per member.
            return
        super()._check(forcedata=forcedata)
        if self.p.orderbook_as_ticks:
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

    def _drain_live_ticks(self, limit=None, *, stop_after_queued_bar=True, deadline_ns=None):
        """Drain available ticks subject to the caller's count and bar bounds.

        Normal load and cohort collection stop after the next queued bar so
        its callback stays paired with the matching line turn.  The legacy
        Tick-timeframe ``_check`` path may opt out of that queued-bar stop.
        Completed aggregate bars still end a drain on every path.
        """
        if self.store is None or not hasattr(self.store, "poll_tick"):
            return False

        drained = False

        drained_count = 0
        while limit is None or drained_count < limit:
            if self._cohort_prepare_deadline_expired(deadline_ns):
                break
            bar_sequence_before = self._bar_sequence
            queued_bars_before = len(self._live)
            tick = self.store.poll_tick(self._dataname)
            if tick is None:
                break
            expired_after_poll = self._cohort_prepare_deadline_expired(deadline_ns)
            drained = True
            drained_count += 1

            if self._validate_raw_cohort_tick_price(tick) is False:
                self._mark_event_dropped(tick, "invalid_ctp_source_tick")
                continue
            self._prepare_tick(tick)
            expired_after_normalize = self._cohort_prepare_deadline_expired(deadline_ns)

            if self._handle_event_health(tick):
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
        return drained

    def _validate_raw_cohort_tick_price(self, tick):
        """Reject malformed source values before tolerant tick normalization."""
        cohort = self._live_bar_cohort
        raw_ctp_tick = _tick_value(tick, "ctp_raw_tick", default=None)
        if raw_ctp_tick is not None:
            problem = _raw_ctp_tick_problem(
                raw_ctp_tick,
                strict_action_day=cohort is not None,
            )
            if problem is not None:
                code, field_name, category, frozen_reason = problem
                if cohort is None:
                    # Preserve ordinary-feed behavior: invalid direct-CTP
                    # ticks do not enter event dispatch or a bar bucket.
                    return False
                member = cohort.member_for_feed(self)
                instrument = member.instrument if member is not None else self._dataname
                report = {
                    "source": "BtApiFeed.ctp_tick",
                    "instrument": _bounded_context_value(instrument),
                    "field": field_name,
                    "category": category,
                    "generation": _bounded_context_value(raw_ctp_tick.get("connection_generation")),
                    "sequence": _bounded_context_value(
                        _tick_value(tick, "ingest_seq", "sequence", default=None)
                    ),
                    "reason": code,
                }
                cohort._freeze(frozen_reason)
                self._cohort_delivery_failed = True
                raise _live_tick_validation_error(report, code=code)

        if cohort is None:
            return True

        field_name, raw_price, present = _raw_tick_field(tick, _TICK_PRICE_FIELDS)
        category = _tick_price_category(raw_price, present)
        if category is None:
            return True

        member = cohort.member_for_feed(self)
        instrument = member.instrument if member is not None else self._dataname
        report = {
            "source": "BtApiFeed.tick",
            "instrument": _bounded_context_value(instrument),
            "field": field_name,
            "category": category,
            "generation": _bounded_context_value(
                _tick_value(tick, "connection_generation", "stream_generation", default=None)
            ),
            "sequence": _bounded_context_value(
                _tick_value(tick, "ingest_seq", "sequence", default=None)
            ),
            "reason": "LAST_PRICE_INVALID",
        }
        cohort._freeze("invalid_source_tick_price")
        self._cohort_delivery_failed = True
        raise _live_tick_validation_error(report)

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

    def _drain_live_orderbooks(self, limit=None, *, deadline_ns=None):
        if self.store is None or not hasattr(self.store, "poll_orderbook"):
            return False

        drained = False

        drained_count = 0
        while limit is None or drained_count < limit:
            if self._cohort_prepare_deadline_expired(deadline_ns):
                break
            orderbook = self.store.poll_orderbook(self._dataname)
            if orderbook is None:
                break
            expired_after_poll = self._cohort_prepare_deadline_expired(deadline_ns)
            drained = True
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

        raw_ctp_tick = _tick_value(tick, "ctp_raw_tick", default=None)
        if isinstance(raw_ctp_tick, Mapping) and self._timeframe != TimeFrame.Ticks:
            scope = (
                raw_ctp_tick.get("connection_generation"),
                raw_ctp_tick.get("TradingDay"),
            )
            bucket_start = self._get_bucket_start(tick_dt)
            if self._ctp_first_bucket_scope != scope:
                self._ctp_first_bucket_scope = scope
                self._ctp_first_bucket_start = bucket_start
            if bucket_start == self._ctp_first_bucket_start:
                # The first cumulative observation is a baseline, so the rest
                # of its partially observed minute cannot form a complete bar.
                return

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
            current["trade_count"] += 1
            for field, aliases, mismatch_flag in (
                ("rules_hash", ("rules_hash",), "RULES_HASH_CHANGED"),
                ("session_segment", ("session_segment",), "SESSION_SEGMENT_CHANGED"),
                ("trading_day", ("trading_day", "TradingDay"), "TRADING_DAY_CHANGED"),
            ):
                value = _tick_value(tick, *aliases, default=current[field])
                if value != current[field]:
                    current["quality_flags"].add(mismatch_flag)
            current["quality_flags"].update(_tick_value(tick, "quality_flags", default=()) or ())
            self._capture_quote(current, tick)
            self._note_service_recovery_quote_from_tick(tick, tick_ts)
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
            "quote_events": [],
            "action_day": _tick_value(tick, "action_day", "ActionDay", default=""),
            "rules_hash": _tick_value(tick, "rules_hash", default=None),
            "session_segment": _tick_value(tick, "session_segment", default=None),
            "connection_generation": _tick_value(
                tick, "connection_generation", "stream_generation", default=None
            ),
            "first_ingest_seq": ingest_seq,
            "last_ingest_seq": ingest_seq,
            "trade_count": 1,
            "volume_complete": bool(_tick_value(tick, "volume_complete", default=True)),
            "quality_flags": set(_tick_value(tick, "quality_flags", default=()) or ()),
        }

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
                tick, "connection_generation", "stream_generation", default=None
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
        """Freeze a prepared tick as a live bar-bound quote record.

        Tick provenance supplies the event fields; the explicit Cerebro feed
        name supplies the shared contract identity.  The caller-owned evidence
        provider may add its candidate id on hand-off.
        """
        raw_event = _tick_value(tick, "event_time_utc", default=None)
        event_time = _as_utc_datetime(
            raw_event
            if raw_event not in (None, "")
            else _tick_value(tick, "timestamp", "datetime", default=None)
        )
        if event_time is None:
            return None
        raw_receive = _tick_value(tick, "recv_time_utc", default=None)
        receive_time = _as_utc_datetime(raw_receive) if raw_receive not in (None, "") else None
        if receive_time is None:
            wall = _finite_market_number(
                _tick_value(tick, "received_wall_time", "local_time", default=None)
            )
            if wall is not None:
                receive_time = _dt.datetime.fromtimestamp(wall, _UTC)
        if receive_time is None:
            return None
        received_mono = _tick_value(tick, "recv_monotonic_ns", default=None)
        if received_mono in (None, ""):
            received_mono = _tick_value(tick, "received_monotonic_ns", default=None)
        if not isinstance(received_mono, int) or received_mono <= 0:
            return None
        return {
            "symbol": self._evidence_symbol(),
            "exchange": str(
                _tick_value(tick, "exchange", "exchange_id", "ExchangeID", default="") or ""
            ),
            "event_time": event_time,
            "received_at": receive_time,
            "received_monotonic_ns": received_mono,
            "ingest_seq": _tick_value(tick, "ingest_seq", "sequence", default=None),
            "generation": _tick_value(
                tick, "connection_generation", "stream_generation", default=None
            ),
            "trading_day": str(_tick_value(tick, "trading_day", "TradingDay", default="") or ""),
            "action_day": str(_tick_value(tick, "action_day", "ActionDay", default="") or ""),
            "session_segment": str(_tick_value(tick, "session_segment", default="") or ""),
            "rules_hash": str(_tick_value(tick, "rules_hash", default="") or ""),
            "clock_domain": str(_tick_value(tick, "clock_domain_id", default="") or ""),
            "clock_mode": "live",
            "quality": str(_tick_value(tick, "quality", default="") or ""),
            "volume_complete": bool(_tick_value(tick, "volume_complete", default=False)),
            "bid": _finite_market_number(
                _tick_value(tick, "bid_price", "bid", "BidPrice1", default=None)
            ),
            "ask": _finite_market_number(
                _tick_value(tick, "ask_price", "ask", "AskPrice1", default=None)
            ),
            "bid_qty": _finite_market_number(
                _tick_value(tick, "bid_volume", "bid_size", "BidVolume1", default=None)
            ),
            "ask_qty": _finite_market_number(
                _tick_value(tick, "ask_volume", "ask_size", "AskVolume1", default=None)
            ),
            "last": _finite_market_number(
                _tick_value(tick, "price", "last_price", "LastPrice", default=None)
            ),
            "source": str(_tick_value(tick, "source", default="") or ""),
            "event_time_source": str(
                _tick_value(tick, "event_time_source", default="") or "ctp-action-day-update-time"
            ),
        }

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
            _safe_log("warning", "btapifeed:1431 fallback on Exception")
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
