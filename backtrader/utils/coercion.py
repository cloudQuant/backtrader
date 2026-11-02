"""Stable, lossless coercion helpers shared by live data adapters.

These helpers never raise for untrusted vendor payloads: they return a typed
fallback instead. They deliberately contain no provider, Store, or SDK logic.
"""

from __future__ import annotations

import math
import warnings
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from .log_message import get_logger

logger = get_logger(__name__)


def coerce_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    """Convert a value to a finite float with a stable fallback."""
    if value is None:
        return default
    if isinstance(value, dict):
        for key in ("amount", "value", "balance", "total"):
            if key in value and value[key] not in (None, ""):
                return coerce_float(value[key], default)
        return default
    if isinstance(value, str):
        value = value.strip().replace(",", "")

    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def coerce_int(value: Any, default: int = 0) -> int:
    """Convert a value to int with a stable fallback.

    Decimal strings must be integral; fractional or non-finite text falls back
    instead of truncating a vendor quantity.
    """
    if value is None:
        return default

    if isinstance(value, str):
        text = value.strip().replace(",", "")
        try:
            number = Decimal(text)
        except (InvalidOperation, ValueError):
            return default
        if not number.is_finite() or number != number.to_integral_value():
            return default
        return int(number)

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def coerce_text(value: Any, default: str = "") -> str:
    """Convert vendor field values to stripped text without noisy warnings."""
    if value is None:
        return default

    if isinstance(value, bytes):
        for encoding in ("utf-8", "gbk", "latin1"):
            try:
                return value.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        return value.decode("utf-8", errors="ignore").strip()

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Failed to convert '.*' from GBK to UTF-8\.",
            category=UnicodeWarning,
        )
        try:
            return str(value).strip()
        except Exception as error:
            logger.debug("Failed to coerce value to text: %s", error)
            return default


def first_float(mapping: Dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    """Return the first finite numeric value found under ``keys``."""
    for key in keys:
        if key not in mapping:
            continue
        number = coerce_float(mapping[key], None)
        if number is not None:
            return number
    return None
