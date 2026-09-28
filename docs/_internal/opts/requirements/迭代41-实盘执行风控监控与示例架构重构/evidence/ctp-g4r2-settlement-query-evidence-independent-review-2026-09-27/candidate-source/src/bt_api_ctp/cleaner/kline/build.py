"""Synthesise one trading day's K lines from the merged tick tree.

The walk is ``<tick_root>/<trading_day>/<exchange>/<instrument>.parquet``; each
file is classified by the venue-supplied :class:`~bt_api_ctp.cleaner.contracts.Classifier`
so combinations and unknown ids are skipped and reported instead of aborting
the whole day.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq

from bt_api_ctp.cleaner.contracts import (
    KIND_COMBINATION,
    KIND_OPTION,
    Classifier,
)
from bt_api_ctp.cleaner.kline.aggregator import aggregate_1min, aggregate_from_1min
from bt_api_ctp.cleaner.kline.writer import append_bars, kline_path

_logger = logging.getLogger(__name__)


@dataclass
class DayBuildReport:
    """What one day's K-line build produced, including what it skipped."""

    trading_day: str
    instruments: int = 0
    skipped_combination: int = 0
    skipped_option: int = 0
    skipped_unknown: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    rows: int = 0
    unparseable_rows: int = 0
    bars_without_price: int = 0
    #: Bars added to files by this run, keyed by period label ("1min", ...).
    bars_added: dict[str, int] = field(default_factory=dict)


def build_day(
    tick_root: Path | str,
    kline_root: Path | str,
    trading_day: str,
    *,
    classifier: Classifier,
    periods: tuple[int, ...] = (1, 5, 15),
    include_options: bool = True,
) -> DayBuildReport:
    """Build K lines for every instrument under ``<tick_root>/<trading_day>``."""
    report = DayBuildReport(trading_day=trading_day)
    report.bars_added = {f"{period}min": 0 for period in periods}

    day_dir = Path(tick_root) / trading_day
    if not day_dir.is_dir():
        return report

    for exchange_dir in sorted(path for path in day_dir.iterdir() if path.is_dir()):
        exchange_id = exchange_dir.name
        for parquet_path in sorted(exchange_dir.glob("*.parquet")):
            instrument_id = parquet_path.stem
            info = classifier(exchange_id, instrument_id)

            if info.kind == KIND_COMBINATION:
                report.skipped_combination += 1
                continue
            if info.kind == KIND_OPTION and not include_options:
                report.skipped_option += 1
                continue
            if not info.is_bar_source or not info.symbol:
                report.skipped_unknown.append(f"{exchange_id}/{instrument_id}")
                continue

            try:
                rows = pq.read_table(parquet_path).to_pylist()
            except Exception:
                _logger.exception("unreadable tick file skipped: %s", parquet_path)
                report.unreadable.append(f"{exchange_id}/{instrument_id}")
                continue

            aggregation = aggregate_1min(rows)
            report.rows += aggregation.rows
            report.unparseable_rows += aggregation.unparseable_rows
            report.bars_without_price += aggregation.bars_without_price
            report.instruments += 1

            for period in periods:
                bars = (
                    aggregation.bars
                    if period == 1
                    else aggregate_from_1min(aggregation.bars, period)
                )
                if not bars:
                    continue
                target = kline_path(kline_root, exchange_id, info.symbol, instrument_id, period)
                append_bars(target, bars)
                report.bars_added[f"{period}min"] += len(bars)

    return report


__all__ = ["DayBuildReport", "build_day"]
