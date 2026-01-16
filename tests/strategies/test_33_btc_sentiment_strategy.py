#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: BtcSentiment Bitcoin Sentiment Strategy

Reference source: Backtrader-Guide-AlgoTrading101/bt_main_btc.py and strategies.py
Uses Bollinger Bands indicator to trade BTC based on Google Trends sentiment data
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script directory to avoid relative path failures.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the search paths.
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


class BtcSentimentStrategy(bt.Strategy):
    """BTC trading strategy based on Google Trends sentiment data.

    This strategy goes long when the sentiment indicator exceeds the upper Bollinger Band,
    goes short when it falls below the lower band, and closes positions when returning to
    the middle region.

    Attributes:
        btc_price: BTC price data from the first data feed.
        google_sentiment: Google Trends sentiment data from the second data feed.
        bbands: Bollinger Bands indicator calculated on sentiment data.
        order: Current pending order.
        bar_num: Counter for the number of bars processed.
        buy_count: Counter for buy orders executed.
        sell_count: Counter for sell orders executed.
        win_count: Counter for profitable trades.
        loss_count: Counter for unprofitable trades.
        sum_profit: Total profit/loss from all closed trades.
    """
    params = (
        ('period', 10),
        ('devfactor', 1),
    )

    def __init__(self):
        """Initialize the BtcSentiment strategy.

        Sets up the data feeds, indicators, and tracking variables for the strategy.
        The strategy uses BTC price data from the first feed and Google Trends sentiment
        data from the second feed. Bollinger Bands are calculated on the sentiment data
        to generate trading signals.
        """
        self.btc_price = self.datas[0].close
        self.google_sentiment = self.datas[1].close
        self.bbands = bt.indicators.BollingerBands(
            self.google_sentiment,
            period=self.params.period,
            devfactor=self.params.devfactor
        )
        self.order = None

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status updates.

        Tracks the number of buy and sell orders as they are executed.
        Resets the pending order reference when the order is completed,
        canceled, margin-triggered, or rejected.

        Args:
            order: The order object with updated status information.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_count += 1
            elif order.issell():
                self.sell_count += 1

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            pass

        self.order = None

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Tracks profit/loss for each completed trade and increments the
        win or loss counters accordingly.

        Args:
            trade: The trade object with P&L information.
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        Implements the Bollinger Bands-based sentiment strategy:
        - Long: When sentiment exceeds the upper Bollinger Band
        - Short: When sentiment falls below the lower Bollinger Band
        - Close: When sentiment returns to the middle region

        Only one order is allowed at a time to prevent over-trading.
        """
        self.bar_num += 1

        if self.order:
            return

        # Long signal - sentiment indicator exceeds upper Bollinger Band
        if self.google_sentiment > self.bbands.lines.top[0]:
            if not self.position:
                self.order = self.buy()

        # Short signal - sentiment indicator falls below lower Bollinger Band
        elif self.google_sentiment < self.bbands.lines.bot[0]:
            if not self.position:
                self.order = self.sell()

        # Neutral signal - close position
        else:
            if self.position:
                self.order = self.close()

    def stop(self):
        """Output statistics when the strategy stops.

        Calculates and prints the final performance statistics including
        bar count, order counts, win/loss counts, win rate percentage,
        and total profit/loss.

        Returns:
            None
        """
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_btc_sentiment_strategy():
    """Test the BtcSentiment Bitcoin sentiment strategy.

    This test loads BTC price data and Google Trends sentiment data,
    runs the BtcSentiment strategy with Bollinger Bands, and verifies
    the backtest results including trade statistics and performance metrics.

    The test asserts that:
        - The strategy processes exactly 189 bars
        - Executes 16 buy and 16 sell orders
        - Achieves 8 winning and 8 losing trades
        - Final portfolio value is approximately 15301.43
        - Sharpe ratio is approximately 0.801
        - Annual return is approximately 23.7%
        - Maximum drawdown is approximately 17.49%

    Returns:
        None

    Raises:
        AssertionError: If any of the expected strategy metrics do not match
            the actual values within the specified tolerance.
        FileNotFoundError: If the required data files (BTCUSD_Weekly.csv or
            BTC_Gtrends.csv) cannot be found in the expected paths.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(10000.0)
    cerebro.broker.setcommission(commission=0.0025)

    print("Loading BTC price data...")
    # First data source - BTC price data (Yahoo Finance CSV format)
    btc_price_path = resolve_data_path("BTCUSD_Weekly.csv")
    data1 = bt.feeds.YahooFinanceCSVData(
        dataname=str(btc_price_path),
        fromdate=datetime.datetime(2018, 1, 1),
        todate=datetime.datetime(2020, 1, 1),
        timeframe=bt.TimeFrame.Weeks
    )
    cerebro.adddata(data1, name="BTCUSD")

    print("Loading Google Trends sentiment data...")
    # Second data source - Google Trends sentiment data
    gtrends_path = resolve_data_path("BTC_Gtrends.csv")
    data2 = bt.feeds.GenericCSVData(
        dataname=str(gtrends_path),
        fromdate=datetime.datetime(2018, 1, 1),
        todate=datetime.datetime(2020, 1, 1),
        nullvalue=0.0,
        dtformat='%Y-%m-%d',
        datetime=0,
        time=-1,
        high=-1,
        low=-1,
        open=-1,
        close=1,
        volume=-1,
        openinterest=-1,
        timeframe=bt.TimeFrame.Weeks
    )
    cerebro.adddata(data2, name="BTC_Gtrends")

    cerebro.addstrategy(BtcSentimentStrategy, period=10, devfactor=1)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analyzer results
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("BtcSentiment Bitcoin Sentiment Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  win_count: {strat.win_count}")
    print(f"  loss_count: {strat.loss_count}")
    print(f"  sum_profit: {strat.sum_profit:.2f}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - ensure the strategy runs correctly
    assert strat.bar_num == 189, f"Expected bar_num=189, got {strat.bar_num}"
    assert strat.buy_count == 16, f"Expected buy_count=16, got {strat.buy_count}"
    assert strat.sell_count == 16, f"Expected sell_count=16, got {strat.sell_count}"
    assert strat.win_count == 8, f"Expected win_count=8, got {strat.win_count}"
    assert strat.loss_count == 8, f"Expected loss_count=8, got {strat.loss_count}"
    assert total_trades == 16, f"Expected total_trades=16, got {total_trades}"
    assert abs(final_value - 15301.43) < 0.01, f"Expected final_value=15301.43, got {final_value}"
    assert abs(sharpe_ratio - 0.8009805278904287) < 1e-6, f"Expected sharpe_ratio=0.8009805278904287, got {sharpe_ratio}"
    assert abs(annual_return - (0.2369894360907055)) < 1e-6, f"Expected annual_return=0.2369894360907055, got {annual_return}"
    assert abs(max_drawdown - 17.49122338684014) < 1e-6, f"Expected max_drawdown=17.49122338684014, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("BtcSentiment Bitcoin Sentiment Strategy Test")
    print("=" * 60)
    test_btc_sentiment_strategy()
