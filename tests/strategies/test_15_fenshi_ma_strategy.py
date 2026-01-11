"""Test cases for TimeLine MA Futures Strategy

Test the TimeLine MA strategy using rebar futures data RB889.csv
- Use PandasData to load single contract data
- Intraday strategy based on time average price line and moving average filter, with trailing stop loss
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
    """Locate data files based on the script directory to avoid relative path failures"""
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


class TimeLine(bt.Indicator):
    """Time average price line indicator

    Calculate the cumulative average of the day's closing prices as the time average price line
    """
    lines = ('day_avg_price',)
    params = (("day_end_time", (15, 0, 0)),)

    def __init__(self):
        """Initialize the TimeLine indicator.

        Creates an empty list to store closing prices for the current day.
        The cumulative average of these prices will be calculated as the
        time average price line.
        """
        self.day_close_price_list = []

    def next(self):
        """Calculate the time average price for the current bar.

        This method is called for each bar in the data series. It:
        1. Appends the current bar's close price to the day's price list
        2. Calculates the cumulative average of all prices in the list
        3. Resets the price list at the end of the trading day

        The time average price line is useful for intraday strategies as it
        represents the average entry price of all market participants throughout
        the day.
        """
        self.day_close_price_list.append(self.data.close[0])
        self.lines.day_avg_price[0] = sum(self.day_close_price_list) / len(self.day_close_price_list)

        self.current_datetime = bt.num2date(self.data.datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        day_end_hour, day_end_minute, _ = self.p.day_end_time
        if self.current_hour == day_end_hour and self.current_minute == day_end_minute:
            self.day_close_price_list = []


class TimeLineMaStrategy(bt.Strategy):
    """Time line moving average strategy

    Trade using time average price line combined with moving average:
    - MA upward + price > MA + price breaks through time MA → go long
    - MA downward + price < MA + price breaks below time MA → go short
    - Use trailing stop loss
    - Close position before market close
    """
    author = 'yunjinqi'
    params = (
        ("ma_period", 200),
        ("stop_mult", 1),
    )

    def log(self, txt, dt=None):
        """Logging function"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the TimeLineMaStrategy.

        Sets up the following components:
        - Counter variables for bars and trades
        - TimeLine indicator for calculating day average price
        - Simple Moving Average (SMA) for trend filtering
        - State variables for tracking positions, daily high/low, and orders
        """
        self.bar_num = 0
        self.day_bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # Time average price line indicator
        self.day_avg_price = TimeLine(self.datas[0])
        self.ma_value = bt.indicators.SMA(self.datas[0].close, period=self.p.ma_period)
        # Trading state
        self.marketposition = 0
        # Current trading day's high, low, and close prices
        self.now_high = 0
        self.now_low = 999999999
        self.now_close = None
        self.now_open = None
        # Trailing stop order
        self.stop_order = None

    def prenext(self):
        """Called before the minimum period is reached.

        This method is called for each bar before the indicators have enough
        data to be valid. Currently empty as all logic is in the next() method.
        """
        pass

    def next(self):
        """Execute the main trading logic for each bar.

        This method implements the core strategy:
        1. Updates daily high/low tracking
        2. Checks if position needs to be closed at market close (14:55)
        3. Generates long signals when:
           - MA is trending up (current > previous)
           - Price is above MA
           - Price breaks above time average price line (bullish breakout)
        4. Generates short signals when:
           - MA is trending down (current < previous)
           - Price is below MA
           - Price breaks below time average price line (bearish breakout)
        5. Places trailing stop orders for risk management
        6. Closes positions when price reverses through time average price line

        Trading hours: 9:00-11:00 and 21:00-23:00
        Position close: 14:55 (before market close at 15:00)
        """
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        self.day_bar_num += 1
        self.bar_num += 1
        data = self.datas[0]

        # Update high, low, close prices
        self.now_high = max(self.now_high, data.high[0])
        self.now_low = min(self.now_low, data.low[0])
        if self.now_close is None:
            self.now_open = data.open[0]
        self.now_close = data.close[0]
        if self.current_hour == 15:
            self.now_high = 0
            self.now_low = 999999999
            self.now_close = None
            self.day_bar_num = 0

        # Initialize
        size = self.getposition(data).size
        if size == 0:
            self.marketposition = 0
            if self.stop_order is not None:
                self.broker.cancel(self.stop_order)
                self.stop_order = None

        # Time line MA strategy
        if len(data.close) > self.p.ma_period:
            # Start trading
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            # Open position
            if open_time_1 or open_time_2:
                # Go long
                if self.marketposition == 0 and self.day_bar_num >= 3 and self.ma_value[0] > self.ma_value[-1] and data.close[0] > self.ma_value[0] and data.close[0] > self.day_avg_price[0] and data.close[-1] < self.day_avg_price[-1]:
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.buy(data, size=lots)
                    self.buy_count += 1
                    self.marketposition = 1
                    self.stop_order = self.sell(data, size=lots, exectype=bt.Order.StopTrail, trailpercent=self.p.stop_mult / 100)
                # Go short
                if self.marketposition == 0 and self.day_bar_num >= 3 and self.ma_value[0] < self.ma_value[-1] and data.close[0] < self.ma_value[0] and data.close[0] < self.day_avg_price[0] and data.close[-1] > self.day_avg_price[-1]:
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.sell(data, size=lots)
                    self.sell_count += 1
                    self.marketposition = -1
                    self.stop_order = self.buy(data, size=lots, exectype=bt.Order.StopTrail, trailpercent=self.p.stop_mult / 100)

            # Signal-based position closing
            # Close long position
            if self.marketposition > 0 and data.close[0] < self.day_avg_price[0] and data.close[0] < self.now_low:
                self.close(data)
                self.marketposition = 0
                if self.stop_order is not None:
                    self.broker.cancel(self.stop_order)
                self.stop_order = None
            # Close short position
            if self.marketposition < 0 and data.close[0] > self.day_avg_price[0] and data.close[0] > self.now_high:
                self.close(data)
                self.marketposition = 0
                if self.stop_order is not None:
                    self.broker.cancel(self.stop_order)
                self.stop_order = None

            # Close position at market close
            if self.marketposition != 0 and self.current_hour == 14 and self.current_minute == 55:
                self.close(data)
                self.marketposition = 0
                if self.stop_order is not None:
                    self.broker.cancel(self.stop_order)
                self.stop_order = None

    def notify_order(self, order):
        """Handle order status updates.

        Called when an order changes status. Logs executed orders and ignores
        pending orders (Submitted/Accepted).

        Args:
            order: The order object that changed status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: price={order.executed.price:.2f}")
            else:
                self.log(f"SELL: price={order.executed.price:.2f}")

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Called when a trade is closed. Logs the profit/loss information
        including gross and net PnL (after commissions).

        Args:
            trade: The trade object that was closed.
        """
        if trade.isclosed:
            self.log(f"Trade completed: pnl={trade.pnl:.2f}, pnlcomm={trade.pnlcomm:.2f}")

    def stop(self):
        """Called when the backtest is finished.

        Logs final statistics including total bars processed and the
        number of buy/sell orders executed during the backtest.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


class RbPandasFeed(bt.feeds.PandasData):
    """Pandas data source for rebar futures data"""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def load_rb889_data(filename: str = "RB889.csv") -> pd.DataFrame:
    """Load rebar futures data

    Keep the original data loading logic
    """
    df = pd.read_csv(resolve_data_path(filename))
    # Only use these columns from the data
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'open_interest']]
    df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    # Sort and deduplicate
    df = df.sort_values("datetime")
    df = df.drop_duplicates("datetime")
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    # Remove error data with close price of 0
    df = df.astype("float")
    df = df[(df["open"] > 0) & (df['close'] > 0)]
    # Shorten date range to speed up testing
    df = df[df.index >= '2019-01-01']
    return df


def test_timeline_ma_strategy():
    """Test time line moving average strategy

    Run backtest using rebar futures data RB889.csv
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Load data
    print("Loading rebar futures data...")
    df = load_rb889_data("RB889.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} bars")

    # Use RbPandasFeed to load data
    name = "RB"
    feed = RbPandasFeed(dataname=df)
    cerebro.adddata(feed, name=name)

    # Set contract trading information
    comm = ComminfoFuturesPercent(commission=0.0001, margin=0.10, mult=10)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(1000000.0)

    # Add strategy with fixed parameters ma_period=200, stop_mult=1
    cerebro.addstrategy(TimeLineMaStrategy, ma_period=200, stop_mult=1)

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
    print("Time line MA strategy backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (exact values) - based on data after 2019-01-01
    assert strat.bar_num == 41306, f"Expected bar_num=41306, got {strat.bar_num}"
    assert strat.buy_count == 337, f"Expected buy_count=337, got {strat.buy_count}"
    assert strat.sell_count == 240, f"Expected sell_count=240, got {strat.sell_count}"
    assert total_trades == 577, f"Expected total_trades=577, got {total_trades}"
    # assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"Expected sharpe_ratio=0.691750545190999, got {sharpe_ratio}"
    assert abs(annual_return - (0.04084785450929118)) < 1e-6, f"Expected annual_return=0.04084785450929118, got {annual_return}"
    assert abs(max_drawdown - 0.17075848708181077) < 1e-6, f"Expected max_drawdown=0.17075848708181077, got {max_drawdown}"
    assert abs(final_value - 1105093.7719086385) < 0.01, f"Expected final_value=1105093.7719086385, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Time Line MA (TimeLine MA) Intraday Strategy Test")
    print("=" * 60)
    test_timeline_ma_strategy()