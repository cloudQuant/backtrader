"""Strategy-owned account-book reads and Backtrader projections.

The SDK owns route validation and account-book wire parsing. This module keeps
the Strategy-bound view and its Backtrader ``Position``/cash/value projection;
it never falls back to account-wide positions or inferred valuation.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from bt_api_py.account_book_contracts import StrategyAccountBookSnapshot as _StrategyAccountBookSnapshot
from bt_api_py.service_account_book_client import ServiceStrategyAccountBookClient

from ..position import Position


class ServiceStrategyAccountBookError(RuntimeError):
    """Finite local or SDK diagnostic for an explicit strategy book view."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code or not code.isascii() or len(code) > 64:
            code = "ACCOUNT_BOOK_UNAVAILABLE"
        self.code = code
        super().__init__(code)


class _StrategyAccountBookProjection:
    """Backtrader projections shared by every strategy-bound book view.

    Subclasses provide ``snapshot()`` returning a validated
    ``StrategyAccountBookSnapshot`` bound to their strategy and account.
    Direct and service views therefore project positions and cash the same
    way and never fall back to account-wide Broker values.
    """

    __slots__ = ()

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


class ServiceStrategyAccountBookView(_StrategyAccountBookProjection):
    """A caller-bound view for one strategy and one account.

    The SDK reader revalidates its exact runtime route and registration on each
    read, then returns the neutral typed snapshot. This view only binds that
    snapshot to the configured Strategy and projects its local broker-facing
    values. Cash requires an explicit currency; portfolio value remains
    unavailable without trusted current marks and FX.
    """

    __slots__ = ("_client", "strategy_ref", "account_ref", "_owner_thread_id", "_frozen")

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
        for value in (mount, scope_ref, strategy_ref, account_ref):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceStrategyAccountBookError("INVALID_SCOPE")
        try:
            client = ServiceStrategyAccountBookClient(
                runtime,
                mount=mount,
                scope_ref=scope_ref,
                strategy_ref=strategy_ref,
                account_ref=account_ref,
            )
        except Exception as error:
            raise ServiceStrategyAccountBookError(_safe_code(error, "INVALID_RUNTIME")) from None
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "strategy_ref", strategy_ref)
        object.__setattr__(self, "account_ref", account_ref)
        object.__setattr__(self, "_owner_thread_id", threading.get_ident())
        object.__setattr__(self, "_frozen", True)

    def snapshot(self) -> _StrategyAccountBookSnapshot:
        """Read one SDK-validated strategy-owned snapshot."""

        if threading.get_ident() != self._owner_thread_id:
            raise ServiceStrategyAccountBookError("WRONG_OWNER_THREAD")
        try:
            snapshot = self._client.snapshot()
        except Exception as error:
            raise ServiceStrategyAccountBookError(
                _safe_code(error, "REMOTE_QUERY_FAILED")
            ) from None
        if type(snapshot) is not _StrategyAccountBookSnapshot:
            raise ServiceStrategyAccountBookError("INVALID_SNAPSHOT")
        if snapshot.strategy_ref != self.strategy_ref or snapshot.account_ref != self.account_ref:
            raise ServiceStrategyAccountBookError("OWNER_BINDING_MISMATCH")
        return snapshot

class DirectStrategyAccountBookView(_StrategyAccountBookProjection):
    """A strategy-bound view over a direct-mode SDK account-book reader.

    ``reader.snapshot()`` must return the same neutral
    ``StrategyAccountBookSnapshot`` the service path returns (for example
    ``bt_api_py.strategy_ledger.StrategyLedgerReader``),
    so strategies, Sizers and analyzers see one contract in both modes.
    """

    __slots__ = ("_reader", "strategy_ref", "account_ref", "_frozen")

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

    def __init__(self, reader: Any) -> None:
        strategy_ref = getattr(reader, "strategy_ref", None)
        account_ref = getattr(reader, "account_ref", None)
        for value in (strategy_ref, account_ref):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceStrategyAccountBookError("INVALID_SCOPE")
        if not callable(getattr(reader, "snapshot", None)):
            raise ServiceStrategyAccountBookError("INVALID_RUNTIME")
        object.__setattr__(self, "_reader", reader)
        object.__setattr__(self, "strategy_ref", strategy_ref)
        object.__setattr__(self, "account_ref", account_ref)
        object.__setattr__(self, "_frozen", True)

    def snapshot(self) -> _StrategyAccountBookSnapshot:
        """Read one locally reconciled strategy-owned snapshot."""

        try:
            snapshot = self._reader.snapshot()
        except Exception as error:
            raise ServiceStrategyAccountBookError(
                _safe_code(error, "LOCAL_QUERY_FAILED")
            ) from None
        if type(snapshot) is not _StrategyAccountBookSnapshot:
            raise ServiceStrategyAccountBookError("INVALID_SNAPSHOT")
        if snapshot.strategy_ref != self.strategy_ref or snapshot.account_ref != self.account_ref:
            raise ServiceStrategyAccountBookError("OWNER_BINDING_MISMATCH")
        return snapshot


@dataclass(frozen=True)
class StrategyBookValuation:
    """One strategy's cash, position values and equity from one snapshot cut.

    Policy ``strategy_spot_equity.v1``: equity = cash in ``currency`` + the sum
    of long spot positions x mark x multiplier, all in ``currency``. Every
    figure comes from the same snapshot (``journal_generation`` /
    ``cursor``), so a caller never mixes two versions of the book.
    """

    currency: str
    cash: Decimal
    positions: Mapping[str, Decimal]
    values: Mapping[str, Decimal]
    multipliers: Mapping[str, Decimal]
    equity: Decimal
    journal_generation: str
    cursor: int


def value_strategy_book(
    snapshot: _StrategyAccountBookSnapshot,
    *,
    marks: Mapping[str, Decimal],
    multipliers: Mapping[str, Decimal],
    currency: str | None = None,
) -> StrategyBookValuation:
    """Value ``snapshot`` or raise a finite ``ServiceStrategyAccountBookError``.

    ``marks`` are the caller's eligible current prices per instrument and
    ``multipliers`` the caller's own contract multipliers (Backtrader
    ``comminfo``); both must agree with the instrument terms the book
    published, otherwise nothing is valued. The inputs themselves are not
    evidence of a mark's provenance or freshness; the caller must establish
    those separately. No input is assumed: a missing
    financial cut, cost, terms, mark, an unsupported model, a second non-zero
    currency (no FX) or a terms conflict makes the valuation unavailable.
    """

    from bt_api_py.strategy_ledger import InstrumentTerms

    if not snapshot.financial_available:
        raise ServiceStrategyAccountBookError(
            snapshot.financial_error_code or "STRATEGY_FINANCIAL_UNAVAILABLE"
        )
    if not snapshot.cost_basis_complete:
        raise ServiceStrategyAccountBookError("STRATEGY_POSITION_COST_INCOMPLETE")
    _require_consistent_financial_cut(snapshot)
    cash_rows = dict(snapshot.cash_by_currency)
    if currency is None:
        if len(cash_rows) != 1:
            raise ServiceStrategyAccountBookError("STRATEGY_CURRENCY_AMBIGUOUS")
        (currency,) = cash_rows
    currency = _required_text(currency, "INVALID_CASH_CURRENCY")
    if currency not in cash_rows:
        raise ServiceStrategyAccountBookError("STRATEGY_CASH_UNAVAILABLE")
    if any(amount != 0 for name, amount in cash_rows.items() if name != currency):
        raise ServiceStrategyAccountBookError("STRATEGY_FX_UNAVAILABLE")
    positions, values, used_multipliers = {}, {}, {}
    for instrument, quantity in snapshot.positions.items():
        if quantity == 0:
            continue
        cost = snapshot.position_costs.get(instrument)
        if cost is None:
            raise ServiceStrategyAccountBookError("STRATEGY_POSITION_COST_MISSING")
        if cost.quantity != quantity:
            raise ServiceStrategyAccountBookError("STRATEGY_POSITION_COST_MISMATCH")
        terms = InstrumentTerms.from_version(cost.metadata_version)
        if terms is None:
            raise ServiceStrategyAccountBookError("STRATEGY_INSTRUMENT_TERMS_UNKNOWN")
        if terms.product_model != "spot" or cost.product_model != "spot":
            raise ServiceStrategyAccountBookError("STRATEGY_VALUATION_MODEL_UNSUPPORTED")
        if terms.quote_currency != currency or cost.cost_currency != currency:
            raise ServiceStrategyAccountBookError("STRATEGY_FX_UNAVAILABLE")
        mark = marks.get(instrument)
        if type(mark) is not Decimal or not mark.is_finite() or mark <= 0:
            raise ServiceStrategyAccountBookError("STRATEGY_MARK_UNAVAILABLE")
        local = multipliers.get(instrument)
        if local is None or Decimal(local) != terms.multiplier:
            raise ServiceStrategyAccountBookError("STRATEGY_INSTRUMENT_TERMS_CONFLICT")
        positions[instrument] = quantity
        values[instrument] = quantity * mark * terms.multiplier
        used_multipliers[instrument] = terms.multiplier
    cash = cash_rows[currency]
    return StrategyBookValuation(
        currency=currency,
        cash=cash,
        positions=MappingProxyType(positions),
        values=MappingProxyType(values),
        multipliers=MappingProxyType(used_multipliers),
        equity=cash + sum(values.values(), Decimal("0")),
        journal_generation=snapshot.journal_generation,
        cursor=snapshot.current_execution_cursor,
    )


def _require_consistent_financial_cut(snapshot: _StrategyAccountBookSnapshot) -> None:
    """Reject financial and position cuts not bound to one ledger transaction.

    Service's current independent financial projection is useful for reads,
    but equal quantities do not prove its cash and positions share a cut.
    Matching the direct ledger's declared cut is a consistency check only;
    it does not authenticate the provider or a caller-supplied price.
    """

    cut = snapshot.financial_ledger_cut
    if (
        snapshot.financial_cut_relationship != "SAME_TRANSACTION"
        or snapshot.financial_freshness != "RECONCILED_IN_SNAPSHOT"
        or snapshot.account_key != snapshot.account_ref
        or cut is None
        or cut.account_key != snapshot.account_key
        or cut.owner_directory_revision != snapshot.scope_directory_revision
    ):
        raise ServiceStrategyAccountBookError("STRATEGY_FINANCIAL_CUT_UNVERIFIED")
    execution = next(
        (item for item in cut.watermarks if item.source_kind == "execution_outbox"), None
    )
    if (
        execution is None
        or execution.source_ref != snapshot.account_ref
        or execution.generation != snapshot.journal_generation
        or execution.cursor != snapshot.current_execution_cursor
    ):
        raise ServiceStrategyAccountBookError("STRATEGY_FINANCIAL_CUT_UNVERIFIED")


def _safe_code(error: BaseException, fallback: str) -> str:
    code = getattr(error, "code", None)
    if (
        type(code) is str
        and 0 < len(code) <= 64
        and code.isascii()
        and all(character.isalnum() or character in "_.-" for character in code)
    ):
        return code
    return fallback


def _finite_float(value: Decimal, error_code: str) -> float:
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        raise ServiceStrategyAccountBookError(error_code) from None
    if not math.isfinite(converted) or (value != 0 and converted == 0.0):
        raise ServiceStrategyAccountBookError(error_code)
    return converted


def _required_text(value: object, error_code: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ServiceStrategyAccountBookError(error_code)
    return value


def _instrument_key(value: object) -> str:
    instrument = value if type(value) is str else getattr(value, "_name", None)
    if type(instrument) is not str or not instrument or instrument != instrument.strip():
        raise ServiceStrategyAccountBookError("INSTRUMENT_REQUIRED")
    return instrument


__all__ = [
    "DirectStrategyAccountBookView",
    "ServiceStrategyAccountBookError",
    "ServiceStrategyAccountBookView",
    "StrategyBookValuation",
    "value_strategy_book",
]
