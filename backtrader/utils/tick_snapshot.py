"""Structural-sharing snapshots for market ticks held by a Store.

``BtApiStore`` keeps the last consumed tick per data name and hands copies to
callers. A full ``copy.deepcopy`` also copies the SDK's frozen contract
objects (``MarketTickEvent`` and friends), which are immutable by
construction and dominate the copy cost.

``snapshot_tick`` produces a copy that is independent of later mutation of
either side for every value a consumer can mutate in place, while sharing
references to values that cannot change:

* immutable scalars (``str``, numbers, ``bool``, ``None``, ``Decimal``,
  date/time values, ``Enum`` members) and tuples/frozensets of them;
* frozen dataclass instances defined by the ``bt_api_base`` / ``bt_api_py``
  contract packages **whose field values are themselves deeply immutable**
  (checked per instance, recursively; ``MappingProxyType`` views of
  immutable items count as immutable). ``frozen`` alone only blocks
  attribute rebinding, so a frozen contract holding a ``dict`` or ``list`` is
  copied, not shared (acceptance report P2-1).

``list``/``set``/``dict`` values are copied one level when their items are
immutable; anything else falls back to ``copy.deepcopy`` for that value only.
Ticks that are neither ``SimpleNamespace`` nor ``dict`` fall back to a full
``deepcopy``. (Iteration 60, step 60.03, INV-11.)
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as _dt
import enum
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from typing import Any

__all__ = ["snapshot_tick"]

_SCALARS = (str, int, float, bool, bytes, Decimal, _dt.date, _dt.time, _dt.timedelta, _dt.tzinfo)
_CONTRACT_PREFIXES = ("bt_api_base.", "bt_api_py.")
_frozen_contract_types: dict[type, bool] = {}


def _is_frozen_contract(value: Any) -> bool:
    cls = type(value)
    cached = _frozen_contract_types.get(cls)
    if cached is None:
        params = getattr(cls, "__dataclass_params__", None)
        cached = bool(
            dataclasses.is_dataclass(cls)
            and params is not None
            and params.frozen
            and cls.__module__.startswith(_CONTRACT_PREFIXES)
        )
        _frozen_contract_types[cls] = cached
    return cached


_MAX_DEPTH = 16


def _is_immutable(value: Any, depth: int = 0) -> bool:
    if value is None or isinstance(value, (_SCALARS, enum.Enum)):
        return True
    if depth > _MAX_DEPTH:
        return False
    if isinstance(value, (tuple, frozenset)):
        return all(_is_immutable(item, depth + 1) for item in value)
    if type(value) is MappingProxyType:
        return all(
            _is_immutable(key, depth + 1) and _is_immutable(item, depth + 1)
            for key, item in value.items()
        )
    if not _is_frozen_contract(value):
        return False
    return all(
        _is_immutable(getattr(value, field.name), depth + 1)
        for field in dataclasses.fields(value)
    )


def _snapshot_value(value: Any) -> Any:
    if _is_immutable(value):
        return value
    kind = type(value)
    if kind is list and all(_is_immutable(item) for item in value):
        return list(value)
    if kind is set and all(_is_immutable(item) for item in value):
        return set(value)
    if kind is dict and all(_is_immutable(k) and _is_immutable(v) for k, v in value.items()):
        return dict(value)
    return copy.deepcopy(value)


def snapshot_tick(tick: Any) -> Any:
    """Return a mutation-independent copy of ``tick`` with structural sharing."""
    kind = type(tick)
    if kind is SimpleNamespace:
        return SimpleNamespace(**{k: _snapshot_value(v) for k, v in vars(tick).items()})
    if kind is dict:
        return {k: _snapshot_value(v) for k, v in tick.items()}
    return copy.deepcopy(tick)
