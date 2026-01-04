"""MACD EMA 期货策略测试用例

使用螺纹钢期货数据 rb99.csv 测试 MACD + EMA 趋势策略
- 使用 PandasDirectData 加载数据（保持原有加载方式不变）
- MACD 金叉/死叉 + EMA 过滤进行趋势交易
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


class MacdEmaStrategy(bt.Strategy):
    """MACD + EMA 期货趋势策略

    使用MACD金叉/死叉作为入场信号，EMA作为止损过滤
    """
    author = 'yunjinqi'
    params = (
        ("period_me1", 10),
        ("period_me2", 20),
        ("period_signal", 9),
    )

    def log(self, txt, dt=None):
        """log信息的功能"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # MACD指标
        self.bt_macd_indicator = bt.indicators.MACD(
            self.datas[0],
            period_me1=self.p.period_me1,
            period_me2=self.p.period_me2,
            period_signal=self.p.period_signal
        )
        # EMA指标
        self.ema = bt.indicators.ExponentialMovingAverage(
            self.datas[0], period=self.p.period_me1
        )

    def prenext(self):
        pass

    def next(self):
        self.bar_num += 1
        # 获取MACD指标值
        dif = self.bt_macd_indicator.macd
        dea = self.bt_macd_indicator.signal
        # 计算当前bar的macd值（使用当前值计算）
        macd_value = 2 * (dif[0] - dea[0])
        # 当前状态
        data = self.datas[0]
        size = self.getposition(self.datas[0]).size

        # 平多
        if size > 0 and data.close[0] < self.ema[0]:
            self.close(data)
            self.sell_count += 1
            size = 0

        # 平空
        if size < 0 and data.close[0] > self.ema[0]:
            self.close(data)
            self.buy_count += 1
            size = 0

        # 开多: DIF从负变正且MACD柱大于0
        if size == 0 and dif[-1] < 0 and dif[0] > 0 and macd_value > 0:
            self.buy(data, size=1)
            self.buy_count += 1

        # 开空: DIF从正变负且MACD柱小于0
        if size == 0 and dif[-1] > 0 and dif[0] < 0 and macd_value < 0:
            self.sell(data, size=1)
            self.sell_count += 1

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: price={order.executed.price:.2f}, cost={order.executed.value:.2f}")
            else:
                self.log(f"SELL: price={order.executed.price:.2f}, cost={order.executed.value:.2f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"交易完成: 毛利润={trade.pnl:.2f}, 净利润={trade.pnlcomm:.2f}")

    def stop(self):
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


class RbPandasFeed(bt.feeds.PandasData):
    """螺纹钢期货数据的Pandas数据源
    
    使用显式列映射，兼容PandasData加载方式
    """
    params = (
        ('datetime', None),  # datetime是索引
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def load_rb_data(filename: str = "rb/rb99.csv") -> pd.DataFrame:
    """加载螺纹钢期货数据
    
    保持原有的数据加载逻辑
    """
    data_kwargs = dict(
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2020, 12, 31),
    )
    
    df = pd.read_csv(resolve_data_path(filename))
    # 只要数据里面的这几列
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    # 修改列的名字
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df[(df.index <= data_kwargs['todate']) & (df.index >= data_kwargs['fromdate'])]
    return df


def test_macd_ema_strategy():
    """测试 MACD + EMA 期货策略
    
    使用螺纹钢期货数据 rb99.csv 进行回测
    """
    # 创建 cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # 加载数据
    print("正在加载螺纹钢期货数据...")
    df = load_rb_data("rb/rb99.csv")
    print(f"数据范围: {df.index[0]} 至 {df.index[-1]}, 共 {len(df)} 条")

    # 使用 RbPandasFeed 加载数据（与原有PandasDirectData逻辑一致）
    name = "RB99"
    feed = RbPandasFeed(dataname=df)
    cerebro.adddata(feed, name=name)

    # 设置合约的交易信息，佣金设置为0.02%，保证金率为10%
    comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(50000.0)

    # 添加策略
    cerebro.addstrategy(MacdEmaStrategy)

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
    print("MACD EMA 策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # 断言测试结果（精确值）
    assert strat.bar_num == 28069, f"Expected bar_num=28069, got {strat.bar_num}"
    assert strat.buy_count == 1008, f"Expected buy_count=1008, got {strat.buy_count}"
    assert strat.sell_count == 1008, f"Expected sell_count=1008, got {strat.sell_count}"
    assert total_trades == 1008, f"Expected total_trades=1008, got {total_trades}"
    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert abs(sharpe_ratio - (-0.4094093376341401)) < 1e-6, f"Expected sharpe_ratio=-0.4094093376341401, got {sharpe_ratio}"
    assert abs(annual_return - (-0.016850037618788616)) < 1e-6, f"Expected annual_return=-0.016850037618788616, got {annual_return}"
    assert abs(max_drawdown - 0.3294344677230617) < 1e-6, f"Expected max_drawdown=0.3294344677230617, got {max_drawdown}"
    assert abs(final_value - 41589.93032683378) < 0.01, f"Expected final_value=41589.93032683378, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("MACD EMA 期货策略测试")
    print("=" * 60)
    test_macd_ema_strategy()