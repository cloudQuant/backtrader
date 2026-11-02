"""Project a validated neutral account-balance snapshot into BT scalars.

The Store owns SDK selection, snapshot freshness/lease validation, and cache
lifecycle.  This module accepts that already-validated snapshot and performs
only the provider-neutral balance/valuation checks required by Backtrader's
single-currency ``cash`` and ``value`` interface.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation
from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple, Type


def require_single_balance_currency(snapshot: Any, *, error_type: Type[Exception]):
    """Check the single-currency constraint of Backtrader's scalar balances."""
    currencies = snapshot.currencies
    balances = snapshot.balances
    if len(currencies) != 1:
        error = error_type(
            "SDK account balance does not have one unambiguous currency"
        )
        error.code = "account_balance_currency_ambiguous"
        raise error

    if len(balances) != 1 or balances[0].currency != currencies[0]:
        error = error_type(
            "SDK account balance does not have one unambiguous resource row"
        )
        error.code = "account_balance_resource_ambiguous"
        raise error
    return currencies, balances


def project_account_balance_snapshot(
    snapshot: Any,
    *,
    account_valuation_type: Type[Any],
    error_type: Type[Exception],
) -> Dict[str, float]:
    """Project one verified SDK snapshot to Backtrader ``cash`` and ``value``.

    ``snapshot`` must already have passed the SDK port's exact-type, usability,
    and lease validation.  The explicit type and error arguments keep this
    module independent of the optional SDK package and Store implementation.
    """
    currencies, balances = require_single_balance_currency(snapshot, error_type=error_type)

    valuation = snapshot.valuation
    if (
        type(snapshot.valuation_available) is not bool
        or snapshot.valuation_available is not True
        or type(valuation) is not account_valuation_type
        or valuation.currency != currencies[0]
        or valuation.currency != balances[0].currency
        or valuation.available_cash is None
        or valuation.equity is None
    ):
        error = error_type(
            "SDK account valuation does not prove same-currency cash and equity"
        )
        error.code = "account_valuation_unavailable"
        raise error

    try:
        available_cash = Decimal(valuation.available_cash)
        equity = Decimal(valuation.equity)
        if not available_cash.is_finite() or not equity.is_finite():
            raise InvalidOperation
        cash_value = float(available_cash)
        equity_value = float(equity)
        if not math.isfinite(cash_value) or not math.isfinite(equity_value):
            raise OverflowError
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        error = error_type("SDK account valuation values are invalid")
        error.code = "account_valuation_invalid"
        raise error from None

    return {"cash": cash_value, "value": equity_value}


def project_venue_balance_snapshot(
    route, snapshot, *, error_type, missing_dependency_error_type
):
    """Project one verified neutral snapshot without combining accounts."""
    try:
        from bt_api_py.account_balance_contracts import (
            AccountBalance,
            AccountBalanceSnapshot,
            AccountValuation,
        )
        from bt_api_py.account_balance_read import validate_venue_balance_snapshot
    except ImportError as exc:
        raise missing_dependency_error_type(
            "bt_api_py.account_balance_contracts is required for venue balances"
        ) from exc

    def unavailable(code: str) -> None:
        error = error_type("SDK venue balance snapshot is unavailable")
        error.code = code
        raise error from None

    valuation, valuation_available = validate_venue_balance_snapshot(
        route,
        snapshot,
        account_balance_type=AccountBalance,
        snapshot_type=AccountBalanceSnapshot,
        valuation_type=AccountValuation,
        unavailable=unavailable,
    )
    if valuation_available:
        projected = project_account_balance_snapshot(
            snapshot,
            account_valuation_type=AccountValuation,
            error_type=error_type,
        )
        cash = projected["cash"]
        value = projected["value"]
        currency = valuation.currency
    else:
        # Balance rows remain useful neutral facts when the optional
        # same-session valuation family is unavailable or incomplete.
        cash = None
        value = None
        currency = None

    valuation_data = None if valuation is None else valuation.to_dict()
    return {
        "exchange_name": route,
        "currency": currency,
        "cash": cash,
        "value": value,
        "currencies": tuple(snapshot.currencies),
        "balances": tuple(row.to_dict() for row in snapshot.balances),
        "valuation": valuation_data,
        "valuation_available": valuation_available,
        "valuation_blockers": tuple(snapshot.valuation_blockers),
    }


def project_sdk_account_push_values(event: Mapping) -> Optional[Tuple[float, float]]:
    """Project supported top-level SDK account values for BT cache updates."""
    cash, value = event.get("cash"), event.get("value")
    if not isinstance(cash, (int, float)) or not isinstance(value, (int, float)):
        return None
    return float(cash), float(value)



__all__ = (
    "project_account_balance_snapshot", "project_venue_balance_snapshot",
    "project_sdk_account_push_values", "require_single_balance_currency",
)
