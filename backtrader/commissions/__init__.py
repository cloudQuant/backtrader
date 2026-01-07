#!/usr/bin/env python
"""Commission Schemes Module - Predefined commission configurations.

This module provides pre-configured commission schemes for common
trading instruments like stocks and futures. These schemes extend
the base CommInfoBase with default parameters.

Classes:
    CommInfo: Base commission scheme with percentage-based commission.
    CommInfoFutures: Futures commission scheme.
    CommInfoFuturesPerc: Futures with percentage commission.
    CommInfoFuturesFixed: Futures with fixed commission.
    CommInfoStocks: Stock commission scheme.
    CommInfoStocksPerc: Stocks with percentage commission.
    CommInfoStocksFixed: Stocks with fixed commission.

Example:
    Setting commission scheme:
    >>> cerebro = bt.Cerebro()
    >>> comminfo = bt.commissions.CommInfoStocks(commission=0.001)
    >>> cerebro.broker.addcommissioninfo(cominfo)
"""
from ..comminfo import CommInfoBase


class CommInfo(CommInfoBase):
    """Base commission scheme with percentage-based commission."""
    pass  # clone of CommissionInfo but with xx% instead of 0.xx


class CommInfoFutures(CommInfoBase):
    """Futures commission scheme."""
    params = (("stocklike", False),)


class CommInfoFuturesPerc(CommInfoFutures):
    params = (("commtype", CommInfoBase.COMM_PERC),)


class CommInfoFuturesFixed(CommInfoFutures):
    params = (("commtype", CommInfoBase.COMM_FIXED),)


class CommInfoStocks(CommInfoBase):
    params = (("stocklike", True),)


class CommInfoStocksPerc(CommInfoStocks):
    params = (("commtype", CommInfoBase.COMM_PERC),)


class CommInfoStocksFixed(CommInfoStocks):
    params = (("commtype", CommInfoBase.COMM_FIXED),)
