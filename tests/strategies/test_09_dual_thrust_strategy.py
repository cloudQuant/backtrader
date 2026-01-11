"""Dual Thrust futures strategy test cases.

Test the Dual Thrust intraday breakout strategy using glass futures data FG889.csv.
- Load single contract data using PandasData
- Intraday strategy based on N-day high/low breakout
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt
from backtrader.comminfo import ComminfoFuturesFixed

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script directory to avoid relative path failures.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

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


class DualThrustStrategy(bt.Strategy):
    """Dual Thrust intraday breakout strategy.

    Calculate upper and lower bands based on N-day high/low prices,
    open positions on breakout, and close positions before market close.
    """
    author = 'yunjinqi'
    params = (
        ("look_back_days", 10),
        ("k1", 0.5),
        ("k2", 0.5),
    )

    def log(self, txt, dt=None):
        """Log information.

        Args:
            txt: Text content to log.
            dt: Datetime object. If None, uses current data's datetime.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the Dual Thrust strategy with tracking variables.

        Sets up variables for tracking bar counts, buy/sell orders,
        daily price data (high, low, close), and current market position.
        """
        self.bar_num = 0
        self.pre_date = None
        self.buy_count = 0
        self.sell_count = 0
        # Save current trading day's high, low, and close prices
        self.now_high = 0
        self.now_low = 999999999
        self.now_close = None
        self.now_open = None
        # Save historical daily high, low, and close prices
        self.day_high_list = []
        self.day_low_list = []
        self.day_close_list = []
        # Save trading status
        self.marketposition = 0

    def prenext(self):
        """Handle prenext phase when minimum period is not yet reached.

        This method is called for bars before the strategy's minimum period
        is satisfied. Currently does nothing as this strategy processes all bars.
        """
        pass

    def next(self):
        """Execute trading logic for each bar.

        Implements the Dual Thrust strategy:
        1. Update daily high/low/close prices
        2. At market close (15:00), save daily data to history
        3. Calculate upper/lower bands using N-day lookback period
        4. Generate entry signals during trading hours (9-11, 21-23)
        5. Handle position reversals when price crosses bands
        6. Close all positions before market close (14:55)
        """
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
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

        # Sufficient data length, start calculating indicators and trading signals
        if len(self.day_high_list) > self.p.look_back_days:
            # Calculate range
            hh = max(self.day_high_list[-1 * self.p.look_back_days:])
            lc = min(self.day_close_list[-1 * self.p.look_back_days:])
            hc = max(self.day_close_list[-1 * self.p.look_back_days:])
            ll = min(self.day_low_list[-1 * self.p.look_back_days:])
            range_price = max(hh - lc, hc - ll)
            # Calculate upper and lower bands
            close = data.close[0]
            upper_line = self.now_open + self.p.k1 * range_price
            lower_line = self.now_open - self.p.k2 * range_price

            # Start trading
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            if open_time_1 or open_time_2:
                # Open long position
                if self.marketposition == 0 and close > upper_line:
                    self.buy(data, size=1)
                    self.buy_count += 1
                    self.marketposition = 1

                # Open short position
                if self.marketposition == 0 and close < lower_line:
                    self.sell(data, size=1)
                    self.sell_count += 1
                    self.marketposition = -1

            # Close long and open short
            if self.marketposition == 1 and close < lower_line:
                self.close(data)
                self.sell(data, size=1)
                self.sell_count += 1
                self.marketposition = -1

            # Close short and open long
            if self.marketposition == -1 and close > upper_line:
                self.close(data)
                self.buy(data, size=1)
                self.buy_count += 1
                self.marketposition = 1

            # Close positions before market close
            if self.marketposition != 0 and self.current_hour == 14 and self.current_minute == 55:
                self.close(data)
                self.marketposition = 0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: Order object containing execution details.

        Logs executed buy/sell orders with their execution price.
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

        Args:
            trade: Trade object containing P&L information.

        Logs the profit/loss when a trade is closed.
        """
        if trade.isclosed:
            self.log(f"Trade completed: pnl={trade.pnl:.2f}, pnlcomm={trade.pnlcomm:.2f}")

    def stop(self):
        """Log final statistics when backtesting completes.

        Outputs the total number of bars processed and buy/sell order counts.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


class FgPandasFeed(bt.feeds.PandasData):
    """Pandas data feed for glass futures data.

    Defines the column mapping for glass futures data loaded from CSV files.
    """
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def load_fg_data(filename: str = "FG889.csv", max_rows: int = None) -> pd.DataFrame:
    """Load glass futures data from CSV file.

    Maintains the original data loading logic with date range filtering.

    Args:
        filename: Name of the CSV file to load.
        max_rows: Maximum number of rows to load for faster testing.

    Returns:
        DataFrame containing the loaded futures data with filtered date range.
    """
    data_kwargs = dict(
        fromdate=datetime.datetime(2020, 1, 1),  # Further shorten date range to accelerate testing
        todate=datetime.datetime(2021, 7, 31),
    )

    df = pd.read_csv(resolve_data_path(filename))
    # Only keep these columns from the data
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'open_interest']]
    df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    # Rename columns
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df[(df.index <= data_kwargs['todate']) & (df.index >= data_kwargs['fromdate'])]
    return df


def test_dual_thrust_strategy():
    """Test Dual Thrust intraday breakout strategy.

    Performs backtesting using glass futures data from FG889.csv file.

    Raises:
        AssertionError: If test assertions fail.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Load data
    print("Loading glass futures data...")
    df = load_fg_data("FG889.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} bars")

    # Load data using FgPandasFeed
    name = "FG"
    feed = FgPandasFeed(dataname=df)
    cerebro.adddata(feed, name=name)

    # Set contract trading information
    comm = ComminfoFuturesFixed(commission=26, margin=0.15, mult=20)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(50000.0)

    # Add strategy
    cerebro.addstrategy(DualThrustStrategy)

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
    print("Dual Thrust Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (exact values) - Based on data from 2020-01-01 to 2021-07-31
    assert strat.bar_num == 123960, f"Expected bar_num=123960, got {strat.bar_num}"
    assert strat.buy_count == 14, f"Expected buy_count=14, got {strat.buy_count}"
    assert strat.sell_count == 7, f"Expected sell_count=7, got {strat.sell_count}"
    assert total_trades == 21, f"Expected total_trades=21, got {total_trades}"
    # final_value tolerance: 0.01, other indicators tolerance: 1e-6
    assert abs(sharpe_ratio - (-16.73034120003273)) < 1e-6, f"Expected sharpe_ratio=-16.73034120003273, got {sharpe_ratio}"
    assert abs(annual_return - (-0.016015877679295135)) < 1e-6, f"Expected annual_return=-0.016015877679295135, got {annual_return}"
    assert abs(max_drawdown - 0.04545908283255804) < 1e-6, f"Expected max_drawdown=0.04545908283255804, got {max_drawdown}"
    assert abs(final_value - 48788.0) < 0.01, f"Expected final_value=48788.0, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Dual Thrust Intraday Breakout Strategy Test")
    print("=" * 60)
    test_dual_thrust_strategy()