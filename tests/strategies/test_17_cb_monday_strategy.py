"""Test cases for convertible bond Friday high premium rate rotation strategy.

Tests the Friday rotation strategy using convertible bond data.
- Uses extended PandasData to load multi-contract convertible bond data (including premium rate)
- Every Friday, buys the 3 convertible bonds with highest premium rates, closes positions next Friday and rebalances
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
    """Extended Pandas data feed with premium rate field."""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
        ('premium_rate', 5),
    )
    lines = ('premium_rate',)


def clean_bond_data_with_premium():
    """Clean convertible bond data and return a dictionary of DataFrames with premium rates."""
    df = pd.read_csv(resolve_data_path('bond_merged_all_data.csv'))
    df.columns = ['symbol', 'bond_symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
                  'pure_bond_value', 'convert_value', 'pure_bond_premium_rate', 'convert_premium_rate']
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df[df['datetime'] > pd.to_datetime("2018-01-01")]

    datas = {}
    for symbol, data in df.groupby('symbol'):
        data = data.set_index('datetime')
        data = data.drop(['symbol', 'bond_symbol'], axis=1)
        # Keep OHLCV and premium rate
        data = data[['open', 'high', 'low', 'close', 'volume', 'convert_premium_rate']]
        data.columns = ['open', 'high', 'low', 'close', 'volume', 'premium_rate']
        data = data.dropna()
        datas[symbol] = data.astype("float")

    return datas


class ConvertibleBondFridayRotationStrategy(bt.Strategy):
    """Convertible bond Friday high premium rate rotation strategy.

    Every Friday:
    - Close existing positions
    - Buy the 3 convertible bonds with highest premium rates
    - Hold until next Friday
    """
    author = 'yunjinqi'
    params = (
        ("hold_num", 3),
    )

    def log(self, txt, dt=None):
        """Log information utility function."""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the convertible bond Friday rotation strategy.

        Sets up tracking variables for bar counting, trade statistics,
        and order management.
        """
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.data_order_dict = {}
        self.order_list = []

    def prenext(self):
        """Handle prenext phase by calling next() directly.

        This strategy executes trading logic from the first bar, so
        prenext delegates to next() without waiting for minimum period.
        """
        self.next()

    def next(self):
        """Execute main trading logic for each bar.

        On Fridays (weekday 5):
        1. Close all existing positions
        2. Select top 3 convertible bonds by premium rate
        3. Allocate 10% of portfolio value to each selected bond
        4. Track orders for future rebalancing

        The strategy uses index data as the primary data feed (self.datas[0])
        and convertible bond data as additional feeds (self.datas[1:]).
        """
        self.bar_num += 1
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])
        total_value = self.broker.get_value()
        available_cash = self.broker.get_cash()

        # If today is Friday, start placing orders to close existing positions and prepare new orders
        today = self.current_datetime.weekday() + 1

        if today == 5:
            # Close existing positions
            for data, order in self.order_list:
                size = self.getposition(data).size
                if size > 0:
                    self.close(data)
                    self.sell_count += 1
                if size == 0:
                    self.cancel(order)
            self.order_list = []

            # Collect currently tradable convertible bonds
            result = []
            for data in self.datas[1:]:
                data_datetime = bt.num2date(data.datetime[0])
                if data_datetime == self.current_datetime:
                    data_name = data._name
                    premium_rate = data.premium_rate[0]
                    result.append([data, premium_rate])

            # Sort by premium rate
            sorted_result = sorted(result, key=lambda x: x[1])

            # Buy the ones with highest premium rates
            for data, _ in sorted_result[-self.p.hold_num:]:
                close_price = data.close[0]
                total_value = self.broker.getvalue()
                plan_tobuy_value = 0.1 * total_value
                lots = 10 * int(plan_tobuy_value / (close_price * 10))
                if lots > 0:
                    order = self.buy(data, size=lots)
                    self.buy_count += 1
                    self.order_list.append([data, order])

    def notify_order(self, order):
        """Handle order status changes.

        Logs buy and sell orders when they are executed. Orders in
        Submitted or Accepted status are ignored until completion.

        Args:
            order: The order object with status information.
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

        Logs the profit/loss when a trade is closed.

        Args:
            trade: The trade object with execution details.
        """
        if trade.isclosed:
            self.log(f"Trade completed: {trade.getdataname()} pnl={trade.pnl:.2f}")

    def stop(self):
        """Log final statistics when backtesting completes.

        Outputs the total number of bars processed, buy orders executed,
        and sell orders executed.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


def test_cb_friday_rotation_strategy():
    """Test convertible bond Friday rotation strategy.

    Run backtest using convertible bond data.
    """
    cerebro = bt.Cerebro(stdstats=True)

    # Load index data
    print("Loading index data...")
    index_data = pd.read_csv(resolve_data_path('bond_index_000000.csv'))
    index_data.index = pd.to_datetime(index_data['datetime'])
    index_data = index_data[index_data.index > pd.to_datetime("2018-01-01")]
    index_data = index_data.drop(['datetime'], axis=1)
    # Add a premium_rate column with default value 0
    index_data['premium_rate'] = 0.0
    print(f"Index data range: {index_data.index[0]} to {index_data.index[-1]}, total {len(index_data)} bars")

    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name='000000')

    # Clean and load convertible bond data
    print("\nLoading convertible bond data...")
    datas = clean_bond_data_with_premium()
    print(f"Total convertible bonds: {len(datas)}")

    added_count = 0
    max_bonds = 30  # Limit the number of bonds to speed up testing
    for symbol, data in datas.items():
        if len(data) > 30:
            if added_count >= max_bonds:
                break
            feed = ExtendPandasFeed(dataname=data)
            cerebro.adddata(feed, name=symbol)
            added_count += 1

    print(f"Successfully added {added_count} convertible bond data feeds")

    # Set commission and initial capital
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.broker.setcash(1000000.0)

    # Add strategy
    cerebro.addstrategy(ConvertibleBondFridayRotationStrategy, hold_num=3)

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
    print("Convertible Bond Friday Rotation Strategy Backtest Results:")
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
    assert strat.buy_count == 1119, f"Expected buy_count=1119, got {strat.buy_count}"
    assert strat.sell_count == 1116, f"Expected sell_count=1116, got {strat.sell_count}"
    assert total_trades == 1117, f"Expected total_trades=1117, got {total_trades}"
    assert abs(sharpe_ratio-(-0.13455036625145408))<1e-6, f"Expected sharpe_ratio=-0.13455036625145442, got {sharpe_ratio}"
    assert abs(annual_return-0.005213988514988448)<1e-6, f"Expected annual_return=0.005213988514988448, got {annual_return}"
    assert abs(max_drawdown-0.134336302193658)<1e-6, f"Expected max_drawdown=0.134336302193658, got {max_drawdown}"
    assert abs(final_value - 1039666.6544150009)<1e-6, f"Expected final_value=1039666.6544150009, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Convertible Bond Friday High Premium Rate Rotation Strategy Test")
    print("=" * 60)
    test_cb_friday_rotation_strategy()