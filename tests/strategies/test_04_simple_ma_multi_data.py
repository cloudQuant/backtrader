#!/usr/bin/env python

import backtrader as bt
"""
多数据源简单均线策略测试用例

使用可转债数据测试多资产均线交叉策略：
- 价格站上60日均线时买入
- 价格跌破60日均线时卖出
- 使用前100个可转债进行回测

使用方法:
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

# 获取数据目录
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(CURRENT_DIR)
DATA_DIR = os.path.join(TESTS_DIR, "datas")


# ============================================================
# 数据源定义
# ============================================================


class ExtendPandasFeed(PandasData):
    """扩展的Pandas数据源，添加可转债特有的字段"""

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
# 策略定义
# ============================================================


class SimpleMAMultiDataStrategy(bt.Strategy):
    """
    多数据源简单均线策略

    策略逻辑：
    - 价格站上60日均线时买入
    - 价格跌破60日均线时卖出
    - 第一个数据是指数，用于日期对齐，不参与交易
    """

    params = (
        ("period", 60),
        ("verbose", False),
    )

    def log(self, txt, dt=None):
        """日志输出"""
        if self.p.verbose:
            dt = dt or self.datas[0].datetime.date(0)
            print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

        # 为每个可转债创建均线指标（第一个数据是指数，不参与交易）
        self.stock_ma_dict = {}
        for idx, data in enumerate(self.datas[1:], start=1):
            ma = btind.SimpleMovingAverage(data.close, period=self.p.period)
            # 关键点：把指标挂到策略对象上，触发 LineSeries.__setattr__，
            # 这样 _owner 会从 MinimalOwner 修正为当前策略，
            # 并且被加入到策略的 _lineiterators 中，_next 才会驱动计算。
            setattr(self, f"ma_{data._name}", ma)
            self.stock_ma_dict[data._name] = ma

        # 保存现有持仓的股票订单
        self.position_dict = {}
        # 当前有交易的股票
        self.stock_dict = {}

    def prenext(self):
        self.next()

    def next(self):
        self.bar_num += 1

        # 当前的交易日
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")

        # 总的价值和现金
        total_value = self.broker.get_value()
        total_cash = self.broker.get_cash()

        # 第一个数据是指数，用于日期对齐，不参与交易
        # 循环所有的可转债，计算当日可交易的数目
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date == data_date:
                stock_name = data._name
                if stock_name not in self.stock_dict:
                    self.stock_dict[stock_name] = 1

        total_target_stock_num = len(self.stock_dict)
        if total_target_stock_num == 0:
            return

        # 现在持仓的股票数目
        total_holding_stock_num = len(self.position_dict)

        # 计算每个股票可用的资金
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

        # 循环可转债，执行交易逻辑
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date != data_date:
                continue

            # 使用 btind.SimpleMovingAverage 计算的均线
            ma_indicator = self.stock_ma_dict.get(data._name)
            if ma_indicator is None:
                continue

            # 指标长度不足，均线尚未稳定
            if len(ma_indicator) < self.p.period + 1:
                continue

            close = data.close[0]
            pre_close = data.close[-1]
            ma = ma_indicator[0]
            pre_ma = ma_indicator[-1]

            # 检查均线是否有效
            if ma <= 0 or pre_ma <= 0 or pd.isna(ma) or pd.isna(pre_ma):
                continue

            # 平多信号：价格跌破均线
            if pre_close > pre_ma and close < ma:
                if self.getposition(data).size > 0:
                    self.close(data)
                    self.sell_count += 1
                    if data._name in self.position_dict:
                        self.position_dict.pop(data._name)
                # 已经下单但订单未成交的情况
                if data._name in self.position_dict and self.getposition(data).size == 0:
                    order = self.position_dict[data._name]
                    self.cancel(order)
                    self.position_dict.pop(data._name)

            # 开多信号：价格站上均线，且无持仓
            if pre_close < pre_ma and close > ma:
                if self.getposition(data).size == 0 and data._name not in self.position_dict:
                    lots = now_value / data.close[0]
                    lots = int(lots / 10) * 10  # 可转债以10张为单位
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
            f"策略结束: bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}"
        )


# ============================================================
# 数据加载函数
# ============================================================


def load_index_data(csv_file):
    """加载指数数据"""
    df = pd.read_csv(csv_file)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.dropna()
    df = df.astype(float)
    return df


def load_bond_data_multi(csv_file, max_bonds=100):
    """
    加载多个可转债数据

    参数:
        csv_file: 合并的可转债数据CSV文件
        max_bonds: 最大加载的可转债数量

    返回:
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

    # 获取唯一的可转债代码
    bond_codes = df["BOND_CODE"].unique()[:max_bonds]

    result = {}
    for code in bond_codes:
        bond_df = df[df["BOND_CODE"] == code].copy()
        bond_df["datetime"] = pd.to_datetime(bond_df["datetime"])
        bond_df = bond_df.set_index("datetime")
        bond_df = bond_df.drop(["BOND_CODE", "BOND_SYMBOL"], axis=1)
        bond_df = bond_df.dropna()
        bond_df = bond_df.astype(float)

        # 只保留数据量足够的可转债（至少60个交易日）
        if len(bond_df) >= 60:
            result[str(code)] = bond_df

    return result


# ============================================================
# 回测运行函数
# ============================================================


def run_strategy(max_bonds=100, initial_cash=10000000.0, commission=0.0002, verbose=False):
    """
    运行多数据源均线策略回测

    参数:
        max_bonds: 最大可转债数量
        initial_cash: 初始资金
        commission: 手续费率
        verbose: 是否打印详细日志

    返回:
        tuple: (cerebro, results, metrics)
    """
    cerebro = bt.Cerebro()

    # 添加策略
    cerebro.addstrategy(SimpleMAMultiDataStrategy, period=60, verbose=verbose)

    # 加载指数数据（用于日期对齐）
    index_file = os.path.join(DATA_DIR, "bond_index_000000.csv")
    index_df = load_index_data(index_file)
    index_feed = ExtendPandasFeed(dataname=index_df)
    cerebro.adddata(index_feed, name="index")

    # 加载可转债数据
    bond_file = os.path.join(DATA_DIR, "bond_merged_all_data.csv")
    bond_data_dict = load_bond_data_multi(bond_file, max_bonds=max_bonds)

    print(f"加载了 {len(bond_data_dict)} 个可转债数据")

    for bond_code, bond_df in bond_data_dict.items():
        feed = ExtendPandasFeed(dataname=bond_df)
        cerebro.adddata(feed, name=bond_code)

    # 设置初始资金和手续费
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission, stocklike=True)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="total_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    # 运行回测
    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
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
# 测试配置
# ============================================================

_test_results = None


def get_test_results():
    """获取回测结果（缓存）"""
    global _test_results
    if _test_results is None:
        _test_results = run_strategy(
            max_bonds=30, initial_cash=10000000.0, commission=0.0002, verbose=False
        )
    return _test_results


# ============================================================
# Pytest 测试函数
# ============================================================


def test_simple_ma_multi_data_strategy():
    """测试多数据源均线策略"""
    cerebro, results, metrics = get_test_results()

    # 打印结果
    print("\n" + "=" * 60)
    print("回测结果:")
    print(f"  加载可转债数量: {metrics['bonds_loaded']}")
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

    # 断言测试结果
    # 整数值使用精确比较
    assert metrics["bonds_loaded"] == 30, f"Expected bonds_loaded=30, got {metrics['bonds_loaded']}"
    assert metrics["bar_num"] == 4434, f"Expected bar_num=4434, got {metrics['bar_num']}"
    assert metrics["buy_count"] == 463, f"Expected buy_count=463, got {metrics['buy_count']}"
    assert metrics["sell_count"] == 450, f"Expected sell_count=450, got {metrics['sell_count']}"
    assert metrics["total_trades"] == 460, f"Expected total_trades=460, got {metrics['total_trades']}"
    # 浮点值使用近似比较（允许小误差）
    assert abs(metrics["sharpe_ratio"] - 0.1920060395982071) < 1e-6, f"Expected sharpe_ratio=0.1920060395982071, got {metrics['sharpe_ratio']}"
    assert abs(metrics["max_drawdown"] - 17.7630) < 0.01, f"Expected max_drawdown=17.7630%, got {metrics['max_drawdown']}"
    assert abs(metrics["final_value"] - 14535803.03) < 1.0, f"Expected final_value=14535803.03, got {metrics['final_value']}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("多数据源简单均线策略测试")
    print("=" * 60)
    test_simple_ma_multi_data_strategy()
