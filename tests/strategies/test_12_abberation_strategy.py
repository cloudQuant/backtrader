"""Test cases for Abberation (Bollinger Band breakout) futures strategy.

Tests the Abberation Bollinger Band breakout strategy using rebar futures data RB889.csv
- Uses PandasData to load single contract data
- Trend strategy based on Bollinger Band upper/lower rail breakouts
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


class AbberationStrategy(bt.Strategy):
    """Abberation Bollinger Band breakout strategy.

    Go long when breaking through the upper Bollinger Band, go short when breaking
    through the lower band. Close long position when falling below the middle band,
    close short position when breaking through the middle band.
    """

    author = 'yunjinqi'
    params = (
        ("boll_period", 200),
        ("boll_mult", 2),
    )

    def log(self, txt, dt=None):
        """Log information function.

        Args:
            txt: Text content to log.
            dt: Optional datetime for the log entry. Defaults to current bar's datetime.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the strategy with indicators and state variables."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # Calculate Bollinger Band indicator
        self.boll_indicator = bt.indicators.BollingerBands(
            self.datas[0], period=self.p.boll_period, devfactor=self.p.boll_mult
        )
        # Save trading status
        self.marketposition = 0

    def prenext(self):
        """Called before minimum period is reached."""
        pass

    def next(self):
        """Called for each bar during backtesting.

        Implements the trading logic:
        - Open long when price breaks above upper Bollinger Band
        - Open short when price breaks below lower Bollinger Band
        - Close long when price falls below middle band
        - Close short when price rises above middle band
        """
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        self.bar_num += 1
        data = self.datas[0]

        # Bollinger Band upper rail, lower rail, middle rail
        top = self.boll_indicator.top
        bot = self.boll_indicator.bot
        mid = self.boll_indicator.mid

        # Open long position
        if self.marketposition == 0 and data.close[0] > top[0] and data.close[-1] < top[-1]:
            # Get the number of lots for 1x leverage order
            info = self.broker.getcommissioninfo(data)
            symbol_multi = info.p.mult
            close = data.close[0]
            total_value = self.broker.getvalue()
            lots = total_value / (symbol_multi * close)
            self.buy(data, size=lots)
            self.buy_count += 1
            self.marketposition = 1

        # Open short position
        if self.marketposition == 0 and data.close[0] < bot[0] and data.close[-1] > bot[-1]:
            # Get the number of lots for 1x leverage order
            info = self.broker.getcommissioninfo(data)
            symbol_multi = info.p.mult
            close = data.close[0]
            total_value = self.broker.getvalue()
            lots = total_value / (symbol_multi * close)
            self.sell(data, size=lots)
            self.sell_count += 1
            self.marketposition = -1

        # Close long position
        if self.marketposition == 1 and data.close[0] < mid[0] and data.close[-1] > mid[-1]:
            self.close()
            self.sell_count += 1
            self.marketposition = 0

        # Close short position
        if self.marketposition == -1 and data.close[0] > mid[0] and data.close[-1] < mid[-1]:
            self.close()
            self.buy_count += 1
            self.marketposition = 0

    def notify_order(self, order):
        """Called when order status changes.

        Args:
            order: The order object with updated status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: price={order.executed.price:.2f}")
            else:
                self.log(f"SELL: price={order.executed.price:.2f}")

    def notify_trade(self, trade):
        """Called when a trade is completed.

        Args:
            trade: The completed trade object.
        """
        if trade.isclosed:
            self.log(f"Trade completed: pnl={trade.pnl:.2f}, pnlcomm={trade.pnlcomm:.2f}")

    def stop(self):
        """Called when backtesting ends.

        Logs final statistics.
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

    Maintains the original data loading logic and limits data rows to speed up testing.

    Args:
        filename: Name of the CSV file to load.
        max_rows: Maximum number of rows to load (default: 50000).

    Returns:
        DataFrame containing the loaded and processed futures data.
    """
    df = pd.read_csv(resolve_data_path(filename))
    # Only keep these columns from the data
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'open_interest']]
    df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    # Sort and deduplicate
    df = df.sort_values("datetime")
    df = df.drop_duplicates("datetime")
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    # Remove some error data with closing price of 0
    df = df.astype("float")
    df = df[(df["open"] > 0) & (df['close'] > 0)]
    # Limit data rows to speed up testing
    if max_rows and len(df) > max_rows:
        df = df.iloc[-max_rows:]
    return df


def test_abberation_strategy():
    """Test the Abberation Bollinger Band breakout strategy.

    Performs backtesting using rebar futures data RB889.csv and validates
    the results against expected values.

    Raises:
        AssertionError: If any of the test assertions fail.
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
    comm = ComminfoFuturesPercent(commission=0.0001, margin=0.10, mult=10)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(1000000.0)

    # Add strategy with fixed parameters boll_period=200, boll_mult=2
    cerebro.addstrategy(AbberationStrategy, boll_period=200, boll_mult=2)

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
    print("Abberation Strategy Backtest Results:")
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
    assert strat.bar_num == 49801, f"Expected bar_num=49801, got {strat.bar_num}"
    assert strat.buy_count == 244, f"Expected buy_count=244, got {strat.buy_count}"
    assert strat.sell_count == 245, f"Expected sell_count=245, got {strat.sell_count}"
    assert total_trades == 245, f"Expected total_trades=245, got {total_trades}"
    assert abs(sharpe_ratio - (-0.207410495949062)) < 1e-6, f"Expected sharpe_ratio=-0.207410495949062, got {sharpe_ratio}"
    assert abs(annual_return - (-0.005304130671472128)) < 1e-6, f"Expected annual_return=-0.005304130671472128, got {annual_return}"
    assert abs(max_drawdown - 0.27322154569702256) < 1e-6, f"Expected max_drawdown=0.27322154569702256, got {max_drawdown}"
    assert abs(final_value - 984213.4012779507) < 0.01, f"Expected final_value=984213.40, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Abberation Bollinger Band Breakout Strategy Test")
    print("=" * 60)
    test_abberation_strategy()
