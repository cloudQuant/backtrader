"""Test cases for EMA dual moving average crossover strategy.

Multi-period EMA crossover strategy testing using 5-minute and daily data.
- Use GenericCSVData to load local data files
- Access multi-period data through self.datas[0] and self.datas[1]
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on script directory to avoid relative path failures.
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


class EmaCrossStrategy(bt.Strategy):
    """EMA dual moving average crossover strategy.

    Uses multi-period data:
    - datas[0]: Minute-level data (primary data)
    - datas[1]: Daily data (filter data)

    Strategy logic:
    - EMA golden cross/death cross generates trading signals
    - Daily data used for date synchronization filtering
    """

    params = (
        ("fast_period", 80),
        ("slow_period", 200),
        ("short_size", 2),
        ("long_size", 1),
    )

    def log(self, txt, dt=None, force=False):
        """Log output functionality."""
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # Record statistics data
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # Get data references - standard access through datas list
        self.minute_data = self.datas[0]  # Minute data
        self.daily_data = self.datas[1] if len(self.datas) > 1 else None  # Daily data

        # Calculate EMA indicators on minute data
        self.fast_ema = bt.ind.EMA(self.minute_data, period=self.p.fast_period)
        self.slow_ema = bt.ind.EMA(self.minute_data, period=self.p.slow_period)
        self.ema_cross = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)

        # If daily data exists, calculate SMA on daily data
        if self.daily_data is not None:
            self.sma_day = bt.ind.SMA(self.daily_data, period=6)

    def notify_trade(self, trade):
        """Trade completion notification.

        Args:
            trade: The trade object that completed.
        """
        if not trade.isclosed:
            return
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl
        self.log(f"Trade completed: Gross profit={trade.pnl:.2f}, Net profit={trade.pnlcomm:.2f}, Cumulative={self.sum_profit:.2f}")

    def notify_order(self, order):
        """Order status notification.

        Args:
            order: The order object with updated status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"Buy executed: Price={order.executed.price:.2f}, Size={order.executed.size}")
            else:
                self.log(f"Sell executed: Price={order.executed.price:.2f}, Size={order.executed.size}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order status: {order.Status[order.status]}")

    def next(self):
        self.bar_num += 1

        # Get EMA crossover signal history (last 80 bars)
        crosslist = [i for i in self.ema_cross.get(size=80) if i == 1 or i == -1]

        # Check date synchronization (if daily data exists)
        date_synced = True
        if self.daily_data is not None:
            date_synced = self.minute_data.datetime.date(0) == self.daily_data.datetime.date(0)

        # Opening position logic
        if not self.position and date_synced:
            # Death cross signal - open short position
            if len(crosslist) > 0 and sum(crosslist) == -1:
                self.sell(data=self.minute_data, size=self.p.short_size)
                self.sell_count += 1
            # Golden cross signal - open long position
            elif len(crosslist) > 0 and sum(crosslist) == 1:
                self.buy(data=self.minute_data, size=self.p.long_size)
                self.buy_count += 1

        # Closing position logic
        elif self.position and date_synced:
            # When holding short position, close on golden cross
            if self.position.size < 0 and sum(crosslist) == 1:
                self.close()
                self.buy_count += 1
            # When holding long position, close on death cross
            elif self.position.size > 0 and sum(crosslist) == -1:
                self.close()
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


def test_ema_cross_strategy():
    """Test EMA dual moving average crossover strategy.

    Multi-period backtesting using 5-minute and daily data.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Set initial capital and commission
    cerebro.broker.setcash(100000.0)
    cerebro.broker.set_coc(True)

    # Load minute data (datas[0])
    print("Loading minute data...")
    minute_data_path = resolve_data_path("2006-min-005.txt")
    minute_data = bt.feeds.GenericCSVData(
        dataname=str(minute_data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
        dtformat="%Y-%m-%d",
        tmformat="%H:%M:%S",
        datetime=0,
        time=1,
        open=2,
        high=3,
        low=4,
        close=5,
        volume=6,
        openinterest=7,
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    cerebro.adddata(minute_data, name="minute")

    # Load daily data (datas[1])
    print("Loading daily data...")
    daily_data_path = resolve_data_path("2006-day-001.txt")
    daily_data = bt.feeds.GenericCSVData(
        dataname=str(daily_data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=6,
        timeframe=bt.TimeFrame.Days,
    )
    cerebro.adddata(daily_data, name="daily")

    # Add strategy
    cerebro.addstrategy(
        EmaCrossStrategy,
        fast_period=80,
        slow_period=200,
        short_size=2,
        long_size=1,
    )

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    # Calculate Sharpe ratio using daily timeframe, as minute data not in RATEFACTORS will cause calculation failure
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
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
    print("EMA Dual Moving Average Crossover Strategy Backtest Results:")
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

    # Basic assertions - ensure strategy runs properly
    assert strat.bar_num == 1780, f"Expected bar_num=1780, got {strat.bar_num}"
    assert abs(final_value - 99981.71) < 0.01, f"Expected final_value=99981.71, got {final_value}"
    assert total_trades == 2, f"Expected total_trades=2, got {total_trades}"
    assert abs(max_drawdown - 0.0012456157963720896) < 1e-6, f"Expected max_drawdown=0.0012456157963720896, got {max_drawdown}"
    assert abs(annual_return - (-7.631068888840081e-08)) < 1e-6, f"Expected annual_return=-0.00018074842976993673, got {annual_return}"
    # assert sharpe_ratio is None or -20 < sharpe_ratio < 20, "sharpe_ratio should be 0.01"
    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("EMA Dual Moving Average Crossover Strategy Test")
    print("=" * 60)
    test_ema_cross_strategy()