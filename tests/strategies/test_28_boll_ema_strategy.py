"""Bollinger Bands + EMA Strategy Test Module.

This module tests the BollEMA strategy which combines Bollinger Bands and
Exponential Moving Average (EMA) to generate trading signals. The strategy
is tested using Shanghai stock data (sh600000.csv).

Strategy Overview:
    The BollEMA strategy generates buy and sell signals based on:
    - Price breaking above/below Bollinger Bands
    - EMA position relative to the middle band
    - Historical price position (last 3 bars)
    - Bollinger Band width as a volatility filter

Test Data:
    - Symbol: Shanghai Stock Exchange 600000 (Pudong Development Bank)
    - Period: 2000-01-01 to 2022-12-31
    - Data source: Local CSV file loaded via Pandas

Reference:
    backtrader-example/strategies/bollema.py

Example:
    >>> test_boll_ema_strategy()
    bar_num=5280, buy_count=43, sell_count=44, ...
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script directory to avoid relative path failures.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path: The resolved path to the data file.

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


class BollEMAStrategy(bt.Strategy):
    """Bollinger Bands + EMA combination trading strategy.

    This strategy implements a trend-following approach using Bollinger Bands
    for entry signals and EMA for trend confirmation. It trades both long and
    short positions with volatility-based filtering.

    Entry Conditions:
        Long (Buy):
            - Current close breaks above upper Bollinger Band
            - Previous close also above upper Band (consecutive break)
            - EMA is above middle band (uptrend confirmation)
            - Last 3 closes all above middle band (trend persistence)
            - Band width > boll_diff parameter (volatility filter)

        Short (Sell):
            - Current close breaks below lower Bollinger Band
            - Previous close also below lower Band (consecutive break)
            - EMA is below middle band (downtrend confirmation)
            - Last 3 closes all below middle band (trend persistence)
            - Band width > boll_diff parameter (volatility filter)

    Exit Conditions:
        Long Position:
            - Stop loss: Price drops by price_diff from entry
            - Trend change: EMA crosses below middle band

        Short Position:
            - Stop loss: Price rises by price_diff from entry
            - Trend change: EMA crosses above middle band

    Attributes:
        bar_num (int): Counter for number of bars processed by the strategy.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.
        sum_profit (float): Cumulative profit/loss from all completed trades.
        win_count (int): Number of profitable trades closed.
        loss_count (int): Number of unprofitable trades closed.
        trade_count (int): Total number of completed trades.
        marketposition (int): Current position state. 0=flat, 1=long, -1=short.
        last_price (float): Execution price of the most recent order.
        data0: Reference to the primary data feed.
        boll: Bollinger Bands indicator instance.
        ema: Exponential Moving Average indicator instance.

    Note:
        Position tracking uses manual state management (marketposition) rather
        than backtrader's built-in position() method to allow for more granular
        control over entry/exit logic.
    """

    params = (
        ("period_boll", 136),
        ("period_ema", 99),
        ("boll_diff", 0.5),    # Minimum Bollinger Band width for entry (volatility filter)
        ("price_diff", 0.3),   # Stop loss threshold from entry price
    )

    def log(self, txt, dt=None, force=False):
        """Log output function.

        Args:
            txt: Text message to log.
            dt: datetime object for the log entry. If None, uses current bar's datetime.
            force: If True, forces output regardless of other conditions.
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the BollEMA strategy.

        Sets up indicators, data references, and tracking variables for
        trade statistics and position management.

        Indicators created:
            - Bollinger Bands: period_boll (default 136) with standard deviation
            - EMA: period_ema (default 99) on close price
        """
        # Initialize statistical counters
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0
        self.trade_count = 0

        # Get data reference
        self.data0 = self.datas[0]

        # Create Bollinger Bands indicator with specified period
        self.boll = bt.indicators.BollingerBands(self.data0, period=self.p.period_boll)
        # Create EMA indicator for trend confirmation
        self.ema = bt.indicators.ExponentialMovingAverage(self.data0.close, period=self.p.period_ema)

        # Trading state variables
        self.marketposition = 0  # 0=flat, 1=long, -1=short
        self.last_price = 0

    def notify_trade(self, trade):
        """Handle trade completion events.

        Called by backtrader when a trade is closed. Updates win/loss statistics
        and cumulative profit tracking.

        Args:
            trade (backtrader.Trade): The trade object that has been completed.
                                     Contains PnL information and trade status.

        Note:
            Only processes closed trades (trade.isclosed == True).
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def notify_order(self, order):
        """Handle order status updates.

        Called by backtrader when order status changes. Tracks execution prices
        for stop-loss calculations.

        Args:
            order (backtrader.Order): The order object with updated status.
                                     Contains execution information when filled.

        Note:
            Only records price from Completed orders. Other statuses (Submitted,
            Accepted, Canceled, etc.) are ignored.
        """
        if order.status == order.Completed:
            self.last_price = order.executed.price

    def gt_last_mid(self):
        """Check if last 3 bars' close prices are above middle band.

        Verifies that the price has maintained position above the middle
        Bollinger Band for the previous 3 bars, indicating sustained uptrend.

        Returns:
            bool: True if all of the last 3 closes were above the middle band,
                  False otherwise.

        Note:
            Index notation: [-1]=previous bar, [-2]=2 bars ago, [-3]=3 bars ago.
        """
        data = self.data0
        return (data.close[-1] > self.boll.mid[-1] and
                data.close[-2] > self.boll.mid[-2] and
                data.close[-3] > self.boll.mid[-3])

    def lt_last_mid(self):
        """Check if last 3 bars' close prices are below middle band.

        Verifies that the price has maintained position below the middle
        Bollinger Band for the previous 3 bars, indicating sustained downtrend.

        Returns:
            bool: True if all of the last 3 closes were below the middle band,
                  False otherwise.

        Note:
            Index notation: [-1]=previous bar, [-2]=2 bars ago, [-3]=3 bars ago.
        """
        data = self.data0
        return (data.close[-1] < self.boll.mid[-1] and
                data.close[-2] < self.boll.mid[-2] and
                data.close[-3] < self.boll.mid[-3])

    def close_gt_up(self):
        """Check if close price is consecutively above upper band.

        Detects consecutive breakouts above the upper Bollinger Band,
        indicating strong upward momentum.

        Returns:
            bool: True if both current [0] and previous [-1] closes are above
                  the upper band, False otherwise.
        """
        data = self.data0
        return data.close[0] > self.boll.top[0] and data.close[-1] > self.boll.top[-1]

    def close_lt_dn(self):
        """Check if close price is consecutively below lower band.

        Detects consecutive breakouts below the lower Bollinger Band,
        indicating strong downward momentum.

        Returns:
            bool: True if both current [0] and previous [-1] closes are below
                  the lower band, False otherwise.
        """
        data = self.data0
        return data.close[0] < self.boll.bot[0] and data.close[-1] < self.boll.bot[-1]

    def next(self):
        """Execute trading logic for each bar.

        Main strategy logic called on each bar. Implements state machine
        with three states: flat (0), long (1), and short (-1).

        Flow:
            1. Increment bar counter
            2. If flat: Check entry conditions for long/short
            3. If long: Check exit conditions (stop loss or EMA crossover)
            4. If short: Check exit conditions (stop loss or EMA crossover)

        Entry logic uses full available cash (ignores position sizing for simplicity).

        Raises:
            None: All errors are handled by backtrader framework.
        """
        self.bar_num += 1

        data = self.data0
        up = self.boll.top[0]      # Upper band
        mid = self.boll.mid[0]      # Middle band (SMA)
        dn = self.boll.bot[0]      # Lower band
        ema = self.ema[0]          # EMA value
        diff = up - dn             # Band width (volatility measure)

        if self.marketposition == 0:
            # FLAT STATE: Check entry conditions
            # Long entry: price breakout + uptrend confirmation + volatility filter
            if self.close_gt_up() and ema > mid and self.gt_last_mid() and diff > self.p.boll_diff:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(data, size=size)
                    self.marketposition = 1
                    self.buy_count += 1

            # Short entry: price breakdown + downtrend confirmation + volatility filter
            if self.close_lt_dn() and ema < mid and self.lt_last_mid() and diff > self.p.boll_diff:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(data, size=size)
                    self.marketposition = -1
                    self.sell_count += 1

        elif self.marketposition == 1:
            # LONG STATE: Check exit conditions
            # Exit on stop loss (price drop) OR trend change (EMA crosses below mid)
            if self.last_price - data.close[0] > self.p.price_diff or ema <= mid:
                self.close()
                self.marketposition = 0
                self.sell_count += 1

        elif self.marketposition == -1:
            # SHORT STATE: Check exit conditions
            # Exit on stop loss (price rise) OR trend change (EMA crosses above mid)
            if data.close[0] - self.last_price > self.p.price_diff or ema >= mid:
                self.close()
                self.marketposition = 0
                self.buy_count += 1

    def stop(self):
        """Output statistics when strategy ends.

        Called by backtrader after backtesting completes. Calculates and prints
        comprehensive performance statistics including win rate and total profit.

        Statistics calculated:
            - Total trades (winners + losers)
            - Win rate percentage
            - Total profit/loss
            - Order counts
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_boll_ema_strategy():
    """Test the BollEMA Bollinger Bands + EMA strategy.

    This test function validates the BollEMA strategy implementation by running
    a historical backtest on Shanghai stock data and asserting expected results.

    Test Process:
        1. Load Shanghai stock 600000 data from CSV file
        2. Filter data for date range (2000-01-01 to 2022-12-31)
        3. Clean data by removing invalid prices (close <= 0)
        4. Create PandasData feed with OHLCV columns
        5. Initialize Cerebro with 100,000 starting capital
        6. Add BollEMAStrategy with parameters: period_boll=136, period_ema=99
        7. Attach performance analyzers (Sharpe, Returns, DrawDown, TradeAnalyzer)
        8. Run backtest
        9. Validate results against expected values

    Expected Results:
        - bar_num: 5280
        - buy_count: 43
        - sell_count: 44
        - win_count: 10
        - loss_count: 26
        - total_trades: 37
        - final_value: 705655.57
        - sharpe_ratio: 0.33646909650176043
        - annual_return: 0.09519461079565394
        - max_drawdown: 0.4537757234136652

    Raises:
        AssertionError: If any performance metric deviates from expected value.
        FileNotFoundError: If sh600000.csv data file cannot be located.

    Note:
        Test uses strict tolerance (1e-6) for most metrics, 1e-2 for final_value
        to account for floating-point precision differences.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading Shanghai stock data...")
    data_path = resolve_data_path("sh600000.csv")
    df = pd.read_csv(data_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')
    df = df.set_index('datetime')
    # Filter for test date range
    df = df[(df.index >= '2000-01-01') & (df.index <= '2022-12-31')]
    # Remove invalid data points
    df = df[df['close'] > 0]

    # Select required OHLCV columns
    df = df[['open', 'high', 'low', 'close', 'volume']]

    # Create data feed with column mapping
    data_feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,  # Using index as datetime
        open=0,
        high=1,
        low=2,
        close=3,
        volume=4,
        openinterest=-1,
    )
    cerebro.adddata(data_feed, name="SH600000")

    # Add strategy with specified parameters
    cerebro.addstrategy(BollEMAStrategy, period_boll=136, period_ema=99, boll_diff=0.5, price_diff=0.3)

    # Attach performance analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    print("Starting backtest...")
    results = cerebro.run()

    # Extract strategy results
    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results summary
    print("\n" + "=" * 50)
    print("BollEMA Bollinger Bands + EMA Strategy Backtest Results:")
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

    # Assert expected values with strict tolerances
    assert strat.bar_num == 5280
    assert strat.buy_count == 43, f"Expected buy_count=43, got {strat.buy_count}"
    assert strat.sell_count == 44, f"Expected sell_count=44, got {strat.sell_count}"
    assert strat.win_count == 10, f"Expected win_count=10, got {strat.win_count}"
    assert strat.loss_count == 26, f"Expected loss_count=26, got {strat.loss_count}"
    assert total_trades == 37, f"Expected total_trades=37, got {total_trades}"
    assert abs(final_value - 705655.57) < 1e-2, f"Expected final_value=705655.57, got {final_value}"
    assert abs(sharpe_ratio - 0.33646909650176043) < 1e-6, f"sharpe_ratio={sharpe_ratio} out of range"
    assert abs(annual_return - 0.09519461079565394) < 1e-6, f"annual_return={annual_return} out of range"
    assert abs(max_drawdown - 0.4537757234136652) < 1e-6, f"max_drawdown={max_drawdown} out of range"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("BollEMA Bollinger Bands + EMA Strategy Test")
    print("=" * 60)
    test_boll_ema_strategy()
