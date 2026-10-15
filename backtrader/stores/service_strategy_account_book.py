"""Explicit strategy-owned account-book reads over the execution service.

The service returns a strategy-scoped virtual book and its reconciliation
coverage. This adapter does not import SDK domain packages and never falls
back to account-wide positions, risk budgets, or inferred cash/value.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
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
class StrategyPositionCost:
    """One persisted owner position and its explicitly sourced cost basis."""

    quantity: Decimal
    cost_basis: Decimal | None
    cost_currency: str | None
    product_model: str
    metadata_version: str
    average_cost: Decimal | None


@dataclass(frozen=True, slots=True)
class StrategyFinancialWatermark:
    """One immutable source cursor from the independent financial cut."""

    source_kind: str
    source_ref: str
    generation: str
    cursor: int
    as_of_ns: int


@dataclass(frozen=True, slots=True)
class StrategyFinancialLedgerCut:
    """The persisted financial ledger cut, kept separate from legacy coverage."""

    account_key: str
    owner_directory_revision: str
    captured_at_ns: int
    watermarks: tuple[StrategyFinancialWatermark, ...]


@dataclass(frozen=True, slots=True)
class StrategyAccountBookSnapshot:
    """Auditable owner projection without an inferred account-wide valuation."""

    strategy_ref: str
    account_ref: str
    scope_directory_revision: str
    journal_generation: str
    baseline_execution_cursor: int
    current_execution_cursor: int
    positions: Mapping[str, Decimal]
    fees_since_baseline: Mapping[str, Decimal]
    cash_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    position_costs: Mapping[str, StrategyPositionCost] = field(default_factory=dict)
    cumulative_fees_by_currency: Mapping[str, Decimal] = field(default_factory=dict)
    financial_available: bool = False
    cost_basis_complete: bool = False
    financial_error_code: str = "STRATEGY_FINANCIAL_UNAVAILABLE"
    financial_source: str | None = None
    financial_freshness: str | None = None
    financial_cut_relationship: str | None = None
    financial_ledger_cut: StrategyFinancialLedgerCut | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "positions", MappingProxyType(dict(self.positions)))
        object.__setattr__(
            self, "fees_since_baseline", MappingProxyType(dict(self.fees_since_baseline))
        )
        object.__setattr__(self, "cash_by_currency", MappingProxyType(dict(self.cash_by_currency)))
        object.__setattr__(self, "position_costs", MappingProxyType(dict(self.position_costs)))
        object.__setattr__(
            self,
            "cumulative_fees_by_currency",
            MappingProxyType(dict(self.cumulative_fees_by_currency)),
        )


class ServiceStrategyAccountBookView:
    """A caller-bound view for one strategy and one account.

    A new service read is performed for each projection. The returned
    Backtrader ``Position`` exposes the book's net quantity and uses an
    average price only when the complete persisted owner cost basis agrees
    with that quantity. Cash is readable only with an explicit currency.
    Portfolio value stays unavailable without trusted current marks and FX.
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
        """Return net quantity and, when complete, the persisted average cost."""

        instrument = _instrument_key(instrument_or_data)
        snapshot = self.snapshot()
        quantity = snapshot.positions.get(instrument, Decimal("0"))
        size = _finite_float(quantity, "POSITION_NOT_REPRESENTABLE")
        price: float | None = 0.0 if size == 0.0 else None
        cost = snapshot.position_costs.get(instrument)
        if snapshot.financial_available and cost is not None and cost.quantity != quantity:
            raise ServiceStrategyAccountBookError("STRATEGY_POSITION_COST_MISMATCH")
        if size != 0.0 and snapshot.financial_available and snapshot.cost_basis_complete:
            if cost is not None and cost.average_cost is not None:
                price = _finite_float(cost.average_cost, "POSITION_COST_NOT_REPRESENTABLE")
        return Position(size=size, price=price)

    def getcash(self, *, currency: str | None = None) -> Decimal:
        """Return this owner's persisted cash amount in one required currency."""

        if currency is None:
            raise ServiceStrategyAccountBookError("STRATEGY_CASH_CURRENCY_REQUIRED")
        currency = _required_text(currency, "INVALID_CASH_CURRENCY")
        snapshot = self.snapshot()
        if not snapshot.financial_available:
            raise ServiceStrategyAccountBookError(snapshot.financial_error_code)
        amount = snapshot.cash_by_currency.get(currency)
        if amount is None:
            raise ServiceStrategyAccountBookError("STRATEGY_CASH_UNAVAILABLE")
        return amount

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
    legacy_account_key = coverage.get("account_key")
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

    financial = _financial_projection_from_result(
        result,
        strategy_ref=strategy_ref,
        expected_account_key=legacy_account_key,
        legacy_positions=positions,
        journal_generation=generation,
        current_execution_cursor=current_cursor,
    )
    return StrategyAccountBookSnapshot(
        strategy_ref=strategy_ref,
        account_ref=account_ref,
        scope_directory_revision=revision,
        journal_generation=generation,
        baseline_execution_cursor=baseline_cursor,
        current_execution_cursor=current_cursor,
        positions=positions,
        fees_since_baseline=fees,
        **financial,
    )


def _financial_projection_from_result(
    result: Mapping[str, Any],
    *,
    strategy_ref: str,
    expected_account_key: Any,
    legacy_positions: Mapping[str, Decimal],
    journal_generation: str,
    current_execution_cursor: int,
) -> dict[str, Any]:
    financial = result.get("financial")
    if financial is None:
        return _unavailable_financial_fields("STRATEGY_FINANCIAL_UNAVAILABLE")
    if not isinstance(financial, Mapping):
        raise ServiceStrategyAccountBookError("INVALID_FINANCIAL_PROJECTION")
    if financial.get("available") is not True:
        code = financial.get("code")
        if type(code) is not str or not code.isascii() or len(code) > 64:
            code = "STRATEGY_FINANCIAL_UNAVAILABLE"
        return _unavailable_financial_fields(code)
    if (
        type(expected_account_key) is not str
        or not expected_account_key
        or expected_account_key != expected_account_key.strip()
    ):
        return _unavailable_financial_fields("STRATEGY_FINANCIAL_ACCOUNT_KEY_UNAVAILABLE")
    if (
        financial.get("source") != "PERSISTED_EXECUTION_FINANCIAL_PROJECTION"
        or financial.get("freshness") != "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED"
        or financial.get("cut_relationship") != "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
        or financial.get("view") != "OWNER_BOOK"
        or financial.get("owner_kind") != "STRATEGY"
        or financial.get("owner_ref") != strategy_ref
        or "state" in financial
        or "unallocated" in financial
    ):
        raise ServiceStrategyAccountBookError("OWNER_BINDING_MISMATCH")
    if financial.get("complete") is not True:
        return _unavailable_financial_fields("STRATEGY_FINANCIAL_INCOMPLETE")

    ledger_cut = financial.get("ledger_cut")
    if not isinstance(ledger_cut, Mapping):
        return _unavailable_financial_fields("STRATEGY_FINANCIAL_CUT_UNAVAILABLE")
    try:
        if set(ledger_cut) != {
            "account_key",
            "owner_directory_revision",
            "captured_at_ns",
            "watermarks",
        }:
            raise ServiceStrategyAccountBookError("INVALID_FINANCIAL_CUT")
        account_key = _required_text(ledger_cut.get("account_key"), "INVALID_FINANCIAL_CUT")
        if account_key != expected_account_key:
            return _unavailable_financial_fields("STRATEGY_FINANCIAL_ACCOUNT_MISMATCH")
        directory_revision = _required_text(
            ledger_cut.get("owner_directory_revision"), "INVALID_FINANCIAL_CUT"
        )
        captured_at_ns = _timestamp(ledger_cut.get("captured_at_ns"))
        watermarks = _rows(ledger_cut.get("watermarks"), "INVALID_FINANCIAL_CUT")
        parsed_watermarks: list[StrategyFinancialWatermark] = []
        for row in watermarks:
            if set(row) != {"source_kind", "source_ref", "generation", "cursor", "as_of_ns"}:
                raise ServiceStrategyAccountBookError("INVALID_FINANCIAL_CUT")
            parsed_watermarks.append(
                StrategyFinancialWatermark(
                    source_kind=_required_text(row.get("source_kind"), "INVALID_FINANCIAL_CUT"),
                    source_ref=_required_text(row.get("source_ref"), "INVALID_FINANCIAL_CUT"),
                    generation=_required_text(row.get("generation"), "INVALID_FINANCIAL_CUT"),
                    cursor=_cursor(row.get("cursor")),
                    as_of_ns=_timestamp(row.get("as_of_ns")),
                )
            )
        watermark_kinds = [item.source_kind for item in parsed_watermarks]
        if (
            len(watermark_kinds) != 3
            or len(set(watermark_kinds)) != 3
            or set(watermark_kinds) != {"execution_outbox", "account_facts", "account_activity"}
            or any(item.as_of_ns > captured_at_ns for item in parsed_watermarks)
        ):
            return _unavailable_financial_fields("STRATEGY_FINANCIAL_CUT_UNAVAILABLE")
        execution_watermark = next(
            item for item in parsed_watermarks if item.source_kind == "execution_outbox"
        )
        if (
            execution_watermark.generation != journal_generation
            or execution_watermark.cursor != current_execution_cursor
        ):
            return _unavailable_financial_fields("STRATEGY_FINANCIAL_CUT_MISMATCH")
    except ServiceStrategyAccountBookError:
        return _unavailable_financial_fields("STRATEGY_FINANCIAL_CUT_UNAVAILABLE")

    financial_cut = StrategyFinancialLedgerCut(
        account_key=account_key,
        owner_directory_revision=directory_revision,
        captured_at_ns=captured_at_ns,
        watermarks=tuple(parsed_watermarks),
    )

    books = _rows(financial.get("books"), "INVALID_FINANCIAL_PROJECTION")
    if len(books) != 1:
        raise ServiceStrategyAccountBookError("OWNER_BOOK_AMBIGUOUS")
    owner_book = books[0]
    if owner_book.get("ledger_cut") != ledger_cut:
        return _unavailable_financial_fields("STRATEGY_FINANCIAL_CUT_MISMATCH")
    owner = owner_book.get("owner")
    if (
        not isinstance(owner, Mapping)
        or owner.get("kind") != "STRATEGY"
        or owner.get("owner_ref") != strategy_ref
    ):
        raise ServiceStrategyAccountBookError("OWNER_BINDING_MISMATCH")

    cash: dict[str, Decimal] = {}
    for row in _rows(owner_book.get("cash"), "INVALID_CASH_PROJECTION"):
        currency = _required_text(row.get("currency"), "INVALID_CASH_PROJECTION")
        if currency in cash:
            raise ServiceStrategyAccountBookError("DUPLICATE_CASH_CURRENCY")
        cash[currency] = _decimal_text(row.get("amount"), "INVALID_CASH_PROJECTION")

    fees: dict[str, Decimal] = {}
    for row in _rows(owner_book.get("cumulative_fees"), "INVALID_FEE_PROJECTION"):
        currency = _required_text(row.get("currency"), "INVALID_FEE_PROJECTION")
        if currency in fees:
            raise ServiceStrategyAccountBookError("DUPLICATE_CUMULATIVE_FEE")
        fees[currency] = _decimal_text(row.get("amount"), "INVALID_FEE_PROJECTION")

    cost_basis_complete = owner_book.get("cost_basis_complete")
    if type(cost_basis_complete) is not bool:
        raise ServiceStrategyAccountBookError("INVALID_COST_BASIS_PROJECTION")
    position_costs: dict[str, StrategyPositionCost] = {}
    for row in _rows(owner_book.get("positions"), "INVALID_COST_BASIS_PROJECTION"):
        instrument = _required_text(row.get("instrument"), "INVALID_COST_BASIS_PROJECTION")
        if instrument in position_costs:
            raise ServiceStrategyAccountBookError("DUPLICATE_POSITION_COST")
        product_model = _required_text(row.get("product_model"), "INVALID_COST_BASIS_PROJECTION")
        if product_model != "SPOT":
            raise ServiceStrategyAccountBookError("UNSUPPORTED_PRODUCT_MODEL")
        metadata_version = _required_text(
            row.get("metadata_version"), "INVALID_COST_BASIS_PROJECTION"
        )
        quantity = _decimal_text(row.get("quantity"), "INVALID_COST_BASIS_PROJECTION")
        if quantity < 0:
            raise ServiceStrategyAccountBookError("INVALID_COST_BASIS_PROJECTION")
        raw_basis = row.get("cost_basis")
        if raw_basis is None:
            cost_basis = None
            cost_currency = row.get("cost_currency")
            if cost_currency is not None:
                raise ServiceStrategyAccountBookError("INVALID_COST_BASIS_PROJECTION")
        else:
            cost_basis = _decimal_text(raw_basis, "INVALID_COST_BASIS_PROJECTION")
            cost_currency = _required_text(
                row.get("cost_currency"), "INVALID_COST_BASIS_PROJECTION"
            )
            if cost_basis < 0 or (quantity == 0 and cost_basis != 0):
                raise ServiceStrategyAccountBookError("INVALID_COST_BASIS_PROJECTION")
            if quantity > 0 and cost_basis == 0:
                raise ServiceStrategyAccountBookError("INVALID_COST_BASIS_PROJECTION")
        if row.get("cost_method") != "AVERAGE_COST":
            raise ServiceStrategyAccountBookError("UNSUPPORTED_COST_METHOD")
        average_cost = None
        if cost_basis_complete and cost_basis is not None:
            average_cost = cost_basis / quantity if quantity else Decimal("0")
        position_costs[instrument] = StrategyPositionCost(
            quantity=quantity,
            cost_basis=cost_basis,
            cost_currency=cost_currency,
            product_model=product_model,
            metadata_version=metadata_version,
            average_cost=average_cost,
        )

    if cost_basis_complete and any(
        quantity != 0
        and (
            (cost := position_costs.get(instrument)) is None
            or cost.quantity != quantity
            or cost.cost_basis is None
        )
        for instrument, quantity in legacy_positions.items()
    ):
        cost_basis_complete = False

    return {
        "cash_by_currency": cash,
        "position_costs": position_costs,
        "cumulative_fees_by_currency": fees,
        "financial_available": True,
        "cost_basis_complete": cost_basis_complete,
        "financial_error_code": "",
        "financial_source": "PERSISTED_EXECUTION_FINANCIAL_PROJECTION",
        "financial_freshness": "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED",
        "financial_cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
        "financial_ledger_cut": financial_cut,
    }


def _unavailable_financial_fields(code: str) -> dict[str, Any]:
    return {
        "cash_by_currency": {},
        "position_costs": {},
        "cumulative_fees_by_currency": {},
        "financial_available": False,
        "cost_basis_complete": False,
        "financial_error_code": code,
        "financial_source": None,
        "financial_freshness": None,
        "financial_cut_relationship": None,
        "financial_ledger_cut": None,
    }


def _finite_float(value: Decimal, error_code: str) -> float:
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        raise ServiceStrategyAccountBookError(error_code) from None
    if not math.isfinite(converted) or (value != 0 and converted == 0.0):
        raise ServiceStrategyAccountBookError(error_code)
    return converted


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


def _timestamp(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ServiceStrategyAccountBookError("INVALID_FINANCIAL_CUT")
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
    "StrategyFinancialLedgerCut",
    "StrategyFinancialWatermark",
    "StrategyPositionCost",
    "StrategyAccountBookSnapshot",
]
