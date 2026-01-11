"""Test cases for Keltner Channel multi-contract futures strategy.

Tests Keltner Channel breakout strategy using rebar futures multi-contract data.
- Uses PandasData to load multiple contract data.
- Keltner Channel upper/lower rail breakout signals + rollover logic.
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


class KeltnerStrategy(bt.Strategy):
    """Keltner Channel multi-contract futures strategy.

    Uses Keltner Channel breakout as entry signals.
    Supports rollover logic for contract expiration.
    """
    author = 'yunjinqi'
    params = (
        ("avg_period", 110),
        ("atr_multi", 3),
    )

    def log(self, txt, dt=None):
        """Log information with timestamp."""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        self.bar_num = 0
        self.current_date = None
        self.buy_count = 0
        self.sell_count = 0
        # Calculate Keltner Channel indicators
        self.middle_price = (self.datas[0].high + self.datas[0].low + self.datas[0].close) / 3
        self.middle_line = bt.indicators.SMA(self.middle_price, period=self.p.avg_period)
        self.atr = bt.indicators.AverageTrueRange(self.datas[0], period=self.p.avg_period)
        self.upper_line = self.middle_line + self.atr * self.p.atr_multi
        self.lower_line = self.middle_line - self.atr * self.p.atr_multi
        # Save which contract is currently being held
        self.holding_contract_name = None

    def prenext(self):
        # Futures data has thousands of bars, each futures contract has different trading dates,
        # so it won't naturally enter next. Need to call next function in each prenext.
        self.next()

    def next(self):
        # Each time it runs, increment bar_num and update trading date
        self.current_date = bt.num2date(self.datas[0].datetime[0])
        self.bar_num += 1
        data = self.datas[0]
        
        # Open positions, close existing positions first
        # Close long position
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size > 0 and data.close[0] < self.middle_line[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.sell_count += 1
            self.holding_contract_name = None
            
        # Close short position
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size < 0 and data.close[0] > self.middle_line[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.buy_count += 1
            self.holding_contract_name = None

        # Open long position
        if self.holding_contract_name is None and data.close[-1] < self.upper_line[-1] and data.close[0] > self.upper_line[0] and self.middle_line[0] > self.middle_line[-1]:
            dominant_contract = self.get_dominant_contract()
            if dominant_contract is not None:
                next_data = self.getdatabyname(dominant_contract)
                self.buy(next_data, size=1)
                self.buy_count += 1
                self.holding_contract_name = dominant_contract

        # Open short position
        if self.holding_contract_name is None and data.close[-1] > self.lower_line[-1] and data.close[0] < self.lower_line[0] and self.middle_line[0] < self.middle_line[-1]:
            dominant_contract = self.get_dominant_contract()
            if dominant_contract is not None:
                next_data = self.getdatabyname(dominant_contract)
                self.sell(next_data, size=1)
                self.sell_count += 1
                self.holding_contract_name = dominant_contract

        # Rollover to next contract
        if self.holding_contract_name is not None:
            dominant_contract = self.get_dominant_contract()
            # If a new dominant contract appears, start rollover
            if dominant_contract is not None and dominant_contract != self.holding_contract_name:
                # Next dominant contract
                next_data = self.getdatabyname(dominant_contract)
                # Current contract position size and data
                size = self.getpositionbyname(self.holding_contract_name).size
                data = self.getdatabyname(self.holding_contract_name)
                # Close old position
                self.close(data)
                # Open new position
                if size > 0:
                    self.buy(next_data, size=abs(size))
                if size < 0:
                    self.sell(next_data, size=abs(size))
                self.holding_contract_name = dominant_contract

    def get_dominant_contract(self):
        """Select the contract with the largest open interest as the dominant contract.

        Returns:
            str or None: The name of the dominant contract data, or None if no data available.
        """
        target_datas = []
        for data in self.datas[1:]:
            try:
                data_date = bt.num2date(data.datetime[0])
                if self.current_date == data_date:
                    target_datas.append([data._name, data.openinterest[0]])
            except:
                pass
        if not target_datas:
            return None
        target_datas = sorted(target_datas, key=lambda x: x[1])
        return target_datas[-1][0]

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: data_name:{order.p.data._name} price:{order.executed.price:.2f}")
            else:
                self.log(f"SELL: data_name:{order.p.data._name} price:{order.executed.price:.2f}")

    def notify_trade(self, trade):
        # Output information when a trade is completed
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
        if trade.isopen:
            self.log('open symbol is : {} , price : {}'.format(
                trade.getdataname(), trade.price))

    def stop(self):
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


def load_rb_multi_data(data_dir: str = "rb") -> dict:
    """Load rebar futures multi-contract data.

    Maintains the original data loading logic.

    Args:
        data_dir: Directory name containing the contract data files.

    Returns:
        dict: Dictionary mapping contract names to DataFrames.
    """
    data_kwargs = dict(
        fromdate=datetime.datetime(2019, 1, 1),  # Shorten date range to speed up testing
        todate=datetime.datetime(2020, 12, 31),
    )
    
    data_path = resolve_data_path(data_dir)
    file_list = os.listdir(data_path)
    
    # Sort file list for consistent ordering across platforms (Windows vs macOS)
    file_list = sorted(file_list, key=lambda x: x.lower())
    
    # Ensure rb99.csv is placed first as index data (case-insensitive for Windows)
    rb99_file = None
    for f in file_list:
        if f.lower() == "rb99.csv":
            rb99_file = f
            break
    if rb99_file:
        file_list.remove(rb99_file)
        file_list = [rb99_file] + file_list
    
    datas = {}
    for file in file_list:
        if not file.endswith('.csv'):
            continue
        name = file[:-4]
        df = pd.read_csv(data_path / file)
        # Only keep these columns from the data
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
        # Modify column names
        df.index = pd.to_datetime(df['datetime'])
        df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
        df = df[(df.index <= data_kwargs['todate']) & (df.index >= data_kwargs['fromdate'])]
        if len(df) == 0:
            continue
        datas[name] = df
    
    return datas


def test_keltner_strategy():
    """Test Keltner Channel multi-contract futures strategy.

    Performs backtesting using rebar futures multi-contract data.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Load multi-contract data
    print("Loading rebar futures multi-contract data...")
    datas = load_rb_multi_data("rb")
    print(f"Loaded {len(datas)} contract data files")

    # Load data using RbPandasFeed
    for name, df in datas.items():
        feed = RbPandasFeed(dataname=df)
        cerebro.adddata(feed, name=name)
        # Set contract trading information
        comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
        cerebro.broker.addcommissioninfo(comm, name=name)

    cerebro.broker.setcash(50000.0)

    # Add strategy
    cerebro.addstrategy(KeltnerStrategy)

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
    print("Keltner Channel Strategy Backtest Results:")
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
    assert strat.bar_num == 5540, f"Expected bar_num=5540, got {strat.bar_num}"
    assert strat.buy_count > 0, f"Expected buy_count > 0, got {strat.buy_count}"
    assert strat.sell_count > 0, f"Expected sell_count > 0, got {strat.sell_count}"
    assert total_trades > 0, f"Expected total_trades > 0, got {total_trades}"
    # Note: sharpe_ratio may vary slightly due to platform differences, using looser tolerance
    assert abs(sharpe_ratio - (-0.7248889123130405)) < 1e-6, f"Expected sharpe_ratio=-0.7248889123130405, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0015868610268626382)) < 1e-6, f"Expected annual_return=-0.0015868610268626382, got {annual_return}"
    assert abs(max_drawdown - 0.1856158167743111) < 1e-6, f"Expected max_drawdown=0.1856158167743111, got {max_drawdown}"
    assert abs(final_value - 49847.09399999999) < 0.01, f"Expected final_value=49847.09399999999, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Keltner Channel Multi-Contract Futures Strategy Test")
    print("=" * 60)
    test_keltner_strategy()