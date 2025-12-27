"""可转债多因子日内策略测试用例

使用可转债数据测试多因子日内交易策略
- 使用 PandasData 加载多合约可转债数据
- 基于均线、分时均价线、成交量等多因子的日内策略
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
    repo_root = BASE_DIR.parent.parent
    search_paths = [
        BASE_DIR / "datas" / filename,
        repo_root / "tests" / "datas" / filename,
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
    ]
    
    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"未找到数据文件: {filename}")


class ExtendPandasFeed(bt.feeds.PandasData):
    """扩展的Pandas数据源，用于可转债数据"""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
    )


def clean_bond_data():
    """清洗可转债数据，返回多个可转债的DataFrame字典"""
    df = pd.read_csv(resolve_data_path('bond_merged_all_data.csv'))
    df.columns = ['symbol', 'bond_symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
                  'pure_bond_value', 'convert_value', 'pure_bond_premium_rate', 'convert_premium_rate']
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df[df['datetime'] > pd.to_datetime("2018-01-01")]

    datas = {}
    for symbol, data in df.groupby('symbol'):
        data = data.set_index('datetime')
        data = data.drop(['symbol', 'bond_symbol'], axis=1)
        # 只保留 ohlcv 列，openinterest 用 volume 代替（日线数据）
        data = data[['open', 'high', 'low', 'close', 'volume']]
        data = data.dropna()
        datas[symbol] = data.astype("float")

    return datas


class ConvertibleBondIntradayStrategy(bt.Strategy):
    """可转债多因子日内策略

    使用多因子进行筛选和交易:
    - 价格 > 20周期均线
    - 价格 > 分时均价线
    - 涨跌幅在-1%到1%之间
    - 成交量 < 30周期平均成交量的4倍
    - 均线上涨但速度变慢
    """
    author = 'yunjinqi'
    params = (
        ("ma_period", 20),
        ("can_trade_num", 2),
    )

    def log(self, txt, dt=None):
        """log信息的功能"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # 同时持仓的可转债的数目
        self.can_trade_num = self.p.can_trade_num
        # 计算每个可转债数据的20周期均线
        self.cb_ma_dict = {data._name: bt.indicators.SMA(data.close, period=self.p.ma_period) for data in self.datas[1:]}
        # 计算最近30周期的平均成交量
        self.cb_avg_volume_dict = {data._name: bt.indicators.SMA(data.volume, period=30) for data in self.datas[1:]}
        # 记录前一天的收盘价
        self.cb_pre_close_dict = {data._name: None for data in self.datas[1:]}
        # 记录开仓的时候的bar的根数
        self.cb_bar_num_dict = {data._name: None for data in self.datas[1:]}
        # 记录开仓的价格
        self.cb_open_position_price_dict = {data._name: None for data in self.datas[1:]}
        # 用最近20个周期的最低点作为前期低点
        self.cb_low_point_dict = {data._name: bt.indicators.Lowest(data.low, period=20) for data in self.datas[1:]}

    def prenext(self):
        self.next()

    def next(self):
        self.bar_num += 1
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])

        for data in self.datas[1:]:
            data_datetime = bt.num2date(data.datetime[0])
            if data_datetime == self.current_datetime:
                data_name = data._name
                close_price = data.close[0]
                
                # 判断是否存在前一天的收盘价
                pre_close = self.cb_pre_close_dict[data_name]
                if pre_close is None:
                    pre_close = data.open[0]
                    self.cb_pre_close_dict[data_name] = pre_close
                
                # 更新收盘价（日线数据直接更新）
                self.cb_pre_close_dict[data_name] = close_price

                # 到期平仓逻辑
                position_size = self.getposition(data).size
                if position_size > 0:
                    try:
                        _ = data.open[2]
                    except:
                        self.close(data)
                        self.cb_bar_num_dict[data_name] = None
                        self.can_trade_num += 1

                # 准备平仓
                open_bar_num = self.cb_bar_num_dict[data_name]
                if open_bar_num is not None:
                    # 持仓超过10个bar，平了
                    if open_bar_num < self.bar_num - 10:
                        self.close(data)
                        self.sell_count += 1
                        self.cb_bar_num_dict[data_name] = None
                        self.can_trade_num += 1

                open_bar_num = self.cb_bar_num_dict[data_name]
                if open_bar_num is not None:
                    # 如果跌破前期低点，平了
                    low_point = self.cb_low_point_dict[data_name][0]
                    if close_price < low_point:
                        self.close(data)
                        self.sell_count += 1
                        self.cb_bar_num_dict[data_name] = None
                        self.can_trade_num += 1

                open_bar_num = self.cb_bar_num_dict[data_name]
                if open_bar_num is not None:
                    # 如果收益率大于3%，止盈
                    open_position_price = self.cb_open_position_price_dict[data_name]
                    if open_position_price and close_price / open_position_price > 1.03:
                        self.close(data)
                        self.sell_count += 1
                        self.cb_bar_num_dict[data_name] = None
                        self.can_trade_num += 1

                # 准备开仓
                ma_line = self.cb_ma_dict[data_name]
                ma_price = ma_line[0]
                if close_price > ma_price:
                    # 判断涨跌幅在-1%到1%之间
                    up_percent = close_price / pre_close
                    if up_percent > 0.99 and up_percent < 1.01:
                        # 判断成交量是否小于平均成交量的4倍
                        volume = data.volume[0]
                        avg_volume = self.cb_avg_volume_dict[data_name][0]
                        if avg_volume > 0 and volume < avg_volume * 4:
                            # 均线上涨但速度变慢
                            if ma_line[0] > ma_line[-1] and ma_line[0] - ma_line[-1] < ma_line[-1] - ma_line[-2]:
                                open_bar_num = self.cb_bar_num_dict[data_name]
                                if self.can_trade_num > 0 and open_bar_num is None:
                                    total_value = self.broker.getvalue()
                                    plan_tobuy_value = 0.4 * total_value
                                    lots = int(plan_tobuy_value / close_price)
                                    if lots > 0:
                                        self.buy(data, size=lots)
                                        self.buy_count += 1
                                        self.can_trade_num -= 1
                                        self.cb_bar_num_dict[data_name] = self.bar_num
                                        try:
                                            self.cb_open_position_price_dict[data_name] = data.open[1]
                                        except:
                                            self.cb_open_position_price_dict[data_name] = close_price

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: {order.p.data._name} price={order.executed.price:.2f}")
            else:
                self.log(f"SELL: {order.p.data._name} price={order.executed.price:.2f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"交易完成: {trade.getdataname()} pnl={trade.pnl:.2f}")

    def stop(self):
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


def test_cb_intraday_strategy():
    """测试可转债多因子日内策略
    
    使用可转债数据进行回测
    """
    cerebro = bt.Cerebro(stdstats=True)

    # 加载指数数据
    print("正在加载指数数据...")
    index_data = pd.read_csv(resolve_data_path('bond_index_000000.csv'))
    index_data.index = pd.to_datetime(index_data['datetime'])
    index_data = index_data[index_data.index > pd.to_datetime("2018-01-01")]
    index_data = index_data.drop(['datetime'], axis=1)
    print(f"指数数据范围: {index_data.index[0]} 至 {index_data.index[-1]}, 共 {len(index_data)} 条")

    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name='000000')

    # 清洗并加载可转债数据
    print("\n正在加载可转债数据...")
    datas = clean_bond_data()
    print(f"总共有 {len(datas)} 只可转债")

    added_count = 0
    max_bonds = 30  # 限制添加数量以加快测试
    for symbol, data in datas.items():
        if len(data) > 30:
            if added_count >= max_bonds:
                break
            feed = ExtendPandasFeed(dataname=data)
            cerebro.adddata(feed, name=symbol)
            comm = ComminfoFuturesPercent(commission=0.0001, margin=0.1, mult=1)
            cerebro.broker.addcommissioninfo(comm, name=symbol)
            added_count += 1

    print(f"成功添加 {added_count} 只可转债数据")

    # 设置初始资金
    cerebro.broker.setcash(1000000.0)

    # 添加策略
    cerebro.addstrategy(ConvertibleBondIntradayStrategy, ma_period=20, can_trade_num=2)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # 运行回测
    print("\n开始运行回测...")
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
    print("可转债多因子日内策略回测结果:")
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
    assert strat.bar_num == 1885, f"Expected bar_num=1885, got {strat.bar_num}"
    assert strat.buy_count == 300, f"Expected buy_count=300, got {strat.buy_count}"
    assert strat.sell_count == 294, f"Expected sell_count=294, got {strat.sell_count}"
    assert total_trades == 299, f"Expected total_trades=299, got {total_trades}"
    assert sharpe_ratio == 0.23032590904888126, f"Expected sharpe_ratio=0.23032590904888126, got {sharpe_ratio}"
    assert annual_return == 0.030084430622900046, f"Expected annual_return=0.030084430622900046, got {annual_return}"
    assert max_drawdown == 0.17750189678557882, f"Expected max_drawdown=0.17750189678557882, got {max_drawdown}"
    assert final_value == 1248218.9149463978, f"Expected final_value=1248218.9149463978, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("可转债多因子日内策略测试")
    print("=" * 60)
    test_cb_intraday_strategy()