import backtrader as bt
"""双均线策略测试用例

使用债券数据 113013.csv 测试双均线交叉策略
"""

import datetime
import os
from pathlib import Path

import numpy as np
import pandas as pd

from backtrader.cerebro import Cerebro
from backtrader.strategy import Strategy
from backtrader.feeds import PandasData

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """根据脚本所在目录定位数据文件，避免相对路径读取失败"""
    search_paths = []

    # 1. 当前目录（tests/strategies）
    search_paths.append(BASE_DIR / filename)

    # 2. tests 目录以及项目根目录
    search_paths.append(BASE_DIR.parent / filename)
    repo_root = BASE_DIR.parent.parent
    search_paths.append(repo_root / filename)

    # 3. 常见的数据目录（examples、tests/datas）
    search_paths.append(repo_root / "examples" / filename)
    search_paths.append(repo_root / "tests" / "datas" / filename)

    # 4. 环境变量 BACKTRADER_DATA_DIR 指定的目录
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
    raise FileNotFoundError(f"未找到数据文件: {filename}. 已尝试路径: {searched}")


class ExtendPandasFeed(PandasData):
    """
    扩展的Pandas数据源，添加可转债特有的字段

    DataFrame结构（set_index后）：
    - 索引：datetime
    - 列0：open
    - 列1：high
    - 列2：low
    - 列3：close
    - 列4：volume
    - 列5：pure_bond_value
    - 列6：convert_value
    - 列7：pure_bond_premium_rate
    - 列8：convert_premium_rate
    """

    params = (
        ("datetime", None),  # datetime是索引，不是数据列
        ("open", 0),  # 第1列 -> 索引0
        ("high", 1),  # 第2列 -> 索引1
        ("low", 2),  # 第3列 -> 索引2
        ("close", 3),  # 第4列 -> 索引3
        ("volume", 4),  # 第5列 -> 索引4
        ("openinterest", -1),  # 不存在该列
        ("pure_bond_value", 5),  # 第6列 -> 索引5
        ("convert_value", 6),  # 第7列 -> 索引6
        ("pure_bond_premium_rate", 7),  # 第8列 -> 索引7
        ("convert_premium_rate", 8),  # 第9列 -> 索引8
    )

    # 定义扩展的数据线
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


class TwoMAStrategy(bt.Strategy):
    """双均线策略

    当短期均线上穿长期均线时买入，下穿时卖出
    """

    params = (
        ("short_period", 5),
        ("long_period", 20),
    )

    def log(self, txt, dt=None):
        """log信息的功能"""
        if dt is None:
            try:
                dt_val = self.datas[0].datetime[0]
                if dt_val > 0:
                    dt = bt.num2date(dt_val)
                else:
                    dt = None
            except (IndexError, ValueError):
                dt = None

        if dt:
            print("{}, {}".format(dt.isoformat(), txt))
        else:
            print("%s" % txt)

    def __init__(self):
        # 计算均线指标
        self.short_ma = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.short_period
        )
        self.long_ma = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.long_period
        )

        # 记录交叉信号
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

        # 记录bar数量
        self.bar_num = 0

        # 记录交易次数
        self.buy_count = 0
        self.sell_count = 0

    def next(self):
        self.bar_num += 1

        # 如果没有持仓，且出现金叉（短期均线上穿长期均线），则买入
        if not self.position:
            if self.crossover > 0:
                # 使用当前资金的90%买入
                cash = self.broker.get_cash()
                price = self.datas[0].close[0]
                size = int(cash * 0.9 / price)
                if size > 0:
                    self.buy(size=size)
                    self.buy_count += 1
        else:
            # 如果有持仓，且出现死叉（短期均线下穿长期均线），则卖出
            if self.crossover < 0:
                self.close()
                self.sell_count += 1

    def stop(self):
        self.log(
            f"bar_num = {self.bar_num}, buy_count = {self.buy_count}, sell_count = {self.sell_count}"
        )

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"买入: 价格={order.executed.price:.2f}, 数量={order.executed.size:.2f}")
            else:
                self.log(f"卖出: 价格={order.executed.price:.2f}, 数量={order.executed.size:.2f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"交易完成: 毛利润={trade.pnl:.2f}, 净利润={trade.pnlcomm:.2f}")


def load_bond_data(filename: str = "113013.csv") -> pd.DataFrame:
    """加载债券数据"""
    df = pd.read_csv(resolve_data_path(filename))
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
    df = df.astype("float")
    return df


def test_two_ma_strategy():
    """
    测试双均线策略

    使用债券数据 113013.csv 进行回测
    """
    # 创建 cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # 添加策略
    cerebro.addstrategy(TwoMAStrategy, short_period=5, long_period=20)

    # 加载数据
    print("正在加载债券数据...")
    df = load_bond_data("113013.csv")
    print(f"数据范围: {df.index[0]} 至 {df.index[-1]}, 共 {len(df)} 条")

    # 添加数据
    feed = ExtendPandasFeed(dataname=df)
    cerebro.adddata(feed, name="113013")

    # 设置佣金
    cerebro.broker.setcommission(commission=0.001)

    # 设置初始资金
    cerebro.broker.setcash(100000.0)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # 运行回测
    print("开始运行回测...")
    results = cerebro.run()

    # 获取结果
    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    max_drawdown = strat.analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # 打印结果
    print("\n" + "=" * 50)
    print("回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # 断言测试结果
    assert strat.bar_num == 1425, f"Expected bar_num=1425, got {strat.bar_num}"
    assert strat.buy_count == 52, f"Expected buy_count=52, got {strat.buy_count}"
    assert strat.sell_count == 51, f"Expected sell_count=51, got {strat.sell_count}"
    assert total_trades == 51, f"Expected total_trades=51, got {total_trades}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("双均线策略测试")
    print("=" * 60)
    test_two_ma_strategy()
