"""R-Breaker 期货策略测试用例

使用螺纹钢期货数据 RB889.csv 测试 R-Breaker 日内突破策略
- 使用 PandasData 加载单合约数据
- 基于前一日高低收计算支撑阻力位的日内策略
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


class RBreakerStrategy(bt.Strategy):
    """R-Breaker 日内突破策略

    基于前一日高低收计算 Pivot、R1/R3、S1/S3 价格
    突破开仓，收盘前平仓
    """
    author = 'yunjinqi'
    params = (
        ("k1", 0.5),
        ("k2", 0.5),
    )

    def log(self, txt, dt=None):
        """log信息的功能"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        self.bar_num = 0
        self.pre_date = None
        self.buy_count = 0
        self.sell_count = 0
        # 保存当前交易日的最高价、最低价，收盘价
        self.now_high = 0
        self.now_low = 999999999
        self.now_close = None
        self.now_open = None
        # 保存历史上的每日的最高价、最低价与收盘价
        self.day_high_list = []
        self.day_low_list = []
        self.day_close_list = []
        # 保存交易状态
        self.marketposition = 0

    def prenext(self):
        pass

    def next(self):
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        self.bar_num += 1
        data = self.datas[0]

        # 更新最高价、最低价、收盘价
        self.now_high = max(self.now_high, data.high[0])
        self.now_low = min(self.now_low, data.low[0])
        if self.now_close is None:
            self.now_open = data.open[0]
        self.now_close = data.close[0]
        
        # 如果是新的交易日的最后一分钟的数据
        if self.current_hour == 15:
            self.day_high_list.append(self.now_high)
            self.day_low_list.append(self.now_low)
            self.day_close_list.append(self.now_close)
            self.now_high = 0
            self.now_low = 999999999
            self.now_close = None

        # 长度足够，开始计算指标、交易信号
        if len(self.day_high_list) > 1:
            pre_high = self.day_high_list[-1]
            pre_low = self.day_low_list[-1]
            pre_close = self.day_close_list[-1]
            pivot = (pre_high + pre_low + pre_close) / 3
            r1 = pivot + (self.p.k1) * (pre_high - pre_low)
            r3 = pivot + (self.p.k1 + self.p.k2) * (pre_high - pre_low)
            s1 = pivot - (self.p.k1) * (pre_high - pre_low)
            s3 = pivot - (self.p.k1 + self.p.k2) * (pre_high - pre_low)

            # 开始交易
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            close = data.close[0]
            if open_time_1 or open_time_2:
                # 开多
                if self.marketposition == 0 and close > r3:
                    self.buy(data, size=1)
                    self.buy_count += 1
                    self.marketposition = 1

                # 开空
                if self.marketposition == 0 and close < s3:
                    self.sell(data, size=1)
                    self.sell_count += 1
                    self.marketposition = -1

                # 平多开空
                if self.marketposition == 1 and close < r1:
                    self.close(data)
                    self.sell(data, size=1)
                    self.sell_count += 1
                    self.marketposition = -1

                # 平空开多
                if self.marketposition == -1 and close > s1:
                    self.close(data)
                    self.buy(data, size=1)
                    self.buy_count += 1
                    self.marketposition = 1

        # 收盘前平仓
        if self.marketposition != 0 and self.current_hour == 14 and self.current_minute == 55:
            self.close(data)
            self.marketposition = 0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: price={order.executed.price:.2f}")
            else:
                self.log(f"SELL: price={order.executed.price:.2f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"交易完成: pnl={trade.pnl:.2f}, pnlcomm={trade.pnlcomm:.2f}")

    def stop(self):
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


class RbPandasFeed(bt.feeds.PandasData):
    """螺纹钢期货数据的Pandas数据源"""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def load_rb889_data(filename: str = "RB889.csv") -> pd.DataFrame:
    """加载螺纹钢期货数据
    
    保持原有的数据加载逻辑
    """
    df = pd.read_csv(resolve_data_path(filename))
    # 只要数据里面的这几列
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'open_interest']]
    df.columns = ['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']
    # 排序和去重
    df = df.sort_values("datetime")
    df = df.drop_duplicates("datetime")
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    return df


def test_r_breaker_strategy():
    """测试 R-Breaker 日内突破策略
    
    使用螺纹钢期货数据 RB889.csv 进行回测
    """
    # 创建 cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # 加载数据
    print("正在加载螺纹钢期货数据...")
    df = load_rb889_data("RB889.csv")
    print(f"数据范围: {df.index[0]} 至 {df.index[-1]}, 共 {len(df)} 条")

    # 使用 RbPandasFeed 加载数据
    name = "RB"
    feed = RbPandasFeed(dataname=df)
    cerebro.adddata(feed, name=name)

    # 设置合约的交易信息
    comm = ComminfoFuturesPercent(commission=0.0003, margin=0.10, mult=10)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(50000.0)

    # 添加策略
    cerebro.addstrategy(RBreakerStrategy)

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
    print("R-Breaker 策略回测结果:")
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
    assert strat.bar_num == 170280, f"Expected bar_num=170280, got {strat.bar_num}"
    assert strat.buy_count == 1121, f"Expected buy_count=1121, got {strat.buy_count}"
    assert strat.sell_count == 1085, f"Expected sell_count=1085, got {strat.sell_count}"
    assert total_trades == 1823, f"Expected total_trades=1823, got {total_trades}"
    assert sharpe_ratio == -0.4954305469460524, f"Expected sharpe_ratio=-0.4954305469460524, got {sharpe_ratio}"
    assert annual_return == -0.04463053240115862, f"Expected annual_return=-0.04463053240115862, got {annual_return}"
    assert max_drawdown == 0.5390700943358133, f"Expected max_drawdown=0.5390700943358133, got {max_drawdown}"
    assert final_value == 29704.966000000306, f"Expected final_value=29704.966000000306, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("R-Breaker 日内突破策略测试")
    print("=" * 60)
    test_r_breaker_strategy()