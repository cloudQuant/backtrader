import backtrader as bt
"""Stop Loss Order Strategy Test Case

Test stop loss order functionality using convertible bond index data bond_index_000000.csv
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
    """Locate data files based on script directory to avoid relative path failures"""
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
        ("datetime", None),  # datetime is index, not a data column
        ("open", 0),  # Column 1 -> index 0
        ("high", 1),  # Column 2 -> index 1
        ("low", 2),  # Column 3 -> index 2
        ("close", 3),  # Column 4 -> index 3
        ("volume", 4),  # Column 5 -> index 4
        ("openinterest", -1),  # Column does not exist
        ("pure_bond_value", 5),  # Column 6 -> index 5
        ("convert_value", 6),  # Column 7 -> index 6
        ("pure_bond_premium_rate", 7),  # Column 8 -> index 7
        ("convert_premium_rate", 8),  # Column 9 -> index 8
    )

    # Define extended data lines
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


class StopOrderStrategy(bt.Strategy):
    """Stop Loss Order Strategy

    Strategy Logic:
    - Use dual moving average crossover to generate buy signals
    - Set stop loss order after buying
    - Stop loss price is a percentage of the buy price
    """

    params = (
        ("short_period", 5),
        ("long_period", 20),
        ("stop_loss_pct", 0.03),  # 3% stop loss
    )

    def log(self, txt, dt=None, force=False):
        """Function for logging information"""
        if not force:
            return  # Default: no log output
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

        # Record crossover signals
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

        # Record bar count
        self.bar_num = 0

        # Record trade counts
        self.buy_count = 0
        self.sell_count = 0
        self.stop_count = 0  # Stop loss trigger count

        # Save order references
        self.order = None
        self.stop_order = None
        self.buy_price = None

    def next(self):
        self.bar_num += 1

        # If there are pending orders, wait
        if self.order:
            return

        # If there is a stop loss order waiting, do not operate
        if self.stop_order:
            # Check if death cross appears, need to actively close position
            if self.crossover < 0:
                self.cancel(self.stop_order)
                self.stop_order = None
                self.order = self.close()
                self.sell_count += 1
            return

        # If no position and golden cross appears, buy
        if not self.position:
            if self.crossover > 0:
                # Use 90% of current funds to buy
                cash = self.broker.get_cash()
                price = self.datas[0].close[0]
                size = int(cash * 0.9 / price)
                if size > 0:
                    self.order = self.buy(size=size)
                    self.buy_count += 1

    def stop(self):
        self.log(
            f"bar_num = {self.bar_num}, buy_count = {self.buy_count}, sell_count = {self.sell_count}, stop_count = {self.stop_count}"
        )

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    f"Buy executed: Price={order.executed.price:.2f}, Size={order.executed.size:.0f}"
                )
                self.buy_price = order.executed.price

                # After successful buy, set stop loss order
                stop_price = self.buy_price * (1 - self.p.stop_loss_pct)
                self.log(f"Set stop loss order: Stop price={stop_price:.2f}")
                self.stop_order = self.sell(
                    size=order.executed.size, exectype=bt.Order.Stop, price=stop_price
                )
            else:
                self.log(
                    f"Sell executed: Price={order.executed.price:.2f}, Size={abs(order.executed.size):.0f}"
                )
                self.buy_price = None

                # Check if this is a stop loss order trigger
                if order == self.stop_order:
                    self.stop_count += 1
                    self.log("Stop loss order triggered!")
                    self.stop_order = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order canceled/insufficient margin/rejected: {order.status}")

        # Reset order status
        if self.stop_order is None or order.ref != self.stop_order.ref:
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"Trade completed: Gross profit={trade.pnl:.2f}, Net profit={trade.pnlcomm:.2f}")


def load_index_data(filename: str = "bond_index_000000.csv") -> pd.DataFrame:
    """Load convertible bond index data"""
    df = pd.read_csv(resolve_data_path(filename))
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.dropna()
    df = df.astype("float")
    return df


def test_stop_order_strategy():
    """
    Test stop loss order strategy

    Run backtest using convertible bond index data bond_index_000000.csv
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Add strategy
    cerebro.addstrategy(StopOrderStrategy, short_period=5, long_period=20, stop_loss_pct=0.03)

    # Load data
    print("Loading convertible bond index data...")
    df = load_index_data("bond_index_000000.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    # Add data
    feed = ExtendPandasFeed(dataname=df)
    cerebro.adddata(feed, name="bond_index")

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
    print("Backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  stop_count: {strat.stop_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (exact values)
    assert strat.bar_num == 4414, f"Expected bar_num=4414, got {strat.bar_num}"
    assert strat.buy_count == 4, f"Expected buy_count=4, got {strat.buy_count}"
    assert strat.sell_count == 1, f"Expected sell_count=1, got {strat.sell_count}"
    assert strat.stop_count == 3, f"Expected stop_count=3, got {strat.stop_count}"
    assert total_trades == 5, f"Expected total_trades=5, got {total_trades}"
    # final_value tolerance: 0.01, other indicators tolerance: 1e-6
    assert abs(sharpe_ratio - (-0.11532400124757156)) < 1e-6, f"Expected sharpe_ratio=-0.11532400124757156, got {sharpe_ratio}"
    assert abs(annual_return - (-0.02594445655033843)) < 1e-6, f"Expected annual_return=-0.02594445655033843, got {annual_return}"
    assert abs(max_drawdown - 0.75241098463008) < 1e-6, f"Expected max_drawdown=0.75241098463008, got {max_drawdown}"
    assert abs(final_value - 62969.156504940926) < 0.01, f"Expected final_value=62969.156504940926, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Stop Loss Order Strategy Test")
    print("=" * 60)
    test_stop_order_strategy()
