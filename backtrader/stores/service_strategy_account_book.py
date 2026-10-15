"""Explicit strategy-owned account-book reads over the execution service.

The service returns a strategy-scoped virtual book and its reconciliation
coverage. This adapter does not import SDK domain packages and never falls
back to account-wide positions, risk budgets, or inferred cash/value.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from ..position import Position

STRATEGY_ACCOUNT_BOOKS_OPERATION = "execution.account_books.query"
_REPLY_FIELDS = frozenset({"ok", "code", "result"})
_REMOTE_CODES = frozenset(
    {"INVALID_REQUEST", "SCOPE_DENIED", "UNAVAILABLE", "REPLY_TOO_LARGE", "UNKNOWN_OPERATION"}
)


class ServiceStrategyAccountBookError(RuntimeError):
    """Finite local or remote diagnostic for an explicit strategy book view."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code or len(code) > 64:
            code = "ACCOUNT_BOOK_UNAVAILABLE"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class StrategyAccountBookSnapshot:
    """Auditable current owner projection with no implied valuation fields."""

    strategy_ref: str
    account_ref: str
    scope_directory_revision: str
    journal_generation: str
    baseline_execution_cursor: int
    current_execution_cursor: int
    positions: Mapping[str, Decimal]
    fees_since_baseline: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))
        object.__setattr__(
            self, "fees_since_baseline", MappingProxyType(dict(self.fees_since_baseline))
        )


class ServiceStrategyAccountBookView:
    """A caller-bound view for one strategy and one account.

    A new service read is performed for each projection. The returned
    Backtrader ``Position`` exposes the book's net quantity and leaves its
    average price unset because the account-book contract has no lot cost
    basis. Cash and value are intentionally unavailable.
    """

    __slots__ = (
        "_runtime",
        "_mount",
        "_scope_ref",
        "strategy_ref",
        "account_ref",
        "_owner_thread_id",
        "_frozen",
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("strategy account-book views are immutable")
        if name not in self.__slots__:
            raise AttributeError("strategy account-book view fields are fixed")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("strategy account-book views are immutable")
        object.__delattr__(self, name)

    def __init__(
        self,
        runtime: Any,
        *,
        mount: str,
        scope_ref: str,
        strategy_ref: str,
        account_ref: str,
    ) -> None:
        if not callable(getattr(runtime, "call", None)):
            raise ServiceStrategyAccountBookError("INVALID_RUNTIME")
        for value in (mount, scope_ref, strategy_ref, account_ref):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceStrategyAccountBookError("INVALID_SCOPE")
        object.__setattr__(self, "_runtime", runtime)
        object.__setattr__(self, "_mount", mount)
        object.__setattr__(self, "_scope_ref", scope_ref)
        object.__setattr__(self, "strategy_ref", strategy_ref)
        object.__setattr__(self, "account_ref", account_ref)
        object.__setattr__(self, "_owner_thread_id", threading.get_ident())
        object.__setattr__(self, "_frozen", True)

    def snapshot(self) -> StrategyAccountBookSnapshot:
        """Read and validate the complete strategy-owned book projection."""

        if threading.get_ident() != self._owner_thread_id:
            raise ServiceStrategyAccountBookError("WRONG_OWNER_THREAD")
        try:
            reply = self._runtime.call(
                self._mount,
                STRATEGY_ACCOUNT_BOOKS_OPERATION,
                {},
                scope_ref=self._scope_ref,
            )
        except Exception as error:
            code = getattr(error, "code", None)
            if type(code) is not str or not code.isascii() or len(code) > 64:
                code = "REMOTE_QUERY_FAILED"
            raise ServiceStrategyAccountBookError(code) from None
        return _snapshot_from_reply(
            reply, strategy_ref=self.strategy_ref, account_ref=self.account_ref
        )

    def getposition(self, instrument_or_data: Any) -> Position:
        """Return a Position-like net quantity for one exact instrument key."""

        instrument = _instrument_key(instrument_or_data)
        snapshot = self.snapshot()
        quantity = snapshot.positions.get(instrument, Decimal("0"))
        try:
            size = float(quantity)
        except (OverflowError, ValueError):
            raise ServiceStrategyAccountBookError("POSITION_NOT_REPRESENTABLE") from None
        if not math.isfinite(size) or (quantity != 0 and size == 0.0):
            raise ServiceStrategyAccountBookError("POSITION_NOT_REPRESENTABLE")
        # Position has no optional-price type, but it accepts None at runtime;
        # preserving None makes the missing cost basis explicit to callers.
        return Position(size=size, price=None if size else 0.0)

    def getcash(self) -> float:
        """Cash is not present in this strategy-book contract."""

        raise ServiceStrategyAccountBookError("STRATEGY_CASH_UNAVAILABLE")

    def getvalue(self) -> float:
        """Portfolio value requires valuation inputs absent from this contract."""

        raise ServiceStrategyAccountBookError("STRATEGY_VALUE_UNAVAILABLE")


def _snapshot_from_reply(
    reply: object, *, strategy_ref: str, account_ref: str
) -> StrategyAccountBookSnapshot:
    if not isinstance(reply, Mapping) or set(reply) != _REPLY_FIELDS:
        raise ServiceStrategyAccountBookError("INVALID_REPLY")
    if reply.get("ok") is not True:
        code = reply.get("code")
        raise ServiceStrategyAccountBookError(
            code if type(code) is str and code in _REMOTE_CODES else "REMOTE_QUERY_REJECTED"
        )
    if reply.get("code") != "OK":
        raise ServiceStrategyAccountBookError("INVALID_REPLY")
    result = reply.get("result")
    if not isinstance(result, Mapping):
        raise ServiceStrategyAccountBookError("INVALID_REPLY")
    if (
        result.get("view") != "OWNER_BOOK"
        or result.get("owner_kind") != "STRATEGY"
        or result.get("owner_ref") != strategy_ref
    ):
        raise ServiceStrategyAccountBookError("OWNER_BINDING_MISMATCH")

    coverage = result.get("coverage")
    if not isinstance(coverage, Mapping):
        raise ServiceStrategyAccountBookError("INVALID_COVERAGE")
    if coverage.get("complete") is not True:
        raise ServiceStrategyAccountBookError("STRATEGY_BOOK_COVERAGE_INCOMPLETE")
    revision = _required_text(coverage.get("scope_directory_revision"), "INVALID_COVERAGE")
    generation = _required_text(coverage.get("journal_generation"), "INVALID_COVERAGE")
    baseline_cursor = _cursor(coverage.get("baseline_execution_cursor"))
    current_cursor = _cursor(coverage.get("current_execution_cursor"))
    if baseline_cursor > current_cursor:
        raise ServiceStrategyAccountBookError("INVALID_COVERAGE")

    books = result.get("books")
    if not isinstance(books, (tuple, list)) or len(books) != 1:
        raise ServiceStrategyAccountBookError("OWNER_BOOK_AMBIGUOUS")
    book = books[0]
    if (
        not isinstance(book, Mapping)
        or book.get("owner_kind") != "STRATEGY"
        or book.get("owner_ref") != strategy_ref
    ):
        raise ServiceStrategyAccountBookError("OWNER_BINDING_MISMATCH")

    positions: dict[str, Decimal] = {}
    for row in _rows(book.get("current_positions"), "INVALID_POSITION_PROJECTION"):
        instrument = _required_text(row.get("instrument"), "INVALID_POSITION_PROJECTION")
        if instrument in positions:
            raise ServiceStrategyAccountBookError("DUPLICATE_POSITION")
        positions[instrument] = _decimal_text(
            row.get("net_quantity"), "INVALID_POSITION_PROJECTION"
        )

    fees: dict[str, Decimal] = {}
    for row in _rows(book.get("fees_since_baseline"), "INVALID_FEE_PROJECTION"):
        currency = _required_text(row.get("currency"), "INVALID_FEE_PROJECTION")
        if currency in fees:
            raise ServiceStrategyAccountBookError("DUPLICATE_FEE")
        fees[currency] = _decimal_text(row.get("amount"), "INVALID_FEE_PROJECTION")

    return StrategyAccountBookSnapshot(
        strategy_ref=strategy_ref,
        account_ref=account_ref,
        scope_directory_revision=revision,
        journal_generation=generation,
        baseline_execution_cursor=baseline_cursor,
        current_execution_cursor=current_cursor,
        positions=positions,
        fees_since_baseline=fees,
    )


def _rows(value: object, error_code: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (tuple, list)):
        raise ServiceStrategyAccountBookError(error_code)
    if any(not isinstance(row, Mapping) for row in value):
        raise ServiceStrategyAccountBookError(error_code)
    return tuple(value)


def _required_text(value: object, error_code: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ServiceStrategyAccountBookError(error_code)
    return value


def _cursor(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ServiceStrategyAccountBookError("INVALID_COVERAGE")
    return value


def _decimal_text(value: object, error_code: str) -> Decimal:
    if type(value) is not str or len(value) > 128:
        raise ServiceStrategyAccountBookError(error_code)
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ServiceStrategyAccountBookError(error_code) from None
    if not parsed.is_finite():
        raise ServiceStrategyAccountBookError(error_code)
    return parsed


def _instrument_key(value: object) -> str:
    instrument = value if type(value) is str else getattr(value, "_name", None)
    if type(instrument) is not str or not instrument or instrument != instrument.strip():
        raise ServiceStrategyAccountBookError("INSTRUMENT_REQUIRED")
    return instrument


__all__ = [
    "STRATEGY_ACCOUNT_BOOKS_OPERATION",
    "ServiceStrategyAccountBookError",
    "ServiceStrategyAccountBookView",
    "StrategyAccountBookSnapshot",
]
