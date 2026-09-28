"""Instrument naming rules for the six domestic exchanges.

The K-line layout is ``<exchange>/<symbol>/<instrument>_<period>min.parquet``,
so every tick file's name has to yield a *symbol*: ``rb2510`` -> ``rb``,
``m2509-C-3000`` -> ``m``, ``SR509C5000`` -> ``SR``.

Two things make this harder than stripping digits:

* the naming convention differs per exchange -- ``ad2610C20000`` (SHFE/INE),
  ``m2509-C-3000`` (DCE), ``FG611C1000`` (CZCE), ``HO2609-C-2500`` (CFFEX);
* CTP also delivers combination ("组合") instruments such as
  ``RM701MSC2100`` and ``c2701-MS-C-2000``, which are neither futures nor
  options and must not be synthesised into bars.

Rather than a per-exchange table, the same ordered pattern list covers all six
exchanges; it was verified against every instrument name collected on
2026-09-17/18/21 (45,902 files, 0 unclassified).  Order matters: an option is
recognised before a combination, because the combination patterns accept an
extra letter group that a plain option does not have.
"""

from __future__ import annotations

import re

from bt_api_ctp.cleaner.contracts import (
    KIND_COMBINATION,
    KIND_FUTURE,
    KIND_OPTION,
    KIND_UNKNOWN,
    InstrumentClass,
)

#: ``m2509-C-3000`` / ``HO2609-C-2500`` / ``lc2611-P-100000``.
_OPTION_DASH = re.compile(r"^([A-Za-z]{1,2})\d{3,4}-[CP]-\d+(?:\.\d+)?$")
#: ``ad2610C20000`` / ``bc2610P600`` / ``FG611C1000``.
_OPTION_NO_DASH = re.compile(r"^([A-Za-z]{1,2})\d{3,4}[CP]\d+$")
#: ``c2701-MS-C-2000`` (DCE/GFEX combination with an infix letter group).
_COMBINATION_DASH = re.compile(r"^[A-Za-z]{1,2}\d{3,4}-[A-Za-z]{1,3}-[CP]-\d+(?:\.\d+)?$")
#: ``RM701MSC2100`` (CZCE combination: infix letter group, no dashes).
_COMBINATION_NO_DASH = re.compile(r"^[A-Za-z]{1,2}\d{3,4}[A-Za-z]{1,3}[CP]\d+$")
#: ``rb2510`` / ``a2611`` / ``AP610`` / ``IF2609`` / ``T2609``.
_FUTURE = re.compile(r"^([A-Za-z]{1,2})\d{3,4}$")


def classify_contract(exchange_id: str, instrument_id: str) -> InstrumentClass:
    """Classify one instrument id.

    ``exchange_id`` is accepted so callers pass the pair they already have and
    per-exchange exceptions stay possible; the current rules are uniform across
    the six exchanges.

    Returns:
        The kind plus the symbol (``None`` for combinations and unknown ids).
    """
    del exchange_id  # rules are currently exchange-independent
    name = instrument_id.strip()

    match = _OPTION_DASH.match(name) or _OPTION_NO_DASH.match(name)
    if match:
        return InstrumentClass(kind=KIND_OPTION, symbol=match.group(1))

    if _COMBINATION_DASH.match(name) or _COMBINATION_NO_DASH.match(name):
        return InstrumentClass(kind=KIND_COMBINATION, symbol=None)

    match = _FUTURE.match(name)
    if match:
        return InstrumentClass(kind=KIND_FUTURE, symbol=match.group(1))

    return InstrumentClass(kind=KIND_UNKNOWN, symbol=None)


__all__ = [
    "KIND_COMBINATION",
    "KIND_FUTURE",
    "KIND_OPTION",
    "KIND_UNKNOWN",
    "InstrumentClass",
    "classify_contract",
]
