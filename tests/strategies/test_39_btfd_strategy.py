#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: BTFD (Buy The F* Dip) Strategy

Reference: backtrader-master2/samples/btfd/btfd.py
Buy when price drops beyond a threshold, sell after holding for a fixed number of days
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the absolute path of a data file by searching in common directories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        The absolute Path to the data file.

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


class BTFDStrategy(bt.Strategy):
    """BTFD (Buy The F* Dip) Strategy.

    Buy when the intraday price drops beyond a threshold, close the position
    after holding for a fixed number of days.
    """
    params = (
        ('fall', -0.01),
        ('hold', 2),
        ('approach', 'highlow'),
        ('target', 1.0),
    )

    def __init__(self):
        """Initialize the BTFD strategy with price drop calculation and tracking variables.

        Sets up the price drop calculation based on the specified approach and
        initializes counters for tracking trades, wins, losses, and profits.

        The approach parameter determines how price drops are calculated:
        - 'closeclose': Close price relative to previous close
        - 'openclose': Close price relative to same day open
        - 'highclose': Close price relative to same day high
        - 'highlow': Low price relative to same day high
        """
        if self.p.approach == 'closeclose':
            self.pctdown = self.data.close / self.data.close(-1) - 1.0
        elif self.p.approach == 'openclose':
            self.pctdown = self.data.close / self.data.open - 1.0
        elif self.p.approach == 'highclose':
            self.pctdown = self.data.close / self.data.high - 1.0
        elif self.p.approach == 'highlow':
            self.pctdown = self.data.low / self.data.high - 1.0

        self.barexit = 0
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status updates and track completed orders.

        Args:
            order: The order object that has been updated.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def notify_trade(self, trade):
        """Handle trade completion and track win/loss statistics.

        Args:
            trade: The trade object that has been closed.
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute the trading logic for each bar.

        Implements the BTFD strategy:
        1. If in a position and the holding period has elapsed, close the position
        2. If not in a position and price drop exceeds the threshold, buy
        """
        self.bar_num += 1
        if self.position:
            if len(self) == self.barexit:
                self.close()
        else:
            if self.pctdown <= self.p.fall:
                self.order_target_percent(target=self.p.target)
                self.barexit = len(self) + self.p.hold

    def stop(self):
        """Print final strategy statistics when backtesting completes.

        Calculates and displays the final performance metrics including
        total trades, win rate, and total profit/loss.
        """
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_btfd_strategy():
    """Test the BTFD (Buy The F* Dip) strategy.

    This test function:
    1. Loads historical price data (2005-2006)
    2. Configures a Cerebro backtest with the BTFD strategy
    3. Runs the backtest with performance analyzers (Sharpe Ratio, Returns, Drawdown, Trade Analyzer)
    4. Validates results against expected values

    The strategy buys when the intraday price drops by 1% or more,
    then closes the position after holding for 2 days.

    Raises:
        AssertionError: If any of the backtest metrics do not match expected values.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.set_coc(True)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    cerebro.addstrategy(BTFDStrategy, fall=-0.01, hold=2, approach='highlow', target=1.0)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("BTFD Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance: 0.01 for final_value, 1e-6 for other metrics
    assert strat.bar_num == 512, f"Expected bar_num=512, got {strat.bar_num}"
    assert abs(final_value - 117395.7) < 0.01, f"Expected final_value=117395.70, got {final_value}"
    assert abs(sharpe_ratio - (1.5601134401434376)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.08213622913145915)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 8.613180756673923) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("BTFD Strategy Test")
    print("=" * 60)
    test_btfd_strategy()
