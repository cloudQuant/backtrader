#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Pairs Trading Strategy.

Reference: https://github.com/arikaufman/algorithmicTrading
Pairs trading based on OLS transformation and Z-Score.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt
import backtrader.indicators as btind
import math

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script directory.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

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


class PairsTradingStrategy(bt.Strategy):
    """Pairs trading strategy.

    Uses OLS transformation to calculate the Z-Score between two assets.
    When Z-Score exceeds the upper limit, short the spread; when Z-Score
    falls below the lower limit, long the spread.

    Attributes:
        orderid: ID of the current order.
        qty1: Quantity of the first asset.
        qty2: Quantity of the second asset.
        upper_limit: Upper threshold for Z-Score to trigger short position.
        lower_limit: Lower threshold for Z-Score to trigger long position.
        up_medium: Upper medium threshold for closing positions.
        low_medium: Lower medium threshold for closing positions.
        status: Current position status (0=none, 1=short, 2=long).
        portfolio_value: Total portfolio value.
        stop_loss: Stop loss threshold.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
        sma1: Simple moving average for first data feed.
        sma2: Simple moving average for second data feed.
        transform: OLS transformation indicator.
        zscore: Z-score of the spread between the two assets.
    """
    params = dict(
        period=20,
        stake=10,
        qty1=0,
        qty2=0,
        upper=2.5,
        lower=-2.5,
        up_medium=0.5,
        low_medium=-0.5,
        status=0,
        portfolio_value=100000,
        stop_loss=3.0
    )

    def log(self, txt, dt=None):
        """Log trading messages with timestamp.

        Args:
            txt: Text message to log.
            dt: Datetime object for the log entry. If None, uses current
                bar's datetime.

        Returns:
            None
        """
        dt = dt or self.data.datetime[0]

    def notify_order(self, order):
        """Handle order status notifications.

        Updates buy/sell counters when orders are completed and resets
        the order ID when orders are finished.

        Args:
            order: Order object with status information.

        Returns:
            None
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

        elif order.status in [order.Expired, order.Canceled, order.Margin]:
            pass

        self.orderid = None

    def __init__(self):
        """Initialize the pairs trading strategy.

        Sets up instance variables, parameters, and indicators including
        simple moving averages and the OLS transformation for calculating
        the Z-score between the two assets.

        Returns:
            None
        """
        self.orderid = None
        self.qty1 = self.p.qty1
        self.qty2 = self.p.qty2
        self.upper_limit = self.p.upper
        self.lower_limit = self.p.lower
        self.up_medium = self.p.up_medium
        self.low_medium = self.p.low_medium
        self.status = self.p.status
        self.portfolio_value = self.p.portfolio_value
        self.stop_loss = self.p.stop_loss

        # Statistical variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

        self.sma1 = bt.indicators.SimpleMovingAverage(self.datas[0], period=50)
        self.sma2 = bt.indicators.SimpleMovingAverage(self.datas[1], period=50)

        # Calculate Z-Score using OLS transformation
        self.transform = btind.OLS_TransformationN(self.data0, self.data1,
                                                   period=self.p.period)
        self.zscore = self.transform.zscore

    def next(self):
        """Execute trading logic for each bar.

        Implements the pairs trading strategy:
        - Short the spread when Z-score exceeds upper limit
        - Long the spread when Z-score falls below lower limit
        - Close positions when Z-score returns to mean range

        Position sizes are calculated based on portfolio allocation
        and deviation from moving averages.

        Returns:
            None
        """
        self.bar_num += 1
        x = 0
        y = 0
        if self.orderid:
            return

        # SHORT condition: zscore exceeds upper limit
        if (self.zscore[0] > self.upper_limit) and (self.status != 1):
            deviationOffSMA1 = math.fabs((self.data0.close[0]/self.sma1[0])-1)
            deviationOffSMA2 = math.fabs((self.data1.close[0]/self.sma2[0])-1)
            value1 = 0.6 * self.portfolio_value
            value2 = 0.4 * self.portfolio_value
            if deviationOffSMA1 > deviationOffSMA2:
                x = int(value1 / (self.data0.close))
                y = int(value2 / (self.data1.close))
            else:
                x = int(value2 / (self.data0.close))
                y = int(value1 / (self.data1.close))

            self.sell(data=self.data0, size=(x + self.qty1))
            self.buy(data=self.data1, size=(y + self.qty2))

            self.qty1 = x
            self.qty2 = y
            self.status = 1

        # LONG condition: zscore falls below lower limit
        elif (self.zscore[0] < self.lower_limit) and (self.status != 2):
            deviationOffSMA1 = math.fabs((self.data0.close[0]/self.sma1[0])-1)
            deviationOffSMA2 = math.fabs((self.data1.close[0]/self.sma2[0])-1)
            value1 = 0.6 * self.portfolio_value
            value2 = 0.4 * self.portfolio_value
            if deviationOffSMA1 > deviationOffSMA2:
                x = int(value1 / (self.data0.close))
                y = int(value2 / (self.data1.close))
            else:
                x = int(value2 / (self.data0.close))
                y = int(value1 / (self.data1.close))

            self.buy(data=self.data0, size=(x + self.qty1))
            self.sell(data=self.data1, size=(y + self.qty2))

            self.qty1 = x
            self.qty2 = y
            self.status = 2

        # Close position condition: zscore returns to mean range
        elif ((self.zscore[0] < self.up_medium and self.zscore[0] > self.low_medium)):
            self.close(self.data0)
            self.close(self.data1)

    def stop(self):
        """Called when the strategy execution is stopped.

        This method is called by Backtrader when the backtest completes.
        Currently a placeholder method for potential cleanup or finalization.

        Returns:
            None
        """
        pass


def test_pairs_trading_strategy():
    """Test the pairs trading strategy.

    This test loads historical price data for Visa (V) and Mastercard (MA),
    runs the pairs trading strategy, and verifies the performance metrics
    match expected values.

    Raises:
        AssertionError: If any of the performance metrics do not match
            expected values within tolerance.
    """
    cerebro = bt.Cerebro()

    # Load Visa data
    data_path_v = resolve_data_path("V.csv")
    df_v = pd.read_csv(data_path_v, parse_dates=['Date'], index_col='Date')
    df_v = df_v[['Open', 'High', 'Low', 'Close', 'Volume']]
    df_v.columns = ['open', 'high', 'low', 'close', 'volume']

    # Load Mastercard data
    data_path_ma = resolve_data_path("MA.csv")
    df_ma = pd.read_csv(data_path_ma, parse_dates=['Date'], index_col='Date')
    df_ma = df_ma[['Open', 'High', 'Low', 'Close', 'Volume']]
    df_ma.columns = ['open', 'high', 'low', 'close', 'volume']

    # Align date ranges
    common_dates = df_v.index.intersection(df_ma.index)
    df_v = df_v.loc[common_dates]
    df_ma = df_ma.loc[common_dates]

    # Use only partial data for faster testing
    df_v = df_v.iloc[:500]
    df_ma = df_ma.iloc[:500]

    data_v = bt.feeds.PandasData(dataname=df_v, name='V')
    data_ma = bt.feeds.PandasData(dataname=df_ma, name='MA')

    cerebro.adddata(data_v)
    cerebro.adddata(data_ma)

    cerebro.addstrategy(PairsTradingStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Pairs Trading Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 451, f"Expected bar_num=451, got {strat.bar_num}"
    assert abs(final_value - 99699.43) < 0.01, f"Expected final_value=99699.43, got {final_value}"
    assert abs(sharpe_ratio - (-0.3156462969633222)) < 1e-6, f"Expected sharpe_ratio=-0.3156462969633222, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0015160238352949257)) < 1e-6, f"Expected annual_return=-0.0015160238352949257, got {annual_return}"
    assert abs(max_drawdown - 1.1570119745556364) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Pairs Trading Strategy Test")
    print("=" * 60)
    test_pairs_trading_strategy()
