import backtrader as bt
"""Test case for dual moving average strategy

Tests dual moving average crossover strategy using bond data 113013.csv
"""

import datetime
import os
from pathlib import Path

import numpy as np
import pandas as pd

from backtrader.cerebro import Cerebro
from backtrader.strategy import Strategy
from backtrader.feeds import PandasData

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on script directory to avoid relative path reading failures"""
    search_paths = []

    # 1. Current directory (tests/strategies)
    search_paths.append(BASE_DIR / filename)

    # 2. tests directory and project root directory
    search_paths.append(BASE_DIR.parent / filename)
    repo_root = BASE_DIR.parent.parent
    search_paths.append(repo_root / filename)

    # 3. Common data directories (examples, tests/datas)
    search_paths.append(repo_root / "examples" / filename)
    search_paths.append(repo_root / "tests" / "datas" / filename)

    # 4. Directory specified by environment variable BACKTRADER_DATA_DIR
    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    fallback = Path(filename)
    if fallback.exists():
        return fallback

    searched = " , ".join(str(path) for path in search_paths + [fallback.resolve()])
    raise FileNotFoundError(f"Data file not found: {filename}. Tried paths: {searched}")


class ExtendPandasFeed(PandasData):
    """
    Extended Pandas data source with convertible bond specific fields

    DataFrame structure (after set_index):
    - Index: datetime
    - Column 0: open
    - Column 1: high
    - Column 2: low
    - Column 3: close
    - Column 4: volume
    - Column 5: pure_bond_value
    - Column 6: convert_value
    - Column 7: pure_bond_premium_rate
    - Column 8: convert_premium_rate
    """

    params = (
        ("datetime", None),  # datetime is the index, not a data column
        ("open", 0),  # Column 1 -> index 0
        ("high", 1),  # Column 2 -> index 1
        ("low", 2),  # Column 3 -> index 2
        ("close", 3),  # Column 4 -> index 3
        ("volume", 4),  # Column 5 -> index 4
        ("openinterest", -1),  # This column does not exist
        ("pure_bond_value", 5),  # Column 6 -> index 5
        ("convert_value", 6),  # Column 7 -> index 6
        ("pure_bond_premium_rate", 7),  # Column 8 -> index 7
        ("convert_premium_rate", 8),  # Column 9 -> index 8
    )

    # Define extended data lines
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


class TwoMAStrategy(bt.Strategy):
    """Dual moving average strategy

    Buy when short-term MA crosses above long-term MA, sell when crosses below
    """

    params = (
        ("short_period", 5),
        ("long_period", 20),
    )

    def log(self, txt, dt=None):
        """Function to log information"""
        if dt is None:
            try:
                dt_val = self.datas[0].datetime[0]
                if dt_val > 0:
                    dt = bt.num2date(dt_val)
                else:
                    dt = None
            except (IndexError, ValueError):
                dt = None

        if dt:
            print("{}, {}".format(dt.isoformat(), txt))
        else:
            print("%s" % txt)

    def __init__(self):
        # Calculate moving average indicators
        self.short_ma = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.short_period
        )
        self.long_ma = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.long_period
        )

        # Record crossover signal
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

        # Record bar count
        self.bar_num = 0

        # Record trade counts
        self.buy_count = 0
        self.sell_count = 0

    def next(self):
        self.bar_num += 1

        # If no position and golden cross occurs (short MA crosses above long MA), buy
        if not self.position:
            if self.crossover > 0:
                # Buy using 90% of current cash
                cash = self.broker.get_cash()
                price = self.datas[0].close[0]
                size = int(cash * 0.9 / price)
                if size > 0:
                    self.buy(size=size)
                    self.buy_count += 1
        else:
            # If holding position and death cross occurs (short MA crosses below long MA), sell
            if self.crossover < 0:
                self.close()
                self.sell_count += 1

    def stop(self):
        self.log(
            f"bar_num = {self.bar_num}, buy_count = {self.buy_count}, sell_count = {self.sell_count}"
        )

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: Price={order.executed.price:.2f}, Size={order.executed.size:.2f}")
            else:
                self.log(f"SELL: Price={order.executed.price:.2f}, Size={order.executed.size:.2f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"Trade completed: Gross profit={trade.pnl:.2f}, Net profit={trade.pnlcomm:.2f}")


def load_bond_data(filename: str = "113013.csv") -> pd.DataFrame:
    """Load bond data"""
    df = pd.read_csv(resolve_data_path(filename))
    df.columns = [
        "symbol",
        "bond_symbol",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "pure_bond_value",
        "convert_value",
        "pure_bond_premium_rate",
        "convert_premium_rate",
    ]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.drop(["symbol", "bond_symbol"], axis=1)
    df = df.dropna()
    df = df.astype("float")
    return df


def test_two_ma_strategy():
    """
    Test dual moving average strategy

    Run backtest using bond data 113013.csv
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Add strategy
    cerebro.addstrategy(TwoMAStrategy, short_period=5, long_period=20)

    # Load data
    print("Loading bond data...")
    df = load_bond_data("113013.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    # Add data
    feed = ExtendPandasFeed(dataname=df)
    cerebro.adddata(feed, name="113013")

    # Set commission
    cerebro.broker.setcommission(commission=0.001)

    # Set initial cash
    cerebro.broker.setcash(100000.0)

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
    print("Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results - using precise assertions
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1424, f"Expected bar_num=1424, got {strat.bar_num}"
    assert strat.buy_count == 52, f"Expected buy_count=52, got {strat.buy_count}"
    assert strat.sell_count == 51, f"Expected sell_count=51, got {strat.sell_count}"
    assert total_trades == 51, f"Expected total_trades=51, got {total_trades}"
    assert abs(sharpe_ratio - (-0.4876104524755018)) < 1e-6, f"Expected sharpe_ratio=-0.4876104524755018, got {sharpe_ratio}"
    assert abs(annual_return - (-0.02770615921670656)) < 1e-6, f"Expected annual_return=-0.02770615921670656, got {annual_return}"
    assert abs(max_drawdown - 0.23265126671771275) < 1e-6, f"Expected max_drawdown=0.23265126671771275, got {max_drawdown}"
    assert abs(final_value - 85129.07932299998) < 0.01, f"Expected final_value=85129.07932299998, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Dual Moving Average Strategy Test")
    print("=" * 60)
    test_two_ma_strategy()
