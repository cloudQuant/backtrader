from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def ctp_code(value: Any, default: str = "") -> str:
    """Normalize CTP enum-like values that may arrive as ints, floats, or strings."""
    if value in (None, ""):
        return default
    text = str(value).strip()
    if not text:
        return default
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    if number.is_integer():
        return str(int(number))
    return text


def ctp_dict_code(content: Mapping[Any, Any], key: Any, default: str = "") -> str:
    if key not in content:
        return default
    return ctp_code(content.get(key), default)


def ctp_int(content: Mapping[Any, Any], key: Any, default: int | None = None) -> int | None:
    if key not in content:
        return default
    value = content.get(key)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
