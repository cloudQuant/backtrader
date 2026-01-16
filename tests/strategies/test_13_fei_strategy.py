"""Test cases for Fei (Fei A'li Four-Price Improved Version) Futures Strategy.

Tests the improved Fei A'li four-price strategy using rebar futures data RB889.csv.
- Uses PandasData to load single-contract data.
- Fei A'li four-price breakout strategy based on Bollinger Bands filtering.
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


class FeiStrategy(bt.Strategy):
    """Fei A'li Four-Price Improved Version Strategy.

    Uses Bollinger Bands for filtering:
    - Go long when price breaks above Bollinger upper band, middle band is trending up,
      and price breaks above previous day's high.
    - Go short when price breaks below Bollinger lower band, middle band is trending down,
      and price breaks below previous day's low.
    - Close positions before market close.
    """
    author = 'yunjinqi'
    params = (
        ("boll_period", 200),
        ("boll_mult", 2),
    )

    def log(self, txt, dt=None):
        """Log information with timestamp.

        Args:
            txt: Text message to log.
            dt: Optional datetime for the log entry. Defaults to current data timestamp.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the Fei A'li strategy instance.

        Sets up instance variables for tracking:
        - Bar counters and trade counts
        - Bollinger Bands indicator for filtering signals
        - Current market position state
        - Daily OHLC price tracking
        - Historical daily high, low, and close lists
        """
        self.bar_num = 0
        self.day_bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # Calculate Bollinger Bands indicator
        self.boll_indicator = bt.indicators.BollingerBands(
            self.datas[0], period=self.p.boll_period, devfactor=self.p.boll_mult
        )
        # Save trading status
        self.marketposition = 0
        # Save current trading day's high, low, and close prices
        self.now_high = 0
        self.now_low = 999999999
        self.now_close = None
        self.now_open = None
        # Save historical daily high, low, and close prices
        self.day_high_list = []
        self.day_low_list = []
        self.day_close_list = []

    def prenext(self):
        """Called before the minimum period of indicators is reached.

        This method is called during the warmup period when not enough data
        bars are available for the strategy's indicators to calculate values.
        No action is taken during this period.
        """
        pass

    def next(self):
        """Main strategy logic called on each bar.

        Implements the Fei A'li four-price strategy with Bollinger Band filtering:
        - Tracks daily OHLC prices and updates historical lists at market close
        - Opens long positions when price breaks above BB upper band, mid band trending up,
          and price breaks above previous day's high
        - Opens short positions when price breaks below BB lower band, mid band trending down,
          and price breaks below previous day's low
        - Closes all positions at 14:55 before market close
        - Trading only allowed during 21:00-23:00 and 9:00-11:00
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

        # Improved version of Fei A'li four-price: Use Bollinger Bands for filtering
        if len(self.day_high_list) > 1:
            top = self.boll_indicator.top
            bot = self.boll_indicator.bot
            mid = self.boll_indicator.mid
            pre_high = self.day_high_list[-1]
            pre_low = self.day_low_list[-1]

            # Start trading
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            # Open position
            if open_time_1 or open_time_2:
                # Open long position
                if self.marketposition == 0 and data.close[0] > top[0] and mid[0] > mid[-1] and data.close[0] > pre_high:
                    # Get order size for 1x leverage
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.buy(data, size=lots)
                    self.buy_count += 1
                    self.marketposition = 1
                # Open short position
                if self.marketposition == 0 and mid[0] < mid[-1] and data.close[0] < bot[0] and data.close[0] < pre_low:
                    # Get order size for 1x leverage
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.sell(data, size=lots)
                    self.sell_count += 1
                    self.marketposition = -1

            if self.marketposition != 0 and self.current_hour == 14 and self.current_minute == 55:
                self.close(data)
                self.marketposition = 0

    def notify_order(self, order):
        """Called when an order status changes.

        Logs executed buy/sell orders when they complete.

        Args:
            order: The order object with status information.
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

        Logs the profit/loss of completed trades.

        Args:
            trade: The trade object with PnL information.
        """
        if trade.isclosed:
            self.log(f"Trade completed: pnl={trade.pnl:.2f}, pnlcomm={trade.pnlcomm:.2f}")

    def stop(self):
        """Called when the backtest is finished.

        Logs final statistics including total bars processed and trade counts.
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

    Maintains original data loading logic and limits data rows to speed up testing.

    Args:
        filename: Name of the CSV file containing rebar futures data.
        max_rows: Maximum number of rows to load. If None, loads all data.

    Returns:
        DataFrame containing the loaded and processed futures data.
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
    # Remove erroneous data with close price of 0
    df = df.astype("float")
    df = df[(df["open"] > 0) & (df['close'] > 0)]
    # Limit data rows to speed up testing
    if max_rows and len(df) > max_rows:
        df = df.iloc[-max_rows:]
    return df


def test_fei_strategy():
    """Test the Fei A'li four-price improved version strategy.

    Runs backtest using rebar futures data RB889.csv.
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

    # Add strategy with fixed parameters boll_period=200, boll_mult=2
    cerebro.addstrategy(FeiStrategy, boll_period=200, boll_mult=2)

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
    print("Fei Strategy Backtest Results:")
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
    assert strat.buy_count == 212, f"Expected buy_count=212, got {strat.buy_count}"
    assert strat.sell_count == 130, f"Expected sell_count=130, got {strat.sell_count}"
    assert total_trades == 342, f"Expected total_trades=342, got {total_trades}"
    assert abs(sharpe_ratio - (-0.9102735975413994)) < 1e-6, f"Expected sharpe_ratio=-0.9102735975413994, got {sharpe_ratio}"
    assert abs(annual_return - (-0.09029688654771216)) < 1e-6, f"Expected annual_return=-0.09029688654771216, got {annual_return}"
    assert abs(max_drawdown - 0.3494575276331572) < 1e-6, f"Expected max_drawdown=0.3494575276331572, got {max_drawdown}"
    assert abs(final_value - 753399.3414635758) < 0.01, f"Expected final_value=753399.34, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Fei (Fei A'li Four-Price Improved Version) Strategy Test")
    print("=" * 60)
    test_fei_strategy()