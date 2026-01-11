"""Test case for Abbration Bollinger Band breakout strategy.

Tests the Bollinger Band breakout strategy using Shanghai stock data sh600000.csv.
- Uses GenericCSVData to load local data files.
- Accesses data through self.datas[0] for standardization.

Reference: backtrader-example/strategies/abbration.py
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
    """Locate data file based on script directory to avoid relative path failures."""
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR.parent.parent / filename,
        BASE_DIR.parent.parent / "tests" / "datas" / filename,
    ]

    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Data file not found: {filename}")


class AbbrationStrategy(bt.Strategy):
    """Abbration Bollinger Band breakout strategy.

    Strategy logic:
    - Open long position when price breaks above the upper Bollinger Band.
    - Open short position when price breaks below the lower Bollinger Band.
    - Close position when price returns to the middle Bollinger Band.

    Data used:
    - datas[0]: Stock price data.
    """

    params = (
        ("boll_period", 200),
        ("boll_mult", 2),
    )

    def log(self, txt, dt=None, force=False):
        """Logging function."""
        if not force:
            return
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # Record statistical data
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # Get data reference - standard access through datas list
        self.data0 = self.datas[0]

        # Calculate Bollinger Band indicator
        self.boll_indicator = bt.indicators.BollingerBands(
            self.data0, period=self.p.boll_period, devfactor=self.p.boll_mult
        )

        # Save trading state
        self.marketposition = 0

    def notify_trade(self, trade):
        """Trade completion notification."""
        if not trade.isclosed:
            return
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl
        self.log(f"Trade completed: Gross profit={trade.pnl:.2f}, Net profit={trade.pnlcomm:.2f}, Cumulative={self.sum_profit:.2f}")

    def notify_order(self, order):
        """Order status notification."""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"Buy executed: Price={order.executed.price:.2f}, Size={order.executed.size}")
            else:
                self.log(f"Sell executed: Price={order.executed.price:.2f}, Size={order.executed.size}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order status: {order.Status[order.status]}")

    def next(self):
        self.bar_num += 1

        data = self.data0
        top = self.boll_indicator.top
        bot = self.boll_indicator.bot
        mid = self.boll_indicator.mid

        # Open long: Price breaks above upper band from below
        if self.marketposition == 0 and data.close[0] > top[0] and data.close[-1] < top[-1]:
            size = int(self.broker.getcash() / data.close[0])
            if size > 0:
                self.buy(data, size=size)
                self.marketposition = 1
                self.buy_count += 1

        # Open short: Price breaks below lower band from above
        if self.marketposition == 0 and data.close[0] < bot[0] and data.close[-1] > bot[-1]:
            size = int(self.broker.getcash() / data.close[0])
            if size > 0:
                self.sell(data, size=size)
                self.marketposition = -1
                self.sell_count += 1

        # Close long: Price crosses below middle band from above
        if self.marketposition == 1 and data.close[0] < mid[0] and data.close[-1] > mid[-1]:
            self.close()
            self.marketposition = 0
            self.sell_count += 1

        # Close short: Price crosses above middle band from below
        if self.marketposition == -1 and data.close[0] > mid[0] and data.close[-1] < mid[-1]:
            self.close()
            self.marketposition = 0
            self.buy_count += 1

    def stop(self):
        """Output statistics when strategy ends."""
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_abbration_strategy():
    """Test Abbration Bollinger Band breakout strategy.

    Run backtest using Shanghai stock data.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Set initial capital
    cerebro.broker.setcash(100000.0)

    # Load data (datas[0])
    print("Loading Shanghai stock data...")
    data_path = resolve_data_path("sh600000.csv")
    df = pd.read_csv(data_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')  # Sort in chronological order
    df = df.set_index('datetime')
    df = df[(df.index >= '2000-01-01') & (df.index <= '2022-12-31')]
    df = df[df['close'] > 0]  # Filter invalid data

    # Reorder columns to match PandandasData default format
    df = df[['open', 'high', 'low', 'close', 'volume']]

    data_feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,  # Use index as date
        open=0,
        high=1,
        low=2,
        close=3,
        volume=4,
        openinterest=-1,
    )
    cerebro.adddata(data_feed, name="SH600000")

    # Add strategy
    cerebro.addstrategy(
        AbbrationStrategy,
        boll_period=200,
        boll_mult=2,
    )

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()

    # Get results
    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("Abbration Bollinger Band breakout strategy backtest results:")
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

    # Assertions - ensure strategy runs correctly
    assert strat.bar_num == 5216, f"Expected bar_num=5216, got {strat.bar_num}"
    assert strat.buy_count == 19, f"Expected buy_count=19, got {strat.buy_count}"
    assert strat.sell_count == 20, f"Expected sell_count=20, got {strat.sell_count}"
    assert strat.win_count == 9, f"Expected win_count=9, got {strat.win_count}"
    assert strat.loss_count == 6, f"Expected loss_count=6, got {strat.loss_count}"
    assert total_trades == 16, f"Expected total_trades=16, got {total_trades}"
    assert abs(final_value - 423916.71) < 0.01, f"Expected final_value=423916.71, got {final_value}"
    assert abs(sharpe_ratio - 0.2701748176643007) < 1e-6, f"Expected sharpe_ratio=0.2701748176643007, got {sharpe_ratio}"
    assert abs(annual_return - (0.06952761581010602)) < 1e-6, f"Expected annual_return=0.06952761581010602, got {annual_return}"
    assert abs(max_drawdown - 0.46515816375898594) < 1e-6, f"Expected max_drawdown=0.46515816375898594, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Abbration Bollinger Band breakout strategy test")
    print("=" * 60)
    test_abbration_strategy()
