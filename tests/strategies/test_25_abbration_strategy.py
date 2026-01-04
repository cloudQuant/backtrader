"""Abbration 布林带突破策略测试用例

使用上证股票数据 sh600000.csv 测试布林带突破策略
- 使用 GenericCSVData 加载本地数据文件
- 通过 self.datas[0] 规范访问数据

参考来源: backtrader-example/strategies/abbration.py
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
    """根据脚本所在目录定位数据文件，避免相对路径读取失败"""
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

    raise FileNotFoundError(f"未找到数据文件: {filename}")


class AbbrationStrategy(bt.Strategy):
    """Abbration 布林带突破策略

    策略逻辑：
    - 价格突破布林带上轨时开多
    - 价格突破布林带下轨时开空
    - 价格回归布林带中轨时平仓
    
    使用数据：
    - datas[0]: 股票价格数据
    """

    params = (
        ("boll_period", 200),
        ("boll_mult", 2),
    )

    def log(self, txt, dt=None, force=False):
        """日志输出功能"""
        if not force:
            return
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        # 记录统计数据
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # 获取数据引用 - 通过 datas 列表规范访问
        self.data0 = self.datas[0]

        # 计算布林带指标
        self.boll_indicator = bt.indicators.BollingerBands(
            self.data0, period=self.p.boll_period, devfactor=self.p.boll_mult
        )

        # 保存交易状态
        self.marketposition = 0

    def notify_trade(self, trade):
        """交易完成通知"""
        if not trade.isclosed:
            return
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl
        self.log(f"交易完成: 毛利润={trade.pnl:.2f}, 净利润={trade.pnlcomm:.2f}, 累计={self.sum_profit:.2f}")

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"买入执行: 价格={order.executed.price:.2f}, 数量={order.executed.size}")
            else:
                self.log(f"卖出执行: 价格={order.executed.price:.2f}, 数量={order.executed.size}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"订单状态: {order.Status[order.status]}")

    def next(self):
        self.bar_num += 1

        data = self.data0
        top = self.boll_indicator.top
        bot = self.boll_indicator.bot
        mid = self.boll_indicator.mid

        # 开多: 价格从下向上突破上轨
        if self.marketposition == 0 and data.close[0] > top[0] and data.close[-1] < top[-1]:
            size = int(self.broker.getcash() / data.close[0])
            if size > 0:
                self.buy(data, size=size)
                self.marketposition = 1
                self.buy_count += 1

        # 开空: 价格从上向下突破下轨
        if self.marketposition == 0 and data.close[0] < bot[0] and data.close[-1] > bot[-1]:
            size = int(self.broker.getcash() / data.close[0])
            if size > 0:
                self.sell(data, size=size)
                self.marketposition = -1
                self.sell_count += 1

        # 平多: 价格从上向下穿越中轨
        if self.marketposition == 1 and data.close[0] < mid[0] and data.close[-1] > mid[-1]:
            self.close()
            self.marketposition = 0
            self.sell_count += 1

        # 平空: 价格从下向上穿越中轨
        if self.marketposition == -1 and data.close[0] > mid[0] and data.close[-1] < mid[-1]:
            self.close()
            self.marketposition = 0
            self.buy_count += 1

    def stop(self):
        """策略结束时输出统计"""
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_abbration_strategy():
    """测试 Abbration 布林带突破策略

    使用上证股票数据进行回测
    """
    # 创建 cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # 设置初始资金
    cerebro.broker.setcash(100000.0)

    # 加载数据 (datas[0])
    print("正在加载上证股票数据...")
    data_path = resolve_data_path("sh600000.csv")
    df = pd.read_csv(data_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')  # 按时间正序排列
    df = df.set_index('datetime')
    df = df[(df.index >= '2000-01-01') & (df.index <= '2022-12-31')]
    df = df[df['close'] > 0]  # 过滤无效数据
    
    # 重新排列列顺序以符合PandasData默认格式
    df = df[['open', 'high', 'low', 'close', 'volume']]
    
    data_feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,  # 使用索引作为日期
        open=0,
        high=1,
        low=2,
        close=3,
        volume=4,
        openinterest=-1,
    )
    cerebro.adddata(data_feed, name="SH600000")

    # 添加策略
    cerebro.addstrategy(
        AbbrationStrategy,
        boll_period=200,
        boll_mult=2,
    )

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
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # 打印结果
    print("\n" + "=" * 50)
    print("Abbration 布林带突破策略回测结果:")
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

    # 断言 - 确保策略正常运行
    assert strat.bar_num == 5216, f"Expected bar_num=5216, got {strat.bar_num}"
    assert strat.buy_count == 19, f"Expected buy_count=19, got {strat.buy_count}"
    assert strat.sell_count == 20, f"Expected sell_count=20, got {strat.sell_count}"
    assert strat.win_count == 9, f"Expected win_count=9, got {strat.win_count}"
    assert strat.loss_count == 6, f"Expected loss_count=6, got {strat.loss_count}"
    assert total_trades == 16, f"Expected total_trades=16, got {total_trades}"
    assert abs(final_value - 423916.71) < 0.01, f"Expected final_value=423916.71, got {final_value}"
    assert abs(sharpe_ratio - 0.2701748176643007) < 1e-6, f"Expected sharpe_ratio=0.2701748176643007, got {sharpe_ratio}"
    assert abs(annual_return - (0.06952761581010602)) < 1e-6, f"Expected annual_return=0.06952761581010602, got {annual_return}"
    assert abs(max_drawdown - 0.46515816375898594) < 1e-6, f"Expected max_drawdown=0.46515816375898594, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Abbration 布林带突破策略测试")
    print("=" * 60)
    test_abbration_strategy()
