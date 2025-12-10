"""止损订单策略测试用例

使用可转债指数数据 bond_index_000000.csv 测试止损订单功能
"""

import datetime
import os
from pathlib import Path

import numpy as np
import pandas as pd

import backtrader as bt
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


class StopOrderStrategy(Strategy):
    """止损订单策略

    策略逻辑：
    - 使用双均线交叉产生买入信号
    - 买入后同时设置止损单（stop loss）
    - 止损价格为买入价的一定比例
    """

    params = (
        ("short_period", 5),
        ("long_period", 20),
        ("stop_loss_pct", 0.03),  # 3%止损
    )

    def log(self, txt, dt=None, force=False):
        """log信息的功能"""
        if not force:
            return  # 默认不输出日志
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
        self.stop_count = 0  # 止损触发次数

        # 保存订单引用
        self.order = None
        self.stop_order = None
        self.buy_price = None

    def next(self):
        self.bar_num += 1

        # 如果有未完成的订单，等待
        if self.order:
            return

        # 如果有止损单在等待，也不要操作
        if self.stop_order:
            # 检查是否出现死叉，需要主动平仓
            if self.crossover < 0:
                self.cancel(self.stop_order)
                self.stop_order = None
                self.order = self.close()
                self.sell_count += 1
            return

        # 如果没有持仓，且出现金叉，则买入
        if not self.position:
            if self.crossover > 0:
                # 使用当前资金的90%买入
                cash = self.broker.get_cash()
                price = self.datas[0].close[0]
                size = int(cash * 0.9 / price)
                if size > 0:
                    self.order = self.buy(size=size)
                    self.buy_count += 1

    def stop(self):
        self.log(
            f"bar_num = {self.bar_num}, buy_count = {self.buy_count}, sell_count = {self.sell_count}, stop_count = {self.stop_count}"
        )

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    f"买入执行: 价格={order.executed.price:.2f}, 数量={order.executed.size:.0f}"
                )
                self.buy_price = order.executed.price

                # 买入成功后，设置止损单
                stop_price = self.buy_price * (1 - self.p.stop_loss_pct)
                self.log(f"设置止损单: 止损价={stop_price:.2f}")
                self.stop_order = self.sell(
                    size=order.executed.size, exectype=bt.Order.Stop, price=stop_price
                )
            else:
                self.log(
                    f"卖出执行: 价格={order.executed.price:.2f}, 数量={abs(order.executed.size):.0f}"
                )
                self.buy_price = None

                # 检查是否是止损单触发
                if order == self.stop_order:
                    self.stop_count += 1
                    self.log("止损单触发!")
                    self.stop_order = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"订单取消/保证金不足/拒绝: {order.status}")

        # 重置订单状态
        if self.stop_order is None or order.ref != self.stop_order.ref:
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"交易完成: 毛利润={trade.pnl:.2f}, 净利润={trade.pnlcomm:.2f}")


def load_index_data(filename: str = "bond_index_000000.csv") -> pd.DataFrame:
    """加载可转债指数数据"""
    df = pd.read_csv(resolve_data_path(filename))
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.dropna()
    df = df.astype("float")
    return df


def test_stop_order_strategy():
    """
    测试止损订单策略

    使用可转债指数数据 bond_index_000000.csv 进行回测
    """
    # 创建 cerebro
    cerebro = Cerebro(stdstats=True)

    # 添加策略
    cerebro.addstrategy(StopOrderStrategy, short_period=5, long_period=20, stop_loss_pct=0.03)

    # 加载数据
    print("正在加载可转债指数数据...")
    df = load_index_data("bond_index_000000.csv")
    print(f"数据范围: {df.index[0]} 至 {df.index[-1]}, 共 {len(df)} 条")

    # 添加数据
    feed = ExtendPandasFeed(dataname=df)
    cerebro.adddata(feed, name="bond_index")

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
    print(f"  stop_count: {strat.stop_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # 断言测试结果
    assert strat.bar_num == 4415, f"Expected bar_num=4415, got {strat.bar_num}"
    assert strat.buy_count == 4, f"Expected buy_count=4, got {strat.buy_count}"
    assert strat.sell_count == 1, f"Expected sell_count=1, got {strat.sell_count}"
    assert strat.stop_count == 3, f"Expected stop_count=3, got {strat.stop_count}"
    assert total_trades == 5, f"Expected total_trades=5, got {total_trades}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("止损订单策略测试")
    print("=" * 60)
    test_stop_order_strategy()
