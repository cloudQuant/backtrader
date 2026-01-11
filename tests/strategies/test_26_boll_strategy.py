"""Bollinger Band Strategy Test Case

Tests the Bollinger Band strategy using Shanghai Stock Exchange data sh600000.csv
- Uses GenericCSVData to load local data files
- Accesses data via self.datas[0]

Reference: backtrader-example/strategies/boll.py
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
    """Locates data files based on the script directory to avoid relative path failures."""
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


class BollStrategy(bt.Strategy):
    """Bollinger Band Strategy.

    Strategy Logic:
    - Open long position when closing price exceeds upper band for two consecutive bars
    - Open short position when closing price falls below lower band for two consecutive bars
    - Close position when price crosses the middle band

    Data Used:
    - datas[0]: Stock price data
    """

    params = (
        ("period_boll", 245),
        ("price_diff", 0.5),  # Stop loss price difference
    )

    def log(self, txt, dt=None, force=False):
        """Log output function."""
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # Record statistical data
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0
        self.trade_count = 0

        # Get data reference
        self.data0 = self.datas[0]

        # Bollinger Band indicator
        self.boll = bt.indicators.BollingerBands(self.data0, period=self.p.period_boll)

        # Trading status
        self.marketposition = 0
        self.position_price = 0

    def notify_trade(self, trade):
        """Trade completion notification."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def notify_order(self, order):
        """Order status notification."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            self.position_price = order.executed.price

    def close_gt_up(self):
        """Closing price continuously above upper band."""
        data = self.data0
        return data.close[0] > self.boll.top[0] and data.close[-1] > self.boll.top[-1]

    def close_lt_dn(self):
        """Closing price continuously below lower band."""
        data = self.data0
        return data.close[0] < self.boll.bot[0] and data.close[-1] < self.boll.bot[-1]

    def down_across_mid(self):
        """Crossing middle band downward."""
        data = self.data0
        return data.close[-1] > self.boll.mid[-1] and data.close[0] < self.boll.mid[0]

    def up_across_mid(self):
        """Crossing middle band upward."""
        data = self.data0
        return data.close[-1] < self.boll.mid[-1] and data.close[0] > self.boll.mid[0]

    def next(self):
        self.bar_num += 1
        data = self.data0

        # Open position
        if self.marketposition == 0:
            if self.close_gt_up():
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(data, size=size)
                    self.marketposition = 1
                    self.buy_count += 1
            elif self.close_lt_dn():
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(data, size=size)
                    self.marketposition = -1
                    self.sell_count += 1
        # Long position
        elif self.marketposition > 0:
            # Stop loss
            if self.position_price - data.close[0] > self.p.price_diff:
                self.close()
                self.marketposition = 0
                self.sell_count += 1
            # Close position when crossing middle band
            elif self.down_across_mid():
                self.close()
                self.marketposition = 0
                self.sell_count += 1
        # Short position
        elif self.marketposition < 0:
            # Stop loss
            if data.close[0] - self.position_price > self.p.price_diff:
                self.close()
                self.marketposition = 0
                self.buy_count += 1
            # Close position when crossing middle band
            elif self.up_across_mid():
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


def test_boll_strategy():
    """Test Bollinger Band strategy."""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading Shanghai Stock Exchange data...")
    data_path = resolve_data_path("sh600000.csv")
    df = pd.read_csv(data_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')
    df = df.set_index('datetime')
    df = df[(df.index >= '2000-01-01') & (df.index <= '2022-12-31')]
    df = df[df['close'] > 0]
    
    df = df[['open', 'high', 'low', 'close', 'volume']]
    
    data_feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open=0,
        high=1,
        low=2,
        close=3,
        volume=4,
        openinterest=-1,
    )
    cerebro.adddata(data_feed, name="SH600000")

    cerebro.addstrategy(BollStrategy, period_boll=245, price_diff=0.5)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    print("Starting backtest...")
    results = cerebro.run()

    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    print("\n" + "=" * 50)
    print("Bollinger Band Strategy Backtest Results:")
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

    assert strat.bar_num == 5171, f"Expected bar_num=5171, got {strat.bar_num}"
    assert strat.buy_count == 23, f"Expected buy_count=23, got {strat.buy_count}"
    assert strat.sell_count == 24, f"Expected sell_count=24, got {strat.sell_count}"
    assert strat.win_count == 6, f"Expected win_count=6, got {strat.win_count}"
    assert strat.loss_count == 13, f"Expected loss_count=13, got {strat.loss_count}"
    assert total_trades == 20, f"Expected total_trades=20, got {total_trades}"
    assert abs(final_value - 325630.39) < 0.01, f"Expected final_value=325630.39, got {final_value}"
    assert abs(sharpe_ratio - 0.23478555305294077) < 1e-6, f"Expected sharpe_ratio=0.23478555305294077, got {sharpe_ratio}"
    assert abs(annual_return - (0.05647903475651481)) < 1e-6, f"Expected annual_return=0.05647903475651481, got {annual_return}"
    assert abs(max_drawdown - 0.45736836540827375) < 1e-6, f"Expected max_drawdown=0.45736836540827375, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Bollinger Band Strategy Test")
    print("=" * 60)
    test_boll_strategy()
