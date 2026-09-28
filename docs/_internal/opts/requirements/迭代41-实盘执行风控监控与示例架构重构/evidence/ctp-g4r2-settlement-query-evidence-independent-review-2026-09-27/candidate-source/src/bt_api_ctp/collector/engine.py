"""The exchange-agnostic collection orchestrator.

``run_once`` drives one collection window: query the universe, apply the
shard filter, connect, subscribe, buffer ticks, flush in batches, then write
the completeness report.  It depends only on the protocols, so any venue
implementation can be plugged in.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from bt_api_ctp.collector.buffer import TickBuffer
from bt_api_ctp.collector.health import CollectionHealthGuard, HealthThresholds
from bt_api_ctp.collector.protocols import (
    DEFAULT_ASSET_TYPES,
    EXCHANGES,
    InstrumentProvider,
    InstrumentSpec,
    MarketDataSubscriber,
    TickRecord,
)
from bt_api_ctp.collector.schedule import TradingCalendar, session_index
from bt_api_ctp.collector.shard import ShardConfig, select_instruments
from bt_api_ctp.collector.sink import DEFAULT_COMPACT_SEGMENTS, ParquetSink, SinkReport

_MAX_POLL_SECONDS = 0.2

_logger = logging.getLogger(__name__)


@dataclass
class CollectionConfig:
    """Everything one collection run needs besides its venue wiring."""

    data_root: Path | str
    #: Defaults to the whole market; a real deployment always narrows this.
    shard: ShardConfig = field(
        default_factory=lambda: ShardConfig(strategy="by_exchange", exchanges=EXCHANGES)
    )
    asset_types: tuple[str, ...] = DEFAULT_ASSET_TYPES
    per_instrument_cap: int = 100_000
    overflow_policy: str = "drop"
    flush_interval_sec: float = 5.0
    merge_existing: bool = True
    gap_threshold_sec: float = 60.0
    #: Pending staging segments per compaction; the memory/rewrite trade-off.
    compact_segment_count: int = DEFAULT_COMPACT_SEGMENTS
    #: Snapshot whose exchange timestamp is outside every session is not market
    #: data (CTP pushes one per instrument on subscribe).
    drop_outside_session: bool = True
    #: Adapt the gap threshold to each instrument's own cadence.
    gap_threshold_factor: float = 10.0
    #: Trading calendar used to score coverage; a window spanning a weekend must
    #: not count sessions that never happen.
    calendar: TradingCalendar | None = None
    #: 0 disables the heartbeat.  Unattended runs should keep it on.
    heartbeat_interval_sec: float = 60.0
    #: Per-instrument tick count at which a progress milestone is logged.
    tick_log_interval: int = 1000
    #: ``every`` reports each multiple of the interval with the cumulative
    #: count, ``off`` disables milestones (same as interval <= 0).
    tick_log_mode: str = "every"
    #: Watch the data *rate* and raise an error when the feed stalls.
    health_check_enabled: bool = True
    health: HealthThresholds = field(default_factory=HealthThresholds)


class _BufferHandler:
    """Bridge the subscriber callback to the buffer (no IO on this path)."""

    def __init__(self, buffer: TickBuffer) -> None:
        self._buffer = buffer
        self.accepted = 0

    def on_tick(self, tick: TickRecord) -> None:
        if self._buffer.append(tick):
            self.accepted += 1


class TickCollectionEngine:
    """Orchestrate provider, subscriber, buffer and sink."""

    def __init__(
        self,
        *,
        provider: InstrumentProvider,
        subscriber: MarketDataSubscriber,
        config: CollectionConfig,
    ) -> None:
        self._provider = provider
        self._subscriber = subscriber
        self._config = config
        self._cumulative: dict[str, int] = {}
        self._reported: dict[str, int] = {}

    @property
    def config(self) -> CollectionConfig:
        return self._config

    def _select(self, instruments):
        if self._config.asset_types:
            instruments = [
                spec for spec in instruments if spec.asset_type in self._config.asset_types
            ]
        return select_instruments(instruments, self._config.shard)

    def run_once(
        self, *, duration_sec: float | None = None, stop_event: Any = None
    ) -> SinkReport:
        """Collect for one window, then flush and report."""
        self._cumulative = {}
        self._reported = {}
        try:
            instruments = self._provider.fetch_instruments()
        finally:
            # The reference query is done (or failed); release the venue's
            # query session either way so it never outlives this call.
            close_provider = getattr(self._provider, "close", None)
            if callable(close_provider):
                close_provider()
        selected = self._select(instruments)
        buffer = TickBuffer(
            per_instrument_cap=self._config.per_instrument_cap,
            overflow_policy=self._config.overflow_policy,
        )
        if not selected:
            _logger.info("collection skipped: no instruments selected")
            return SinkReport(trading_day="", dropped_ticks=buffer.dropped_count())

        sink = ParquetSink(
            self._config.data_root,
            merge_existing=self._config.merge_existing,
            gap_threshold_sec=self._config.gap_threshold_sec,
            compact_segment_count=self._config.compact_segment_count,
            gap_threshold_factor=self._config.gap_threshold_factor,
            drop_outside_session=self._config.drop_outside_session,
            calendar=self._config.calendar,
        )
        handler = _BufferHandler(buffer)
        guard = (
            CollectionHealthGuard(self._config.health)
            if self._config.health_check_enabled
            else None
        )
        self._subscriber.set_handler(handler)
        self._subscriber.connect()
        # CTP depth callbacks carry no ExchangeID; hand the venue the
        # instrument -> exchange map so ticks keep their exchange directory.
        set_exchanges = getattr(self._subscriber, "set_instrument_exchanges", None)
        if callable(set_exchanges):
            set_exchanges({spec.instrument_id: spec.exchange_id for spec in selected})
        self._subscriber.subscribe([spec.instrument_id for spec in selected])
        self._report_subscription(selected)

        poll_seconds = min(_MAX_POLL_SECONDS, max(self._config.flush_interval_sec, 0.001))
        deadline = None
        if duration_sec is not None:
            deadline = time.monotonic() + float(duration_sec)
        started = time.monotonic()
        last_flush = started
        last_heartbeat = started
        trading_day = ""

        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                time.sleep(poll_seconds)
                now = time.monotonic()
                if buffer.should_flush() or (now - last_flush) >= self._config.flush_interval_sec:
                    trading_day = self._flush(sink, buffer, trading_day, guard)
                    last_flush = now
                if (
                    self._config.heartbeat_interval_sec > 0
                    and (now - last_heartbeat) >= self._config.heartbeat_interval_sec
                ):
                    stats_fn = getattr(self._subscriber, "subscription_stats", None)
                    stats = stats_fn() if callable(stats_fn) else {}
                    _logger.info(
                        "heartbeat: received=%d buffered=%d dropped=%d sub_ok=%s sub_failed=%s elapsed=%.0fs",
                        handler.accepted,
                        buffer.pending(),
                        buffer.dropped_count(),
                        stats.get("ok", "n/a"),
                        stats.get("failed", "n/a"),
                        now - started,
                    )
                    last_heartbeat = now
                    self._report_health(guard, now=now, subscribed=len(selected))
        finally:
            trading_day = self._flush(sink, buffer, trading_day, guard)
            self._subscriber.close()

        if not trading_day:
            _logger.info(
                "collection finished: no data persisted (received=%d)", handler.accepted
            )
            return SinkReport(trading_day="", dropped_ticks=buffer.dropped_count())
        report = sink.finalize(
            trading_day,
            dropped_ticks=buffer.dropped_count(),
            **self._session_diagnostics(),
        )
        _logger.info(
            "collection finished: trading_day=%s instruments=%d received=%d dropped=%d",
            report.trading_day,
            len(report.instruments),
            handler.accepted,
            buffer.dropped_count(),
        )
        return report

    def _current_session(self) -> int | None:
        """Session index the wall clock currently falls in, else ``None``."""
        return session_index(datetime.now())

    def _report_health(
        self, guard: CollectionHealthGuard | None, *, now: float, subscribed: int
    ) -> None:
        """Log one health sample and raise an error when collection is unhealthy.

        The heartbeat only reported cumulative counters, which keep creeping up
        even while the feed is dead; this reports the rate instead.
        """
        if guard is None:
            return
        verdict = guard.evaluate(
            now=now, subscribed=subscribed, session=self._current_session()
        )
        _logger.info("health: %s", verdict.describe())
        for reason in verdict.alarm_reasons:
            _logger.error("collection health alarm: %s", reason)

    def _session_diagnostics(self) -> dict[str, Any]:
        """Collect whatever session diagnostics the subscriber can report.

        Every hook is optional and belongs to pluggable venue code, so a broken
        one degrades to "no diagnostics" -- it must never take the completeness
        report down with it.
        """

        def read(name: str, default: Any) -> Any:
            hook = getattr(self._subscriber, name, None)
            if not callable(hook):
                return default
            try:
                return hook()
            except Exception:
                _logger.exception("subscriber diagnostics hook %s failed", name)
                return default

        return {
            "disconnects": read("disconnect_windows", []),
            "callback_errors": read("error_count", 0),
            "connection_generations": read("generation_changes", []),
            "failed_instruments": read("failed_instruments", {}),
            "resubscribes": read("resubscribe_events", []),
        }

    def _report_subscription(self, selected: list[InstrumentSpec]) -> None:
        """Log the requested universe per asset type, then the acknowledgement."""
        counts = Counter(spec.asset_type for spec in selected)
        breakdown = ", ".join(f"{name}={counts[name]}" for name in sorted(counts))
        _logger.info(
            "subscribed %d instruments (shard=%s, flush=%ss): %s",
            len(selected),
            self._config.shard.strategy,
            self._config.flush_interval_sec,
            breakdown,
        )
        ack = self._await_subscription_ack(len(selected))
        if not ack:
            return
        # "ok" 只代表柜台 ACK 无错误码；只有 acked == requested 才算就绪。
        _logger.info(
            "subscribe acknowledged: requested=%d acked=%d failed=%d timed_out=%d",
            ack["requested"],
            ack["acked"],
            ack["failed"],
            ack["timed_out"],
        )
        if ack["acked"] < ack["requested"] or ack["failed"]:
            # acked > requested 只说明有过重复提交（柜台 ACK 幂等），不算未就绪；
            # 但柜台明确报错的合约即使计数被"补平"也必须告警。
            _logger.warning(
                "subscribe not ready: %d of %d instruments unacknowledged "
                "(failed=%d timed_out=%d last_error_id=%s)",
                max(ack["requested"] - ack["acked"], 0),
                ack["requested"],
                ack["failed"],
                ack["timed_out"],
                ack["last_error_id"],
            )

    def _await_subscription_ack(self, expected: int, timeout_sec: float = 15.0) -> dict[str, Any]:
        """Wait briefly for the per-batch subscribe responses to come back.

        Responses arrive on the native callback thread *after* ``subscribe``
        returns, so reading the counters immediately reports a partial result.
        The wait is bounded: a slow counter must never delay collection.

        Returns ``{}`` when the subscriber cannot report statistics, otherwise
        the requested/acked/failed/timed_out breakdown.
        """
        stats_fn = getattr(self._subscriber, "subscription_stats", None)
        if not callable(stats_fn):
            return {}
        deadline = time.monotonic() + timeout_sec
        stats = stats_fn()
        while (
            int(stats.get("ok", 0) or 0) + int(stats.get("failed", 0) or 0) < expected
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
            stats = stats_fn()
        acked = int(stats.get("ok", 0) or 0)
        failed = int(stats.get("failed", 0) or 0)
        return {
            "requested": int(expected),
            "acked": acked,
            "failed": failed,
            "timed_out": max(int(expected) - acked - failed, 0),
            "last_error_id": stats.get("last_error_id"),
        }

    def _flush(
        self,
        sink: ParquetSink,
        buffer: TickBuffer,
        trading_day: str,
        guard: CollectionHealthGuard | None = None,
    ) -> str:
        drained = buffer.drain()
        if not drained:
            return trading_day
        rows = sum(len(ticks) for ticks in drained.values())
        # 行情确实到了就先记账：落盘失败是另一回事，不能被误报成"行情停摆"。
        if guard is not None:
            guard.observe(drained, now=time.monotonic())
        try:
            report = sink.write(drained)
        except Exception:
            # Never lose a batch to a transient sink error (disk full, IO):
            # hand the ticks back to the buffer; dedup makes order irrelevant.
            _logger.exception(
                "flush failed; returning %d instruments / %d ticks to buffer",
                len(drained),
                rows,
            )
            for ticks in drained.values():
                for tick in ticks:
                    buffer.append(tick)
            return trading_day
        # 写盘成功后才记账：批内先全量累加，同一批报出的全局总数才一致。
        for instrument_id, ticks in drained.items():
            self._cumulative[instrument_id] = self._cumulative.get(instrument_id, 0) + len(ticks)
        # 本批条数可能是"全市场正常"，累计合约数却极小（数据只来自极少数合约）：
        # 两者必须一起报，否则这种塌缩在日志里看不出来。
        _logger.info(
            "flushed %d instruments / %d ticks (cumulative: instruments=%d ticks=%d dropped=%d)",
            len(drained),
            rows,
            len(self._cumulative),
            sum(self._cumulative.values()),
            buffer.dropped_count(),
        )
        self._report_tick_milestones(drained)
        return report.trading_day or trading_day

    def _report_tick_milestones(self, drained: dict[str, list[TickRecord]]) -> None:
        """Log per-instrument progress once ticks accumulate past a threshold.

        Runs on the flush path, never inside the market-data callback, so the
        counters add no work to the hot path.  :meth:`_flush` advances the
        cumulative counters only after a successful write, so ticks handed back
        to the buffer on a sink error are not counted twice.

        Every line carries the instrument's own value *and* the running total: a
        single number cannot tell "this instrument" from "the whole run".
        """
        interval = self._config.tick_log_interval
        mode = self._config.tick_log_mode
        if interval <= 0 or mode == "off":
            return
        total_written = sum(self._cumulative.values())
        for instrument_id in drained:
            total = self._cumulative.get(instrument_id, 0)
            reached = total // interval
            reported = self._reported.get(instrument_id, 0)
            if reached <= reported:
                continue
            for multiple in range(reported + 1, reached + 1):
                _logger.info(
                    "tick milestone: %s reached %d ticks, total reached %d ticks",
                    instrument_id,
                    multiple * interval,
                    total_written,
                )
            self._reported[instrument_id] = reached


__all__ = ["CollectionConfig", "TickCollectionEngine"]
