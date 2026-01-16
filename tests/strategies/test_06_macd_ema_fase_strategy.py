"""Test cases for MACD EMA futures strategy.

Tests the MACD + EMA trend strategy using rebar futures data (rb99.csv).
- Uses PandasDirectData to load data (maintaining original loading method)
- Trend trading using MACD golden cross/death cross + EMA filter
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
    """Locate data files based on the script's directory to avoid relative path failures.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path: Absolute path to the data file.

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


class MacdEmaStrategy(bt.Strategy):
    """MACD + EMA futures trend strategy.

    Uses MACD golden cross/death cross as entry signals and EMA as stop-loss filter.
    """
    author = 'yunjinqi'
    params = (
        ("period_me1", 10),
        ("period_me2", 20),
        ("period_signal", 9),
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
        """Initialize the MACD EMA strategy.

        Sets up counters for bars, buy/sell orders, and initializes the
        MACD and EMA indicators with the configured parameters.
        """
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # MACD indicator
        self.bt_macd_indicator = bt.indicators.MACD(
            self.datas[0],
            period_me1=self.p.period_me1,
            period_me2=self.p.period_me2,
            period_signal=self.p.period_signal
        )
        # EMA indicator
        self.ema = bt.indicators.ExponentialMovingAverage(
            self.datas[0], period=self.p.period_me1
        )

    def prenext(self):
        """Handle the prenext phase before minimum period is reached.

        This method is called for each bar before the indicator's minimum
        period has been reached. No action is taken during this phase.
        """
        pass

    def next(self):
        """Execute trading logic for each bar.

        Implements the MACD + EMA trend trading strategy:
        - Close long positions when price falls below EMA
        - Close short positions when price rises above EMA
        - Open long when DIF crosses from negative to positive with MACD bar > 0
        - Open short when DIF crosses from positive to negative with MACD bar < 0
        """
        self.bar_num += 1
        # Get MACD indicator values
        dif = self.bt_macd_indicator.macd
        dea = self.bt_macd_indicator.signal
        # Calculate MACD value for current bar (using current value)
        macd_value = 2 * (dif[0] - dea[0])
        # Current state
        data = self.datas[0]
        size = self.getposition(self.datas[0]).size

        # Close long position
        if size > 0 and data.close[0] < self.ema[0]:
            self.close(data)
            self.sell_count += 1
            size = 0

        # Close short position
        if size < 0 and data.close[0] > self.ema[0]:
            self.close(data)
            self.buy_count += 1
            size = 0

        # Open long: DIF changes from negative to positive and MACD bar > 0
        if size == 0 and dif[-1] < 0 and dif[0] > 0 and macd_value > 0:
            self.buy(data, size=1)
            self.buy_count += 1

        # Open short: DIF changes from positive to negative and MACD bar < 0
        if size == 0 and dif[-1] > 0 and dif[0] < 0 and macd_value < 0:
            self.sell(data, size=1)
            self.sell_count += 1

    def notify_order(self, order):
        """Handle order status notifications.

        Logs executed orders when they are completed. Orders that are
        submitted or accepted are ignored.

        Args:
            order: The order object with status information.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: price={order.executed.price:.2f}, cost={order.executed.value:.2f}")
            else:
                self.log(f"SELL: price={order.executed.price:.2f}, cost={order.executed.value:.2f}")

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Logs profit and loss information when a trade is closed.

        Args:
            trade: The trade object with P&L information.
        """
        if trade.isclosed:
            self.log(f"Trade completed: gross_profit={trade.pnl:.2f}, net_profit={trade.pnlcomm:.2f}")

    def stop(self):
        """Called when the backtest is finished.

        Logs final statistics including the total number of bars processed
        and the total buy/sell order counts.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


class RbPandasFeed(bt.feeds.PandasData):
    """Pandas data feed for rebar futures data.

    Uses explicit column mapping, compatible with PandasData loading method.
    """
    params = (
        ('datetime', None),  # datetime is the index
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def load_rb_data(filename: str = "rb/rb99.csv") -> pd.DataFrame:
    """Load rebar futures data.

    Maintains the original data loading logic.

    Args:
        filename: Path to the CSV file containing rebar futures data.

    Returns:
        pd.DataFrame: DataFrame containing the loaded and filtered futures data.
    """
    data_kwargs = dict(
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2020, 12, 31),
    )
    
    df = pd.read_csv(resolve_data_path(filename))
    # Only keep these columns from the data
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    # Set datetime as index
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df[(df.index <= data_kwargs['todate']) & (df.index >= data_kwargs['fromdate'])]
    return df


def test_macd_ema_strategy():
    """Test MACD + EMA futures strategy.

    Performs backtesting using rebar futures data (rb99.csv).

    Raises:
        AssertionError: If any of the test assertions fail.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Load data
    print("Loading rebar futures data...")
    df = load_rb_data("rb/RB99.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    # Use RbPandasFeed to load data (consistent with original PandasDirectData logic)
    name = "RB99"
    feed = RbPandasFeed(dataname=df)
    cerebro.adddata(feed, name=name)

    # Set contract trading information: commission 0.02%, margin rate 10%
    comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(50000.0)

    # Add strategy
    cerebro.addstrategy(MacdEmaStrategy)

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
    print("MACD EMA Strategy Backtest Results:")
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
    assert strat.bar_num == 28069, f"Expected bar_num=28069, got {strat.bar_num}"
    assert strat.buy_count == 1008, f"Expected buy_count=1008, got {strat.buy_count}"
    assert strat.sell_count == 1008, f"Expected sell_count=1008, got {strat.sell_count}"
    assert total_trades == 1008, f"Expected total_trades=1008, got {total_trades}"
    # final_value tolerance: 0.01, other indicators tolerance: 1e-6
    assert abs(sharpe_ratio - (-0.4094093376341401)) < 1e-6, f"Expected sharpe_ratio=-0.4094093376341401, got {sharpe_ratio}"
    assert abs(annual_return - (-0.016850037618788616)) < 1e-6, f"Expected annual_return=-0.016850037618788616, got {annual_return}"
    assert abs(max_drawdown - 0.3294344677230617) < 1e-6, f"Expected max_drawdown=0.3294344677230617, got {max_drawdown}"
    assert abs(final_value - 41589.93032683378) < 0.01, f"Expected final_value=41589.93032683378, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("MACD EMA Futures Strategy Test")
    print("=" * 60)
    test_macd_ema_strategy()