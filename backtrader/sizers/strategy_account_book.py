"""Cash-based sizing from an explicitly bound strategy-owned account book.

This sizer is for instruments whose feed price is denominated in the selected
cash currency and whose native quantity is directly priced in that currency.
It does not model contract multipliers, margin, fees, or cross-currency
conversion. Those constraints remain the order writer's responsibility.
"""

import math
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from ..parameters import Float, ParameterDescriptor
from ..sizer import Sizer

__all__ = ["StrategyAccountBookPercentSizer"]


class StrategyAccountBookPercentSizer(Sizer):
    """Size buys from this strategy's explicit cash view, not Broker totals.

    ``currency`` is required at use time. Buy sizing uses the strategy-bound
    account book's available cash in that currency and the current data close.
    Sell sizing is capped at the strategy-owned position for the data feed.
    A missing or mismatched owner binding fails closed; account-level Broker
    getters are never consulted.

    This is an advisory spot-style sizer, not a margin, derivative, fee, or FX
    calculator. Use only when one native unit is priced directly by ``close``
    in ``currency``. The normal Broker and execution writer retain their
    account-level and authorization semantics.
    """

    currency = ParameterDescriptor(
        default=None,
        type_=str,
        validator=lambda value: type(value) is str and bool(value) and value == value.strip(),
        doc="Exact quote currency used by the strategy account book",
    )
    percents = ParameterDescriptor(
        default=100.0,
        type_=float,
        validator=Float(min_val=0.0, max_val=100.0),
        doc="Percentage of strategy-owned cash to use for buys",
    )
    retint = ParameterDescriptor(
        default=False, type_=bool, doc="Truncate the suggested size to a whole unit"
    )

    def getsizing(self, data, isbuy):
        """Return a size without reading aggregate Broker cash or positions."""

        account_book = self._owner_account_book()
        if type(isbuy) is not bool:
            raise ValueError("order direction must be boolean")

        try:
            position = account_book.getposition(data)
            position_size = Decimal(str(position.size))
        except (AttributeError, TypeError, ValueError, InvalidOperation) as error:
            raise ValueError("strategy account-book position is invalid") from error
        if not position_size.is_finite():
            raise ValueError("strategy account-book position is invalid")
        # This sizer has no short/margin model. In particular, never turn the
        # absolute value of an existing short into a same-direction sell size.
        if position_size < 0:
            return 0

        if not isbuy:
            return self._native_size(position_size)

        currency = self.get_param("currency")
        if type(currency) is not str or not currency or currency != currency.strip():
            raise ValueError("an explicit account-book cash currency is required")
        cash = account_book.getcash(currency=currency)
        if not isinstance(cash, Decimal) or not cash.is_finite() or cash < 0:
            raise ValueError("strategy account-book cash is invalid")

        try:
            price = Decimal(str(data.close[0]))
        except (AttributeError, IndexError, KeyError, TypeError, ValueError, InvalidOperation):
            return 0
        if not price.is_finite() or price <= 0:
            return 0

        percent = Decimal(str(self.get_param("percents")))
        if not percent.is_finite() or percent < 0 or percent > 100:
            raise ValueError("sizing percentage must be between zero and one hundred")
        quantity = cash * percent / Decimal("100") / price
        if self.get_param("retint"):
            quantity = quantity.to_integral_value(rounding=ROUND_DOWN)
        return self._native_size(quantity)

    def _getsizing(self, comminfo, cash, data, isbuy):
        """Keep direct legacy calls on the same strategy-scoped contract."""

        return self.getsizing(data, isbuy)

    def _owner_account_book(self):
        strategy = self.strategy
        account_book = getattr(strategy, "account_book", None)
        strategy_params = getattr(strategy, "p", None)
        expected_strategy = getattr(strategy_params, "strategy_ref", None)
        expected_account = getattr(strategy_params, "account_ref", None)
        if (
            account_book is None
            or not callable(getattr(account_book, "getcash", None))
            or not callable(getattr(account_book, "getposition", None))
            or type(expected_strategy) is not str
            or not expected_strategy
            or type(expected_account) is not str
            or not expected_account
            or getattr(account_book, "strategy_ref", None) != expected_strategy
            or getattr(account_book, "account_ref", None) != expected_account
        ):
            raise ValueError("a matching strategy-owned account book is required")
        return account_book

    def _native_size(self, quantity):
        if not isinstance(quantity, Decimal) or not quantity.is_finite() or quantity < 0:
            raise ValueError("strategy-owned size is invalid")
        if self.get_param("retint"):
            return int(quantity)
        value = float(quantity)
        if not math.isfinite(value):
            raise ValueError("strategy-owned size cannot be represented")
        return value
