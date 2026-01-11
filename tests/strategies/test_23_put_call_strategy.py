"""Put/Call 期权比率策略测试用例

使用 SPY 和 Put/Call 期权比率数据测试情绪驱动策略
- 使用 GenericCSVData 加载本地数据文件
- 通过 self.datas[0] 规范访问数据

参考来源: https://github.com/cloudQuant/sentiment-fear-and-greed.git
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

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


class SPYPutCallData(bt.feeds.GenericCSVData):
    """SPY + Put/Call 期权比率数据源
    
    CSV 格式:
    Date,Open,High,Low,Close,Adj Close,Volume,Put Call,Fear Greed,VIX
    """
    lines = ('put_call', 'fear_greed', 'vix')

    params = (
        ('dtformat', '%Y-%m-%d'),
        ('datetime', 0),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 6),
        ('openinterest', -1),
        ('put_call', 7),
        ('fear_greed', 8),
        ('vix', 9),
    )


class PutCallStrategy(bt.Strategy):
    """Put/Call 期权比率策略

    策略逻辑：
    - 当 Put/Call > 1 (看跌期权多于看涨，市场恐慌) 时买入
    - 当 Put/Call < 0.45 (看涨期权远多于看跌，市场过度乐观) 时卖出
    
    使用数据：
    - datas[0]: SPY 价格数据 + Put/Call 指标
    """

    params = (
        ("high_threshold", 1.0),   # 高阈值，高于此值买入（恐慌）
        ("low_threshold", 0.45),   # 低阈值，低于此值卖出（贪婪）
    )

    def log(self, txt, dt=None, force=False):
        """日志输出功能"""
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
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
        self.put_call = self.data0.put_call
        self.close = self.data0.close

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

        # 计算可买入数量
        size = int(self.broker.getcash() / self.close[0])

        # Put/Call 高时买入（市场恐慌）
        if self.put_call[0] > self.p.high_threshold and not self.position:
            if size > 0:
                self.buy(size=size)
                self.buy_count += 1

        # Put/Call 低时卖出（市场过度乐观）
        if self.put_call[0] < self.p.low_threshold and self.position.size > 0:
            self.sell(size=self.position.size)
            self.sell_count += 1

    def stop(self):
        """策略结束时输出统计"""
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_put_call_strategy():
    """测试 Put/Call 期权比率策略

    使用 SPY 和 Put/Call 数据进行回测
    """
    # 创建 cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # 设置初始资金
    cerebro.broker.setcash(100000.0)

    # 加载数据 (datas[0])
    print("正在加载 SPY + Put/Call 数据...")
    data_path = resolve_data_path("spy-put-call-fear-greed-vix.csv")
    data_feed = SPYPutCallData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2011, 1, 1),
        todate=datetime.datetime(2021, 12, 31),
    )
    cerebro.adddata(data_feed, name="SPY")

    # 添加策略
    cerebro.addstrategy(
        PutCallStrategy,
        high_threshold=1.0,
        low_threshold=0.45,
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
    print("Put/Call 期权比率策略回测结果:")
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
    assert strat.bar_num == 2445, f"Expected bar_num=2445, got {strat.bar_num}"
    assert strat.buy_count == 6, f"Expected buy_count=6, got {strat.buy_count}"
    assert strat.sell_count == 3, f"Expected sell_count=3, got {strat.sell_count}"
    assert strat.win_count == 3, f"Expected win_count=3, got {strat.win_count}"
    assert strat.loss_count == 0, f"Expected loss_count=0, got {strat.loss_count}"
    assert total_trades == 3, f"Expected total_trades=3, got {total_trades}"
    assert abs(sharpe_ratio - 0.8266766851573092) < 1e-6, f"Expected sharpe_ratio=0.8266766851573092, got {sharpe_ratio}"
    assert abs(annual_return - (0.09446114583761168)) < 1e-6, f"Expected annual_return=0.09446114583761168, got {annual_return}"
    assert abs(max_drawdown - 0.24769723055528914) < 1e-6, f"Expected max_drawdown=0.24769723055528914, got {max_drawdown}"
    assert abs(final_value - 240069.35) < 0.01, f"Expected final_value=240069.35, got {final_value}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("Put/Call 期权比率策略测试")
    print("=" * 60)
    test_put_call_strategy()
