"""Explicit Feed calendar scope for the 007_ctp examples (iteration 67, D67-11).

The Feed asks the Store's read-only ``trading_calendar_query`` for one exact
``(route, venue, kind, product, contract)`` scope.  Nothing is inferred from a
symbol: the scope lives in ``calendars.feed_scope.<symbol>`` in the example's own
``config.yaml`` and each field is a caller declaration.  This module only reads
the already parsed configuration mapping; it never touches the calendar
directory, the SDK store, credentials or a provider, and it never prints a path
or a declared value.

A missing ``feed_scope`` (or a missing symbol entry) is reported as
``calendar_feed_scope_unconfigured``: ``--dry-run`` reports it and the live
start refuses it.  A malformed or conflicting declaration raises
:class:`CalendarFeedScopeRefusal` with a finite code, which both modes refuse.

``calendars.feed_scope`` is a consumer-side declaration.  The Store's SDK
parser accepts only ``root`` and ``review_mode`` under ``calendars``, so
:func:`store_calendar_section` returns that subset for the Store call.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

CALENDAR_FEED_SCOPE_UNCONFIGURED = "calendar_feed_scope_unconfigured"
CALENDAR_FEED_SCOPE_INVALID = "calendar_feed_scope_invalid"
CALENDAR_FEED_SCOPE_CONFLICT = "calendar_feed_scope_conflict"

_REQUIRED_KEYS = ("venue", "kind", "product", "contract")
_SCOPE_KEYS = ("route",) + _REQUIRED_KEYS
_TEXT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_KINDS = frozenset({"future", "option"})
_STORE_KEYS = ("root", "review_mode")
_RESERVED = frozenset("calendar_" + name for name in _SCOPE_KEYS)

_REASONS = {
    CALENDAR_FEED_SCOPE_UNCONFIGURED: (
        "calendars.feed_scope is missing for one or more symbols; declare an "
        "explicit Feed calendar scope (D67-11)"
    ),
    CALENDAR_FEED_SCOPE_INVALID: (
        "calendars.feed_scope is malformed; every scope needs venue, kind, "
        "product and contract"
    ),
    CALENDAR_FEED_SCOPE_CONFLICT: (
        "calendars.feed_scope conflicts with the configured symbol, exchange, "
        "route or feed keys"
    ),
}


class CalendarFeedScopeRefusal(ValueError):
    """A finite scope refusal; ``code`` and ``reason`` never contain a path or value."""

    def __init__(self, code, reason=None):
        if code not in _REASONS:
            raise ValueError("unknown calendar feed scope code")
        super().__init__(code)
        self.code = code
        self.reason = reason or _REASONS[code]


@dataclass(frozen=True)
class CalendarFeedScopeResult:
    """``scopes`` maps each configured symbol to ``BtApiFeed`` ``calendar_*`` kwargs.

    ``code`` is set only for a missing declaration, which the caller reports:
    the dry-run passes with that code and the live start refuses it.
    """

    scopes: dict = field(default_factory=dict)
    code: str | None = None
    reason: str | None = None


def _text(value):
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and bool(_TEXT.match(value))
    )


def store_calendar_section(config):
    """Return the ``calendars`` subset accepted by the SDK and Store parser.

    ``feed_scope`` is a consumer-side declaration; the Store's SDK parser
    rejects unknown ``calendars`` keys, so only ``root`` and ``review_mode`` are
    forwarded.  An absent section stays absent; an invalid shape is returned
    unchanged so the Store reports it exactly as before.
    """
    section = config.get("calendars") if isinstance(config, Mapping) else None
    if section is None:
        return None
    if type(section) is not dict:
        return section
    return {key: section[key] for key in _STORE_KEYS if key in section}


def _validate_scope(symbol, scope, *, route, contract_exchange):
    if type(scope) is not dict:
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    if set(scope) - set(_SCOPE_KEYS):
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    if any(key not in scope for key in _REQUIRED_KEYS):
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    if any(not _text(scope[key]) for key in _REQUIRED_KEYS):
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    if scope["kind"] not in _KINDS:
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    declared_route = scope.get("route")
    if declared_route is not None:
        if not _text(declared_route):
            raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
        if declared_route != route:
            raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
    if scope["contract"] != symbol:
        # The Feed's dataname is the symbol; a different contract would query
        # another instrument's calendar.  Never derive it from the symbol.
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
    if contract_exchange is not None and scope["venue"] != contract_exchange:
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
    return {
        "calendar_route": declared_route if declared_route is not None else route,
        "calendar_venue": scope["venue"],
        "calendar_kind": scope["kind"],
        "calendar_product": scope["product"],
        "calendar_contract": scope["contract"],
    }


def check_direct_feed_scope(config, *, symbols, route):
    """Resolve one explicit Feed calendar scope per configured symbol.

    ``symbols`` and ``route`` are the example's own explicit declarations.
    Reads no files and never guesses symbol->contract.  An absent ``calendars``
    section is left to the D67-01 root gate and returns an empty result.
    """
    if (
        type(symbols) not in (tuple, list)
        or not symbols
        or any(type(symbol) is not str or not symbol for symbol in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    if not _text(route):
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    section = config.get("calendars") if isinstance(config, Mapping) else None
    if section is None:
        return CalendarFeedScopeResult()
    if type(section) is not dict:
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    declared = section.get("feed_scope")
    if declared is None or declared == {}:
        return CalendarFeedScopeResult(
            {}, CALENDAR_FEED_SCOPE_UNCONFIGURED, _REASONS[CALENDAR_FEED_SCOPE_UNCONFIGURED]
        )
    if type(declared) is not dict:
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_INVALID)
    if set(declared) - set(symbols):
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
    if set(symbols) - set(declared):
        # Fail closed instead of wiring a partial set of feeds.
        return CalendarFeedScopeResult(
            {}, CALENDAR_FEED_SCOPE_UNCONFIGURED, _REASONS[CALENDAR_FEED_SCOPE_UNCONFIGURED]
        )
    feed = config.get("feed")
    contracts = config.get("contracts")
    if isinstance(feed, Mapping) and set(feed) & _RESERVED:
        # The Feed calendar scope has exactly one source; a duplicated key in
        # ``feed`` would silently overwrite or duplicate it.
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
    if contracts is not None and type(contracts) is not dict:
        raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
    scopes = {}
    for symbol in symbols:
        row = contracts.get(symbol) if isinstance(contracts, dict) else None
        if row is not None and type(row) is not dict:
            raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
        if isinstance(row, dict) and set(row) & _RESERVED:
            raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
        exchange = row.get("exchange") if isinstance(row, dict) else None
        if exchange is not None and not _text(exchange):
            raise CalendarFeedScopeRefusal(CALENDAR_FEED_SCOPE_CONFLICT)
        scopes[symbol] = _validate_scope(
            symbol, declared[symbol], route=route, contract_exchange=exchange
        )
    return CalendarFeedScopeResult(scopes)
