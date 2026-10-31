"""Backtrader-owned bar/datetime projection helpers.

These helpers are the framework projection layer: they accept already-obtained
provider values and produce Backtrader bars. They contain no provider field
names and no SDK imports.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict

from ..utils.coercion import coerce_float
from ..utils.log_message import get_logger

logger = get_logger(__name__)

_UTC = _dt.timezone.utc


def datetime_to_utc_naive(value: _dt.datetime) -> _dt.datetime:
    """Return a naive UTC datetime for a timezone-aware or naive input."""
    if value.tzinfo is not None and value.utcoffset() is not None:
        return value.astimezone(_UTC).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def normalize_datetime(value: Any) -> _dt.datetime:
    """Normalize timestamps to naive UTC datetimes."""
    if isinstance(value, _dt.datetime):
        return datetime_to_utc_naive(value)

    if isinstance(value, _dt.date):
        return _dt.datetime.combine(value, _dt.time.min)

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        return _dt.datetime.fromtimestamp(timestamp, _UTC).replace(tzinfo=None)

    if isinstance(value, str):
        try:
            return datetime_to_utc_naive(_dt.datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError as error:
            logger.error("Unsupported datetime string: %r", value)
            raise ValueError(f"Unsupported datetime string: {value!r}") from error

    raise ValueError(f"Unsupported datetime value: {value!r}")


def normalize_bar(bar: Any) -> Dict[str, Any]:
    """Normalize historical/live bar payloads into a common dict."""
    if isinstance(bar, dict):
        dt_value = bar.get("timestamp")
        if dt_value in (None, ""):
            dt_value = bar.get("datetime") or bar.get("dt") or bar.get("time")
        return {
            "datetime": normalize_datetime(dt_value),
            "open": coerce_float(bar.get("open")),
            "high": coerce_float(bar.get("high")),
            "low": coerce_float(bar.get("low")),
            "close": coerce_float(bar.get("close")),
            "volume": coerce_float(bar.get("volume")),
            "openinterest": coerce_float(bar.get("openinterest"), 0.0),
        }

    if isinstance(bar, (list, tuple)) and len(bar) >= 6:
        return {
            "datetime": normalize_datetime(bar[0]),
            "open": coerce_float(bar[1]),
            "high": coerce_float(bar[2]),
            "low": coerce_float(bar[3]),
            "close": coerce_float(bar[4]),
            "volume": coerce_float(bar[5]),
            "openinterest": coerce_float(bar[6], 0.0) if len(bar) > 6 else 0.0,
        }

    raise ValueError(f"Unsupported bar payload: {bar!r}")
