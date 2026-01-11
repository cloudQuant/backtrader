"""VIX Volatility Index Strategy Test Cases

Tests sentiment-driven strategy using SPY and VIX volatility index data.
- Uses GenericCSVData to load local data files.
- Accesses data via self.datas[0] following best practices.

Reference: https://github.com/cloudQuant/sentiment-fear-and-greed.git
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import backtrader as bt

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


class SPYVixData(bt.feeds.GenericCSVData):
    """SPY + VIX volatility index data feed.

    CSV format:
    Date,Open,High,Low,Close,Adj Close,Volume,Put Call,Fear Greed,VIX
    """
    lines = ('put_call', 'fear_greed', 'vix')

    params = (
        ('dtformat', '%Y-%m-%d'),
        ('datetime', 0),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 6),
        ('openinterest', -1),
        ('put_call', 7),
        ('fear_greed', 8),
        ('vix', 9),
    )


class VIXStrategy(bt.Strategy):
    """VIX volatility index strategy.

    Strategy logic:
    - Buy when VIX > 35 (extreme market fear)
    - Sell when VIX < 10 (extreme market calm)

    Data used:
    - datas[0]: SPY price data + VIX indicator
    """

    params = (
        ("high_threshold", 35),  # High threshold: buy above this level (fear)
        ("low_threshold", 10),   # Low threshold: sell below this level (calm)
    )

    def log(self, txt, dt=None, force=False):
        """Log output function."""
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # Record statistics
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # Get data references - access via datas list following best practices
        self.data0 = self.datas[0]
        self.vix = self.data0.vix
        self.close = self.data0.close

    def notify_trade(self, trade):
        """Trade completion notification."""
        if not trade.isclosed:
            return
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl
        self.log(f"Trade completed: gross_profit={trade.pnl:.2f}, net_profit={trade.pnlcomm:.2f}, cumulative={self.sum_profit:.2f}")

    def notify_order(self, order):
        """Order status notification."""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY EXECUTED: price={order.executed.price:.2f}, size={order.executed.size}")
            else:
                self.log(f"SELL EXECUTED: price={order.executed.price:.2f}, size={order.executed.size}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"ORDER STATUS: {order.Status[order.status]}")

    def next(self):
        self.bar_num += 1

        # Calculate buyable quantity
        size = int(self.broker.getcash() / self.close[0])

        # Buy when VIX is high (market fear)
        if self.vix[0] > self.p.high_threshold and not self.position:
            if size > 0:
                self.buy(size=size)
                self.buy_count += 1

        # Sell when VIX is low (market calm)
        if self.vix[0] < self.p.low_threshold and self.position.size > 0:
            self.sell(size=self.position.size)
            self.sell_count += 1

    def stop(self):
        """Output statistics when strategy ends."""
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_vix_strategy():
    """Test VIX volatility index strategy.

    Run backtest using SPY and VIX data.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Set initial cash
    cerebro.broker.setcash(100000.0)

    # Load data (datas[0])
    print("Loading SPY + VIX data...")
    data_path = resolve_data_path("spy-put-call-fear-greed-vix.csv")
    data_feed = SPYVixData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2011, 1, 1),
        todate=datetime.datetime(2021, 12, 31),
    )
    cerebro.adddata(data_feed, name="SPY")

    # Add strategy
    cerebro.addstrategy(
        VIXStrategy,
        high_threshold=35,
        low_threshold=10,
    )

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
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("VIX Volatility Index Strategy Backtest Results:")
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

    # Assertions - ensure strategy runs correctly
    assert strat.bar_num == 2445, f"Expected bar_num=2445, got {strat.bar_num}"
    assert strat.buy_count == 3, f"Expected buy_count=3, got {strat.buy_count}"
    assert strat.sell_count == 1, f"Expected sell_count=1, got {strat.sell_count}"
    assert strat.win_count == 1, f"Expected win_count=1, got {strat.win_count}"
    assert strat.loss_count == 0, f"Expected loss_count=0, got {strat.loss_count}"
    assert total_trades == 2, f"Expected total_trades=2, got {total_trades}"
    assert abs(sharpe_ratio - 0.918186863324403) < 1e-6, f"Expected sharpe_ratio=0.918186863324403, got {sharpe_ratio}"
    assert abs(annual_return - (0.1040505783834931)) < 1e-6, f"Expected annual_return=0.1040505783834931, got {annual_return}"
    assert abs(max_drawdown - 0.3367517000981378) < 1e-6, f"Expected max_drawdown=0.3367517000981378, got {max_drawdown}"
    assert abs(final_value - 261273.5) < 0.01, f"Expected final_value=261273.50, got {final_value}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("VIX Volatility Index Strategy Test")
    print("=" * 60)
    test_vix_strategy()
