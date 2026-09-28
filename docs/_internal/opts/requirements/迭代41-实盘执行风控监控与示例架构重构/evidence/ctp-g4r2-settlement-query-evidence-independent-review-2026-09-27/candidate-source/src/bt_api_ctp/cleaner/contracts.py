"""Contract classification types shared by the generic cleaner and venue adapters.

The generic cleaner must not import venue code, but it still needs to know
whether a tick file is a future, an option, or something that produces no bars,
and which symbol directory the bars belong to.  A venue adapter (for CTP:
:mod:`bt_api_ctp.cleaner_ctp.symbols`) implements :class:`Classifier`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

KIND_FUTURE = "future"
KIND_OPTION = "option"
KIND_COMBINATION = "combination"
KIND_UNKNOWN = "unknown"

#: Every kind a classifier may return.
KINDS = (KIND_FUTURE, KIND_OPTION, KIND_COMBINATION, KIND_UNKNOWN)


@dataclass(frozen=True)
class InstrumentClass:
    """What an instrument id is, and which K-line symbol directory it belongs to."""

    kind: str
    symbol: str | None

    @property
    def is_bar_source(self) -> bool:
        """Whether this instrument produces K-line bars (futures and options do)."""
        return self.kind in (KIND_FUTURE, KIND_OPTION)


class Classifier(Protocol):
    """Venue-supplied instrument naming rules."""

    def __call__(self, exchange_id: str, instrument_id: str) -> InstrumentClass: ...


__all__ = [
    "KIND_COMBINATION",
    "KIND_FUTURE",
    "KIND_OPTION",
    "KIND_UNKNOWN",
    "KINDS",
    "Classifier",
    "InstrumentClass",
]
