"""BollEMA Bollinger Bands + EMA Strategy Test Case

Tests the Bollinger Bands + EMA combination strategy using Shanghai stock data
(sh600000.csv).
- Uses GenericCSVData to load local data files
- Accesses data through self.datas[0] standard interface

Reference: backtrader-example/strategies/bollema.py
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
        Path: The resolved path to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path.
    """
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


class BollEMAStrategy(bt.Strategy):
    """BollEMA Bollinger Bands + EMA Strategy.

    Strategy Logic:
        - Price breaks above upper band + EMA > middle band + last 3 bars above
          middle band -> Open long position
        - Price breaks below lower band + EMA < middle band + last 3 bars below
          middle band -> Open short position
        - Close position on stop loss or EMA crossing middle band

    Data Used:
        - datas[0]: Stock price data

    Attributes:
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
        sum_profit: Total profit from all trades.
        win_count: Number of winning trades.
        loss_count: Number of losing trades.
        trade_count: Total number of trades completed.
        marketposition: Current market position (0=flat, 1=long, -1=short).
        last_price: Last executed order price.
    """

    params = (
        ("period_boll", 136),
        ("period_ema", 99),
        ("boll_diff", 0.5),    # Bollinger Bands width threshold
        ("price_diff", 0.3),   # Stop loss price difference
    )

    def log(self, txt, dt=None, force=False):
        """Log output function.

        Args:
            txt: Text message to log.
            dt: datetime object for the log entry. If None, uses current bar's datetime.
            force: If True, forces output regardless of other conditions.
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # Initialize statistical counters
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
        self.boll = bt.indicators.BollingerBands(self.data0, period=self.p.period_boll)
        # EMA indicator
        self.ema = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.period_ema)

        # Trading state
        self.marketposition = 0
        self.last_price = 0

    def notify_trade(self, trade):
        """Trade completion notification callback.

        Args:
            trade: Trade object that has been completed.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def notify_order(self, order):
        """Order status notification callback.

        Args:
            order: Order object with status update.
        """
        if order.status == order.Completed:
            self.last_price = order.executed.price

    def gt_last_mid(self):
        """Check if last 3 bars' close prices are above middle band.

        Returns:
            bool: True if last 3 bars closed above middle band, False otherwise.
        """
        data = self.data0
        return (data.close[-1] > self.boll.mid[-1] and 
                data.close[-2] > self.boll.mid[-2] and 
                data.close[-3] > self.boll.mid[-3])

    def lt_last_mid(self):
        """Check if last 3 bars' close prices are below middle band.

        Returns:
            bool: True if last 3 bars closed below middle band, False otherwise.
        """
        data = self.data0
        return (data.close[-1] < self.boll.mid[-1] and 
                data.close[-2] < self.boll.mid[-2] and 
                data.close[-3] < self.boll.mid[-3])

    def close_gt_up(self):
        """Check if close price is consecutively above upper band.

        Returns:
            bool: True if current and previous close are above upper band, False otherwise.
        """
        data = self.data0
        return data.close[0] > self.boll.top[0] and data.close[-1] > self.boll.top[-1]

    def close_lt_dn(self):
        """Check if close price is consecutively below lower band.

        Returns:
            bool: True if current and previous close are below lower band, False otherwise.
        """
        data = self.data0
        return data.close[0] < self.boll.bot[0] and data.close[-1] < self.boll.bot[-1]

    def next(self):
        self.bar_num += 1

        data = self.data0
        up = self.boll.top[0]
        mid = self.boll.mid[0]
        dn = self.boll.bot[0]
        ema = self.ema[0]
        diff = up - dn

        if self.marketposition == 0:
            # Long entry conditions
            if self.close_gt_up() and ema > mid and self.gt_last_mid() and diff > self.p.boll_diff:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(data, size=size)
                    self.marketposition = 1
                    self.buy_count += 1
            # Short entry conditions
            if self.close_lt_dn() and ema < mid and self.lt_last_mid() and diff > self.p.boll_diff:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(data, size=size)
                    self.marketposition = -1
                    self.sell_count += 1
        elif self.marketposition == 1:
            # Long position stop loss or EMA <= mid exit
            if self.last_price - data.close[0] > self.p.price_diff or ema <= mid:
                self.close()
                self.marketposition = 0
                self.sell_count += 1
        elif self.marketposition == -1:
            # Short position stop loss or EMA >= mid exit
            if data.close[0] - self.last_price > self.p.price_diff or ema >= mid:
                self.close()
                self.marketposition = 0
                self.buy_count += 1

    def stop(self):
        """Output statistics when strategy ends.

        Prints summary statistics including bar count, trade counts, win/loss
        ratio, and total profit.
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_boll_ema_strategy():
    """Test the BollEMA Bollinger Bands + EMA strategy.

    This test function:
        1. Loads Shanghai stock data (sh600000.csv)
        2. Initializes the BollEMAStrategy with specified parameters
        3. Runs a backtest from 2000-01-01 to 2022-12-31
        4. Analyzes performance metrics (Sharpe ratio, returns, drawdown)
        5. Asserts expected values for validation

    Raises:
        AssertionError: If any of the expected values don't match.
    """
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

    cerebro.addstrategy(BollEMAStrategy, period_boll=136, period_ema=99, boll_diff=0.5, price_diff=0.3)

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
    print("BollEMA Bollinger Bands + EMA Strategy Backtest Results:")
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

    assert strat.bar_num == 5280
    assert strat.buy_count == 43, f"Expected buy_count=43, got {strat.buy_count}"
    assert strat.sell_count == 44, f"Expected sell_count=44, got {strat.sell_count}"
    assert strat.win_count == 10, f"Expected win_count=10, got {strat.win_count}"
    assert strat.loss_count == 26, f"Expected loss_count=26, got {strat.loss_count}"
    assert total_trades == 37, f"Expected total_trades=37, got {total_trades}"
    assert abs(final_value - 705655.57) <1e-2,  f"Expected final_value=705655.57, got {final_value}"
    assert abs(sharpe_ratio-0.33646909650176043)<1e-6, f"sharpe_ratio={sharpe_ratio} out of range"
    assert abs(annual_return-0.09519461079565394)<1e-6, f"annual_return={annual_return} out of range"
    assert abs(max_drawdown-0.4537757234136652)<1e-6, f"max_drawdown={max_drawdown} out of range"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("BollEMA Bollinger Bands + EMA Strategy Test")
    print("=" * 60)
    test_boll_ema_strategy()
