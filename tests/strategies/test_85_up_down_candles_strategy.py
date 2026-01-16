#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Up Down Candles Strategy

Reference: https://github.com/backtrader-stuff/strategies
Mean reversion strategy based on candlestick strength and returns
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The absolute path to the first matching data file found.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.
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


class UpDownCandleStrength(bt.Indicator):
    """Up Down Candle Strength Indicator.

    This indicator calculates the strength of price movement by measuring
    the ratio of up candles to down candles over a specified period.

    The strength value ranges from 0.0 (all down candles) to 1.0 (all up candles),
    with 0.5 indicating an equal number of up and down candles.

    Attributes:
        lines.strength: The calculated strength ratio (0.0 to 1.0).
        params.period: The number of periods to analyze for candle strength.

    Note:
        A strength value of 0.5 is returned when there are no clear up or down
        candles (i.e., all candles have equal open and close prices).
    """
    lines = ('strength',)
    params = dict(period=20,)

    def __init__(self):
        """Initialize the UpDownCandleStrength indicator.

        Sets the minimum period required for calculation based on the
        configured period parameter.
        """
        self.addminperiod(self.p.period)

    def next(self):
        """Calculate the candle strength ratio for the current bar.

        Counts the number of up candles (close > open) and down candles
        (close < open) over the specified period and calculates the ratio.

        The strength value is calculated as:
            strength = up_count / (up_count + down_count)

        If no candles have clear directional movement (all open == close),
        the strength is set to 0.5 (neutral).
        """
        up_count = 0
        down_count = 0
        for i in range(self.p.period):
            if self.data.close[-i] > self.data.open[-i]:
                up_count += 1
            elif self.data.close[-i] < self.data.open[-i]:
                down_count += 1

        total = up_count + down_count
        if total == 0:
            self.lines.strength[0] = 0.5
        else:
            self.lines.strength[0] = up_count / total


class PercentReturnsPeriod(bt.Indicator):
    """Period Percentage Returns Indicator.

    Calculates the percentage return of price over a specified period.
    This measures the cumulative price change from N periods ago to the
    current period, expressed as a percentage.

    Attributes:
        lines.returns: The calculated percentage return.
        params.period: The number of periods to calculate returns over.

    Note:
        Returns are calculated as:
            returns = (current_close - close_N_periods_ago) / close_N_periods_ago
    """
    lines = ('returns',)
    params = dict(period=40,)

    def __init__(self):
        """Initialize the PercentReturnsPeriod indicator.

        Sets the minimum period required for calculation based on the
        configured period parameter.
        """
        self.addminperiod(self.p.period)

    def next(self):
        """Calculate the percentage return for the current bar.

        Computes the return from N periods ago to the current period.
        Returns 0 if the closing price N periods ago is zero to avoid
        division by zero errors.

        The return is calculated as:
            returns = (close[0] - close[-period]) / close[-period]
        """
        if self.data.close[-self.p.period] != 0:
            self.lines.returns[0] = (self.data.close[0] - self.data.close[-self.p.period]) / self.data.close[-self.p.period]
        else:
            self.lines.returns[0] = 0


class UpDownCandlesStrategy(bt.Strategy):
    """Up Down Candles Strategy.

    A mean reversion strategy that identifies overbought and oversold
    conditions based on price returns over a specified period. The strategy
    assumes that extreme price movements will revert to the mean.

    Trading Logic:
        - When returns are strongly negative (< -threshold), the asset is
          considered oversold and the strategy goes long.
        - When returns are strongly positive (> +threshold), the asset is
          considered overbought and the strategy goes short.
        - Positions are closed when returns revert toward zero.

    Attributes:
        params.stake: The number of shares/units to trade per order.
        params.strength_period: Period for candle strength calculation (default: 20).
        params.returns_period: Period for returns calculation (default: 40).
        params.returns_threshold: Minimum return threshold to trigger trades (default: 0.01).
    """
    params = dict(
        stake=10,
        strength_period=20,
        returns_period=40,
        returns_threshold=0.01,
    )

    def __init__(self):
        """Initialize the UpDownCandlesStrategy.

        Sets up the indicators and tracking variables for the strategy.
        Creates the candle strength and period returns indicators, and
        initializes counters for tracking trades and bars.
        """
        self.dataclose = self.datas[0].close

        self.strength = UpDownCandleStrength(
            self.datas[0],
            period=self.p.strength_period
        )

        self.returns = PercentReturnsPeriod(
            self.datas[0],
            period=self.p.returns_period
        )

        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called by Backtrader when an order's status changes. Tracks completed
        orders by incrementing buy/sell counters and resets the order reference
        when the order is complete or cancelled.

        Args:
            order: The order object with updated status information.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute the strategy logic for each bar.

        This method is called by Backtrader for each bar of data.
        Implements the mean reversion trading logic:

        1. Skip if there's a pending order
        2. Skip if returns are within the threshold (no signal)
        3. If no position:
           - Go long when returns are strongly negative (oversold)
           - Go short when returns are strongly positive (overbought)
        4. If in position:
           - Close long positions when returns turn positive
           - Close short positions when returns turn negative
        """
        self.bar_num += 1

        if self.order:
            return

        returns = self.returns[0]

        if abs(returns) < self.p.returns_threshold:
            return

        if not self.position:
            # Mean reversion: short when overbought, long when oversold
            if returns < -self.p.returns_threshold:
                self.order = self.buy(size=self.p.stake)
            elif returns > self.p.returns_threshold:
                self.order = self.sell(size=self.p.stake)
        else:
            # Close position when returns revert to within threshold
            if self.position.size > 0 and returns > 0:
                self.order = self.close()
            elif self.position.size < 0 and returns < 0:
                self.order = self.close()


def test_up_down_candles_strategy():
    """Test the Up Down Candles strategy.

    This test function:
    1. Loads historical price data from a CSV file
    2. Runs the UpDownCandlesStrategy with default parameters
    3. Validates backtest results against expected values

    Raises:
        AssertionError: If any of the backtest metrics do not match expected values
            within the specified tolerance.
    """
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(UpDownCandlesStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Up Down Candles Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1218, f"Expected bar_num=1218, got {strat.bar_num}"
    assert abs(final_value - 99976.91) < 0.01, f"Expected final_value=99976.91, got {final_value}"
    assert abs(sharpe_ratio - (-0.11438879840513524)) < 1e-6, f"Expected sharpe_ratio=-0.11438879840513524, got {sharpe_ratio}"
    assert abs(annual_return - (-4.629057819258505e-05)) < 1e-12, f"Expected annual_return=-4.629057819258505e-05, got {annual_return}"
    assert abs(max_drawdown - 0.13256895983198377) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Up Down Candles Strategy Test")
    print("=" * 60)
    test_up_down_candles_strategy()
