"""Normalize native CTP depth-market snapshots into ``TickRecord``.

Every member of ``CThostFtdcDepthMarketDataField`` is mapped.  Native
unavailable sentinels (``DBL_MAX``) and non-finite values become ``None``
so that downstream Parquet columns stay statistically meaningful.
"""

from __future__ import annotations

import math
import time
from typing import Any

from bt_api_ctp.collector.protocols import TickRecord
from bt_api_ctp.instrument import field_value

#: CTP uses DBL_MAX for "no such price" (for example an absent limit price).
_DBL_MAX_THRESHOLD = 1e308

_LEVEL_COUNT = 5

_FLOAT_FIELDS: tuple[tuple[str, str], ...] = (
    ("last_price", "LastPrice"),
    ("pre_settlement", "PreSettlementPrice"),
    ("pre_close", "PreClosePrice"),
    ("pre_open_interest", "PreOpenInterest"),
    ("open_price", "OpenPrice"),
    ("highest_price", "HighestPrice"),
    ("lowest_price", "LowestPrice"),
    ("turnover", "Turnover"),
    ("open_interest", "OpenInterest"),
    ("close_price", "ClosePrice"),
    ("settlement_price", "SettlementPrice"),
    ("upper_limit", "UpperLimitPrice"),
    ("lower_limit", "LowerLimitPrice"),
    ("pre_delta", "PreDelta"),
    ("curr_delta", "CurrDelta"),
    ("average_price", "AveragePrice"),
    ("banding_upper_price", "BandingUpperPrice"),
    ("banding_lower_price", "BandingLowerPrice"),
)

_INT_FIELDS: tuple[tuple[str, str], ...] = (("volume", "Volume"),)


def _finite_float(source: Any, name: str) -> float | None:
    value = field_value(source, name)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number >= _DBL_MAX_THRESHOLD:
        return None
    return number


def _finite_int(source: Any, name: str) -> int | None:
    value = field_value(source, name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _levels(source: Any, prefix: str, *, as_int: bool) -> tuple[Any, ...]:
    reader = _finite_int if as_int else _finite_float
    return tuple(reader(source, f"{prefix}{index}") for index in range(1, _LEVEL_COUNT + 1))


class CtpTickNormalizer:
    """Transform one native CTP tick into a venue-neutral ``TickRecord``."""

    def normalize(self, raw: Any, *, local_receive_time: int | None = None) -> TickRecord | None:
        """Return ``None`` when the payload carries no instrument identity."""
        instrument_id = field_value(raw, "InstrumentID")
        if not instrument_id:
            return None

        exchange_inst_id = field_value(raw, "ExchangeInstID")
        values: dict[str, Any] = {
            name: _finite_float(raw, native) for name, native in _FLOAT_FIELDS
        }
        for name, native in _INT_FIELDS:
            values[name] = _finite_int(raw, native)

        return TickRecord(
            exchange_id=str(field_value(raw, "ExchangeID") or ""),
            instrument_id=str(instrument_id),
            exchange_inst_id=str(exchange_inst_id) if exchange_inst_id else None,
            trading_day=str(field_value(raw, "TradingDay") or ""),
            action_day=str(field_value(raw, "ActionDay") or ""),
            update_time=str(field_value(raw, "UpdateTime") or ""),
            update_millisec=_finite_int(raw, "UpdateMillisec") or 0,
            local_receive_time=(
                int(local_receive_time) if local_receive_time is not None else time.time_ns()
            ),
            bid_price=_levels(raw, "BidPrice", as_int=False),
            bid_volume=_levels(raw, "BidVolume", as_int=True),
            ask_price=_levels(raw, "AskPrice", as_int=False),
            ask_volume=_levels(raw, "AskVolume", as_int=True),
            **values,
        )


__all__ = ["CtpTickNormalizer"]
