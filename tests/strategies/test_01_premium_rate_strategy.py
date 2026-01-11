#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Convertible bond premium rate moving average crossover strategy test.

Calculates moving averages using conversion premium rate. Buy when the
short-term moving average crosses above the long-term moving average,
and sell to close positions when it crosses below.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script directory to avoid relative path failures.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path: Absolute path to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path.
    """
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR.parent / "datas" / filename,
    ]

    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Data file not found: {filename}")


class ExtendPandasFeed(bt.feeds.PandasData):
    """Extended Pandas data feed with convertible bond-specific fields.

    DataFrame structure (after set_index):
        - Index: datetime
        - Column 0: open, Column 1: high, Column 2: low, Column 3: close,
          Column 4: volume
        - Column 5: pure_bond_value, Column 6: convert_value
        - Column 7: pure_bond_premium_rate, Column 8: convert_premium_rate
    """

    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
        ('pure_bond_value', 5),
        ('convert_value', 6),
        ('pure_bond_premium_rate', 7),
        ('convert_premium_rate', 8)
    )

    lines = ('pure_bond_value', 'convert_value',
             'pure_bond_premium_rate', 'convert_premium_rate')


class PremiumRateCrossoverStrategy(bt.Strategy):
    """Conversion premium rate moving average crossover strategy.

    Strategy logic:
        - Use conversion premium rate (convert_premium_rate) to calculate
          moving averages
        - Buy when short-term moving average (default 10-day) crosses above
          long-term moving average (default 60-day)
        - Sell to close positions when short-term moving average crosses below
          long-term moving average
    """

    params = (
        ('short_period', 10),
        ('long_period', 60),
    )

    def __init__(self):
        self.premium_rate = self.datas[0].convert_premium_rate
        self.sma_short = bt.indicators.SimpleMovingAverage(
            self.premium_rate, period=self.p.short_period
        )
        self.sma_long = bt.indicators.SimpleMovingAverage(
            self.premium_rate, period=self.p.long_period
        )
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        self.bar_num += 1
        if self.order:
            return

        if not self.position:
            if self.crossover > 0:
                cash = self.broker.getcash()
                size = int((cash * 0.95) / self.datas[0].close[0])
                self.order = self.buy(size=size)
        else:
            if self.crossover < 0:
                self.order = self.close()


def load_bond_data(csv_file: str) -> pd.DataFrame:
    """Load convertible bond data from CSV file.

    Args:
        csv_file: Path to the CSV file.

    Returns:
        pd.DataFrame: Processed DataFrame with bond data.
    """
    df = pd.read_csv(csv_file)
    df.columns = ['BOND_CODE', 'BOND_SYMBOL', 'datetime', 'open', 'high', 'low',
                  'close', 'volume', 'pure_bond_value', 'convert_value',
                  'pure_bond_premium_rate', 'convert_premium_rate']

    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    df = df.drop(['BOND_CODE', 'BOND_SYMBOL'], axis=1)
    df = df.dropna()
    df = df.astype(float)

    return df


def test_premium_rate_strategy():
    """Test convertible bond premium rate moving average crossover strategy.

    Uses 113013.csv data for backtesting to verify strategy metrics
    meet expected values.
    """
    cerebro = bt.Cerebro()

    # Load data
    print("Loading convertible bond data...")
    data_path = resolve_data_path("113013.csv")
    df = load_bond_data(str(data_path))
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    data = ExtendPandasFeed(dataname=df)
    cerebro.adddata(data)

    # Set initial capital and commission
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0003)

    # Add strategy
    cerebro.addstrategy(PremiumRateCrossoverStrategy)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio')
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm100')
    max_drawdown = strat.analyzers.drawdown.get_analysis()['max']['drawdown']
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("Convertible Bond Premium Rate Crossover Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (based on complete 113013.csv data)
    assert strat.bar_num == 1384, f"Expected bar_num=1384, got {strat.bar_num}"
    assert abs(final_value - 104275.87) < 0.01, \
        f"Expected final_value=104275.87, got {final_value}"
    assert sharpe_ratio is not None, "Sharpe ratio should not be None"
    assert abs(sharpe_ratio - 0.11457095300469224) < 1e-6, \
        f"Expected sharpe_ratio=0.11457095300469224, got {sharpe_ratio}"
    assert abs(annual_return - 0.733367887488441) < 1e-6, \
        f"Expected annual_return=0.733367887488441, got {annual_return}"
    assert abs(max_drawdown - 17.413029757464745) < 1e-6, \
        f"Expected max_drawdown=17.413, got {max_drawdown}"
    assert total_trades == 21, f"Expected total_trades=21, got {total_trades}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Convertible Bond Premium Rate Crossover Strategy Test")
    print("=" * 60)
    test_premium_rate_strategy()
