"""Backtrader Store cache for the latest tick observed per feed name.

The Store owns this cache and its lifecycle.  Values are detached on both
insertion and retrieval so neither a later SDK mutation nor a caller mutation
can alter the cached snapshot.  Instrument-name alias matching remains an SDK
contract supplied by the Store adapter.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List


class StoreLatestTickCache:
    """Store-owned latest-tick snapshots with alias-aware read access."""

    def __init__(
        self,
        *,
        snapshot_tick: Callable[[Any], Any],
        aliases_for: Callable[[Any], List[str]],
    ) -> None:
        if not callable(snapshot_tick) or not callable(aliases_for):
            raise TypeError("latest tick cache requires snapshot and alias callbacks")
        self._snapshot_tick = snapshot_tick
        self._aliases_for = aliases_for
        self._lock = threading.Lock()
        self._ticks: Dict[str, Any] = {}

    def store(self, dataname: str, tick: Any) -> None:
        """Publish a detached copy while holding the cache lock."""
        with self._lock:
            self._ticks[dataname] = self._snapshot_tick(tick)

    def snapshot(
        self,
        dataname: str,
        *,
        find_alias_match: Callable[..., Any],
    ) -> Any:
        """Return an independent copy of the first configured alias match."""
        aliases = self._aliases_for(dataname)
        with self._lock:
            found, tick = find_alias_match(
                self._ticks,
                aliases,
                alias_fn=self._aliases_for,
                require_truthy=False,
            )
            return self._snapshot_tick(tick) if found else None

    def clear(self) -> None:
        """Clear all names at the Store's existing lifecycle boundary."""
        with self._lock:
            self._ticks.clear()


__all__ = ("StoreLatestTickCache",)
