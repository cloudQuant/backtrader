#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for the Calmar Ratio analyzer.

This module tests the Calmar ratio analyzer which measures risk-adjusted returns
of a trading strategy. The Calmar ratio is calculated as:

    Calmar Ratio = Annualized Return / Maximum Drawdown

This metric is useful for evaluating strategy performance by considering both
returns and risk. Higher Calmar ratios indicate better risk-adjusted performance.

Reference: backtrader-master2/samples/calmar/calmar-test.py

Example:
    To run the test directly::

        python tests/strategies/test_49_calmar_analyzer.py

    Or via pytest::

        pytest tests/strategies/test_49_calmar_analyzer.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching multiple possible locations.

    This function attempts to locate a data file by checking several common
    directory locations relative to the test file. This makes tests more robust
    when run from different working directories.

    Args:
        filename: The name of the data file to locate (e.g., 'yhoo-1996-2014.txt').

    Returns:
        The absolute Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.

    Note:
        The search order is:
        1. BASE_DIR / filename
        2. BASE_DIR.parent / filename
        3. BASE_DIR / "datas" / filename
        4. BASE_DIR.parent / "datas" / filename
    """
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR / "datas" / filename,
        BASE_DIR.parent / "datas" / filename,
    ]
    for p in search_paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find data file: {filename}")


class CalmarTestStrategy(bt.Strategy):
    """A dual moving average crossover strategy for testing the Calmar analyzer.

    This strategy implements a simple trend-following approach using two Simple
    Moving Averages (SMA). It generates buy signals when the faster SMA crosses
    above the slower SMA, and sell signals when it crosses below.

    The strategy is designed specifically to test the Calmar ratio analyzer, which
    measures risk-adjusted returns. The dual moving average approach provides a
    mix of winning and losing trades to properly test the analyzer's ability to
    calculate annualized returns and maximum drawdown.

    Attributes:
        crossover (bt.ind.CrossOver): Indicator that signals when SMAs cross.
            Positive values indicate bullish crossover (fast SMA above slow SMA).
            Negative values indicate bearish crossover (fast SMA below slow SMA).
        order (bt.Order): Reference to the currently pending order, or None if
            no order is pending. Used to prevent multiple simultaneous orders.
        bar_num (int): Counter tracking the number of bars processed during the
            backtest. Used for validation in test assertions.
        buy_count (int): Counter tracking the number of completed buy orders.
            Used for validation in test assertions.
        sell_count (int): Counter tracking the number of completed sell orders.
            Used for validation in test assertions.

    params:
        p1 (int): Period for the fast SMA. Defaults to 15 periods.
        p2 (int): Period for the slow SMA. Defaults to 50 periods.

    Note:
        The strategy closes any existing position before opening a new one in
        the opposite direction, ensuring only one position is held at a time.
    """

    params = (('p1', 15), ('p2', 50))

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Sets up the dual moving average system with a crossover indicator to
        generate trading signals. Also initializes counters for tracking
        execution metrics.
        """
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(ma1, ma2)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track completed trades.

        This method is called by the backtrader engine whenever an order's
        status changes. It tracks completed orders to update buy/sell counters
        and clears the pending order reference when orders are no longer alive.

        Args:
            order (bt.Order): The order object with updated status information.
                The order can be in various states including Submitted, Accepted,
                Partial, Completed, Cancelled, or Expired.

        Note:
            The order.alive() method returns False for completed, cancelled, or
            expired orders, allowing us to detect when an order is final.
        """
        if not order.alive():
            self.order = None
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        """Execute trading logic for each bar.

        This method is called for every bar of data after the minimum period
        requirement has been met. It implements the core trading logic:

        1. Increment the bar counter for test validation
        2. Check if there's a pending order (skip trading if yes)
        3. If fast SMA crosses above slow SMA (crossover > 0):
           - Close any existing position
           - Open a new long position
        4. If fast SMA crosses below slow SMA (crossover < 0):
           - Close any existing position
           - No short selling (strategy goes to cash)

        Note:
            This strategy only goes long (buys) and goes to cash (closes).
            It does not short sell, which limits drawdown during bear markets.
        """
        self.bar_num += 1
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_calmar_analyzer():
    """Test the Calmar Ratio analyzer with a dual moving average strategy.

    This test function validates the Calmar ratio analyzer by running a backtest
    over Yahoo stock data from 2005-2010. It verifies that the analyzer correctly
    calculates risk-adjusted returns and compares them against expected values.

    The test:
    1. Sets up a Cerebro engine with initial capital of $100,000
    2. Loads Yahoo historical price data (yhoo-1996-2014.txt)
    3. Runs the CalmarTestStrategy (15/50 dual SMA crossover)
    4. Attaches multiple analyzers: Calmar, Sharpe Ratio, Returns, Drawdown, Trades
    5. Validates all metrics against expected values with strict assertions

    Expected Results:
        - Final portfolio value: $98,020.00 (loss of ~2%)
        - Sharpe ratio: -0.469 (negative due to poor risk-adjusted returns)
        - Annual return: -0.33% (slight loss)
        - Maximum drawdown: 3.24%
        - Total trades: 16
        - Calmar ratio: -4.71e-05 (very poor risk-adjusted performance)

    Raises:
        AssertionError: If any of the calculated metrics do not match expected
            values within the specified tolerance. Each assertion includes a
            descriptive message showing the expected vs. actual values.

    Note:
        The Calmar ratio is particularly useful in this test because the strategy
        underperforms, demonstrating how the analyzer captures both the negative
        returns and the drawdown in a single metric. The negative Calmar ratio
        indicates that the annualized return is negative while drawdown is positive.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2010, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(CalmarTestStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=100)

    # Add analyzers - calculate Sharpe ratio using daily timeframe
    cerebro.addanalyzer(bt.analyzers.Calmar, _name="calmar")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    calmar_analysis = strat.analyzers.calmar.get_analysis()
    # Calmar returns OrderedDict, keys are dates, values are Calmar ratios for that period
    if calmar_analysis:
        last_date = list(calmar_analysis.keys())[-1]
        calmar_ratio = calmar_analysis[last_date]
    else:
        calmar_ratio = None

    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    drawdown = strat.analyzers.drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("\n" + "=" * 50)
    print("Calmar Analyzer Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  calmar_ratio: {calmar_ratio}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 1460, f"Expected bar_num=1460, got {strat.bar_num}"
    assert abs(final_value - 98020.00) < 0.01, f"Expected final_value=98020.00, got {final_value}"
    assert abs(sharpe_ratio - (-0.4689333841227036)) < 1e-6, f"Expected sharpe_ratio=-0.4689333841227036, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0033319591262466032)) < 1e-6, f"Expected annual_return=-0.0033319591262466032, got {annual_return}"
    assert abs(max_drawdown - 3.2398371164458886) < 1e-6, f"Expected max_drawdown=3.2398371164458886, got {max_drawdown}"
    assert total_trades == 16, f"Expected total_trades=16, got {total_trades}"
    # Calmar ratio assertions
    assert calmar_ratio is not None, "Calmar ratio should not be None"
    assert abs(calmar_ratio - (-4.713556837089328e-05)) < 1e-6, f"Expected calmar_ratio=-4.713556837089328e-05, got {calmar_ratio}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Calmar Analyzer Test")
    print("=" * 60)
    test_calmar_analyzer()
