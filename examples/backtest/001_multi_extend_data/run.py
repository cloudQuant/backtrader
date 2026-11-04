#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Strategy runner - convertible-bond dual-low factor across multiple products."""

import os
import datetime
import yaml
from pathlib import Path

import backtrader as bt
import pandas as pd
from backtrader.comminfo import ComminfoFuturesPercent
from backtrader.utils.paths import data_path

# Import the strategy class
from strategy_multi_extend_data import BondConvertTwoFactor, ExtendPandasFeed

BASE_DIR = Path(__file__).resolve().parent


def load_config():
    """Load configuration from config.yaml."""
    config_path = BASE_DIR / "config.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_index_data(csv_file):
    """Load the index data."""
    df = pd.read_csv(csv_file)
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
    df = df.astype(float)
    return df


def clean_data():
    """Clean and prepare the convertible-bond data."""
    df = pd.read_csv(data_path("tests/datas/bond_merged_all_data.csv"))
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
    df = df[df["datetime"] > pd.to_datetime("2018-01-01")]

    datas = {}
    for symbol, data in df.groupby("symbol", sort=True):
        data = data.set_index("datetime")
        data = data.drop(["symbol", "bond_symbol"], axis=1)
        data = data.dropna()
        datas[symbol] = data.astype("float")

    return datas


def run(max_bonds=None):
    """Run the strategy backtest."""
    config = load_config()

    # Create the Cerebro engine
    cerebro = bt.Cerebro(stdstats=True)

    # Add the strategy (params loaded from config)
    params = config.get('params', {})
    cerebro.addstrategy(BondConvertTwoFactor, **params)




    # Add the index data
    print("Loading index data...")
    index_data = pd.read_csv(data_path("tests/datas/bond_index_000000.csv"))
    index_data.index = pd.to_datetime(index_data["datetime"])
    index_data = index_data[index_data.index > pd.to_datetime("2023-01-01")]
    index_data = index_data.drop(["datetime"], axis=1)
    print(f"Index data range: {index_data.index[0]} to {index_data.index[-1]}, total {len(index_data)} records")

    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name="000000")

    # Clean the data and add the convertible-bond feeds
    print("\nLoading convertible bond data...")
    datas = clean_data()
    print(f"Total {len(datas)} convertible bonds")

    added_count = 0
    for symbol, data in datas.items():
        if len(data) > 30:
            if max_bonds is not None and added_count >= max_bonds:
                break

            feed = ExtendPandasFeed(dataname=data)
            cerebro.adddata(feed, name=symbol)
            added_count += 1
            if added_count > 10:
                break

            # Add trading commissions
            comm = ComminfoFuturesPercent(commission=0.0001, margin=0.1, mult=1)
            cerebro.broker.addcommissioninfo(comm, name=symbol)

            if added_count % 100 == 0:
                print(f"Added {added_count} convertible bonds...")

    print(f"\nSuccessfully added {added_count} convertible bonds")

    # Set the starting cash
    bt_config = config.get('backtest', {})
    cerebro.broker.setcash(bt_config.get('initial_cash', 100000000.0))

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")
    # Logging configuration
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_bars=True,
        log_indicators=True,       # Include strategy indicators in the data log
        log_dir=log_dir,
        log_format='text',         # 'json' (default) or 'text'
        # MySQL disabled by default - uncomment to enable
        # mysql_enabled=True,
        # mysql_host='localhost',
        # mysql_port=3306,
        # mysql_user='root',
        # mysql_password='your_password',
        # mysql_database='backtrder_web',
        # mysql_table_prefix='bt',
    )

    # Run the backtest
    print("\nStarting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Collect the results
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis()["sharperatio"]
    annual_return = strat.analyzers.my_returns.get_analysis()["rnorm"]
    max_drawdown = strat.analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_num = strat.analyzers.my_trade_analyzer.get_analysis()["total"]["total"]

    # Print the results
    print("\n" + "=" * 60)
    print("Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  trade_num: {trade_num}")
    print("=" * 60)

    print("\nBacktest completed.")
    return results


if __name__ == "__main__":
    print("=" * 60)
    print("Convertible Bond Double-Low Strategy Backtest")
    print("=" * 60)
    try:
        run(max_bonds=None)
    except FileNotFoundError as exc:
        print(f"BLOCKED: {exc}; provide the required local configuration and tests/datas fixtures")
        raise SystemExit(2)
