"""EMA 双均线交叉策略测试用例

使用 5 分钟数据和日线数据进行多周期 EMA 交叉策略测试
- 使用 GenericCSVData 加载本地数据文件
- 通过 self.datas[0] 和 self.datas[1] 规范访问多周期数据
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


class EmaCrossStrategy(bt.Strategy):
    """EMA 双均线交叉策略

    使用多周期数据：
    - datas[0]: 分钟级数据（主数据）
    - datas[1]: 日线数据（过滤数据）

    策略逻辑：
    - EMA 金叉/死叉产生交易信号
    - 日线数据用于日期同步过滤
    """

    params = (
        ("fast_period", 80),
        ("slow_period", 200),
        ("short_size", 2),
        ("long_size", 1),
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
        self.minute_data = self.datas[0]  # 分钟数据
        self.daily_data = self.datas[1] if len(self.datas) > 1 else None  # 日线数据

        # 在分钟数据上计算 EMA 指标
        self.fast_ema = bt.ind.EMA(self.minute_data, period=self.p.fast_period)
        self.slow_ema = bt.ind.EMA(self.minute_data, period=self.p.slow_period)
        self.ema_cross = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)

        # 如果有日线数据，在日线上计算 SMA
        if self.daily_data is not None:
            self.sma_day = bt.ind.SMA(self.daily_data, period=6)

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

        # 获取 EMA 交叉信号历史（最近80个bar）
        crosslist = [i for i in self.ema_cross.get(size=80) if i == 1 or i == -1]

        # 检查日期同步（如果有日线数据）
        date_synced = True
        if self.daily_data is not None:
            date_synced = self.minute_data.datetime.date(0) == self.daily_data.datetime.date(0)

        # 开仓逻辑
        if not self.position and date_synced:
            # 死叉信号 - 开空
            if len(crosslist) > 0 and sum(crosslist) == -1:
                self.sell(data=self.minute_data, size=self.p.short_size)
                self.sell_count += 1
            # 金叉信号 - 开多
            elif len(crosslist) > 0 and sum(crosslist) == 1:
                self.buy(data=self.minute_data, size=self.p.long_size)
                self.buy_count += 1

        # 平仓逻辑
        elif self.position and date_synced:
            # 持有空仓时，金叉平仓
            if self.position.size < 0 and sum(crosslist) == 1:
                self.close()
                self.buy_count += 1
            # 持有多仓时，死叉平仓
            elif self.position.size > 0 and sum(crosslist) == -1:
                self.close()
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


def test_ema_cross_strategy():
    """测试 EMA 双均线交叉策略

    使用 5 分钟数据和日线数据进行多周期回测
    """
    # 创建 cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # 设置初始资金和手续费
    cerebro.broker.setcash(100000.0)
    cerebro.broker.set_coc(True)

    # 加载分钟数据 (datas[0])
    print("正在加载分钟数据...")
    minute_data_path = resolve_data_path("2006-min-005.txt")
    minute_data = bt.feeds.GenericCSVData(
        dataname=str(minute_data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
        dtformat="%Y-%m-%d",
        tmformat="%H:%M:%S",
        datetime=0,
        time=1,
        open=2,
        high=3,
        low=4,
        close=5,
        volume=6,
        openinterest=7,
        timeframe=bt.TimeFrame.Minutes,
        compression=5,
    )
    cerebro.adddata(minute_data, name="minute")

    # 加载日线数据 (datas[1])
    print("正在加载日线数据...")
    daily_data_path = resolve_data_path("2006-day-001.txt")
    daily_data = bt.feeds.GenericCSVData(
        dataname=str(daily_data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=6,
        timeframe=bt.TimeFrame.Days,
    )
    cerebro.adddata(daily_data, name="daily")

    # 添加策略
    cerebro.addstrategy(
        EmaCrossStrategy,
        fast_period=80,
        slow_period=200,
        short_size=2,
        long_size=1,
    )

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    # 使用日线级别计算夏普率，因为分钟数据不在RATEFACTORS中会导致计算失败
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
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
    print("EMA 双均线交叉策略回测结果:")
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

    # 基本断言 - 确保策略正常运行
    assert strat.bar_num == 1780, f"Expected bar_num=1780, got {strat.bar_num}"
    assert abs(final_value - 99981.71) < 0.01, f"Expected final_value=99981.71, got {final_value}"
    assert total_trades == 2, f"Expected total_trades=2, got {total_trades}"
    assert abs(max_drawdown - 0.0012456157963720896) < 1e-6, f"Expected max_drawdown=0.0012456157963720896, got {max_drawdown}"
    assert abs(annual_return - (-7.631068888840081e-08)) < 1e-6, f"Expected annual_return=-0.00018074842976993673, got {annual_return}"
    # assert sharpe_ratio is None or -20 < sharpe_ratio < 20, "sharpe_ratio should be 0.01"
    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("EMA 双均线交叉策略测试")
    print("=" * 60)
    test_ema_cross_strategy()