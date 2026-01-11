"""Test cases for Sky Garden futures strategy.

Tests the Sky Garden intraday breakout strategy using zinc futures data ZN889.csv.
- Uses PandasData to load single-contract data
- Intraday strategy based on gap opening and first candlestick high/low points
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
    """Locate data files based on the script directory to avoid relative path failures."""
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


class SkyGardenStrategy(bt.Strategy):
    """Sky Garden intraday breakout strategy.

    Opens positions based on gap opening and first candlestick high/low breakouts.
    Closes positions before market close.
    """
    author = 'yunjinqi'
    params = (
        ("k1", 8),
        ("k2", 8),
    )

    def log(self, txt, dt=None):
        """Log information with timestamp."""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the Sky Garden strategy.

        Sets up all instance variables for tracking:
        - Bar counters (total and daily)
        - Trade counters (buy/sell)
        - Daily price data (high, low, close, open)
        - Historical price lists
        - Market position status
        - First candlestick high/low prices
        """
        self.bar_num = 0
        self.day_bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pre_date = None
        # Store current trading day's high, low, and close prices
        self.now_high = 0
        self.now_low = 999999999
        self.now_close = None
        self.now_open = None
        # Store historical daily high, low, and close prices
        self.day_high_list = []
        self.day_low_list = []
        self.day_close_list = []
        # Store trading status
        self.marketposition = 0
        # High and low prices of the first candlestick
        self.first_bar_high_price = 0
        self.first_bar_low_price = 0

    def prenext(self):
        """Called before minimum period is reached.

        This method is called for each bar before the strategy's minimum
        period is satisfied. No trading logic is needed here.
        """
        pass

    def next(self):
        """Execute trading logic for each bar.

        Implements the Sky Garden strategy logic:
        1. Track daily high/low/close prices
        2. At market close (15:00), store daily data and reset
        3. When sufficient data exists:
           - Record first candlestick high/low
           - Check gap opening conditions (k1 for bullish, k2 for bearish)
           - Enter long if open gaps up and breaks first candlestick high
           - Enter short if open gaps down and breaks first candlestick low
        4. Close all positions at 14:55 before market close

        Trading hours:
        - Evening session: 21:00-23:00
        - Day session: 9:00-11:00
        """
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        self.day_bar_num += 1
        self.bar_num += 1
        data = self.datas[0]

        # Update high, low, and close prices
        self.now_high = max(self.now_high, data.high[0])
        self.now_low = min(self.now_low, data.low[0])
        if self.now_close is None:
            self.now_open = data.open[0]
        self.now_close = data.close[0]

        # If it's the last minute of a new trading day
        if self.current_hour == 15:
            self.day_high_list.append(self.now_high)
            self.day_low_list.append(self.now_low)
            self.day_close_list.append(self.now_close)
            self.now_high = 0
            self.now_low = 999999999
            self.now_close = None
            self.day_bar_num = 0

        # Sufficient data length, start calculating indicators and trading signals
        if len(self.day_high_list) > 1:
            pre_high = self.day_high_list[-1]
            pre_low = self.day_low_list[-1]
            pre_close = self.day_close_list[-1]

            # Calculate Sky Garden opening conditions
            # If it's the first candlestick at market open
            if self.day_bar_num == 0:
                self.first_bar_high_price = data.high[0]
                self.first_bar_low_price = data.low[0]

            # Start trading
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            close = data.close[0]
            if open_time_1 or open_time_2:
                # Open long position
                if self.marketposition == 0 and self.now_open > pre_close * (self.p.k1 / 1000 + 1) and data.close[0] > self.first_bar_high_price:
                    self.buy(data, size=1)
                    self.buy_count += 1
                    self.marketposition = 1

                # Open short position
                if self.marketposition == 0 and self.now_open < pre_close * (-1 * self.p.k2 / 1000 + 1) and data.close[0] < self.first_bar_low_price:
                    self.sell(data, size=1)
                    self.sell_count += 1
                    self.marketposition = -1

        # Close positions before market close
        if self.marketposition != 0 and self.current_hour == 14 and self.current_minute == 55:
            self.close(data)
            self.marketposition = 0

    def notify_order(self, order):
        """Called when order status changes.

        Args:
            order: The order object with updated status.

        Logs buy/sell orders when they are completed. Orders in Submitted or
        Accepted status are ignored as they haven't been filled yet.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: price={order.executed.price:.2f}")
            else:
                self.log(f"SELL: price={order.executed.price:.2f}")

    def notify_trade(self, trade):
        """Called when a trade is closed.

        Args:
            trade: The trade object that was closed.

        Logs the profit/loss (pnl) and profit/loss after commission (pnlcomm)
        when a trade is completed.
        """
        if trade.isclosed:
            self.log(f"Trade completed: pnl={trade.pnl:.2f}, pnlcomm={trade.pnlcomm:.2f}")

    def stop(self):
        """Called when backtesting is complete.

        Logs final statistics including total bars processed and
        total buy/sell orders executed during the backtest.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


class ZnPandasFeed(bt.feeds.PandasData):
    """Pandas data feed for zinc futures data."""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def load_zn889_data(filename: str = "ZN889.csv") -> pd.DataFrame:
    """Load zinc futures data.

    Maintains the original data loading logic.

    Args:
        filename: Name of the CSV file containing zinc futures data.

    Returns:
        DataFrame with zinc futures data.
    """
    df = pd.read_csv(resolve_data_path(filename))
    # Only keep these columns from the data
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'open_interest']]
    df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    # Sort and remove duplicates
    df = df.sort_values("datetime")
    df = df.drop_duplicates("datetime")
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    # Shorten date range to speed up testing
    df = df[df.index >= '2020-01-01']
    return df


def test_sky_garden_strategy():
    """Test Sky Garden intraday breakout strategy.

    Runs backtest using zinc futures data ZN889.csv.

    Raises:
        AssertionError: If any of the test assertions fail.
    """

    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Load data
    print("Loading zinc futures data...")
    df = load_zn889_data("ZN889.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    # Load data using ZnPandasFeed
    name = "ZN"
    feed = ZnPandasFeed(dataname=df)
    cerebro.adddata(feed, name=name)

    # Set contract trading information
    comm = ComminfoFuturesPercent(commission=0.0003, margin=0.10, mult=10)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(50000.0)

    # Add strategy with fixed parameters k1=8, k2=8
    cerebro.addstrategy(SkyGardenStrategy, k1=8, k2=8)

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
    max_drawdown = strat.analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("Sky Garden Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (exact values) - based on data after 2018-01-01
    assert strat.bar_num == 32349, f"Expected bar_num=32349, got {strat.bar_num}"
    assert strat.buy_count == 20, f"Expected buy_count=20, got {strat.buy_count}"
    assert strat.sell_count == 21, f"Expected sell_count=21, got {strat.sell_count}"
    assert total_trades > 0, f"Expected total_trades > 0, got {total_trades}"
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert abs(sharpe_ratio - (1.7399955949849073)) < 1e-6, f"Expected sharpe_ratio=0.4071392839128455, got {sharpe_ratio}"
    assert abs(annual_return - (0.1594097201976482)) < 1e-6, f"Expected annual_return=0.05046792274087781, got {annual_return}"
    assert abs(max_drawdown - 0.1489498258942073) < 1e-6, f"Expected max_drawdown=0.16266069999999963, got {max_drawdown}"
    assert abs(final_value - 64961.97000000003) < 0.01, f"Expected final_value=61050.48500000002, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Sky Garden Intraday Breakout Strategy Test")
    print("=" * 60)
    test_sky_garden_strategy()