"""Turn tick rows into 1-minute bars, then 1-minute bars into 5/15-minute bars.

Two rules matter for correctness and are covered by tests:

* **Buckets are clock-aligned** -- ``09:00:00.000`` through ``09:00:59.999``
  belong to the ``09:00`` bucket.  A session break therefore simply produces no
  bars; it never produces empty ones.
* **Volume and amount are differenced** -- the exchange reports them
  cumulatively within a trading day.  A tick contributes the increment since
  the previous tick, and the very first captured tick contributes its whole
  accumulated value so that the bar totals still add up to the day's total.

The 5/15-minute bars are derived from the 1-minute bars rather than from the
ticks, so ``sum(1min volume) == 5min volume`` holds by construction and the two
periods can be cross-checked.
"""

from __future__ import annotations

import math
from calendar import timegm
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from bt_api_ctp.cleaner.kline.schema import Bar

_MINUTE_NS = 60 * 1_000_000_000


@dataclass(frozen=True)
class MinuteAggregation:
    """Result of a 1-minute aggregation, with the counters a report needs."""

    bars: list[Bar] = field(default_factory=list)
    rows: int = 0
    unparseable_rows: int = 0
    bars_without_price: int = 0


def _parse_ns(row: dict[str, Any]) -> int | None:
    """Exchange wall clock (``action_day`` + ``update_time`` + ms) as epoch ns."""
    try:
        moment = datetime.strptime(f"{row['action_day']} {row['update_time']}", "%Y%m%d %H:%M:%S")
    except (KeyError, TypeError, ValueError):
        return None
    try:
        millisec = int(row.get("update_millisec") or 0)
    except (TypeError, ValueError):
        millisec = 0
    return timegm(moment.timetuple()) * 1_000_000_000 + millisec * 1_000_000


def _number(value: Any, cast):
    if value is None:
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _valid_price(value: Any) -> float | None:
    """A price usable for OHLC.

    Pre-open snapshots can carry a zero or an ``inf`` sentinel; those ticks
    must not drag a bar's high/low to nonsense.
    """
    price = _number(value, float)
    if price is None or not math.isfinite(price) or price <= 0:
        return None
    return price


@dataclass
class _BarAccumulator:
    bucket: int
    trading_day: str
    exchange_id: str
    instrument_id: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int = 0
    amount: float = 0.0
    open_interest: float | None = None

    def add_tick(
        self, price: float | None, delta_volume: int, delta_amount: float, oi: float | None
    ) -> None:
        if price is not None:
            if self.open is None:
                self.open = price
                self.high = price
                self.low = price
            else:
                assert self.high is not None and self.low is not None
                self.high = max(self.high, price)
                self.low = min(self.low, price)
            self.close = price
        self.volume += delta_volume
        self.amount += delta_amount
        if oi is not None:
            self.open_interest = oi

    def merge_bar(self, bar: Bar) -> None:
        if self.open is None:
            self.open = bar.open
            self.high = bar.high
            self.low = bar.low
        else:
            assert self.high is not None and self.low is not None
            self.high = max(self.high, bar.high)
            self.low = min(self.low, bar.low)
        self.close = bar.close
        self.volume += bar.volume
        self.amount += bar.amount
        if bar.open_interest is not None:
            self.open_interest = bar.open_interest

    def to_bar(self) -> Bar | None:
        """``None`` when the bucket carried no usable price at all."""
        if self.open is None or self.high is None or self.low is None or self.close is None:
            return None
        return Bar(
            datetime=self.bucket,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            amount=self.amount,
            open_interest=self.open_interest,
            trading_day=self.trading_day,
            exchange_id=self.exchange_id,
            instrument_id=self.instrument_id,
        )


def aggregate_1min(rows: Iterable[dict[str, Any]]) -> MinuteAggregation:
    """Aggregate one instrument's tick rows into 1-minute bars.

    Rows are sorted by their exchange timestamp first, so callers may hand over
    whatever order the parquet read produced.
    """
    ordered: list[tuple[int, dict[str, Any]]] = []
    unparseable = 0
    for row in rows:
        ns = _parse_ns(row)
        if ns is None:
            unparseable += 1
            continue
        ordered.append((ns, row))
    ordered.sort(key=lambda item: item[0])

    bars: list[Bar] = []
    bars_without_price = 0
    accumulator: _BarAccumulator | None = None
    previous_volume: int | None = None
    previous_amount: float | None = None

    for ns, row in ordered:
        volume = _number(row.get("volume"), int)
        amount = _number(row.get("turnover"), float)
        price = _valid_price(row.get("last_price"))
        oi = _number(row.get("open_interest"), float)

        if volume is None:
            delta_volume = 0
        elif previous_volume is None or volume >= previous_volume:
            delta_volume = volume - (previous_volume or 0)
        else:
            # Counter reset (a new trading day inside one file): restart from 0.
            delta_volume = volume
        if volume is not None:
            previous_volume = volume

        if amount is None:
            delta_amount = 0.0
        elif previous_amount is None or amount >= previous_amount:
            delta_amount = amount - (previous_amount or 0.0)
        else:
            delta_amount = amount
        if amount is not None:
            previous_amount = amount

        bucket = ns - (ns % _MINUTE_NS)
        if accumulator is None or accumulator.bucket != bucket:
            if accumulator is not None:
                bar = accumulator.to_bar()
                if bar is None:
                    bars_without_price += 1
                else:
                    bars.append(bar)
            accumulator = _BarAccumulator(
                bucket=bucket,
                trading_day=str(row.get("trading_day") or ""),
                exchange_id=str(row.get("exchange_id") or ""),
                instrument_id=str(row.get("instrument_id") or ""),
            )
        accumulator.add_tick(price, delta_volume, delta_amount, oi)

    if accumulator is not None:
        bar = accumulator.to_bar()
        if bar is None:
            bars_without_price += 1
        else:
            bars.append(bar)

    return MinuteAggregation(
        bars=bars,
        rows=len(ordered),
        unparseable_rows=unparseable,
        bars_without_price=bars_without_price,
    )


def aggregate_from_1min(bars: Iterable[Bar], minutes: int) -> list[Bar]:
    """Roll 1-minute bars up to ``minutes``-minute bars (clock-aligned)."""
    if minutes <= 1:
        return list(bars)
    period = minutes * _MINUTE_NS
    rolled: list[Bar] = []
    accumulator: _BarAccumulator | None = None
    for bar in bars:
        bucket = bar.datetime - (bar.datetime % period)
        if accumulator is None or accumulator.bucket != bucket:
            if accumulator is not None:
                previous = accumulator.to_bar()
                if previous is not None:
                    rolled.append(previous)
            accumulator = _BarAccumulator(
                bucket=bucket,
                trading_day=bar.trading_day,
                exchange_id=bar.exchange_id,
                instrument_id=bar.instrument_id,
            )
        accumulator.merge_bar(bar)
    if accumulator is not None:
        last = accumulator.to_bar()
        if last is not None:
            rolled.append(last)
    return rolled


def dedup_bars(bars: Iterable[Bar]) -> list[Bar]:
    """Sort bars by bucket and keep the newest value per bucket.

    Appending a day's bars to a file that already holds that day must be
    idempotent; a later write for the same bucket wins.
    """
    latest: dict[int, Bar] = {}
    for bar in bars:
        latest[bar.datetime] = bar  # iteration order decides, callers pass oldest first
    return [latest[key] for key in sorted(latest)]


__all__ = [
    "MinuteAggregation",
    "aggregate_1min",
    "aggregate_from_1min",
    "dedup_bars",
]
