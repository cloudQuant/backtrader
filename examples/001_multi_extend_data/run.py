#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""策略运行脚本 - 可转债双低因子多品种策略"""

import os
import datetime
import yaml
from pathlib import Path

import backtrader as bt
import pandas as pd
from backtrader.comminfo import ComminfoFuturesPercent

# 导入策略类
from strategy_multi_extend_data import BondConvertTwoFactor, ExtendPandasFeed

BASE_DIR = Path(__file__).resolve().parent


def load_config():
    """从config.yaml加载配置"""
    config_path = BASE_DIR / "config.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def resolve_data_path(filename: str) -> Path:
    """查找数据文件路径"""
    search_paths = []

    # 1. Current directory
    search_paths.append(BASE_DIR / filename)

    # 2. tests directory and project root directory
    search_paths.append(BASE_DIR.parent / filename)
    repo_root = BASE_DIR.parent.parent
    search_paths.append(repo_root / filename)

    # 3. Common data directories
    search_paths.append(repo_root / "datas" / filename)
    search_paths.append(repo_root / "examples" / filename)
    search_paths.append(repo_root / "tests" / "datas" / filename)

    # 4. Directory specified by environment variable
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


def load_index_data(csv_file):
    """加载指数数据"""
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
    """清洗并准备可转债数据"""
    df = pd.read_csv(resolve_data_path("bond_merged_all_data.csv"))
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
    """运行策略回测"""
    config = load_config()

    # 创建cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # 添加策略（从config加载参数）
    params = config.get('params', {})
    cerebro.addstrategy(BondConvertTwoFactor, **params)




    # 添加指数数据
    print("Loading index data...")
    index_data = pd.read_csv(resolve_data_path("bond_index_000000.csv"))
    index_data.index = pd.to_datetime(index_data["datetime"])
    index_data = index_data[index_data.index > pd.to_datetime("2023-01-01")]
    index_data = index_data.drop(["datetime"], axis=1)
    print(f"Index data range: {index_data.index[0]} to {index_data.index[-1]}, total {len(index_data)} records")

    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name="000000")

    # 清洗数据并添加可转债数据
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

            # 添加交易手续费
            comm = ComminfoFuturesPercent(commission=0.0001, margin=0.1, mult=1)
            cerebro.broker.addcommissioninfo(comm, name=symbol)

            if added_count % 100 == 0:
                print(f"Added {added_count} convertible bonds...")

    print(f"\nSuccessfully added {added_count} convertible bonds")

    # 添加资金
    bt_config = config.get('backtest', {})
    cerebro.broker.setcash(bt_config.get('initial_cash', 100000000.0))

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")
    # 日志配置
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_data=True,
        log_indicators=True,       # 在data日志中包含策略指标
        log_dir=log_dir,
        log_file_enabled=True,
        file_format='log',         # 默认log(tab分隔)，也可选'csv'
        # MySQL disabled by default - uncomment to enable
        # mysql_enabled=True,
        # mysql_host='localhost',
        # mysql_port=3306,
        # mysql_user='root',
        # mysql_password='your_password',
        # mysql_database='backtrder_web',
        # mysql_table_prefix='bt',
    )

    # 运行回测
    print("\nStarting backtest...")
    results = cerebro.run()
    strat = results[0]

    # 获取结果
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis()["sharperatio"]
    annual_return = strat.analyzers.my_returns.get_analysis()["rnorm"]
    max_drawdown = strat.analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_num = strat.analyzers.my_trade_analyzer.get_analysis()["total"]["total"]

    # 打印结果
    print("\n" + "=" * 60)
    print("Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  trade_num: {trade_num}")
    print("=" * 60)

    # **关键**：与原test文件完全相同的断言
    assert strat.bar_num == 1885, f"Expected bar_num=1885, got {strat.bar_num}"
    assert trade_num == 12, f"Expected trade_num=12, got {trade_num}"
    assert abs(sharpe_ratio - (-6.232087920949364)) < 1e-6, f"Expected sharpe_ratio=-6.232087920949364, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0006854281197833842)) < 1e-6, f"Expected annual_return=-0.0006854281197833842, got {annual_return}"
    assert abs(max_drawdown - 0.005450401808403724) < 1e-6, f"Expected max_drawdown=0.005450401808403724, got {max_drawdown}"

    print("\nAll tests passed!")
    return results


if __name__ == "__main__":
    print("=" * 60)
    print("Convertible Bond Double-Low Strategy Backtest")
    print("=" * 60)
    run(max_bonds=None)
