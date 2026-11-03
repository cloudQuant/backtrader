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
  (checked per instance, recursively). ``frozen`` alone only blocks
  attribute rebinding, so a frozen contract holding a ``dict`` or ``list`` is
  copied, not shared (acceptance report P2-1).

A ``MappingProxyType`` is only a read-only *view*: whoever holds the dict
behind it can still change it. Even a frozen contract cannot establish that
its backing dict is private merely by holding the proxy. Each proxy is copied
into a new proxy over a new dict (acceptance report 2026-11-03 F2).

Built-in containers are copied recursively, including proxies nested inside
them. Other mutable values fall back to ``copy.deepcopy``.
(Iteration 60, step 60.03, INV-11.)
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as _dt
import enum
import weakref
from decimal import Decimal
from types import MappingProxyType, SimpleNamespace
from typing import Any

__all__ = ["snapshot_tick"]

_SCALARS = (str, int, float, bool, bytes, Decimal, _dt.date, _dt.time, _dt.timedelta, _dt.tzinfo)
_CONTRACT_PREFIXES = ("bt_api_base.", "bt_api_py.")
_frozen_contract_types: dict[type, bool] = {}
_verified: dict[int, tuple] = {}


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
        return False
    if not _is_frozen_contract(value):
        return False
    # A frozen contract verified deeply immutable can never change afterwards,
    # so the verdict is cached per live object (id + weak reference; entries
    # vanish with the object).
    key = id(value)
    cached = _verified.get(key)
    if cached is not None and cached[0]() is value:
        return True
    immutable = all(
        _is_immutable(getattr(value, field.name), depth + 1)
        for field in dataclasses.fields(value)
    )
    if immutable:
        try:
            ref = weakref.ref(value, lambda _ref, key=key: _verified.pop(key, None))
        except TypeError:  # no weakref support (slots): just don't cache
            return True
        _verified[key] = (ref,)
    return immutable


def _snapshot_value(value: Any, memo: dict[int, Any]) -> Any:
    if _is_immutable(value):
        return value
    identity = id(value)
    if identity in memo:
        return memo[identity]
    kind = type(value)
    if kind is list:
        if all(_is_immutable(item) for item in value):
            shallow_list = list(value)
            memo[identity] = shallow_list
            return shallow_list
        result: list = []
        memo[identity] = result
        result.extend(_snapshot_value(item, memo) for item in value)
        return result
    if kind is dict or kind is MappingProxyType:
        if kind is dict and all(
            _is_immutable(key) and _is_immutable(item) for key, item in value.items()
        ):
            shallow_dict = dict(value)
            memo[identity] = shallow_dict
            return shallow_dict
        result_dict: dict = {}
        result = MappingProxyType(result_dict) if kind is MappingProxyType else result_dict
        memo[identity] = result
        for key, item in value.items():
            result_dict[_snapshot_value(key, memo)] = _snapshot_value(item, memo)
        return result
    if kind is set:
        if all(_is_immutable(item) for item in value):
            shallow_set = set(value)
            memo[identity] = shallow_set
            return shallow_set
        result_set: set = set()
        memo[identity] = result_set
        result_set.update(_snapshot_value(item, memo) for item in value)
        return result_set
    if kind is tuple:
        items = [_snapshot_value(item, memo) for item in value]
        # A cycle through a mutable child may already have completed this tuple.
        if identity in memo:
            return memo[identity]
        result_tuple = tuple(items)
        memo[identity] = result_tuple
        return result_tuple
    if kind is SimpleNamespace:
        result_namespace = SimpleNamespace()
        memo[identity] = result_namespace
        for key, item in vars(value).items():
            setattr(result_namespace, key, _snapshot_value(item, memo))
        return result_namespace
    if _is_frozen_contract(value):
        # deepcopy cannot pickle mappingproxy. Prime only its memo entries,
        # then let deepcopy reconstruct the dataclass and its other state.
        _prime_contract_proxies(value, memo, set())
    return copy.deepcopy(value, memo)


def _prime_contract_proxies(value: Any, memo: dict[int, Any], seen: set[int]) -> None:
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    kind = type(value)
    if kind is MappingProxyType:
        _snapshot_value(value, memo)
    elif kind is dict:
        for key, item in value.items():
            _prime_contract_proxies(key, memo, seen)
            _prime_contract_proxies(item, memo, seen)
    elif kind in (list, tuple, set, frozenset):
        for item in value:
            _prime_contract_proxies(item, memo, seen)
    elif _is_frozen_contract(value):
        for field in dataclasses.fields(value):
            _prime_contract_proxies(getattr(value, field.name), memo, seen)


def snapshot_tick(tick: Any) -> Any:
    """Return a mutation-independent copy of ``tick`` with structural sharing."""
    return _snapshot_value(tick, {})
