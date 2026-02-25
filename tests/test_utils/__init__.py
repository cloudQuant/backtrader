# -*- coding: utf-8 -*-
"""Test utilities package for Backtrader test suite.

This package provides shared utilities, factory functions, and helpers
for testing the Backtrader quantitative trading framework.
"""

from .factories import (
    # Data feed factories
    create_data_feed,
    create_week_data,
    create_multiple_data_feeds,

    # Cerebro factories
    create_cerebro,

    # Strategy factories
    create_simple_sma_strategy,
    create_crossover_strategy,
    create_buy_and_close_strategy,

    # Indicator factories
    create_sma_indicator,
    create_ema_indicator,
    create_macd_indicator,
    create_rsi_indicator,

    # Analyzer factories
    create_sharpe_analyzer,
    create_returns_analyzer,
    create_drawdown_analyzer,

    # Observer factories
    create_drawdown_observer,
    create_broker_observer,
    create_trades_observer,

    # Complete setup
    setup_basic_backtest,
    run_backtest,
    validate_backtest_results,

    # Path helpers
    get_project_root,
    get_datas_path,
)

__all__ = [
    # Data feed factories
    "create_data_feed",
    "create_week_data",
    "create_multiple_data_feeds",

    # Cerebro factories
    "create_cerebro",

    # Strategy factories
    "create_simple_sma_strategy",
    "create_crossover_strategy",
    "create_buy_and_close_strategy",

    # Indicator factories
    "create_sma_indicator",
    "create_ema_indicator",
    "create_macd_indicator",
    "create_rsi_indicator",

    # Analyzer factories
    "create_sharpe_analyzer",
    "create_returns_analyzer",
    "create_drawdown_analyzer",

    # Observer factories
    "create_drawdown_observer",
    "create_broker_observer",
    "create_trades_observer",

    # Complete setup
    "setup_basic_backtest",
    "run_backtest",
    "validate_backtest_results",

    # Path helpers
    "get_project_root",
    "get_datas_path",
]
