"""Hans123 (汉斯123改进版) 期货策略测试用例

使用螺纹钢期货数据 RB889.csv 测试 Hans123 日内突破策略
- 使用 PandasData 加载单合约数据
- 基于开盘N根K线高低点突破，配合均线过滤的日内策略
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


class Hans123Strategy(bt.Strategy):
    """Hans123 日内突破策略（均线过滤版）

    使用开盘前N根K线的高低点作为突破区间:
    - 均线向上 + 价格 > 均线 + 价格突破上轨 → 做多
    - 均线向下 + 价格 < 均线 + 价格跌破下轨 → 做空
    - 收盘前平仓
    """
    author = 'yunjinqi'
    params = (
        ("ma_period", 200),
        ("bar_num", 2),
    )

    def log(self, txt, dt=None):
        """log信息的功能"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        self.bar_num = 0
        self.day_bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # 计算均线指标
        self.ma_value = bt.indicators.SMA(self.datas[0].close, period=self.p.ma_period)
        # 保存交易状态
        self.marketposition = 0
        # 保存当前交易日的最高价、最低价，收盘价
        self.now_high = 0
        self.now_low = 999999999
        self.now_close = None
        self.now_open = None
        # 上轨与下轨
        self.upper_line = None
        self.lower_line = None

    def prenext(self):
        pass

    def next(self):
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        self.day_bar_num += 1
        self.bar_num += 1
        data = self.datas[0]

        # 更新最高价、最低价、收盘价
        self.now_high = max(self.now_high, data.high[0])
        self.now_low = min(self.now_low, data.low[0])
        if self.now_close is None:
            self.now_open = data.open[0]
        self.now_close = data.close[0]
        
        # 如果当前的bar的数目等于计算高低点的时间,计算上下轨的价格
        if self.day_bar_num == self.p.bar_num:
            self.upper_line = self.now_high
            self.lower_line = self.now_low

        # 如果是新的交易日的最后一分钟的数据
        if self.current_hour == 15:
            self.now_high = 0
            self.now_low = 999999999
            self.now_close = None
            self.day_bar_num = 0

        # hans123的改进版本：使用均线过滤交易
        if len(data.close) > self.p.ma_period and self.day_bar_num >= self.p.bar_num:
            # 开始交易
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            # 开仓
            if open_time_1 or open_time_2:
                # 开多
                if self.marketposition == 0 and self.ma_value[0] > self.ma_value[-1] and data.close[0] > self.ma_value[0] and data.close[0] > self.upper_line:
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.buy(data, size=lots)
                    self.buy_count += 1
                    self.marketposition = 1
                # 开空
                if self.marketposition == 0 and self.ma_value[0] < self.ma_value[-1] and data.close[0] < self.ma_value[0] and data.close[0] < self.lower_line:
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.sell(data, size=lots)
                    self.sell_count += 1
                    self.marketposition = -1
            # 平仓
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


def load_rb889_data(filename: str = "RB889.csv", max_rows: int = 50000) -> pd.DataFrame:
    """加载螺纹钢期货数据
    
    保持原有的数据加载逻辑，限制数据行数以加快测试
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
    # 删除部分收盘价为0的错误数据
    df = df.astype("float")
    df = df[(df["open"] > 0) & (df['close'] > 0)]
    # 限制数据行数以加快测试
    if max_rows and len(df) > max_rows:
        df = df.iloc[-max_rows:]
    return df


def test_hans123_strategy():
    """测试 Hans123 日内突破策略
    
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
    comm = ComminfoFuturesPercent(commission=0.0001, margin=0.10, mult=10)
    cerebro.broker.addcommissioninfo(comm, name=name)
    cerebro.broker.setcash(1000000.0)

    # 添加策略，使用固定参数 ma_period=200, bar_num=2
    cerebro.addstrategy(Hans123Strategy, ma_period=200, bar_num=2)

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
    print("Hans123 策略回测结果:")
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
    assert strat.bar_num == 49801, f"Expected bar_num=49801, got {strat.bar_num}"
    assert strat.buy_count == 346, f"Expected buy_count=346, got {strat.buy_count}"
    assert strat.sell_count == 252, f"Expected sell_count=252, got {strat.sell_count}"
    assert total_trades == 598, f"Expected total_trades=598, got {total_trades}"
    assert abs(sharpe_ratio - (-0.38853827472284613)) < 1e-6, f"Expected sharpe_ratio=-0.38853827472284613, got {sharpe_ratio}"
    assert abs(annual_return - (-0.05485916735255581)) < 1e-6, f"Expected annual_return=-0.05485916735255581, got {annual_return}"
    assert abs(max_drawdown - 0.34452640045840965) < 1e-6, f"Expected max_drawdown=0.34452640045840965, got {max_drawdown}"
    assert abs(final_value - 844664.1285503485) < 0.01, f"Expected final_value=844664.13, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Hans123 (汉斯123) 日内突破策略测试")
    print("=" * 60)
    test_hans123_strategy()