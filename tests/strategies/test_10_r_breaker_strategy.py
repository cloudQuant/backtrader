"""R-Breaker futures strategy test cases.

Test R-Breaker intraday breakout strategy using rebar futures data RB889.csv.
- Load single contract data using PandasData
- Intraday strategy based on support/resistance levels calculated from
  previous day's high, low, and close
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
    """Locate data files based on script directory to avoid relative path failures."""
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


class RBreakerStrategy(bt.Strategy):
    """R-Breaker intraday breakout strategy.

    Calculate Pivot, R1/R3, S1/S3 price levels based on previous day's
    high, low, and close. Open positions on breakouts, close positions
    before market close.
    """
    author = 'yunjinqi'
    params = (
        ("k1", 0.5),
        ("k2", 0.5),
    )

    def log(self, txt, dt=None):
        """Log strategy information with timestamp.

        Args:
            txt: Text message to log.
            dt: Optional datetime object for the log entry. If None, uses
                current bar's datetime from the first data feed.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize R-Breaker strategy with tracking variables.

        Initializes counters for bars, trades, and price tracking lists.
        Sets up variables to track current and historical daily price data
        for calculating pivot points and resistance/support levels.
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
        """Handle bars before minimum period is reached.

        This method is called for each bar before the strategy's minimum
        period requirement is met. No action is taken during this phase.
        """
        pass

    def next(self):
        """Execute trading logic for each bar.

        Implements the R-Breaker strategy:
        1. Track current day's high, low, close prices
        2. Calculate pivot point and support/resistance levels from previous day
        3. Generate long signals when price breaks above R3
        4. Generate short signals when price breaks below S3
        5. Reverse positions when price pulls back to R1/S1
        6. Close all positions before market close (14:55)

        Trading hours:
        - Night session: 21:00-23:00
        - Day session: 9:00-11:00
        - Position closing: 14:55
        - End of day: 15:00
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
        if len(self.day_high_list) > 1:
            pre_high = self.day_high_list[-1]
            pre_low = self.day_low_list[-1]
            pre_close = self.day_close_list[-1]
            pivot = (pre_high + pre_low + pre_close) / 3
            r1 = pivot + (self.p.k1) * (pre_high - pre_low)
            r3 = pivot + (self.p.k1 + self.p.k2) * (pre_high - pre_low)
            s1 = pivot - (self.p.k1) * (pre_high - pre_low)
            s3 = pivot - (self.p.k1 + self.p.k2) * (pre_high - pre_low)

            # Start trading
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            close = data.close[0]
            if open_time_1 or open_time_2:
                # Open long position
                if self.marketposition == 0 and close > r3:
                    self.buy(data, size=1)
                    self.buy_count += 1
                    self.marketposition = 1

                # Open short position
                if self.marketposition == 0 and close < s3:
                    self.sell(data, size=1)
                    self.sell_count += 1
                    self.marketposition = -1

                # Close long and open short
                if self.marketposition == 1 and close < r1:
                    self.close(data)
                    self.sell(data, size=1)
                    self.sell_count += 1
                    self.marketposition = -1

                # Close short and open long
                if self.marketposition == -1 and close > s1:
                    self.close(data)
                    self.buy(data, size=1)
                    self.buy_count += 1
                    self.marketposition = 1

        # Close position before market close
        if self.marketposition != 0 and self.current_hour == 14 and self.current_minute == 55:
            self.close(data)
            self.marketposition = 0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: Order object with status and execution information.

        Logs buy/sell orders when they are completed. Orders that are
        submitted or accepted are ignored until they fill.
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
            trade: Trade object with profit/loss information.

        Logs trade results when a position is closed, showing both
        gross profit (pnl) and net profit after commissions (pnlcomm).
        """
        if trade.isclosed:
            self.log(f"Trade completed: pnl={trade.pnl:.2f}, pnlcomm={trade.pnlcomm:.2f}")

    def stop(self):
        """Log final statistics when backtest completes.

        Called after all data has been processed. Logs the total number
        of bars processed and total buy/sell orders executed.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


class RbPandasFeed(bt.feeds.PandasData):
    """Pandas data feed for rebar futures data."""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def load_rb889_data(filename: str = "RB889.csv", max_rows: int = 50000) -> pd.DataFrame:
    """Load rebar futures data.

    Maintains original data loading logic and limits data rows for faster testing.

    Args:
        filename: Name of the CSV file to load.
        max_rows: Maximum number of rows to load from the data.

    Returns:
        DataFrame containing the loaded and processed futures data.
    """
    df = pd.read_csv(resolve_data_path(filename))
    # Only keep specific columns from the data
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'open_interest']]
    df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    # Sort and remove duplicates
    df = df.sort_values("datetime")
    df = df.drop_duplicates("datetime")
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    # Limit data rows for faster testing
    if max_rows and len(df) > max_rows:
        df = df.iloc[-max_rows:]
    return df


def test_r_breaker_strategy():
    """Test R-Breaker intraday breakout strategy.

    Performs backtesting using rebar futures data RB889.csv.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Load data
    print("Loading rebar futures data...")
    df = load_rb889_data("RB889.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    # Load data using RbPandasFeed
    name = "RB"
    feed = RbPandasFeed(dataname=df)
    cerebro.adddata(feed, name=name)

    # Set contract trading information
    comm = ComminfoFuturesPercent(commission=0.0003, margin=0.10, mult=10)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(50000.0)

    # Add strategy
    cerebro.addstrategy(RBreakerStrategy)

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
    print("R-Breaker Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (exact values)
    assert strat.bar_num == 50000, f"Expected bar_num=50000, got {strat.bar_num}"
    assert strat.buy_count == 437, f"Expected buy_count=437, got {strat.buy_count}"
    assert strat.sell_count == 396, f"Expected sell_count=396, got {strat.sell_count}"
    assert total_trades == 667, f"Expected total_trades=667, got {total_trades}"
    assert abs(sharpe_ratio - (-1.9029317932144931)) < 1e-6, f"Expected sharpe_ratio=-1.9029317932144931, got {sharpe_ratio}"
    assert abs(annual_return - (-0.21595324795115386)) < 1e-6, f"Expected annual_return=-0.21595324795115386, got {annual_return}"
    assert abs(max_drawdown - 0.5703196091543717) < 1e-6, f"Expected max_drawdown=0.5703196091543717, got {max_drawdown}"
    assert abs(final_value - 24145.40199999989) < 0.01, f"Expected final_value=24145.40, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("R-Breaker Intraday Breakout Strategy Test")
    print("=" * 60)
    test_r_breaker_strategy()