"""Merge shard copies and the local authoritative tree into one, deduplicated day.

The dedup rule is deliberately the collector's own: same key
``(action_day, update_time, update_millisec)``, newest ``local_receive_time``
wins.  Reusing ``collector.sink``'s primitives keeps one definition of
"duplicate" across collection and cleaning instead of two that slowly diverge.

A remote file can in principle carry a different schema (an older collector
build); rows are aligned to the fixed tick schema by column *name* so a missing
column becomes null and is reported rather than crashing the merge.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from bt_api_ctp.collector.sink import TICK_ARROW_SCHEMA, _dedup_sort, _write_atomically

_logger = logging.getLogger(__name__)

_EXPECTED_COLUMNS = [field_.name for field_ in TICK_ARROW_SCHEMA]


@dataclass
class MergeStat:
    """What merging one instrument changed."""

    exchange_id: str
    instrument_id: str
    #: Rows the merge brought in that the authoritative file did not have.
    added: int = 0
    #: Input rows collapsed into an existing key.
    deduped: int = 0
    #: Rows in the merged file.
    total: int = 0


@dataclass
class DayMergeReport:
    """Aggregate of one trading day's merge."""

    trading_day: str
    instruments: int = 0
    added: int = 0
    deduped: int = 0
    total: int = 0
    stats: list[MergeStat] = field(default_factory=list)
    #: ``"<file>: missing ['x', ...]"`` entries for schema drift.
    schema_drift: list[str] = field(default_factory=list)


def _read_aligned(path: Path) -> tuple[list[dict], list[str]]:
    """Read rows aligned to :data:`TICK_ARROW_SCHEMA`, filling missing columns."""
    table = pq.read_table(path)
    present = set(table.schema.names)
    missing = [name for name in _EXPECTED_COLUMNS if name not in present]
    for name in missing:
        table = table.append_column(
            name, pa.nulls(table.num_rows, TICK_ARROW_SCHEMA.field(name).type)
        )
    if table.schema.names != _EXPECTED_COLUMNS:
        table = table.select(_EXPECTED_COLUMNS)
    return table.to_pylist(), missing


def merge_instrument(
    target: Path, sources: list[Path], *, merge_existing: bool = True
) -> tuple[MergeStat, list[str]]:
    """Merge ``sources`` (and the existing ``target``) into ``target``.

    Returns:
        The statistics for this instrument and any schema-drift notes.
    """
    drift: list[str] = []
    existing: list[dict] = []
    if merge_existing and target.exists():
        existing, missing = _read_aligned(target)
        if missing:
            drift.append(f"{target.name}: missing {missing}")

    incoming: list[dict] = []
    for source in sources:
        rows, missing = _read_aligned(source)
        incoming.extend(rows)
        if missing:
            drift.append(f"{source.name}: missing {missing}")

    existing_unique = _dedup_sort(existing)
    merged = _dedup_sort(existing + incoming)
    stat = MergeStat(
        exchange_id=target.parent.name,
        instrument_id=target.stem,
        added=len(merged) - len(existing_unique),
        deduped=(len(existing) + len(incoming)) - len(merged),
        total=len(merged),
    )
    if merged:
        _write_atomically(target, merged)
    return stat, drift


def merge_day(
    tick_root: Path | str,
    staging_root: Path | str,
    trading_day: str,
    *,
    hosts: Iterable[str] | None = None,
) -> DayMergeReport:
    """Merge every staged copy of ``trading_day`` into the authoritative tree.

    Staging layout is ``<staging_root>/<host>/<trading_day>/<exchange>/<instrument>.parquet``.
    ``hosts`` restricts the merge to the given host names; the pipeline passes
    only the hosts whose copy verified, so a failed host's staged (possibly
    corrupt) files are never read.
    """
    report = DayMergeReport(trading_day=trading_day)
    staging = Path(staging_root)
    if not staging.is_dir():
        return report

    allowed = set(hosts) if hosts is not None else None
    sources_by_instrument: dict[tuple[str, str], list[Path]] = {}
    for host_dir in sorted(path for path in staging.iterdir() if path.is_dir()):
        if allowed is not None and host_dir.name not in allowed:
            continue
        day_dir = host_dir / trading_day
        if not day_dir.is_dir():
            continue
        for exchange_dir in sorted(path for path in day_dir.iterdir() if path.is_dir()):
            for parquet_path in sorted(exchange_dir.glob("*.parquet")):
                key = (exchange_dir.name, parquet_path.stem)
                sources_by_instrument.setdefault(key, []).append(parquet_path)

    root = Path(tick_root)
    for (exchange_id, instrument_id), sources in sorted(sources_by_instrument.items()):
        target = root / trading_day / exchange_id / f"{instrument_id}.parquet"
        stat, drift = merge_instrument(target, sources)
        report.stats.append(stat)
        report.instruments += 1
        report.added += stat.added
        report.deduped += stat.deduped
        report.total += stat.total
        report.schema_drift.extend(drift)
        if drift:
            _logger.warning(
                "schema drift while merging %s/%s: %s", exchange_id, instrument_id, drift
            )

    return report


def drop_staging_day(
    staging_root: Path | str, trading_day: str, *, hosts: Iterable[str] | None = None
) -> None:
    """Remove the staged copy of a merged day (best effort).

    Only merged hosts are dropped; a host that failed verification keeps its
    staging so the failure stays diagnosable and the day can be retried.
    """
    staging = Path(staging_root)
    if not staging.is_dir():
        return
    allowed = set(hosts) if hosts is not None else None
    for host_dir in staging.iterdir():
        if allowed is not None and host_dir.name not in allowed:
            continue
        day_dir = host_dir / trading_day
        if day_dir.is_dir():
            for path in sorted(day_dir.rglob("*"), reverse=True):
                try:
                    path.unlink() if path.is_file() else path.rmdir()
                except OSError:  # pragma: no cover - best effort cleanup
                    _logger.warning("could not remove staging path: %s", path)
            try:
                day_dir.rmdir()
            except OSError:  # pragma: no cover - best effort cleanup
                _logger.warning("could not remove staging day: %s", day_dir)


__all__ = ["DayMergeReport", "MergeStat", "drop_staging_day", "merge_day", "merge_instrument"]
