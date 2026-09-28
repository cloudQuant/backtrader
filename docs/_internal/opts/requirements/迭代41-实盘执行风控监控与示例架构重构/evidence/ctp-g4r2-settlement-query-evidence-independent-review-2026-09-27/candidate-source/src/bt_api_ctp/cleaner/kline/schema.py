"""K-line data model and the fixed on-disk schema.

Bars are keyed by ``datetime`` alone inside a file: the file path already fixes
the exchange, instrument and period, and a bar's bucket start time is unique
within a trading day.  ``datetime`` is the exchange's local wall clock encoded
as an epoch-nanosecond integer (naive, i.e. no timezone), which is also how
pyarrow stores ``timestamp[ns]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyarrow as pa


@dataclass(frozen=True)
class Bar:
    """One aggregated K line."""

    #: Bucket start, epoch nanoseconds of the exchange-local wall clock.
    datetime: int
    open: float
    high: float
    low: float
    close: float
    #: Traded volume inside the bucket (differenced from the cumulative field).
    volume: int
    #: Traded amount inside the bucket (differenced from the cumulative field).
    amount: float
    #: Open interest at the end of the bucket.
    open_interest: float | None
    trading_day: str
    exchange_id: str
    instrument_id: str


#: Fixed K-line schema (迭代06 NFR-5).  Column order never changes.
BAR_ARROW_SCHEMA = pa.schema(
    [
        pa.field("datetime", pa.timestamp("ns")),
        pa.field("trading_day", pa.string()),
        pa.field("exchange_id", pa.string()),
        pa.field("instrument_id", pa.string()),
        pa.field("open", pa.float64()),
        pa.field("high", pa.float64()),
        pa.field("low", pa.float64()),
        pa.field("close", pa.float64()),
        pa.field("volume", pa.int64()),
        pa.field("amount", pa.float64()),
        pa.field("open_interest", pa.float64()),
    ]
)


def bar_to_row(bar: Bar) -> dict[str, Any]:
    """Convert a :class:`Bar` into a row matching :data:`BAR_ARROW_SCHEMA`."""
    return {
        "datetime": bar.datetime,
        "trading_day": bar.trading_day,
        "exchange_id": bar.exchange_id,
        "instrument_id": bar.instrument_id,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "amount": bar.amount,
        "open_interest": bar.open_interest,
    }


__all__ = ["BAR_ARROW_SCHEMA", "Bar", "bar_to_row"]
