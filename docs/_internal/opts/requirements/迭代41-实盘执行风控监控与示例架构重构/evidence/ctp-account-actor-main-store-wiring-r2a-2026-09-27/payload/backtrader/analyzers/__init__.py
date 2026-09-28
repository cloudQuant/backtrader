#!/usr/bin/env python
"""Performance Analyzers Module.

This module provides a collection of analyzers for evaluating strategy
performance. Analyzers calculate metrics like returns, drawdowns, Sharpe
ratio, trade statistics, and more.

Available Analyzers:
    - AnnualReturn: Annual return breakdown
    - Calmar: Calmar ratio (return / max drawdown)
    - DrawDown: Drawdown analysis
    - Leverage: Leverage tracking
    - LogReturnsRolling: Rolling log returns
    - PeriodStats: Statistics by period
    - Positions: Position analysis
    - PyFolio: PyFolio integration
    - Returns: Return analysis
    - Sharpe: Sharpe ratio
    - SQN: System Quality Number
    - TimeReturn: Time-weighted returns
    - TotalValue: Total value tracking
    - TradeAnalyzer: Detailed trade statistics
    - Transactions: Transaction log
    - VWR: Variance-Weighted Return

Example:
    Adding analyzers to a strategy:
    >>> cerebro.addanalyzer(bt.analyzers.Sharpe, _name='sharpe')
    >>> cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
"""

# The modules below should/must define __all__ with the objects wishes
# or prepend an "_" (underscore) to private classes/variables

from .annualreturn import *
from .calmar import *
from .drawdown import *
from .leverage import *
from .logreturnsrolling import *
from .periodstats import *
from .positions import *
from .pyfolio import *
from .returns import *
from .sharpe import *
from .sqn import *
from .timereturn import *
from .total_value import *
from .tradeanalyzer import *
from .transactions import *
from .vwr import *
