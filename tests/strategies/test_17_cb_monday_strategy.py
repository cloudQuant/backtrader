"""可转债周五高溢价率轮动策略测试用例

使用可转债数据测试周五轮动策略
- 使用扩展的 PandasData 加载多合约可转债数据（含溢价率）
- 每周五买入溢价率最高的3只可转债，下周五平仓并换仓
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
    """扩展的Pandas数据源，添加溢价率字段"""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
        ('premium_rate', 5),
    )
    lines = ('premium_rate',)


def clean_bond_data_with_premium():
    """清洗可转债数据，返回含溢价率的DataFrame字典"""
    df = pd.read_csv(resolve_data_path('bond_merged_all_data.csv'))
    df.columns = ['symbol', 'bond_symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
                  'pure_bond_value', 'convert_value', 'pure_bond_premium_rate', 'convert_premium_rate']
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df[df['datetime'] > pd.to_datetime("2018-01-01")]

    datas = {}
    for symbol, data in df.groupby('symbol'):
        data = data.set_index('datetime')
        data = data.drop(['symbol', 'bond_symbol'], axis=1)
        # 保留 ohlcv 和溢价率
        data = data[['open', 'high', 'low', 'close', 'volume', 'convert_premium_rate']]
        data.columns = ['open', 'high', 'low', 'close', 'volume', 'premium_rate']
        data = data.dropna()
        datas[symbol] = data.astype("float")

    return datas


class ConvertibleBondFridayRotationStrategy(bt.Strategy):
    """可转债周五高溢价率轮动策略

    每周五:
    - 平掉现有持仓
    - 买入溢价率最高的3只可转债
    - 持有到下周五
    """
    author = 'yunjinqi'
    params = (
        ("hold_num", 3),
    )

    def log(self, txt, dt=None):
        """log信息的功能"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.data_order_dict = {}
        self.order_list = []

    def prenext(self):
        self.next()

    def next(self):
        self.bar_num += 1
        self.current_datetime = bt.num2date(self.datas[0].datetime[0])
        total_value = self.broker.get_value()
        available_cash = self.broker.get_cash()

        # 如果今天是周五，就开始下单平掉现有的持仓，并准备下单
        today = self.current_datetime.weekday() + 1

        if today == 5:
            # 平掉现有持仓
            for data, order in self.order_list:
                size = self.getposition(data).size
                if size > 0:
                    self.close(data)
                    self.sell_count += 1
                if size == 0:
                    self.cancel(order)
            self.order_list = []

            # 收集当前可交易的可转债
            result = []
            for data in self.datas[1:]:
                data_datetime = bt.num2date(data.datetime[0])
                if data_datetime == self.current_datetime:
                    data_name = data._name
                    premium_rate = data.premium_rate[0]
                    result.append([data, premium_rate])

            # 获取溢价率排序
            sorted_result = sorted(result, key=lambda x: x[1])

            # 买入溢价率最高的几只
            for data, _ in sorted_result[-self.p.hold_num:]:
                close_price = data.close[0]
                total_value = self.broker.getvalue()
                plan_tobuy_value = 0.1 * total_value
                lots = 10 * int(plan_tobuy_value / (close_price * 10))
                if lots > 0:
                    order = self.buy(data, size=lots)
                    self.buy_count += 1
                    self.order_list.append([data, order])

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


def test_cb_friday_rotation_strategy():
    """测试可转债周五轮动策略
    
    使用可转债数据进行回测
    """
    cerebro = bt.Cerebro(stdstats=True)

    # 加载指数数据
    print("正在加载指数数据...")
    index_data = pd.read_csv(resolve_data_path('bond_index_000000.csv'))
    index_data.index = pd.to_datetime(index_data['datetime'])
    index_data = index_data[index_data.index > pd.to_datetime("2018-01-01")]
    index_data = index_data.drop(['datetime'], axis=1)
    # 添加一列 premium_rate 默认为0
    index_data['premium_rate'] = 0.0
    print(f"指数数据范围: {index_data.index[0]} 至 {index_data.index[-1]}, 共 {len(index_data)} 条")

    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name='000000')

    # 清洗并加载可转债数据
    print("\n正在加载可转债数据...")
    datas = clean_bond_data_with_premium()
    print(f"总共有 {len(datas)} 只可转债")

    added_count = 0
    max_bonds = 30  # 限制添加数量以加快测试
    for symbol, data in datas.items():
        if len(data) > 30:
            if added_count >= max_bonds:
                break
            feed = ExtendPandasFeed(dataname=data)
            cerebro.adddata(feed, name=symbol)
            added_count += 1

    print(f"成功添加 {added_count} 只可转债数据")

    # 设置手续费和初始资金
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.broker.setcash(1000000.0)

    # 添加策略
    cerebro.addstrategy(ConvertibleBondFridayRotationStrategy, hold_num=3)

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
    print("可转债周五轮动策略回测结果:")
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
    assert strat.bar_num > 0
    assert strat.buy_count == 1119, f"Expected buy_count=1119, got {strat.buy_count}"
    assert strat.sell_count == 1116, f"Expected sell_count=1116, got {strat.sell_count}"
    assert total_trades == 1117, f"Expected total_trades=1117, got {total_trades}"
    assert abs(sharpe_ratio-(-0.13455036625145408))<1e-6, f"Expected sharpe_ratio=-0.13455036625145442, got {sharpe_ratio}"
    assert abs(annual_return-0.005213988514988448)<1e-6, f"Expected annual_return=0.005213988514988448, got {annual_return}"
    assert abs(max_drawdown-0.134336302193658)<1e-6, f"Expected max_drawdown=0.134336302193658, got {max_drawdown}"
    assert abs(final_value - 1039666.6544150009)<1e-6, f"Expected final_value=1039666.6544150009, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("可转债周五高溢价率轮动策略测试")
    print("=" * 60)
    test_cb_friday_rotation_strategy()