"""Test cases for convertible bond multi-factor intraday strategy.

Tests multi-factor intraday trading strategy using convertible bond data.
- Uses PandasData to load multi-contract convertible bond data
- Intraday strategy based on multiple factors: moving averages, time-weighted
  average price lines, trading volume, etc.
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
    """Locate data files based on the script directory to avoid relative path failures."""
    repo_root = BASE_DIR.parent.parent
    search_paths = [
        BASE_DIR / "datas" / filename,
        repo_root / "tests" / "datas" / filename,
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
    ]
    
    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Data file not found: {filename}")


class ExtendPandasFeed(bt.feeds.PandasData):
    """Extended Pandas data feed for convertible bond data."""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
    )


def clean_bond_data():
    """Clean convertible bond data and return a dictionary of DataFrames for multiple bonds."""
    df = pd.read_csv(resolve_data_path('bond_merged_all_data.csv'))
    df.columns = ['symbol', 'bond_symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
                  'pure_bond_value', 'convert_value', 'pure_bond_premium_rate', 'convert_premium_rate']
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df[df['datetime'] > pd.to_datetime("2018-01-01")]

    datas = {}
    for symbol, data in df.groupby('symbol'):
        data = data.set_index('datetime')
        data = data.drop(['symbol', 'bond_symbol'], axis=1)
        # Keep only ohlcv columns, use volume for openinterest (daily data)
        data = data[['open', 'high', 'low', 'close', 'volume']]
        data = data.dropna()
        datas[symbol] = data.astype("float")

    return datas


class ConvertibleBondIntradayStrategy(bt.Strategy):
    """Convertible bond multi-factor intraday strategy.

    Uses multiple factors for screening and trading:
    - Price > 20-period moving average
    - Price > time-weighted average price line
    - Price change between -1% and 1%
    - Volume < 4x of 30-period average volume
    - Moving average rising but slowing down
    """
    author = 'yunjinqi'
    params = (
        ("ma_period", 20),
        ("can_trade_num", 2),
    )

    def log(self, txt, dt=None):
        """Log information with timestamp."""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the convertible bond intraday strategy.

        Sets up tracking dictionaries for indicators, positions, and trading state
        for each convertible bond data feed. Calculates technical indicators including
        moving averages, volume averages, and lowest price points.
        """
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # Maximum number of convertible bonds that can be held simultaneously
        self.can_trade_num = self.p.can_trade_num
        # Calculate 20-period moving average for each convertible bond
        self.cb_ma_dict = {data._name: bt.indicators.SMA(data.close, period=self.p.ma_period) for data in self.datas[1:]}
        # Calculate average volume for the recent 30 periods
        self.cb_avg_volume_dict = {data._name: bt.indicators.SMA(data.volume, period=30) for data in self.datas[1:]}
        # Record previous day's closing price
        self.cb_pre_close_dict = {data._name: None for data in self.datas[1:]}
        # Record the bar number when opening a position
        self.cb_bar_num_dict = {data._name: None for data in self.datas[1:]}
        # Record the opening position price
        self.cb_open_position_price_dict = {data._name: None for data in self.datas[1:]}
        # Use the lowest point of the recent 20 periods as the previous low point
        self.cb_low_point_dict = {data._name: bt.indicators.Lowest(data.low, period=20) for data in self.datas[1:]}

    def prenext(self):
        """Handle prenext phase by delegating to next method.

        This allows the strategy to run logic even before minimum period
        requirements are met.
        """
        self.next()

    def next(self):
        """Execute main trading logic for each bar.

        Iterates through all convertible bond data feeds and implements
        multi-factor entry and exit logic:

        Entry conditions:
        - Price > 20-period moving average
        - Price change between -1% and +1%
        - Volume < 4x of 30-period average volume
        - Moving average rising but slowing down

        Exit conditions:
        - Position held for more than 10 bars
        - Price falls below 20-period low
        - Profit exceeds 3%
        - Data feed expires (no future data available)
        """
        self.bar_num += 1
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])

        for data in self.datas[1:]:
            data_datetime = bt.num2date(data.datetime[0])
            if data_datetime == self.current_datetime:
                data_name = data._name
                close_price = data.close[0]

                # Check if previous day's closing price exists
                pre_close = self.cb_pre_close_dict[data_name]
                if pre_close is None:
                    pre_close = data.open[0]
                    self.cb_pre_close_dict[data_name] = pre_close

                # Update closing price (direct update for daily data)
                self.cb_pre_close_dict[data_name] = close_price

                # Expiration closing logic
                position_size = self.getposition(data).size
                if position_size > 0:
                    try:
                        _ = data.open[2]
                    except:
                        self.close(data)
                        self.cb_bar_num_dict[data_name] = None
                        self.can_trade_num += 1

                # Prepare to close position
                open_bar_num = self.cb_bar_num_dict[data_name]
                if open_bar_num is not None:
                    # Close position if held for more than 10 bars
                    if open_bar_num < self.bar_num - 10:
                        self.close(data)
                        self.sell_count += 1
                        self.cb_bar_num_dict[data_name] = None
                        self.can_trade_num += 1

                open_bar_num = self.cb_bar_num_dict[data_name]
                if open_bar_num is not None:
                    # Close position if price falls below previous low point
                    low_point = self.cb_low_point_dict[data_name][0]
                    if close_price < low_point:
                        self.close(data)
                        self.sell_count += 1
                        self.cb_bar_num_dict[data_name] = None
                        self.can_trade_num += 1

                open_bar_num = self.cb_bar_num_dict[data_name]
                if open_bar_num is not None:
                    # Take profit if return exceeds 3%
                    open_position_price = self.cb_open_position_price_dict[data_name]
                    if open_position_price and close_price / open_position_price > 1.03:
                        self.close(data)
                        self.sell_count += 1
                        self.cb_bar_num_dict[data_name] = None
                        self.can_trade_num += 1

                # Prepare to open position
                ma_line = self.cb_ma_dict[data_name]
                ma_price = ma_line[0]
                if close_price > ma_price:
                    # Check if price change is between -1% and 1%
                    up_percent = close_price / pre_close
                    if up_percent > 0.99 and up_percent < 1.01:
                        # Check if volume is less than 4x of average volume
                        volume = data.volume[0]
                        avg_volume = self.cb_avg_volume_dict[data_name][0]
                        if avg_volume > 0 and volume < avg_volume * 4:
                            # Moving average rising but slowing down
                            if ma_line[0] > ma_line[-1] and ma_line[0] - ma_line[-1] < ma_line[-1] - ma_line[-2]:
                                open_bar_num = self.cb_bar_num_dict[data_name]
                                if self.can_trade_num > 0 and open_bar_num is None:
                                    total_value = self.broker.getvalue()
                                    plan_tobuy_value = 0.4 * total_value
                                    lots = int(plan_tobuy_value / close_price)
                                    if lots > 0:
                                        self.buy(data, size=lots)
                                        self.buy_count += 1
                                        self.can_trade_num -= 1
                                        self.cb_bar_num_dict[data_name] = self.bar_num
                                        try:
                                            self.cb_open_position_price_dict[data_name] = data.open[1]
                                        except:
                                            self.cb_open_position_price_dict[data_name] = close_price

    def notify_order(self, order):
        """Handle order status notifications.

        Args:
            order: The order object with status information.

        Logs buy/sell orders when they are completed. Orders that are
        submitted or accepted are ignored as they haven't filled yet.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: {order.p.data._name} price={order.executed.price:.2f}")
            else:
                self.log(f"SELL: {order.p.data._name} price={order.executed.price:.2f}")

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Args:
            trade: The trade object with profit/loss information.

        Logs the final profit/loss when a trade is closed.
        """
        if trade.isclosed:
            self.log(f"Trade completed: {trade.getdataname()} pnl={trade.pnl:.2f}")

    def stop(self):
        """Log final statistics when backtesting completes.

        Called after all data has been processed. Outputs the total
        number of bars processed and the count of buy/sell operations.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


def test_cb_intraday_strategy():
    """Test convertible bond multi-factor intraday strategy.

    Performs backtesting using convertible bond data.
    """
    cerebro = bt.Cerebro(stdstats=True)

    # Load index data
    print("Loading index data...")
    index_data = pd.read_csv(resolve_data_path('bond_index_000000.csv'))
    index_data.index = pd.to_datetime(index_data['datetime'])
    index_data = index_data[index_data.index > pd.to_datetime("2018-01-01")]
    index_data = index_data.drop(['datetime'], axis=1)
    print(f"Index data range: {index_data.index[0]} to {index_data.index[-1]}, total {len(index_data)} bars")

    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name='000000')

    # Clean and load convertible bond data
    print("\nLoading convertible bond data...")
    datas = clean_bond_data()
    print(f"Total {len(datas)} convertible bonds")

    added_count = 0
    max_bonds = 30  # Limit the number of bonds to speed up testing
    for symbol, data in datas.items():
        if len(data) > 30:
            if added_count >= max_bonds:
                break
            feed = ExtendPandasFeed(dataname=data)
            cerebro.adddata(feed, name=symbol)
            comm = ComminfoFuturesPercent(commission=0.0001, margin=0.1, mult=1)
            cerebro.broker.addcommissioninfo(comm, name=symbol)
            added_count += 1

    print(f"Successfully added {added_count} convertible bond data feeds")

    # Set initial capital
    cerebro.broker.setcash(1000000.0)

    # Add strategy
    cerebro.addstrategy(ConvertibleBondIntradayStrategy, ma_period=20, can_trade_num=2)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # Run backtest
    print("\nStarting backtest...")
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
    print("Convertible Bond Multi-Factor Intraday Strategy Backtest Results:")
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
    assert strat.bar_num == 1885, f"Expected bar_num=1885, got {strat.bar_num}"
    assert strat.buy_count == 300, f"Expected buy_count=300, got {strat.buy_count}"
    assert strat.sell_count == 294, f"Expected sell_count=294, got {strat.sell_count}"
    assert total_trades == 299, f"Expected total_trades=299, got {total_trades}"
    # assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"Expected sharpe_ratio=0.23032590904888126, got {sharpe_ratio}"
    assert abs(annual_return - (0.030084430622900046)) < 1e-6, f"Expected annual_return=0.030084430622900046, got {annual_return}"
    assert abs(max_drawdown - 0.17750189678557882) < 1e-6, f"Expected max_drawdown=0.17750189678557882, got {max_drawdown}"
    assert abs(final_value - 1248218.9149463978) < 0.01, f"Expected final_value=1248218.9149463978, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Convertible Bond Multi-Factor Intraday Strategy Test")
    print("=" * 60)
    test_cb_intraday_strategy()