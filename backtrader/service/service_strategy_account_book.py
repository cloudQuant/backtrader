"""Strategy-owned account-book reads and Backtrader projections.

The SDK owns route validation and account-book wire parsing. This module keeps
the Strategy-bound view and its Backtrader ``Position``/cash/value projection;
it never falls back to account-wide positions or inferred valuation.
"""

from __future__ import annotations

import math
import threading
from decimal import Decimal
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


class ServiceStrategyAccountBookView:
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
    "ServiceStrategyAccountBookError",
    "ServiceStrategyAccountBookView",
]
