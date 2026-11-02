"""Own Backtrader Store history-bar caches and row-copy projection.

This component contains no SDK query or provider logic. ``BtApiStore`` remains
responsible for deciding when to fetch history; this object owns the local
seeded/default cache, request-keyed cache, and copy/normalization rules used
by Backtrader feeds.
"""

from __future__ import annotations

import collections
from collections.abc import Mapping
from copy import deepcopy
from types import MappingProxyType
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple


class StoreBarHistoryCache:
    """Single owner for local history caches and Backtrader bar copies."""

    def __init__(
        self,
        *,
        preserve_raw_bars: bool,
        normalize_bar: Callable[[Any], Any],
    ) -> None:
        if type(preserve_raw_bars) is not bool or not callable(normalize_bar):
            raise TypeError("history cache requires an exact preserve flag and normalizer")
        self._preserve_raw_bars = preserve_raw_bars
        self._normalize_bar = normalize_bar
        self._bars: Dict[Any, Any] = collections.defaultdict(collections.deque)
        self._query_cache: Dict[Any, List[Any]] = {}

    @property
    def preserve_raw_bars(self) -> bool:
        """Whether source bar fields are retained for strict consumers."""
        return self._preserve_raw_bars

    def seed(self, source: Optional[Mapping[str, Iterable[Any]]]) -> None:
        """Append initialization bars to their exact dataname cache."""
        if not source:
            return
        for dataname, bars in source.items():
            self._bars[dataname].extend(self.copy_or_normalize_bar(bar) for bar in bars)

    def copy_or_normalize_bar(self, bar: Any) -> Any:
        """Normalize ordinary bars or deeply preserve explicit raw mappings."""
        if not self._preserve_raw_bars:
            return self._normalize_bar(bar)
        if isinstance(bar, Mapping):
            source = dict(bar)
            field_observations = source.get("field_observations")
            mapping_proxy_type = type(MappingProxyType({}))
            if type(field_observations) is mapping_proxy_type:
                memo = {}
                copied_observations = MappingProxyType(deepcopy(dict(field_observations), memo))
                memo[id(field_observations)] = copied_observations
                return {
                    deepcopy(key, memo): deepcopy(value, memo)
                    for key, value in source.items()
                }
            return deepcopy(source)
        return deepcopy(bar)

    def copy_history_sequence(self, bars: Iterable[Any]) -> List[Any]:
        """Return independent history rows with the existing opt-in PIT rule."""
        if self._preserve_raw_bars:
            return [self.copy_or_normalize_bar(bar) for bar in bars]
        return deepcopy(list(bars))

    @staticmethod
    def is_default_request(timeframe, compression, since, limit) -> bool:
        return timeframe is None and int(compression or 1) == 1 and since is None and limit is None

    @staticmethod
    def request_key(dataname, timeframe, compression, since, limit) -> Tuple[Any, ...]:
        return (
            str(dataname),
            repr(timeframe),
            int(compression or 1),
            repr(since),
            None if limit is None else int(limit),
        )

    def lookup(
        self,
        dataname: str,
        timeframe,
        compression,
        since,
        limit,
    ) -> Tuple[bool, Any, bool, List[Any]]:
        """Return a copied hit, its key, and default-request classification."""
        request_key = self.request_key(dataname, timeframe, compression, since, limit)
        default_request = self.is_default_request(timeframe, compression, since, limit)
        if default_request and self._bars[dataname]:
            return (
                True,
                request_key,
                default_request,
                self.copy_history_sequence(self._bars[dataname]),
            )
        if request_key in self._query_cache:
            return (
                True,
                request_key,
                default_request,
                self.copy_history_sequence(self._query_cache[request_key]),
            )
        return False, request_key, default_request, []

    def has_default_history(self, dataname: str) -> bool:
        """Check the default history cache, retaining defaultdict lookup behavior."""
        return bool(self._bars[dataname])

    def cached_default_history(self, dataname: str) -> List[Any]:
        """Return an independent copy of one default history cache."""
        return self.copy_history_sequence(self._bars[dataname])

    def cache_result(
        self,
        dataname: str,
        request_key: Any,
        default_request: bool,
        bars: List[Any],
    ) -> None:
        """Store already projected rows under the original default/query rule."""
        if default_request:
            self._bars[dataname].clear()
            self._bars[dataname].extend(bars)
        else:
            self._query_cache[request_key] = list(bars)

    def set_history(self, dataname: str, bars: Iterable[Any]) -> None:
        """Replace local seeded history and invalidate that dataname's query rows."""
        self.clear_query_cache(dataname)
        self._bars[dataname] = collections.deque(
            self.copy_or_normalize_bar(bar) for bar in bars
        )

    def clear_query_cache(self, dataname: str) -> None:
        """Clear every cached request whose original key names this dataname."""
        key_prefix = str(dataname)
        for key in [key for key in self._query_cache if key[0] == key_prefix]:
            self._query_cache.pop(key, None)


__all__ = ("StoreBarHistoryCache",)
