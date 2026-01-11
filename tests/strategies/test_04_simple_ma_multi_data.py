#!/usr/bin/env python

import backtrader as bt
"""
Test case for multi-data source simple moving average strategy

Tests a multi-asset moving average crossover strategy using convertible bond data:
- Buy when price rises above 60-day moving average
- Sell when price falls below 60-day moving average
- Backtest using the first 100 convertible bonds

Usage:
    python tests/strategies/test_04_simple_ma_multi_data.py
    pytest tests/strategies/test_04_simple_ma_multi_data.py -v
"""

import os
import warnings

import pandas as pd

from backtrader.cerebro import Cerebro
from backtrader.strategy import Strategy
from backtrader.feeds import PandasData
import backtrader.indicators as btind

warnings.filterwarnings("ignore")

# Get data directory
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(CURRENT_DIR)
DATA_DIR = os.path.join(TESTS_DIR, "datas")


# ============================================================
# Data source definitions
# ============================================================


class ExtendPandasFeed(PandasData):
    """Extended Pandas data feed with convertible bond-specific fields"""

    params = (
        ("datetime", None),
        ("open", 0),
        ("high", 1),
        ("low", 2),
        ("close", 3),
        ("volume", 4),
        ("openinterest", -1),
        ("pure_bond_value", 5),
        ("convert_value", 6),
        ("pure_bond_premium_rate", 7),
        ("convert_premium_rate", 8),
    )
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


# ============================================================
# Strategy definitions
# ============================================================


class SimpleMAMultiDataStrategy(bt.Strategy):
    """
    Multi-data source simple moving average strategy

    Strategy logic:
    - Buy when price rises above 60-day moving average
    - Sell when price falls below 60-day moving average
    - First data is index used for date alignment, not for trading
    """

    params = (
        ("period", 60),
        ("verbose", False),
    )

    def log(self, txt, dt=None):
        """Log output"""
        if self.p.verbose:
            dt = dt or self.datas[0].datetime.date(0)
            print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

        # Create moving average indicators for each convertible bond (first data is index, not for trading)
        self.stock_ma_dict = {}
        for idx, data in enumerate(self.datas[1:], start=1):
            ma = btind.SimpleMovingAverage(data.close, period=self.p.period)
            # Key point: Attach indicator to strategy object to trigger LineSeries.__setattr__,
            # which corrects _owner from MinimalOwner to current strategy,
            # and adds it to strategy's _lineiterators so _next drives calculation.
            setattr(self, f"ma_{data._name}", ma)
            self.stock_ma_dict[data._name] = ma

        # Save orders for existing positions
        self.position_dict = {}
        # Stocks currently being traded
        self.stock_dict = {}

    def prenext(self):
        self.next()

    def next(self):
        self.bar_num += 1

        # Current trading day
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")

        # Total value and cash
        total_value = self.broker.get_value()
        total_cash = self.broker.get_cash()

        # First data is index used for date alignment, not for trading
        # Loop through all convertible bonds to count tradable ones for the day
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date == data_date:
                stock_name = data._name
                if stock_name not in self.stock_dict:
                    self.stock_dict[stock_name] = 1

        total_target_stock_num = len(self.stock_dict)
        if total_target_stock_num == 0:
            return

        # Number of stocks currently holding
        total_holding_stock_num = len(self.position_dict)

        # Calculate available funds for each stock
        if total_holding_stock_num < total_target_stock_num:
            remaining = total_target_stock_num - total_holding_stock_num
            if remaining > 0:
                now_value = total_cash / remaining
                stock_value = total_value / total_target_stock_num
                now_value = min(now_value, stock_value)
            else:
                now_value = total_value / total_target_stock_num
        else:
            now_value = total_value / total_target_stock_num

        # Loop through convertible bonds and execute trading logic
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date != data_date:
                continue

            # Moving average calculated using btind.SimpleMovingAverage
            ma_indicator = self.stock_ma_dict.get(data._name)
            if ma_indicator is None:
                continue

            # Indicator length insufficient, moving average not yet stable
            if len(ma_indicator) < self.p.period + 1:
                continue

            close = data.close[0]
            pre_close = data.close[-1]
            ma = ma_indicator[0]
            pre_ma = ma_indicator[-1]

            # Check if moving average is valid
            if ma <= 0 or pre_ma <= 0 or pd.isna(ma) or pd.isna(pre_ma):
                continue

            # Close long signal: price falls below moving average
            if pre_close > pre_ma and close < ma:
                if self.getposition(data).size > 0:
                    self.close(data)
                    self.sell_count += 1
                    if data._name in self.position_dict:
                        self.position_dict.pop(data._name)
                # Order placed but not yet filled
                if data._name in self.position_dict and self.getposition(data).size == 0:
                    order = self.position_dict[data._name]
                    self.cancel(order)
                    self.position_dict.pop(data._name)

            # Open long signal: price rises above moving average and no position
            if pre_close < pre_ma and close > ma:
                if self.getposition(data).size == 0 and data._name not in self.position_dict:
                    lots = now_value / data.close[0]
                    lots = int(lots / 10) * 10  # Convertible bonds traded in units of 10
                    if lots > 0:
                        order = self.buy(data, size=lots)
                        self.position_dict[data._name] = order
                        self.buy_count += 1

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Rejected:
            self.log(f"Rejected: {order.p.data._name}")
        elif order.status == order.Margin:
            self.log(f"Margin: {order.p.data._name}")
        elif order.status == order.Cancelled:
            self.log(f"Cancelled: {order.p.data._name}")
        elif order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: {order.p.data._name} @ {order.executed.price:.2f}")
            else:
                self.log(f"SELL: {order.p.data._name} @ {order.executed.price:.2f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(
                f"Trade closed: {trade.getdataname()}, PnL: {trade.pnl:.2f}, Net: {trade.pnlcomm:.2f}"
            )
        if trade.isopen:
            self.log(f"Trade opened: {trade.getdataname()} @ {trade.price:.2f}")

    def stop(self):
        print(
            f"Strategy ended: bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}"
        )


# ============================================================
# Data loading functions
# ============================================================


def load_index_data(csv_file):
    """Load index data"""
    df = pd.read_csv(csv_file)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.dropna()
    df = df.astype(float)
    return df


def load_bond_data_multi(csv_file, max_bonds=100):
    """
    Load multiple convertible bond data

    Args:
        csv_file: Merged convertible bond data CSV file
        max_bonds: Maximum number of convertible bonds to load

    Returns:
        dict: {bond_code: DataFrame}
    """
    df = pd.read_csv(csv_file)
    df.columns = [
        "BOND_CODE",
        "BOND_SYMBOL",
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

    # Get unique convertible bond codes
    bond_codes = df["BOND_CODE"].unique()[:max_bonds]

    result = {}
    for code in bond_codes:
        bond_df = df[df["BOND_CODE"] == code].copy()
        bond_df["datetime"] = pd.to_datetime(bond_df["datetime"])
        bond_df = bond_df.set_index("datetime")
        bond_df = bond_df.drop(["BOND_CODE", "BOND_SYMBOL"], axis=1)
        bond_df = bond_df.dropna()
        bond_df = bond_df.astype(float)

        # Only keep convertible bonds with sufficient data (at least 60 trading days)
        if len(bond_df) >= 60:
            result[str(code)] = bond_df

    return result


# ============================================================
# Backtest execution functions
# ============================================================


def run_strategy(max_bonds=100, initial_cash=10000000.0, commission=0.0002, verbose=False):
    """
    Run multi-data source moving average strategy backtest

    Args:
        max_bonds: Maximum number of convertible bonds
        initial_cash: Initial capital
        commission: Commission rate
        verbose: Whether to print detailed logs

    Returns:
        tuple: (cerebro, results, metrics)
    """
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(SimpleMAMultiDataStrategy, period=60, verbose=verbose)

    # Load index data (used for date alignment)
    index_file = os.path.join(DATA_DIR, "bond_index_000000.csv")
    index_df = load_index_data(index_file)
    index_feed = ExtendPandasFeed(dataname=index_df)
    cerebro.adddata(index_feed, name="index")

    # Load convertible bond data
    bond_file = os.path.join(DATA_DIR, "bond_merged_all_data.csv")
    bond_data_dict = load_bond_data_multi(bond_file, max_bonds=max_bonds)

    print(f"Loaded {len(bond_data_dict)} convertible bond data files")

    for bond_code, bond_df in bond_data_dict.items():
        feed = ExtendPandasFeed(dataname=bond_df)
        cerebro.adddata(feed, name=bond_code)

    # Set initial capital and commission
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission, stocklike=True)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="total_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    final_value = cerebro.broker.getvalue()
    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    returns_analysis = strat.analyzers.returns.get_analysis()
    drawdown_analysis = strat.analyzers.drawdown.get_analysis()
    trades_analysis = strat.analyzers.trades.get_analysis()

    total_trades = trades_analysis.get("total", {}).get("total", 0)
    sharpe_ratio = sharpe_analysis.get("sharperatio")
    annual_return = returns_analysis.get("rnorm")
    max_drawdown = (
        drawdown_analysis["max"]["drawdown"] if drawdown_analysis["max"]["drawdown"] else 0
    )

    metrics = {
        "bar_num": strat.bar_num,
        "buy_count": strat.buy_count,
        "sell_count": strat.sell_count,
        "final_value": final_value,
        "total_profit": final_value - initial_cash,
        "return_rate": (final_value / initial_cash - 1) * 100,
        "sharpe_ratio": sharpe_ratio,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "total_trades": total_trades,
        "initial_cash": initial_cash,
        "bonds_loaded": len(bond_data_dict),
    }

    return cerebro, results, metrics


# ============================================================
# Test configuration
# ============================================================

_test_results = None


def get_test_results():
    """Get backtest results (cached)"""
    global _test_results
    if _test_results is None:
        _test_results = run_strategy(
            max_bonds=30, initial_cash=10000000.0, commission=0.0002, verbose=False
        )
    return _test_results


# ============================================================
# Pytest test functions
# ============================================================


def test_simple_ma_multi_data_strategy():
    """Test multi-data source moving average strategy"""
    cerebro, results, metrics = get_test_results()

    # Print results
    print("\n" + "=" * 60)
    print("Backtest results:")
    print(f"  Bonds loaded: {metrics['bonds_loaded']}")
    print(f"  bar_num: {metrics['bar_num']}")
    print(f"  buy_count: {metrics['buy_count']}")
    print(f"  sell_count: {metrics['sell_count']}")
    print(f"  total_trades: {metrics['total_trades']}")
    print(f"  final_value: {metrics['final_value']:.2f}")
    print(f"  total_profit: {metrics['total_profit']:.2f}")
    print(f"  return_rate: {metrics['return_rate']:.4f}%")
    print(f"  sharpe_ratio: {metrics['sharpe_ratio']}")
    print(f"  annual_return: {metrics['annual_return']}")
    print(f"  max_drawdown: {metrics['max_drawdown']:.4f}%")
    print("=" * 60)

    # Assert test results
    # Integer values use exact comparison
    assert metrics["bonds_loaded"] == 30, f"Expected bonds_loaded=30, got {metrics['bonds_loaded']}"
    assert metrics["bar_num"] == 4434, f"Expected bar_num=4434, got {metrics['bar_num']}"
    assert metrics["buy_count"] == 463, f"Expected buy_count=463, got {metrics['buy_count']}"
    assert metrics["sell_count"] == 450, f"Expected sell_count=450, got {metrics['sell_count']}"
    assert metrics["total_trades"] == 460, f"Expected total_trades=460, got {metrics['total_trades']}"
    # Float values use approximate comparison (allow small errors)
    assert abs(metrics["sharpe_ratio"] - 0.1920060395982071) < 1e-6, f"Expected sharpe_ratio=0.1920060395982071, got {metrics['sharpe_ratio']}"
    assert abs(metrics["max_drawdown"] - 17.7630) < 0.01, f"Expected max_drawdown=17.7630%, got {metrics['max_drawdown']}"
    assert abs(metrics["final_value"] - 14535803.03) < 1.0, f"Expected final_value=14535803.03, got {metrics['final_value']}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Multi-data source simple moving average strategy test")
    print("=" * 60)
    test_simple_ma_multi_data_strategy()
