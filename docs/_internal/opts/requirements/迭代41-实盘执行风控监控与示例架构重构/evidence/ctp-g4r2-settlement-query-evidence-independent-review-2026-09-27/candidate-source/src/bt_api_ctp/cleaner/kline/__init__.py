"""K-line aggregation and storage.

Ticks are aggregated to 1-minute bars first; the 5- and 15-minute bars are
rolled up from the 1-minute bars so the periods stay mutually consistent.
"""

from __future__ import annotations

__all__ = [
    "BAR_ARROW_SCHEMA",
    "Bar",
    "DayBuildReport",
    "MinuteAggregation",
    "aggregate_1min",
    "aggregate_from_1min",
    "append_bars",
    "build_day",
    "dedup_bars",
    "kline_path",
]

from bt_api_ctp.cleaner.kline.aggregator import (
    MinuteAggregation,
    aggregate_1min,
    aggregate_from_1min,
    dedup_bars,
)
from bt_api_ctp.cleaner.kline.build import DayBuildReport, build_day
from bt_api_ctp.cleaner.kline.schema import BAR_ARROW_SCHEMA, Bar
from bt_api_ctp.cleaner.kline.writer import append_bars, kline_path
