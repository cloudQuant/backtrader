"""分时均线 (TimeLine MA) 期货策略测试用例

使用螺纹钢期货数据 RB889.csv 测试分时均线策略
- 使用 PandasData 加载单合约数据
- 基于分时均价线和均线过滤的日内策略，配合移动止损
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


class TimeLine(bt.Indicator):
    """分时均价线指标
    
    计算当日收盘价的累积平均值作为分时均价线
    """
    lines = ('day_avg_price',)
    params = (("day_end_time", (15, 0, 0)),)

    def __init__(self):
        self.day_close_price_list = []

    def next(self):
        self.day_close_price_list.append(self.data.close[0])
        self.lines.day_avg_price[0] = sum(self.day_close_price_list) / len(self.day_close_price_list)

        self.current_datetime = bt.num2date(self.data.datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        day_end_hour, day_end_minute, _ = self.p.day_end_time
        if self.current_hour == day_end_hour and self.current_minute == day_end_minute:
            self.day_close_price_list = []


class TimeLineMaStrategy(bt.Strategy):
    """分时均线策略

    使用分时均价线配合均线进行交易:
    - 均线向上 + 价格 > 均线 + 价格突破分时均线 → 做多
    - 均线向下 + 价格 < 均线 + 价格跌破分时均线 → 做空
    - 使用移动止损
    - 收盘前平仓
    """
    author = 'yunjinqi'
    params = (
        ("ma_period", 200),
        ("stop_mult", 1),
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
        # 分时均价线指标
        self.day_avg_price = TimeLine(self.datas[0])
        self.ma_value = bt.indicators.SMA(self.datas[0].close, period=self.p.ma_period)
        # 保存交易状态
        self.marketposition = 0
        # 保存当前交易日的最高价、最低价，收盘价
        self.now_high = 0
        self.now_low = 999999999
        self.now_close = None
        self.now_open = None
        # 跟踪止损单
        self.stop_order = None

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
        if self.current_hour == 15:
            self.now_high = 0
            self.now_low = 999999999
            self.now_close = None
            self.day_bar_num = 0

        # 初始化
        size = self.getposition(data).size
        if size == 0:
            self.marketposition = 0
            if self.stop_order is not None:
                self.broker.cancel(self.stop_order)
                self.stop_order = None

        # 分时均线策略
        if len(data.close) > self.p.ma_period:
            # 开始交易
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            # 开仓
            if open_time_1 or open_time_2:
                # 开多
                if self.marketposition == 0 and self.day_bar_num >= 3 and self.ma_value[0] > self.ma_value[-1] and data.close[0] > self.ma_value[0] and data.close[0] > self.day_avg_price[0] and data.close[-1] < self.day_avg_price[-1]:
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.buy(data, size=lots)
                    self.buy_count += 1
                    self.marketposition = 1
                    self.stop_order = self.sell(data, size=lots, exectype=bt.Order.StopTrail, trailpercent=self.p.stop_mult / 100)
                # 开空
                if self.marketposition == 0 and self.day_bar_num >= 3 and self.ma_value[0] < self.ma_value[-1] and data.close[0] < self.ma_value[0] and data.close[0] < self.day_avg_price[0] and data.close[-1] > self.day_avg_price[-1]:
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.sell(data, size=lots)
                    self.sell_count += 1
                    self.marketposition = -1
                    self.stop_order = self.buy(data, size=lots, exectype=bt.Order.StopTrail, trailpercent=self.p.stop_mult / 100)

            # 信号平仓
            # 平多
            if self.marketposition > 0 and data.close[0] < self.day_avg_price[0] and data.close[0] < self.now_low:
                self.close(data)
                self.marketposition = 0
                if self.stop_order is not None:
                    self.broker.cancel(self.stop_order)
                self.stop_order = None
            # 平空
            if self.marketposition < 0 and data.close[0] > self.day_avg_price[0] and data.close[0] > self.now_high:
                self.close(data)
                self.marketposition = 0
                if self.stop_order is not None:
                    self.broker.cancel(self.stop_order)
                self.stop_order = None

            # 收盘平仓
            if self.marketposition != 0 and self.current_hour == 14 and self.current_minute == 55:
                self.close(data)
                self.marketposition = 0
                if self.stop_order is not None:
                    self.broker.cancel(self.stop_order)
                self.stop_order = None

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
    # 删除部分收盘价为0的错误数据
    df = df.astype("float")
    df = df[(df["open"] > 0) & (df['close'] > 0)]
    return df


def test_timeline_ma_strategy():
    """测试分时均线策略
    
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

    # 添加策略，使用固定参数 ma_period=200, stop_mult=1
    cerebro.addstrategy(TimeLineMaStrategy, ma_period=200, stop_mult=1)

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
    print("分时均线策略回测结果:")
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
    assert strat.bar_num == 170081, f"Expected bar_num=170081, got {strat.bar_num}"
    assert strat.buy_count == 1453, f"Expected buy_count=1453, got {strat.buy_count}"
    assert strat.sell_count == 1449, f"Expected sell_count=1449, got {strat.sell_count}"
    assert total_trades == 2902, f"Expected total_trades=2902, got {total_trades}"
    assert sharpe_ratio == 0.3757684439655264, f"Expected sharpe_ratio=0.3757684439655264, got {sharpe_ratio}"
    assert annual_return == 0.11220154901666389, f"Expected annual_return=0.11220154901666389, got {annual_return}"
    assert max_drawdown == 0.23238052534148135, f"Expected max_drawdown=0.23238052534148135, got {max_drawdown}"
    assert final_value == 3362883.104588703, f"Expected final_value=3362883.104588703, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("分时均线 (TimeLine MA) 日内策略测试")
    print("=" * 60)
    test_timeline_ma_strategy()