# -*- coding: utf-8 -*-
"""Data factory module for Backtrader test suite.

This module provides factory functions for creating test data, strategies,
and Cerebro instances with sensible defaults. Using factories reduces code
duplication, makes tests more maintainable, and ensures consistency across
the test suite.

Factory Functions:
    create_data_feed(): Create data feeds with default or custom parameters
    create_cerebro(): Create configured Cerebro instances
    create_strategy(): Create strategy instances for testing
    create_indicator(): Create indicator instances for testing

Example:
    >>> from tests.test_utils.factories import create_data_feed, create_cerebro
    >>> data = create_data_feed()
    >>> cerebro = create_cerebro(cash=10000.0)
    >>> cerebro.adddata(data)
"""

import os
from pathlib import Path
from typing import Optional, List, Any, Dict
from datetime import datetime

import backtrader as bt


# =============================================================================
# Path Configuration
# =============================================================================

def get_project_root() -> Path:
    """Get the project root directory.

    Returns:
        Path: Project root directory path
    """
    return Path(__file__).parent.parent.parent


def get_datas_path() -> Path:
    """Get the test data directory path.

    Returns:
        Path: Test data directory path
    """
    return get_project_root() / "tests" / "datas"


# =============================================================================
# Data Feed Factories
# =============================================================================

def create_data_feed(
    dataname: Optional[str] = None,
    fromdate: Optional[datetime] = None,
    todate: Optional[datetime] = None,
    timeframe: Optional[int] = None,
    compression: Optional[int] = None,
    name: Optional[str] = None,
) -> bt.feeds.BacktraderCSVData:
    """Create a data feed with default or specified parameters.

    This factory function creates BacktraderCSVData feeds with sensible
    defaults for testing. If no parameters are provided, it uses the
    standard 2006 daily data file.

    Args:
        dataname: Path to data file. If None, uses default 2006-day-001.txt
        fromdate: Start date for data filtering. Defaults to 2006-01-01
        todate: End date for data filtering. Defaults to 2006-12-31
        timeframe: Timeframe for the data (e.g., bt.TimeFrame.Days)
        compression: Compression factor for the data
        name: Name for the data feed

    Returns:
        bt.feeds.BacktraderCSVData: Configured data feed

    Example:
        >>> # Use all defaults
        >>> data = create_data_feed()
        >>> # Custom date range
        >>> data = create_data_feed(
        ...     fromdate=datetime(2006, 6, 1),
        ...     todate=datetime(2006, 12, 31)
        ... )
    """
    datas_path = get_datas_path()

    if dataname is None:
        dataname = str(datas_path / "2006-day-001.txt")
    elif not os.path.isabs(dataname):
        dataname = str(datas_path / dataname)

    if fromdate is None:
        fromdate = datetime(2006, 1, 1)

    if todate is None:
        todate = datetime(2006, 12, 31)

    # Build kwargs, only include non-None values
    kwargs = {
        "dataname": dataname,
        "fromdate": fromdate,
        "todate": todate,
    }
    if timeframe is not None:
        kwargs["timeframe"] = timeframe
    if compression is not None:
        kwargs["compression"] = compression
    if name is not None:
        kwargs["name"] = name

    return bt.feeds.BacktraderCSVData(**kwargs)


def create_week_data(
    dataname: Optional[str] = None,
    fromdate: Optional[datetime] = None,
    todate: Optional[datetime] = None,
) -> bt.feeds.BacktraderCSVData:
    """Create a weekly data feed for testing.

    Args:
        dataname: Path to weekly data file. If None, uses 2006-week-001.txt
        fromdate: Start date for data filtering
        todate: End date for data filtering

    Returns:
        bt.feeds.BacktraderCSVData: Configured weekly data feed
    """
    datas_path = get_datas_path()

    if dataname is None:
        dataname = str(datas_path / "2006-week-001.txt")
    elif not os.path.isabs(dataname):
        dataname = str(datas_path / dataname)

    if fromdate is None:
        fromdate = datetime(2006, 1, 1)

    if todate is None:
        todate = datetime(2006, 12, 31)

    return bt.feeds.BacktraderCSVData(
        dataname=dataname,
        fromdate=fromdate,
        todate=todate,
    )


def create_multiple_data_feeds(
    datafiles: Optional[List[str]] = None,
    fromdate: Optional[datetime] = None,
    todate: Optional[datetime] = None,
) -> List[bt.feeds.BacktraderCSVData]:
    """Create multiple data feeds for multi-data testing.

    Args:
        datafiles: List of data file names. If None, uses default list
        fromdate: Start date for data filtering
        todate: End date for data filtering

    Returns:
        list: List of configured data feeds

    Example:
        >>> feeds = create_multiple_data_feeds(['2006-day-001.txt', '2006-day-002.txt'])
    """
    datas_path = get_datas_path()

    if datafiles is None:
        datafiles = ['2006-day-001.txt', '2006-day-002.txt']

    feeds = []
    for filename in datafiles:
        datapath = datas_path / filename
        if datapath.exists():
            feed = create_data_feed(
                dataname=str(datapath),
                fromdate=fromdate,
                todate=todate,
            )
            feeds.append(feed)

    return feeds


# =============================================================================
# Cerebro Engine Factories
# =============================================================================

def create_cerebro(
    cash: float = 10000.0,
    commission: Optional[float] = None,
    slippery: Optional[float] = None,
) -> bt.Cerebro:
    """Create a Cerebro instance with common configuration.

    Args:
        cash: Initial cash amount. Defaults to 10000.0
        commission: Commission rate (e.g., 0.001 for 0.1%)
        slippery: Slippage per share/contract

    Returns:
        bt.Cerebro: Configured Cerebro instance

    Example:
        >>> cerebro = create_cerebro(cash=100000.0, commission=0.001)
    """
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)

    if commission is not None:
        cerebro.broker.setcommission(commission=commission)

    if slippery is not None:
        cerebro.broker.set_slippage_perc(slippery)

    return cerebro


# =============================================================================
# Strategy Factories
# =============================================================================

def create_simple_sma_strategy(period: int = 15) -> type:
    """Create a simple SMA crossover strategy class.

    Args:
        period: SMA period. Defaults to 15

    Returns:
        type: Strategy class for testing

    Example:
        >>> StrategyClass = create_simple_sma_strategy(period=20)
        >>> cerebro.addstrategy(StrategyClass)
    """
    class SimpleSMAStrategy(bt.Strategy):
        """Simple moving average crossover strategy for testing."""

        params = (
            ("period", period),
        )

        def __init__(self):
            self.sma = bt.indicators.SMA(self.data, period=self.p.period)

        def next(self):
            if not self.position:
                if self.data.close[0] > self.sma[0]:
                    self.buy()
            elif self.data.close[0] < self.sma[0]:
                self.close()

    return SimpleSMAStrategy


def create_crossover_strategy(period: int = 15) -> type:
    """Create a crossover strategy using CrossOver indicator.

    Args:
        period: SMA period for crossover detection. Defaults to 15

    Returns:
        type: Strategy class with CrossOver indicator

    Example:
        >>> StrategyClass = create_crossover_strategy(period=20)
        >>> cerebro.addstrategy(StrategyClass)
    """
    class CrossoverStrategy(bt.Strategy):
        """Crossover strategy with CrossOver indicator for testing."""

        params = (
            ("period", period),
        )

        def __init__(self):
            self.sma = bt.indicators.SMA(self.data, period=self.p.period)
            self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

        def next(self):
            if not self.position.size:
                if self.cross > 0:
                    self.buy()
            elif self.cross < 0:
                self.close()

    return CrossoverStrategy


def create_buy_and_close_strategy() -> type:
    """Create a simple buy-and-close strategy for broker testing.

    Returns:
        type: Strategy class that buys once then closes

    Example:
        >>> StrategyClass = create_buy_and_close_strategy()
        >>> cerebro.addstrategy(StrategyClass)
    """
    class BuyAndCloseStrategy(bt.Strategy):
        """Simple buy-once then close strategy for broker testing."""

        def __init__(self):
            self.order = None
            self.bar_count = 0

        def next(self):
            self.bar_count += 1
            if not self.position:
                self.order = self.buy()
            elif self.bar_count > 50:
                self.order = self.close()

    return BuyAndCloseStrategy


# =============================================================================
# Indicator Factories
# =============================================================================

def create_sma_indicator(period: int = 15, data=None) -> bt.indicators.SMA:
    """Create an SMA indicator for testing.

    Args:
        period: SMA period. Defaults to 15
        data: Data feed. If None, indicator must be attached later

    Returns:
        bt.indicators.SMA: SMA indicator instance

    Example:
        >>> sma = create_sma_indicator(period=20)
    """
    return bt.indicators.SMA(data, period=period)


def create_ema_indicator(period: int = 15, data=None) -> bt.indicators.EMA:
    """Create an EMA indicator for testing.

    Args:
        period: EMA period. Defaults to 15
        data: Data feed. If None, indicator must be attached later

    Returns:
        bt.indicators.EMA: EMA indicator instance
    """
    return bt.indicators.EMA(data, period=period)


def create_macd_indicator(
    period_me1: int = 12,
    period_me2: int = 26,
    period_signal: int = 9,
    data=None,
) -> bt.indicators.MACD:
    """Create a MACD indicator for testing.

    Args:
        period_me1: Fast EMA period. Defaults to 12
        period_me2: Slow EMA period. Defaults to 26
        period_signal: Signal line period. Defaults to 9
        data: Data feed. If None, indicator must be attached later

    Returns:
        bt.indicators.MACD: MACD indicator instance
    """
    return bt.indicators.MACD(
        data,
        period_me1=period_me1,
        period_me2=period_me2,
        period_signal=period_signal,
    )


def create_rsi_indicator(period: int = 14, data=None) -> bt.indicators.RSI:
    """Create an RSI indicator for testing.

    Args:
        period: RSI period. Defaults to 14
        data: Data feed. If None, indicator must be attached later

    Returns:
        bt.indicators.RSI: RSI indicator instance
    """
    return bt.indicators.RSI(data, period=period)


# =============================================================================
# Analyzer Factories
# =============================================================================

def create_sharpe_analyzer(
    timeframe: bt.TimeFrame = bt.TimeFrame.Days,
    riskfreerate: float = 0.0,
    annualize: bool = True,
) -> tuple:
    """Create Sharpe Ratio analyzer configuration.

    Args:
        timeframe: Timeframe for calculations
        riskfreerate: Risk-free rate
        annualize: Whether to annualize the ratio

    Returns:
        tuple: (bt.analyzers.SharpeRatio, kwargs dict)

    Example:
        >>> analyzer_class, kwargs = create_sharpe_analyzer()
        >>> cerebro.addanalyzer(analyzer_class, **kwargs)
    """
    return (
        bt.analyzers.SharpeRatio,
        {
            "_name": "sharpe",
            "timeframe": timeframe,
            "riskfreerate": riskfreerate,
            "annualize": annualize,
        },
    )


def create_returns_analyzer() -> tuple:
    """Create Returns analyzer configuration.

    Returns:
        tuple: (bt.analyzers.Returns, kwargs dict)
    """
    return (
        bt.analyzers.Returns,
        {"_name": "returns"},
    )


def create_drawdown_analyzer() -> tuple:
    """Create DrawDown analyzer configuration.

    Returns:
        tuple: (bt.analyzers.DrawDown, kwargs dict)
    """
    return (
        bt.analyzers.DrawDown,
        {"_name": "drawdown"},
    )


# =============================================================================
# Observer Factories
# =============================================================================

def create_drawdown_observer() -> type:
    """Create DrawDown observer for testing.

    Returns:
        type: bt.observers.DrawDown class
    """
    return bt.observers.DrawDown


def create_broker_observer() -> type:
    """Create Broker observer for testing.

    Returns:
        type: bt.observers.Broker class
    """
    return bt.observers.Broker


def create_trades_observer() -> type:
    """Create Trades observer for testing.

    Returns:
        type: bt.observers.Trades class
    """
    return bt.observers.Trades


# =============================================================================
# Complete Test Setup Factory
# =============================================================================

def setup_basic_backtest(
    cash: float = 10000.0,
    strategy: Optional[type] = None,
    data_feeds: Optional[List] = None,
    analyzers: Optional[List[tuple]] = None,
    observers: Optional[List[type]] = None,
    commission: Optional[float] = None,
) -> bt.Cerebro:
    """Create a complete backtest setup with all components.

    This factory function sets up a complete Cerebro instance with:
    - Initial cash
    - Data feeds
    - Strategy
    - Analyzers
    - Observers
    - Commission

    Args:
        cash: Initial cash amount
        strategy: Strategy class to add
        data_feeds: List of data feeds to add
        analyzers: List of (analyzer_class, kwargs) tuples
        observers: List of observer classes
        commission: Commission rate

    Returns:
        bt.Cerebro: Fully configured Cerebro instance

    Example:
        >>> cerebro = setup_basic_backtest(
        ...     strategy=SimpleStrategy,
        ...     data_feeds=[create_data_feed()],
        ...     analyzers=[create_sharpe_analyzer()],
        ...     commission=0.001
        ... )
        >>> results = cerebro.run()
    """
    cerebro = create_cerebro(cash=cash, commission=commission)

    # Add data feeds
    if data_feeds:
        for feed in data_feeds:
            cerebro.adddata(feed)

    # Add strategy
    if strategy:
        cerebro.addstrategy(strategy)

    # Add analyzers
    if analyzers:
        for analyzer_class, kwargs in analyzers:
            cerebro.addanalyzer(analyzer_class, **kwargs)

    # Add observers
    if observers:
        for observer in observers:
            cerebro.addobserver(observer)

    return cerebro


# =============================================================================
# Helper Functions
# =============================================================================

def run_backtest(
    cerebro: bt.Cerebro,
    plot: bool = False,
) -> list:
    """Run a backtest and return results.

    Args:
        cerebro: Configured Cerebro instance
        plot: Whether to plot results

    Returns:
        list: Strategy instances from backtest
    """
    results = cerebro.run()
    if plot:
        cerebro.plot()
    return results


def validate_backtest_results(
    results: list,
    min_strategies: int = 1,
    min_bars: int = 1,
    min_value: float = 0.0,
) -> Dict[str, Any]:
    """Validate backtest results and return summary.

    Args:
        results: Results from cerebro.run()
        min_strategies: Minimum expected strategy count
        min_bars: Minimum expected bars processed
        min_value: Minimum expected portfolio value

    Returns:
        dict: Validation summary with strategy info

    Raises:
        AssertionError: If validation fails
    """
    assert len(results) >= min_strategies, "No strategies returned from backtest"

    strat = results[0]
    bars_processed = len(strat)

    summary = {
        "strategies": len(results),
        "bars_processed": bars_processed,
        "final_value": strat.broker.getvalue() if hasattr(strat, 'broker') else None,
        "strategy_class": type(strat).__name__,
    }

    if min_bars > 0:
        assert bars_processed >= min_bars, f"Only {bars_processed} bars processed"

    if min_value > 0 and summary["final_value"] is not None:
        assert summary["final_value"] >= min_value, f"Portfolio value {summary['final_value']} below minimum"

    return summary
