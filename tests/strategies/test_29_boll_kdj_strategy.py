"""Test cases for BOLLKDJ Bollinger Bands + KDJ strategy.

Tests the Bollinger Bands + KDJ combination strategy using Shanghai stock data
from sh600000.csv.
- Uses GenericCSVData to load local data files
- Accesses data through self.datas[0]

Reference: backtrader-example/strategies/bollkdj.py
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
    """Locate data files based on the script's directory to avoid relative path failures."""
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


class KDJ(bt.Indicator):
    """KDJ indicator.

    Refactoring note: Uses the next() method instead of line binding
    (self.l.K = self.kd.percD) because line binding has idx synchronization
    issues in the current architecture.
    """
    lines = ('K', 'D', 'J')

    params = (
        ('period', 9),
        ('period_dfast', 3),
        ('period_dslow', 3),
    )

    def __init__(self):
        self.kd = bt.indicators.StochasticFull(
            self.data,
            period=self.p.period,
            period_dfast=self.p.period_dfast,
            period_dslow=self.p.period_dslow,
        )

    def next(self):
        self.l.K[0] = self.kd.percD[0]
        self.l.D[0] = self.kd.percDSlow[0]
        self.l.J[0] = self.l.K[0] * 3 - self.l.D[0] * 2


class BOLLKDJStrategy(bt.Strategy):
    """BOLLKDJ Bollinger Bands + KDJ strategy.

    Strategy logic:
    - BOLL crosses below lower band + KDJ golden cross (at low level) -> Buy
    - BOLL crosses above upper band + KDJ death cross (at high level) -> Sell
    - Close position on stop loss or reverse signal

    Data used:
    - datas[0]: Stock price data
    """

    params = (
        ("boll_period", 53),
        ("boll_mult", 2),
        ("kdj_period", 9),
        ("kdj_ma1", 3),
        ("kdj_ma2", 3),
        ("price_diff", 0.5),  # Stop loss price difference
    )

    def log(self, txt, dt=None, force=False):
        """Logging function."""
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # Record statistics
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0
        self.trade_count = 0

        # Get data reference
        self.data0 = self.datas[0]

        # Bollinger Bands indicator
        self.boll = bt.indicators.BollingerBands(
            self.data0, period=self.p.boll_period, devfactor=self.p.boll_mult
        )
        # KDJ indicator
        self.kdj = KDJ(
            self.data0, period=self.p.kdj_period,
            period_dfast=self.p.kdj_ma1, period_dslow=self.p.kdj_ma2
        )

        # Trading state
        self.marketposition = 0
        self.position_price = 0

        # Signals
        self.boll_signal = 0
        self.kdj_signal = 0

    def notify_trade(self, trade):
        """Notification when a trade is completed."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def notify_order(self, order):
        """Notification of order status changes."""
        if order.status == order.Completed:
            self.position_price = order.executed.price

    def up_across(self):
        """Check if price crosses above upper band."""
        data = self.data0
        return data.close[-1] < self.boll.top[-1] and data.close[0] > self.boll.top[0]

    def dn_across(self):
        """Check if price crosses below lower band."""
        data = self.data0
        return data.close[-1] > self.boll.bot[-1] and data.close[0] < self.boll.bot[0]

    def check_boll_signal(self):
        """Check for BOLL signals."""
        if self.up_across():
            self.boll_signal = -1  # Sell signal
        elif self.dn_across():
            self.boll_signal = 1   # Buy signal

    def check_kdj_signal(self):
        """Check for KDJ signals."""
        condition1 = self.kdj.J[-1] - self.kdj.D[-1]
        condition2 = self.kdj.J[0] - self.kdj.D[0]
        # Golden cross at low level
        if condition1 < 0 and condition2 > 0 and (self.kdj.K[0] <= 25 and self.kdj.D[0] <= 25 and self.kdj.J[0] <= 25):
            self.kdj_signal = 1
        # Death cross at high level
        elif condition1 > 0 and condition2 < 0 and (self.kdj.K[0] >= 75 and self.kdj.D[0] >= 75 and self.kdj.J[0] >= 75):
            self.kdj_signal = -1

    def next(self):
        self.bar_num += 1

        # Check signals
        self.check_boll_signal()
        self.check_kdj_signal()

        data = self.data0

        # No position
        if self.marketposition == 0:
            # Buy condition
            if self.boll_signal > 0 and self.kdj_signal > 0:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(data, size=size)
                    self.marketposition = 1
                    self.buy_count += 1
                self.boll_signal = 0
                self.kdj_signal = 0
            # Sell condition
            elif self.boll_signal < 0 and self.kdj_signal < 0:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(data, size=size)
                    self.marketposition = -1
                    self.sell_count += 1
                self.boll_signal = 0
                self.kdj_signal = 0
        # Short position
        elif self.marketposition == -1:
            # Stop loss
            if self.position_price > 0 and (data.close[0] - self.position_price > self.p.price_diff):
                self.close()
                self.marketposition = 0
                self.position_price = 0
                self.boll_signal = 0
                self.kdj_signal = 0
                self.buy_count += 1
            # Close on reverse signal
            elif self.boll_signal > 0 and self.kdj_signal > 0:
                self.close()
                self.marketposition = 0
                self.position_price = 0
                self.boll_signal = 0
                self.kdj_signal = 0
                self.buy_count += 1
        # Long position
        elif self.marketposition == 1:
            # Stop loss
            if self.position_price - data.close[0] > self.p.price_diff:
                self.close()
                self.marketposition = 0
                self.position_price = 0
                self.boll_signal = 0
                self.kdj_signal = 0
                self.sell_count += 1
            # Close on reverse signal
            elif self.boll_signal < 0 and self.kdj_signal < 0:
                self.close()
                self.marketposition = 0
                self.position_price = 0
                self.boll_signal = 0
                self.kdj_signal = 0
                self.sell_count += 1

    def stop(self):
        """Output statistics when strategy ends."""
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_boll_kdj_strategy():
    """Test the BOLLKDJ Bollinger Bands + KDJ strategy."""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading Shanghai stock data...")
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

    cerebro.addstrategy(BOLLKDJStrategy, boll_period=53, kdj_period=9, price_diff=0.5)

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
    print("BOLLKDJ Bollinger Bands + KDJ Strategy Backtest Results:")
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

    assert strat.bar_num == 5363, f"Expected bar_num=5363, got {strat.bar_num}"
    assert strat.buy_count == 82, f"Expected buy_count=82, got {strat.buy_count}"
    assert strat.sell_count == 81, f"Expected sell_count=81, got {strat.sell_count}"
    assert total_trades == 66, f"Expected total_trades=66, got {total_trades}"
    assert abs(final_value - 75609.19) < 0.01, f"Expected final_value=75609.19, got {final_value}"
    assert abs(sharpe_ratio - (-0.08347216120029895)) < 1e-6, f"Expected sharpe_ratio=-0.08347216120029895, got {sharpe_ratio}"
    assert abs(annual_return - (-0.012927216297173407)) < 1e-6, f"Expected annual_return=-0.012927216297173407, got {annual_return}"
    assert abs(max_drawdown - 0.6605349686435283) < 1e-6, f"Expected max_drawdown=0.6605349686435283, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("BOLLKDJ Bollinger Bands + KDJ Strategy Test")
    print("=" * 60)
    test_boll_kdj_strategy()
