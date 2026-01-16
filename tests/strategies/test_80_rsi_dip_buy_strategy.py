#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: RSI Dip Buy Strategy

Reference: https://github.com/Backtesting/strategies
Buy when RSI crosses above 50, sell when RSI crosses below or hits take profit/stop loss.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common directories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

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


class RSIDipBuyStrategy(bt.Strategy):
    """RSI Dip Buy Strategy.

    This strategy buys when RSI crosses above 50 from below (indicating
    momentum shift) and sells when RSI falls below 45 or hits stop loss/take profit.

    Entry conditions:
        - RSI crosses above 50 from below

    Exit conditions:
        - RSI falls below 45
        - Stop loss hit (0.5% below entry price)
        - Take profit hit (0.5% above entry price)
    """
    params = dict(
        stake=10,
        rsi_period=10,
        rsi_buy=50,
        rsi_sell=45,
        stop_loss=0.005,
        take_profit=0.005,
    )

    def __init__(self):
        """Initialize strategy indicators and state variables."""
        self.dataclose = self.datas[0].close
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.order = None
        self.buy_price = 0

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object that was updated.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.buy_price = order.executed.price
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute trading logic for each bar."""
        self.bar_num += 1
        if self.order:
            return

        if not self.position:
            # Buy when RSI crosses above 50 from below
            if self.rsi[-1] <= self.p.rsi_buy and self.rsi[0] > self.p.rsi_buy:
                self.order = self.buy(size=self.p.stake)
        else:
            # Exit on stop loss, take profit, or RSI drop
            stop_loss_hit = self.dataclose[0] < self.buy_price * (1 - self.p.stop_loss)
            take_profit_hit = self.dataclose[0] > self.buy_price * (1 + self.p.take_profit)
            rsi_exit = self.rsi[0] < self.p.rsi_sell

            if stop_loss_hit or take_profit_hit or rsi_exit:
                self.order = self.sell(size=self.p.stake)


def test_rsi_dip_buy_strategy():
    """Test the RSI Dip Buy strategy.

    This test validates that the RSI-based dip buying strategy correctly
    identifies entry and exit points based on RSI levels and produces
    expected backtest results.

    Raises:
        AssertionError: If any of the expected values do not match the
            actual results within the specified tolerance.
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
    cerebro.addstrategy(RSIDipBuyStrategy)
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
    print("RSI Dip Buy Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance: final_value 0.01, other metrics 1e-6
    assert strat.bar_num == 1247, f"Expected bar_num=1247, got {strat.bar_num}"
    assert abs(final_value - 99893.93) < 0.01, f"Expected final_value=99893.93, got {final_value}"
    assert abs(sharpe_ratio - (-0.6332718772573606)) < 1e-6, f"Expected sharpe_ratio=-0.6332718772573606, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00021274294674960664)) < 1e-9, f"Expected annual_return=-0.00021274294674960664, got {annual_return}"
    assert abs(max_drawdown - 0.16146151315165563) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("RSI Dip Buy Strategy Test")
    print("=" * 60)
    test_rsi_dip_buy_strategy()
