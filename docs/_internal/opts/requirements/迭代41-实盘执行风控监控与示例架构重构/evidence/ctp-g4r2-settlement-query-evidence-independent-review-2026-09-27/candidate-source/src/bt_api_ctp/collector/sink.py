"""Parquet sink: staged writes, compaction, and the integrity report.

Collecting never rewrites a final file.  Each flush appends one *segment* under
``<root>/.staging/<run_id>/``; segments are merged into the final layout
``<root>/<trading_day>/<exchange_id>/<instrument_id>.parquet`` only during
compaction, which runs once enough segments have piled up and again at close.

That indirection is what keeps the rewrite count off the flush interval: the
old design read-merged-rewrote every instrument on every 5s flush (463,897
rewrites in one session), while this one rewrites a final file once per
compaction batch that touches it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from bt_api_ctp.collector.protocols import TickRecord
from bt_api_ctp.collector.schedule import (
    TradingCalendar,
    covered_session_seconds,
    is_quote_window,
    session_index,
)

try:  # pragma: no cover - Windows has no fcntl
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

_logger = logging.getLogger(__name__)

_LEVEL_COUNT = 5

#: Staging tree, deliberately outside the trading-day directories so the data
#: tree only ever contains final files.
_STAGING_DIRNAME = ".staging"

#: How many pending segments trigger one compaction.  This single number is the
#: memory/rewrite trade-off: batch = N segments in memory (Arrow), and a final
#: file is rewritten once per batch that carries rows for it.
DEFAULT_COMPACT_SEGMENTS = 64

#: Domestic exchanges quote in China Standard Time; local receive timestamps
#: are true UTC epoch, so the two clocks need an explicit offset to compare.
_CST = timezone(timedelta(hours=8))

#: CTP pushes a depth snapshot every 500ms for an actively quoted instrument.
_SNAPSHOT_INTERVAL_SECONDS = 0.5

#: A gap threshold is adapted to the instrument's own cadence by this factor,
#: but never below the configured floor, and only once enough intervals exist
#: to trust the median.
_DEFAULT_GAP_THRESHOLD_FACTOR = 10.0
_MIN_INTERVALS_FOR_ADAPTIVE_GAP = 5

#: A volume increment counts as a lost-snapshot signal when it exceeds both the
#: instrument's typical increment and an absolute floor (lots), so that thin
#: instruments do not produce noise from small numbers.
_VOLUME_JUMP_FACTOR = 10.0
_MIN_VOLUME_JUMP = 50.0

_QUOTE_COLUMNS: tuple[tuple[str, pa.DataType], ...] = (
    ("last_price", pa.float64()),
    ("pre_settlement", pa.float64()),
    ("pre_close", pa.float64()),
    ("pre_open_interest", pa.float64()),
    ("open_price", pa.float64()),
    ("highest_price", pa.float64()),
    ("lowest_price", pa.float64()),
    ("volume", pa.int64()),
    ("turnover", pa.float64()),
    ("open_interest", pa.float64()),
    ("close_price", pa.float64()),
    ("settlement_price", pa.float64()),
    ("upper_limit", pa.float64()),
    ("lower_limit", pa.float64()),
    ("pre_delta", pa.float64()),
    ("curr_delta", pa.float64()),
    ("average_price", pa.float64()),
    ("banding_upper_price", pa.float64()),
    ("banding_lower_price", pa.float64()),
)

_BOOK_COLUMNS: tuple[tuple[str, pa.DataType], ...] = (
    ("bid_price", pa.float64()),
    ("bid_volume", pa.int64()),
    ("ask_price", pa.float64()),
    ("ask_volume", pa.int64()),
)


def _build_schema() -> pa.Schema:
    fields = [
        pa.field("trading_day", pa.string()),
        pa.field("action_day", pa.string()),
        pa.field("update_time", pa.string()),
        pa.field("update_millisec", pa.int32()),
        pa.field("local_receive_time", pa.int64()),
        pa.field("exchange_id", pa.string()),
        pa.field("instrument_id", pa.string()),
        pa.field("exchange_inst_id", pa.string()),
    ]
    fields.extend(pa.field(name, dtype) for name, dtype in _QUOTE_COLUMNS)
    for prefix, dtype in _BOOK_COLUMNS:
        for level in range(1, _LEVEL_COUNT + 1):
            fields.append(pa.field(f"{prefix}_{level}", dtype))
    return pa.schema(fields)


#: Fixed on-disk schema (NFR-5).  Column order never changes across runs.
TICK_ARROW_SCHEMA = _build_schema()


@dataclass
class InstrumentReport:
    """Per-instrument collection statistics."""

    exchange_id: str
    instrument_id: str
    rows: int
    first_update: str | None = None
    last_update: str | None = None
    gaps: list[dict[str, Any]] = field(default_factory=list)
    #: Data-quality metrics (整改方案 P2-2 ~ P2-5).
    expected_ticks: int | None = None
    coverage: float | None = None
    receive_gaps: int = 0
    max_receive_lag_seconds: float | None = None
    #: Largest same-session silence regardless of the adaptive threshold, so a
    #: real outage is visible even for instruments whose cadence raises it.
    max_gap_seconds: float | None = None
    max_gap_after: str | None = None
    max_gap_before: str | None = None
    volume_jumps: int = 0
    max_volume_jump: float | None = None
    estimated_missing_ticks: int | None = None


@dataclass
class SinkReport:
    """Result of one write or finalize call."""

    trading_day: str
    instruments: list[InstrumentReport] = field(default_factory=list)
    dropped_ticks: int = 0
    generated_at: str = ""
    #: Session diagnostics, so a completeness report can explain its own gaps.
    disconnects: list[dict[str, Any]] = field(default_factory=list)
    callback_errors: int = 0
    connection_generations: list[dict[str, Any]] = field(default_factory=list)
    failed_instruments: dict[str, int] = field(default_factory=dict)
    resubscribes: list[dict[str, Any]] = field(default_factory=list)
    #: Compaction counters: how often final files were rewritten, and what is
    #: still staged.  A non-zero ``pending_segments`` at close means the merge
    #: did not finish (see the failure count) and a later run must recover it.
    compactions: int = 0
    compaction_failures: int = 0
    pending_segments: int = 0
    compaction_last_error: str | None = None
    #: Snapshots discarded because their exchange timestamp was outside every
    #: trading session (subscribe-time synthetic snapshots).
    ticks_outside_session: int = 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _time_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (row["action_day"] or "", row["update_time"] or "", int(row["update_millisec"] or 0))


def _stamp(row: dict[str, Any]) -> str:
    return (
        f"{row['action_day']} {row['update_time']}."
        f"{int(row['update_millisec'] or 0):03d}"
    )


def _row_moment(row: dict[str, Any]) -> datetime | None:
    try:
        return datetime.strptime(
            f"{row['action_day']} {row['update_time']}", "%Y%m%d %H:%M:%S"
        )
    except (TypeError, ValueError):
        return None


def _row_seconds(row: dict[str, Any]) -> float | None:
    moment = _row_moment(row)
    if moment is None:
        return None
    return moment.replace(tzinfo=_CST).timestamp() + (int(row["update_millisec"] or 0) / 1000.0)


def _row_received_seconds(row: dict[str, Any]) -> float | None:
    received = row.get("local_receive_time")
    return None if not received else int(received) / 1e9


def _row_lag_seconds(row: dict[str, Any]) -> float | None:
    """Local receive time minus the exchange moment, in seconds.

    A large positive value means the snapshot reached us long after the
    exchange stamped it -- the relay buffered it.  Since CTP cannot replay
    history, that is a data-quality signal in its own right.
    """
    received = _row_received_seconds(row)
    seconds = _row_seconds(row)
    if received is None or seconds is None:
        return None
    return received - seconds


def _outside_session(tick: TickRecord) -> bool:
    """Whether a snapshot's exchange timestamp falls outside every session.

    On subscribe, CTP pushes a synthetic snapshot per instrument (observed:
    4,757 instruments sharing one pre-open timestamp) which is not market data.
    An unparseable timestamp is kept: dropping data on bad input is worse than
    storing it.
    """
    try:
        moment = datetime.strptime(f"{tick.action_day} {tick.update_time}", "%Y%m%d %H:%M:%S")
    except (TypeError, ValueError):
        return False
    return not is_quote_window(moment)


def _to_row(tick: TickRecord) -> dict[str, Any]:
    row: dict[str, Any] = {
        "trading_day": tick.trading_day,
        "action_day": tick.action_day,
        "update_time": tick.update_time,
        "update_millisec": int(tick.update_millisec),
        "local_receive_time": int(tick.local_receive_time),
        "exchange_id": tick.exchange_id,
        "instrument_id": tick.instrument_id,
        "exchange_inst_id": tick.exchange_inst_id,
    }
    for name, _ in _QUOTE_COLUMNS:
        row[name] = getattr(tick, name)
    for prefix, source in (
        ("bid_price", tick.bid_price),
        ("bid_volume", tick.bid_volume),
        ("ask_price", tick.ask_price),
        ("ask_volume", tick.ask_volume),
    ):
        for index in range(_LEVEL_COUNT):
            row[f"{prefix}_{index + 1}"] = source[index] if index < len(source) else None
    return row


def _dedup_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate (action_day, update_time, update_millisec) keys.

    CTP may re-push a snapshot after a reconnect, so the newest local
    receive wins for an identical time key.
    """
    latest: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = _time_key(row)
        current = latest.get(key)
        if current is None or int(row["local_receive_time"] or 0) >= int(
            current["local_receive_time"] or 0
        ):
            latest[key] = row
    return sorted(latest.values(), key=_time_key)


def _read_existing(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return pq.read_table(path).to_pylist()


def _write_atomically(path: Path, rows: list[dict[str, Any]]) -> None:
    table = pa.Table.from_pylist(rows, schema=TICK_ARROW_SCHEMA)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temp name: two processes writing the same instrument must never
    # fight over one scratch file.
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _quarantine(path: Path) -> None:
    """Move an unreadable segment aside while keeping it on disk.

    Deleting it would lose whatever data it carries, so the evidence is kept
    under a ``.bad`` suffix: out of the ``*.parquet`` glob (so it is not
    retried on every run) but still visible to an operator.
    """
    target = path.with_suffix(".bad")
    try:
        path.rename(target)
    except OSError:  # pragma: no cover - 宁可留在原地也不能丢数据
        _logger.exception("could not quarantine %s; leaving it in place", path)


def _pid_is_alive(run_id: str) -> bool:
    """Whether the run that owns ``run_id`` (``<pid>-<nonce>``) is still alive.

    An unparseable id counts as alive: staging that might still be written to
    must never be consumed.
    """
    head = run_id.split("-", 1)[0]
    if not head.isdigit():
        return True
    try:
        os.kill(int(head), 0)
    except ProcessLookupError:
        return False
    except OSError:  # pragma: no cover - 权限等异常时保守视为存活
        return True
    return True


@contextmanager
def _instrument_lock(root: Path, path: Path):
    """Cross-process exclusive lock guarding one instrument's read-modify-write.

    Callers may run several collectors over the same data root (for example
    overlapping shards or an accidental double start); without this lock the
    read-merge-write cycle silently loses rows.

    Lock files live under ``<root>/.locks/<trading_day>/<exchange>/`` instead of
    next to the parquet, so the data tree stays clean.  They are deliberately
    *not* unlinked after use: removing a lock file while another process is
    still waiting on it breaks mutual exclusion -- the waiter would hold a lock
    on an orphaned inode while a third process locks a freshly created file at
    the same path.
    """
    if fcntl is None:  # pragma: no cover - Windows fallback
        yield
        return
    relative = path.relative_to(root)
    lock_path = root / ".locks" / relative.parent / f"{relative.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ParquetSink:
    """Stage tick batches, compact them into Parquet, and report completeness."""

    def __init__(
        self,
        root: Path | str,
        *,
        merge_existing: bool = True,
        gap_threshold_sec: float = 60.0,
        compact_segment_count: int = DEFAULT_COMPACT_SEGMENTS,
        gap_threshold_factor: float = _DEFAULT_GAP_THRESHOLD_FACTOR,
        drop_outside_session: bool = True,
        calendar: TradingCalendar | None = None,
    ) -> None:
        if int(compact_segment_count) < 1:
            raise ValueError("compact_segment_count must be >= 1")
        self._root = Path(root)
        self._merge_existing = merge_existing
        self._gap_threshold_sec = float(gap_threshold_sec)
        self._compact_segment_count = int(compact_segment_count)
        self._gap_threshold_factor = float(gap_threshold_factor)
        self._drop_outside_session = bool(drop_outside_session)
        #: Trading calendar, so a window spanning a weekend does not count
        #: sessions that never happen when scoring coverage.
        self._calendar = calendar or TradingCalendar()
        self._ticks_outside_session = 0
        # Identifies this process's staging tree, and tells a later run whether
        # the segments it finds belong to a dead run (see _recover_dead_staging).
        self._run_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._segments: list[Path] = []
        self._segment_seq = 0
        # Compaction is the slow half of the sink, so it runs on its own thread
        # and the collection loop only appends segments; see _compact_pending.
        self._segments_lock = threading.Lock()
        self._compact_lock = threading.Lock()
        self._compact_thread: threading.Thread | None = None
        self._compactions = 0
        self._compaction_failures = 0
        self._last_compaction_error: str | None = None

    @property
    def root(self) -> Path:
        return self._root

    def _effective_gap_threshold(self, intervals: list[float]) -> float:
        """Adapt the gap threshold to the instrument's own cadence.

        A sparse option quoting once a minute must not have its normal silence
        reported as a gap, while a liquid instrument on a 500ms cadence should
        still be flagged past the configured floor.  Fewer than five intervals
        is not enough evidence to adapt, so the floor is used as-is.
        """
        if self._gap_threshold_factor <= 0 or len(intervals) < _MIN_INTERVALS_FOR_ADAPTIVE_GAP:
            return self._gap_threshold_sec
        median = sorted(intervals)[len(intervals) // 2]
        return max(self._gap_threshold_sec, median * self._gap_threshold_factor)

    def _volume_metrics(self, rows: list[dict[str, Any]]) -> tuple[int, float | None, int | None]:
        """Count suspicious volume jumps and estimate the snapshots they hide.

        Volume is cumulative within a trading day, so a large increment between
        two adjacent snapshots means snapshots in between never arrived.  The
        estimate divides the jump by the instrument's typical increment, which
        is an upper bound: one busy window can also produce a large increment.
        """
        deltas: list[float] = []
        previous: float | None = None
        for row in rows:
            volume = row.get("volume")
            if volume is None:
                continue
            volume = float(volume)
            if previous is not None and volume >= previous:
                deltas.append(volume - previous)
            previous = volume
        if not deltas:
            return 0, None, None
        typical = sorted(deltas)[len(deltas) // 2]
        threshold = max(_MIN_VOLUME_JUMP, typical * _VOLUME_JUMP_FACTOR)
        jumps = [delta for delta in deltas if delta > threshold]
        if not jumps:
            return 0, None, None
        if typical <= 0:
            # 绝大多数快照成交量没变化，无法据此估算丢失条数，只报事实。
            return len(jumps), max(jumps), None
        estimate = sum(max(round(delta / typical) - 1, 1) for delta in jumps)
        return len(jumps), max(jumps), estimate

    def _instrument_report(
        self, exchange_id: str, instrument_id: str, rows: list[dict[str, Any]]
    ) -> InstrumentReport:
        samples: list[tuple[datetime, float, int | None, float | None, dict[str, Any]]] = []
        max_lag: float | None = None
        for row in rows:
            moment = _row_moment(row)
            seconds = _row_seconds(row)
            if moment is None or seconds is None:
                continue
            lag = _row_lag_seconds(row)
            if lag is not None and (max_lag is None or lag > max_lag):
                max_lag = lag
            samples.append(
                (moment, seconds, session_index(moment), _row_received_seconds(row), row)
            )

        intervals = [
            current[1] - previous[1]
            for previous, current in zip(samples, samples[1:])
            if current[2] is not None and current[2] == previous[2]
        ]
        threshold = self._effective_gap_threshold(intervals)

        gaps: list[dict[str, Any]] = []
        receive_gaps = 0
        max_gap: float | None = None
        max_gap_after: str | None = None
        max_gap_before: str | None = None
        for previous, current in zip(samples, samples[1:]):
            # Only silence inside one continuous session is a data gap;
            # scheduled breaks and the close-to-open jump are not.
            if current[2] is None or current[2] != previous[2]:
                continue
            delta = current[1] - previous[1]
            if max_gap is None or delta > max_gap:
                max_gap = delta
                max_gap_after = _stamp(previous[4])
                max_gap_before = _stamp(current[4])
            if delta > threshold:
                gaps.append(
                    {
                        "after": _stamp(previous[4]),
                        "before": _stamp(current[4]),
                        "seconds": delta,
                    }
                )
            # The receive clock catches outages the exchange clock hides, e.g.
            # a relay that buffered snapshots and delivered them in a burst.
            if previous[3] is not None and current[3] is not None:
                if current[3] - previous[3] > threshold:
                    receive_gaps += 1

        expected: int | None = None
        coverage: float | None = None
        if samples:
            window = covered_session_seconds(samples[0][0], samples[-1][0], self._calendar)
            if window > 0:
                expected = max(int(window / _SNAPSHOT_INTERVAL_SECONDS), 1)
                coverage = round(len(rows) / expected, 4)

        volume_jumps, max_volume_jump, estimated_missing = self._volume_metrics(rows)

        return InstrumentReport(
            exchange_id=exchange_id,
            instrument_id=instrument_id,
            rows=len(rows),
            first_update=_stamp(rows[0]) if rows else None,
            last_update=_stamp(rows[-1]) if rows else None,
            gaps=gaps,
            expected_ticks=expected,
            coverage=coverage,
            receive_gaps=receive_gaps,
            max_receive_lag_seconds=max_lag,
            max_gap_seconds=max_gap,
            max_gap_after=max_gap_after,
            max_gap_before=max_gap_before,
            volume_jumps=volume_jumps,
            max_volume_jump=max_volume_jump,
            estimated_missing_ticks=estimated_missing,
        )

    def write(
        self, ticks_by_instrument: dict[str, list[TickRecord]], *, dropped_ticks: int = 0
    ) -> SinkReport:
        """Append one batch to staging, then compact if enough segments piled up.

        Nothing is read or rewritten here, so the cost is proportional to the
        batch rather than to the day collected so far.  A batch may straddle two
        trading days (the night session opens at 21:00 and CTP flips
        ``TradingDay`` instantly), so rows are grouped by their own trading day.

        Per-instrument statistics are not available at this point; they are
        computed by :meth:`finalize` after compaction.
        """
        rows_by_day: dict[str, list[dict[str, Any]]] = {}
        outside_session = 0
        for ticks in ticks_by_instrument.values():
            for tick in ticks:
                if not tick.trading_day:
                    raise ValueError("tick without trading_day")
                if not tick.exchange_id:
                    raise ValueError("tick without exchange_id")
                if not tick.instrument_id:
                    raise ValueError("tick without instrument_id")
                if self._drop_outside_session and _outside_session(tick):
                    outside_session += 1
                    continue
                rows_by_day.setdefault(tick.trading_day, []).append(_to_row(tick))
        self._ticks_outside_session += outside_session

        if not rows_by_day:
            return SinkReport(trading_day="", dropped_ticks=dropped_ticks)

        for rows in rows_by_day.values():
            self._write_segment(rows)
        self._compact_in_background()

        trading_day = max(rows_by_day, key=lambda day: len(rows_by_day[day]))
        return SinkReport(trading_day=trading_day, dropped_ticks=dropped_ticks)

    def _staging_dir(self) -> Path:
        return self._root / _STAGING_DIRNAME / self._run_id

    def _write_segment(self, rows: list[dict[str, Any]]) -> None:
        with self._segments_lock:
            path = self._staging_dir() / f"{self._segment_seq:08d}.parquet"
            self._segment_seq += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(path, rows)
        with self._segments_lock:
            self._segments.append(path)

    def _take_all_pending(self) -> list[Path]:
        with self._segments_lock:
            batch, self._segments = list(self._segments), []
            return batch

    def _requeue(self, batch: list[Path]) -> None:
        """Put failed work back at the head of the queue.

        Paths already queued are skipped, and so are paths that no longer exist
        (a segment quarantined as ``.bad`` during the same attempt): retrying
        either would just add noise and inflate the counters.
        """
        with self._segments_lock:
            pending = set(self._segments)
            self._segments = [
                path for path in batch if path not in pending and path.exists()
            ] + self._segments

    def _compact_in_background(self) -> None:
        """Hand one batch of segments to the compaction worker if it is idle.

        Called from the collection thread, so it must not wait: the merge itself
        is the slow half of the sink and happens on ``tick-compact``.  The whole
        decision is taken under the pending lock so two callers can never spawn
        two workers.
        """
        with self._segments_lock:
            if self._compact_thread is not None and self._compact_thread.is_alive():
                return  # 已有压缩在跑：留给下一次写入或收盘，不堆积线程
            if len(self._segments) < self._compact_segment_count:
                return
            batch = self._segments[: self._compact_segment_count]
            self._segments = self._segments[len(batch) :]
            thread = threading.Thread(
                target=self._compact_batch, args=(batch,), name="tick-compact", daemon=True
            )
            self._compact_thread = thread
        thread.start()

    def _drain_pending(self) -> None:
        """Compact everything pending, synchronously (close path)."""
        while True:
            batch = self._take_all_pending()
            if not batch:
                return
            if not self._compact_batch(batch):
                return  # 失败时段留在盘上，交由后续运行认领，不再空转重试

    def _await_compaction(self) -> None:
        thread = self._compact_thread
        if thread is not None:
            thread.join()
            self._compact_thread = None

    def _compact_batch(self, batch: list[Path]) -> bool:
        """Compact one batch; keep its segments for a retry when it fails."""
        if not batch:
            return True
        try:
            with self._compact_lock:
                written = self._compact(batch)
        except Exception as exc:
            with self._segments_lock:
                self._compaction_failures += 1
                self._last_compaction_error = str(exc)
            _logger.exception("compaction failed; %d segment(s) kept", len(batch))
            self._requeue(batch)
            return False
        if written:
            with self._segments_lock:
                self._compactions += 1
            _logger.info(
                "compacted %d staging segment(s) into %d instrument file(s)", len(batch), written
            )
        return True

    def compaction_stats(self) -> dict[str, Any]:
        """Return compaction counters, including anything still staged."""
        with self._segments_lock:
            return {
                "compactions": self._compactions,
                "failures": self._compaction_failures,
                "pending_segments": len(self._segments),
                "last_error": self._last_compaction_error,
            }
    def _compact(self, segments: list[Path]) -> int:
        """Merge segment files (plus any existing final files) into final files.

        Memory stays bounded by the batch: segments are concatenated as Arrow,
        and only one instrument's rows are materialized as Python objects at a
        time.  A segment that cannot be read is quarantined and counted -- it
        must never be deleted together with the data it carries.

        Returns:
            How many instrument files were written (0 when nothing was readable).
        """
        tables: list[pa.Table] = []
        readable: list[Path] = []
        for path in segments:
            try:
                tables.append(pq.read_table(path))
            except Exception:
                _logger.exception("unreadable staging segment preserved: %s", path)
                with self._segments_lock:
                    self._compaction_failures += 1
                    self._last_compaction_error = f"unreadable segment: {path.name}"
                _quarantine(path)
            else:
                readable.append(path)
        if not tables:
            return 0
        combined = pa.concat_tables(tables) if len(tables) > 1 else tables[0]

        keys = combined.group_by(["trading_day", "exchange_id", "instrument_id"]).aggregate([])
        written = 0
        for key in keys.to_pylist():
            trading_day = key["trading_day"]
            exchange_id = key["exchange_id"]
            instrument_id = key["instrument_id"]
            rows = combined.filter(
                pc.and_(
                    pc.and_(
                        pc.equal(combined["trading_day"], trading_day),
                        pc.equal(combined["exchange_id"], exchange_id),
                    ),
                    pc.equal(combined["instrument_id"], instrument_id),
                )
            ).to_pylist()
            path = self._root / trading_day / exchange_id / f"{instrument_id}.parquet"
            with _instrument_lock(self._root, path):
                if self._merge_existing:
                    rows = _read_existing(path) + rows
                _write_atomically(path, _dedup_sort(rows))
            written += 1
        # 只丢弃成功读入的段；全部最终文件写成功后才丢弃，中途崩溃重新合并是幂等的。
        self._discard(readable)
        return written

    def _discard(self, segments: list[Path]) -> None:
        for path in segments:
            path.unlink(missing_ok=True)
        for directory in {path.parent for path in segments}:
            try:
                directory.rmdir()
            except OSError:
                pass  # 仍有段（或另一进程在用）时保留目录

    def _recover_dead_staging(self) -> None:
        """Merge segments left behind by runs that are no longer alive.

        A hard kill (SIGKILL, power loss) leaves complete segment files but no
        final files.  Without this step that data would never reach the data
        tree.  Staging owned by a live process is skipped, so a sibling shard's
        in-flight segments are never consumed.
        """
        base = self._root / _STAGING_DIRNAME
        if not base.exists():
            return
        with self._segments_lock:
            already_pending = set(self._segments)
        for directory in sorted(path for path in base.iterdir() if path.is_dir()):
            if directory.name == self._run_id or _pid_is_alive(directory.name):
                continue
            segments = [
                path
                for path in sorted(directory.glob("*.parquet"))
                if path not in already_pending
            ]
            if not segments:
                continue
            _logger.warning(
                "merging %d staging segment(s) left by run %s", len(segments), directory.name
            )
            if not self._compact_batch(segments):
                # 认领失败不能让整份报告消失：段仍在盘上，下次运行或下次收盘再试。
                _logger.error("could not recover staging from run %s", directory.name)

    def finalize(
        self,
        trading_day: str,
        *,
        dropped_ticks: int = 0,
        disconnects: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        callback_errors: int = 0,
        connection_generations: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        failed_instruments: dict[str, int] | None = None,
        resubscribes: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    ) -> SinkReport:
        """Scan every persisted file and write the completeness report.

        ``disconnects`` / ``callback_errors`` / ``connection_generations`` /
        ``failed_instruments`` / ``resubscribes`` come from the venue session;
        recording them makes a gap explainable instead of merely visible.
        """
        # 收盘：先等后台压缩收尾，再排空剩余段，最后认领崩溃运行遗留的段。
        self._await_compaction()
        self._drain_pending()
        self._recover_dead_staging()

        base = self._root / trading_day
        instruments: list[InstrumentReport] = []
        if base.exists():
            for exchange_dir in sorted(path for path in base.iterdir() if path.is_dir()):
                for parquet_path in sorted(exchange_dir.glob("*.parquet")):
                    rows = _read_existing(parquet_path)
                    if not rows:
                        continue
                    instruments.append(
                        self._instrument_report(exchange_dir.name, parquet_path.stem, rows)
                    )

        report = SinkReport(
            trading_day=trading_day,
            instruments=instruments,
            dropped_ticks=dropped_ticks,
            generated_at=_now_iso(),
            disconnects=[dict(entry) for entry in disconnects],
            callback_errors=int(callback_errors),
            connection_generations=[dict(entry) for entry in connection_generations],
            failed_instruments={str(key): int(value) for key, value in (failed_instruments or {}).items()},
            resubscribes=[dict(entry) for entry in resubscribes],
            compactions=self._compactions,
            compaction_failures=self._compaction_failures,
            pending_segments=self.compaction_stats()["pending_segments"],
            compaction_last_error=self._last_compaction_error,
            ticks_outside_session=self._ticks_outside_session,
        )
        base.mkdir(parents=True, exist_ok=True)
        payload = {
            "trading_day": report.trading_day,
            "generated_at": report.generated_at,
            "dropped_ticks": report.dropped_ticks,
            "callback_errors": report.callback_errors,
            "disconnects": report.disconnects,
            "connection_generations": report.connection_generations,
            "failed_instruments": report.failed_instruments,
            "resubscribes": report.resubscribes,
            "compactions": report.compactions,
            "compaction_failures": report.compaction_failures,
            "pending_segments": report.pending_segments,
            "compaction_last_error": report.compaction_last_error,
            "ticks_outside_session": report.ticks_outside_session,
            "instruments": [
                {
                    "exchange_id": entry.exchange_id,
                    "instrument_id": entry.instrument_id,
                    "rows": entry.rows,
                    "first_update": entry.first_update,
                    "last_update": entry.last_update,
                    "gaps": entry.gaps,
                    "expected_ticks": entry.expected_ticks,
                    "coverage": entry.coverage,
                    "receive_gaps": entry.receive_gaps,
                    "max_receive_lag_seconds": entry.max_receive_lag_seconds,
                    "max_gap_seconds": entry.max_gap_seconds,
                    "max_gap_after": entry.max_gap_after,
                    "max_gap_before": entry.max_gap_before,
                    "volume_jumps": entry.volume_jumps,
                    "max_volume_jump": entry.max_volume_jump,
                    "estimated_missing_ticks": entry.estimated_missing_ticks,
                }
                for entry in report.instruments
            ],
        }
        (base / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return report


__all__ = [
    "DEFAULT_COMPACT_SEGMENTS",
    "TICK_ARROW_SCHEMA",
    "InstrumentReport",
    "ParquetSink",
    "SinkReport",
]
