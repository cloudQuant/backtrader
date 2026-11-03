#!/usr/bin/env python
"""Position Sizer Module - Position size calculation.

This module provides the base class for position sizers, which determine
the size of orders to place based on available cash, risk parameters,
and other factors.

Classes:
    Sizer: Base class for position sizers.
    FixedSize: Sizer that uses a fixed size.
    FixedReverser: Sizer that reverses positions with fixed size.
    PercentSizer: Sizer that uses a percentage of available cash.
    AllInSizer: Sizer that uses all available cash.
    RiskReturnSizer: Sizer that sizes based on risk/reward ratio.

Example:
    Creating a custom sizer:
    >>> class MySizer(bt.Sizer):
    ...     params = (('perc', 0.1),)
    ...
    ...     def _getsizing(self, comminfo, cash, data, isbuy):
    ...         return int(cash * self.p.perc / data.close[0])
"""

import math

from .parameters import ParameterizedBase


# Sizer class - Refactored to use new parameter system
class Sizer(ParameterizedBase):
    """Base class for position sizers.

    This is the base class for sizers. Any sizer should subclass this
    and override the ``_getsizing`` method to provide custom position
    sizing logic.

    Attributes:
        strategy: The strategy using this sizer.
        broker: The broker instance for portfolio information.

    Methods:
        getsizing(data, isbuy): Get the position size for an order.
        _getsizing(comminfo, cash, data, isbuy): Override to implement sizing logic.
        set(strategy, broker): Set the strategy and broker references.

    Example:
        >>> cerebro.addsizer(bt.sizers.FixedSize, stake=100)
    """

    #: Whether ``_getsizing`` uses the ``cash`` argument (Broker account cash).
    uses_account_cash = True

    strategy = None
    broker = None

    def __init__(self, **kwargs):
        """Initialize the Sizer with any provided parameters."""
        super().__init__(**kwargs)

    # Get the specific position size for order placement
    def getsizing(self, data, isbuy):
        """Get the position size for an order.

        Args:
            data: The target data for the order.
            isbuy: True for buy operations, False for sell operations.

        Returns:
            int: The position size to use for the order, as determined
                by the _getsizing method.
        """
        comminfo = self.broker.getcommissioninfo(data)
        # Iteration 60 (60.11-R3): with a strategy account book bound, Broker
        # cash is the shared account's cash, not this strategy's. A Sizer that
        # sizes from ``cash`` receives this strategy's own cash instead, from
        # one book snapshot, in its single cash currency; when that cash is
        # unavailable (no capital, unreconciled, a second currency, a
        # non stock-like instrument) the Sizer is refused before any order is
        # created, never given account cash. Sizers that do not use ``cash``
        # declare ``uses_account_cash = False``. The size is advice: the
        # ledger admits the order against the same cash atomically.
        strategy = getattr(self, "strategy", None)
        scoped = getattr(strategy, "_strategy_account_book", None)
        account_book = scoped(self.broker) if callable(scoped) else None
        if self.uses_account_cash and account_book is not None:
            return self._getsizing(
                comminfo, _strategy_cash(account_book, comminfo, type(self).__name__), data, isbuy
            )
        return self._getsizing(comminfo, self.broker.getcash(), data, isbuy)

    def _getsizing(self, comminfo, cash, data, isbuy):
        """This method has to be overriden by subclasses of Sizer to provide
        the sizing functionality

        Params:
          - ``comminfo``: The CommissionInfo instance that contains
            information about the commission for the data and allows
            calculation of position value, operation cost, commission for the
            operation

          - ``cash``: current available cash in the *broker*

          - ``data``: target of the operation

          - ``isbuy``: will be ``True`` for *buy* operations and ``False``
            for *sell* operations

        The method has to return the actual size (an int) to be executed. If
         `0` is returned, nothing will be executed.

        The absolute value of the returned value will be used
        # This method needs to be overridden when in use, takes four parameters:
        # comminfo represents the commission instance, can be used to get commission etc.
        # cash represents currently available cash
        # data represents which data to trade on
        # isbuy represents True for buy operations, False for sell operations

        """
        raise NotImplementedError

    # Set strategy and broker
    def set(self, strategy, broker):
        """Set the strategy and broker references for this sizer.

        Args:
            strategy: The strategy instance using this sizer.
            broker: The broker instance for portfolio information.
        """
        self.strategy = strategy
        self.broker = broker


# SizerBase class
SizerBase = Sizer


def _strategy_cash(account_book, comminfo, sizer_name):
    """This strategy's cash for a cash-based Sizer, or ``ValueError``."""

    if not getattr(comminfo, "stocklike", False):
        raise ValueError(
            f"{sizer_name}: strategy cash sizing is unavailable for futures-like instruments"
        )
    from .service.service_strategy_account_book import ServiceStrategyAccountBookError

    try:
        snapshot = account_book.snapshot()
        if not snapshot.financial_available:
            raise ServiceStrategyAccountBookError(snapshot.financial_error_code)
        rows = dict(snapshot.cash_by_currency)
        if len(rows) != 1:
            code = "STRATEGY_FX_UNAVAILABLE" if rows else "STRATEGY_CASH_UNAVAILABLE"
            raise ServiceStrategyAccountBookError(code)
        (cash,) = rows.values()
    except ServiceStrategyAccountBookError as error:
        raise ValueError(f"{sizer_name}: strategy cash is unavailable ({error.code})") from None
    cash = float(cash)
    if not math.isfinite(cash):
        raise ValueError(f"{sizer_name}: strategy cash is unavailable (STRATEGY_CASH_INVALID)")
    return max(cash, 0.0)
