"""Explicit replay-only adapter for the neutral SDK replay market contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from types import SimpleNamespace


class ReplayMarketAdapterError(ValueError):
    """Finite error raised when a replay port or event violates its binding."""

    _CODES = frozenset(
        {
            "REPLAY_CONTRACT_UNAVAILABLE",
            "REPLAY_PORT_INVALID",
            "REPLAY_BINDING_MISMATCH",
            "REPLAY_SEQUENCE_GAP",
            "REPLAY_SYMBOL_MISMATCH",
            "REPLAY_EOF_WATERMARK_INVALID",
        }
    )

    def __init__(self, code):
        self.code = code if type(code) is str and code in self._CODES else "REPLAY_PORT_INVALID"
        super().__init__(self.code)


def _load_replay_contracts():
    try:
        from bt_api_py.replay_market_contracts import (
            REPLAY_MARKET_TICK_SCHEMA_VERSION_TEXT,
            ReplayMarketMode,
            ReplayMarketPollStatus,
            ReplayMarketTickEvent,
            ReplayMarketTickPollResult,
            ReplayMarketTickPort,
            ReplayVolumeSemantics,
            MarketInstrumentKey,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        raise ReplayMarketAdapterError("REPLAY_CONTRACT_UNAVAILABLE") from exc
    return (
        REPLAY_MARKET_TICK_SCHEMA_VERSION_TEXT,
        ReplayMarketMode,
        ReplayMarketPollStatus,
        ReplayMarketTickEvent,
        ReplayMarketTickPollResult,
        ReplayMarketTickPort,
        ReplayVolumeSemantics,
        MarketInstrumentKey,
    )


class ReplayMarketTickAdapter:
    """Poll and project one exact replay port without adding live evidence."""

    def __init__(self, port, symbol):
        (
            self._schema_version,
            self._mode_type,
            self._poll_status_type,
            self._event_type,
            self._poll_result_type,
            self._port_type,
            self._volume_type,
            self._instrument_type,
        ) = _load_replay_contracts()
        if not isinstance(port, self._port_type):
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        if type(symbol) is not str or not symbol:
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        mode = getattr(port, "replay_mode", None)
        source_ref = getattr(port, "replay_source_ref", None)
        replay_epoch = getattr(port, "replay_epoch", None)
        instrument = getattr(port, "instrument", None)
        if (
            type(mode) is not self._mode_type
            or type(source_ref) is not str
            or not source_ref
            or type(replay_epoch) is not str
            or not replay_epoch
            or type(instrument) is not self._instrument_type
            or not callable(getattr(port, "start_replay", None))
            or not callable(getattr(port, "poll_replay_tick", None))
            or not callable(getattr(port, "close_replay", None))
        ):
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        if symbol not in {instrument.instrument_id, instrument.native_symbol}:
            raise ReplayMarketAdapterError("REPLAY_SYMBOL_MISMATCH")
        self._port = port
        self._symbol = symbol
        self._mode = mode
        self._source_ref = source_ref
        self._epoch = replay_epoch
        self._instrument = instrument
        self.source_mode = mode.value
        self.replay_source_ref = source_ref
        self.replay_epoch = replay_epoch
        self.instrument = instrument
        self._last_sequence = None
        self._last_event_time = None
        self._started = False
        self._ever_started = False
        self._exhausted = False
        self._final_event_time_watermark_utc = None

    @property
    def exhausted(self):
        return self._exhausted

    @property
    def final_event_time_watermark_utc(self):
        return self._final_event_time_watermark_utc

    @property
    def has_events(self):
        return self._last_sequence is not None

    def start(self):
        """Start the local replay reader without invoking generic Store hooks."""
        if self._started or self._ever_started or self._exhausted:
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        result = self._port.start_replay(self._symbol)
        if result is not None:
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        self._started = True
        self._ever_started = True

    def close(self):
        """Close only the explicitly bound replay reader."""
        if not self._started:
            return
        result = self._port.close_replay(self._symbol)
        if result is not None:
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        self._started = False

    def poll(self):
        """Return one projected event, or ``None`` after explicit terminal EOF."""
        if not self._started:
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        if self._exhausted:
            return None
        result = self._port.poll_replay_tick(self._symbol)
        if type(result) is not self._poll_result_type:
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        if result.status is self._poll_status_type.EOF:
            watermark = result.final_event_time_watermark_utc
            if self.has_events and watermark is None:
                raise ReplayMarketAdapterError("REPLAY_EOF_WATERMARK_INVALID")
            if self._last_event_time is not None and watermark < self._last_event_time:
                raise ReplayMarketAdapterError("REPLAY_EOF_WATERMARK_INVALID")
            self._exhausted = True
            self._final_event_time_watermark_utc = watermark
            return None
        if result.status is not self._poll_status_type.EVENT:
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        event = result.event
        if type(event) is not self._event_type:
            raise ReplayMarketAdapterError("REPLAY_PORT_INVALID")
        if (
            event.mode is not self._mode
            or event.source_ref != self._source_ref
            or event.replay_epoch != self._epoch
            or event.instrument != self._instrument
        ):
            raise ReplayMarketAdapterError("REPLAY_BINDING_MISMATCH")
        if event.instrument.instrument_id != self._symbol and event.instrument.native_symbol != self._symbol:
            raise ReplayMarketAdapterError("REPLAY_SYMBOL_MISMATCH")
        if self._last_sequence is not None and event.sequence != self._last_sequence + 1:
            raise ReplayMarketAdapterError("REPLAY_SEQUENCE_GAP")
        self._last_sequence = event.sequence
        if self._last_event_time is None or event.event_time_utc > self._last_event_time:
            self._last_event_time = event.event_time_utc
        semantics = event.volume_semantics
        return SimpleNamespace(
            schema="sdk.replay.market.tick",
            schema_version=self._schema_version,
            source_mode=event.mode.value,
            replay_source_ref=event.source_ref,
            replay_epoch=event.replay_epoch,
            replay_sequence=event.sequence,
            instrument=event.instrument,
            instrument_id=event.instrument.instrument_id,
            symbol=event.instrument.native_symbol,
            exchange=event.instrument.venue,
            asset_type=event.instrument.product_type,
            provider=event.instrument.provider,
            environment=event.instrument.environment,
            event_time_utc=event.event_time_utc,
            provider_event_time_utc=event.event_time_utc.isoformat().replace("+00:00", "Z"),
            timestamp=event.event_time_utc.timestamp(),
            trading_day=event.trading_day.isoformat() if event.trading_day else None,
            event_session_date=(
                event.event_session_date.isoformat() if event.event_session_date else None
            ),
            price=event.last_price,
            last_price=event.last_price,
            bid_price=event.bid_price,
            ask_price=event.ask_price,
            bid_volume=event.bid_size,
            ask_volume=event.ask_size,
            bid_size=event.bid_size,
            ask_size=event.ask_size,
            lower_limit=event.lower_limit,
            upper_limit=event.upper_limit,
            volume=event.delta_volume,
            delta_volume=event.delta_volume,
            cumulative_volume=event.cumulative_volume,
            cum_volume=event.cumulative_volume,
            volume_semantics=semantics.value,
            volume_complete=semantics is self._volume_type.DELTA,
            volume_quality=(
                "REPLAY_DELTA" if semantics is self._volume_type.DELTA else "UNAVAILABLE"
            ),
            turnover=event.turnover,
            open_interest=event.open_interest,
            # Replay event time is the only time carried across this adapter.
            # Host receive clocks and live stream identity are deliberately absent.
            recv_time_utc=None,
            recv_monotonic_ns=None,
            recv_monotonic=None,
            received_wall_time=None,
            received_monotonic_ns=None,
            local_time=None,
            exchange_time=None,
            clock_domain_id=None,
            source_clock_quality="unknown",
            receive_clock_quality="unknown",
            source_clock_error_ms=None,
            receive_clock_error_ms=None,
            freshness_status="unavailable",
            freshness_verified=False,
            freshness_reasons=("REPLAY_CLOCK_NOT_CALIBRATED",),
            data_clock_qualified=False,
            execution_eligible=False,
            connection_generation=None,
            subscription_epoch=None,
            ingest_seq=None,
            sequence=None,
            continuity_status="continuous",
            stale=False,
            stale_reason="",
            quality="REPLAY_ONLY",
            quality_flags=(),
        )


@dataclass
class ReplayBarEvent:
    """BT bar projection whose identity is exclusively replay scoped.

    It intentionally has no ``connection_generation``, ingress sequence,
    receive time, monotonic time, clock-domain, freshness, or authorization
    fields. ``replay_available_at`` is a deterministic event-time watermark,
    not a receive-clock observation.
    """

    timestamp: float
    symbol: str
    exchange: str
    venue: str
    asset_type: str
    source_mode: str
    replay_source_ref: str
    replay_epoch: str
    replay_bar_sequence: int
    first_replay_sequence: int
    last_replay_sequence: int
    replay_bucket_start: datetime
    replay_bucket_end: datetime
    replay_available_at: datetime
    replay_bar_status: str
    replay_close_reason: str
    trading_day: str
    event_session_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    openinterest: float
    replay_volume_complete: bool
    replay_quality_flags: tuple[str, ...] = ()
    replay_bar_id: str = ""
    datetime: object = None
    schema: str = "bt.replay.market.bar"
    schema_version: str = "bt.replay.market.bar.v1"

    @property
    def event_type(self):
        return "bar"

    @property
    def event_time_utc(self):
        return datetime.fromtimestamp(self.timestamp, timezone.utc)

    def to_dict(self):
        """Return a JSON-ready replay bar projection."""
        result = asdict(self)
        for name in (
            "replay_bucket_start",
            "replay_bucket_end",
            "replay_available_at",
            "datetime",
        ):
            value = getattr(self, name)
            if isinstance(value, datetime):
                result[name] = value.isoformat().replace("+00:00", "Z")
        result["event_time_utc"] = self.event_time_utc.isoformat().replace("+00:00", "Z")
        return result


__all__ = ["ReplayBarEvent", "ReplayMarketAdapterError", "ReplayMarketTickAdapter"]
