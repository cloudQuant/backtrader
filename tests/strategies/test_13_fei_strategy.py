"""Fei (菲阿里四价改进版) 期货策略测试用例

使用螺纹钢期货数据 RB889.csv 测试菲阿里四价改进版策略
- 使用 PandasData 加载单合约数据
- 基于布林带过滤的菲阿里四价突破策略
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


class FeiStrategy(bt.Strategy):
    """菲阿里四价改进版策略

    使用布林带进行过滤:
    - 当价格突破布林带上轨，并且中轨向上，且突破前日高点，才做多
    - 当价格突破布林带下轨，并且中轨向下，且跌破前日低点，才做空
    - 收盘前平仓
    """
    author = 'yunjinqi'
    params = (
        ("boll_period", 200),
        ("boll_mult", 2),
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
        # 计算布林带指标
        self.boll_indicator = bt.indicators.BollingerBands(
            self.datas[0], period=self.p.boll_period, devfactor=self.p.boll_mult
        )
        # 保存交易状态
        self.marketposition = 0
        # 保存当前交易日的最高价、最低价，收盘价
        self.now_high = 0
        self.now_low = 999999999
        self.now_close = None
        self.now_open = None
        # 保存历史上的每日的最高价、最低价与收盘价
        self.day_high_list = []
        self.day_low_list = []
        self.day_close_list = []

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
        
        # 如果是新的交易日的最后一分钟的数据
        if self.current_hour == 15:
            self.day_high_list.append(self.now_high)
            self.day_low_list.append(self.now_low)
            self.day_close_list.append(self.now_close)
            self.now_high = 0
            self.now_low = 999999999
            self.now_close = None
            self.day_bar_num = 0

        # 菲阿里四价的改进版本：使用布林带进行过滤
        if len(self.day_high_list) > 1:
            top = self.boll_indicator.top
            bot = self.boll_indicator.bot
            mid = self.boll_indicator.mid
            pre_high = self.day_high_list[-1]
            pre_low = self.day_low_list[-1]

            # 开始交易
            open_time_1 = self.current_hour >= 21 and self.current_hour <= 23
            open_time_2 = self.current_hour >= 9 and self.current_hour <= 11
            # 开仓
            if open_time_1 or open_time_2:
                # 开多
                if self.marketposition == 0 and data.close[0] > top[0] and mid[0] > mid[-1] and data.close[0] > pre_high:
                    # 获取一倍杠杆下单的手数
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.buy(data, size=lots)
                    self.buy_count += 1
                    self.marketposition = 1
                # 开空
                if self.marketposition == 0 and mid[0] < mid[-1] and data.close[0] < bot[0] and data.close[0] < pre_low:
                    # 获取一倍杠杆下单的手数
                    info = self.broker.getcommissioninfo(data)
                    symbol_multi = info.p.mult
                    close = data.close[0]
                    total_value = self.broker.getvalue()
                    lots = total_value / (symbol_multi * close)
                    self.sell(data, size=lots)
                    self.sell_count += 1
                    self.marketposition = -1

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


def test_fei_strategy():
    """测试菲阿里四价改进版策略
    
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

    # 添加策略，使用固定参数 boll_period=200, boll_mult=2
    cerebro.addstrategy(FeiStrategy, boll_period=200, boll_mult=2)

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
    print("Fei 策略回测结果:")
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
    assert strat.buy_count == 212, f"Expected buy_count=212, got {strat.buy_count}"
    assert strat.sell_count == 130, f"Expected sell_count=130, got {strat.sell_count}"
    assert total_trades == 342, f"Expected total_trades=342, got {total_trades}"
    assert abs(sharpe_ratio - (-0.9102735975413994)) < 1e-6, f"Expected sharpe_ratio=-0.9102735975413994, got {sharpe_ratio}"
    assert abs(annual_return - (-0.09029688654771216)) < 1e-6, f"Expected annual_return=-0.09029688654771216, got {annual_return}"
    assert abs(max_drawdown - 0.3494575276331572) < 1e-6, f"Expected max_drawdown=0.3494575276331572, got {max_drawdown}"
    assert abs(final_value - 753399.3414635758) < 0.01, f"Expected final_value=753399.34, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Fei (菲阿里四价改进版) 策略测试")
    print("=" * 60)
    test_fei_strategy()