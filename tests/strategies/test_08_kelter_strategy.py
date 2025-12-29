"""Keltner Channel 多合约期货策略测试用例

使用螺纹钢期货多合约数据测试 Keltner Channel 通道突破策略
- 使用 PandasData 加载多个合约数据
- Keltner Channel 上下轨突破信号 + 移仓换月逻辑
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


class KeltnerStrategy(bt.Strategy):
    """Keltner Channel 多合约期货策略

    使用 Keltner Channel 通道突破作为入场信号
    支持移仓换月逻辑
    """
    author = 'yunjinqi'
    params = (
        ("avg_period", 110),
        ("atr_multi", 3),
    )

    def log(self, txt, dt=None):
        """log信息的功能"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        self.bar_num = 0
        self.current_date = None
        self.buy_count = 0
        self.sell_count = 0
        # 计算 Keltner Channel 指标
        self.middle_price = (self.datas[0].high + self.datas[0].low + self.datas[0].close) / 3
        self.middle_line = bt.indicators.SMA(self.middle_price, period=self.p.avg_period)
        self.atr = bt.indicators.AverageTrueRange(self.datas[0], period=self.p.avg_period)
        self.upper_line = self.middle_line + self.atr * self.p.atr_multi
        self.lower_line = self.middle_line - self.atr * self.p.atr_multi
        # 保存现在持仓的合约是哪一个
        self.holding_contract_name = None

    def prenext(self):
        # 由于期货数据有几千个，每个期货交易日期不同，并不会自然进入next
        # 需要在每个prenext中调用next函数进行运行
        self.next()

    def next(self):
        # 每次运行一次，bar_num自然加1,并更新交易日
        self.current_date = bt.num2date(self.datas[0].datetime[0])
        self.bar_num += 1
        data = self.datas[0]
        
        # 开仓，先平后开
        # 平多
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size > 0 and data.close[0] < self.middle_line[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.sell_count += 1
            self.holding_contract_name = None
            
        # 平空
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size < 0 and data.close[0] > self.middle_line[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.buy_count += 1
            self.holding_contract_name = None

        # 开多
        if self.holding_contract_name is None and data.close[-1] < self.upper_line[-1] and data.close[0] > self.upper_line[0] and self.middle_line[0] > self.middle_line[-1]:
            dominant_contract = self.get_dominant_contract()
            if dominant_contract is not None:
                next_data = self.getdatabyname(dominant_contract)
                self.buy(next_data, size=1)
                self.buy_count += 1
                self.holding_contract_name = dominant_contract

        # 开空
        if self.holding_contract_name is None and data.close[-1] > self.lower_line[-1] and data.close[0] < self.lower_line[0] and self.middle_line[0] < self.middle_line[-1]:
            dominant_contract = self.get_dominant_contract()
            if dominant_contract is not None:
                next_data = self.getdatabyname(dominant_contract)
                self.sell(next_data, size=1)
                self.sell_count += 1
                self.holding_contract_name = dominant_contract

        # 移仓换月
        if self.holding_contract_name is not None:
            dominant_contract = self.get_dominant_contract()
            # 如果出现了新的主力合约，那么就开始换月
            if dominant_contract is not None and dominant_contract != self.holding_contract_name:
                # 下个主力合约
                next_data = self.getdatabyname(dominant_contract)
                # 当前合约持仓大小及数据
                size = self.getpositionbyname(self.holding_contract_name).size
                data = self.getdatabyname(self.holding_contract_name)
                # 平掉旧的
                self.close(data)
                # 开新的
                if size > 0:
                    self.buy(next_data, size=abs(size))
                if size < 0:
                    self.sell(next_data, size=abs(size))
                self.holding_contract_name = dominant_contract

    def get_dominant_contract(self):
        """以持仓量最大的合约作为主力合约,返回数据的名称"""
        target_datas = []
        for data in self.datas[1:]:
            try:
                data_date = bt.num2date(data.datetime[0])
                if self.current_date == data_date:
                    target_datas.append([data._name, data.openinterest[0]])
            except:
                pass
        if not target_datas:
            return None
        target_datas = sorted(target_datas, key=lambda x: x[1])
        return target_datas[-1][0]

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: data_name:{order.p.data._name} price:{order.executed.price:.2f}")
            else:
                self.log(f"SELL: data_name:{order.p.data._name} price:{order.executed.price:.2f}")

    def notify_trade(self, trade):
        # 一个trade结束的时候输出信息
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
        if trade.isopen:
            self.log('open symbol is : {} , price : {}'.format(
                trade.getdataname(), trade.price))

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


def load_rb_multi_data(data_dir: str = "rb") -> dict:
    """加载螺纹钢期货多合约数据
    
    保持原有的数据加载逻辑
    返回: {合约名: DataFrame} 的字典
    """
    data_kwargs = dict(
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2020, 12, 31),
    )
    
    data_path = resolve_data_path(data_dir)
    file_list = os.listdir(data_path)
    
    # 确保 rb99.csv 作为指数数据放在第一个
    if "rb99.csv" in file_list:
        file_list.remove("rb99.csv")
        file_list = ["rb99.csv"] + file_list
    
    datas = {}
    for file in file_list:
        if not file.endswith('.csv'):
            continue
        name = file[:-4]
        df = pd.read_csv(data_path / file)
        # 只要数据里面的这几列
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
        # 修改列的名字
        df.index = pd.to_datetime(df['datetime'])
        df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
        df = df[(df.index <= data_kwargs['todate']) & (df.index >= data_kwargs['fromdate'])]
        if len(df) == 0:
            continue
        datas[name] = df
    
    return datas


def test_keltner_strategy():
    """测试 Keltner Channel 多合约期货策略
    
    使用螺纹钢期货多合约数据进行回测
    """
    # 创建 cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # 加载多合约数据
    print("正在加载螺纹钢期货多合约数据...")
    datas = load_rb_multi_data("rb")
    print(f"共加载 {len(datas)} 个合约数据")

    # 使用 RbPandasFeed 加载数据
    for name, df in datas.items():
        feed = RbPandasFeed(dataname=df)
        cerebro.adddata(feed, name=name)
        # 设置合约的交易信息
        comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
        cerebro.broker.addcommissioninfo(comm, name=name)

    cerebro.broker.setcash(50000.0)

    # 添加策略
    cerebro.addstrategy(KeltnerStrategy)

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
    print("Keltner Channel 策略回测结果:")
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
    # Note: Expected values updated to match actual behavior on both master and refactored branches
    # after fixing rb99.csv case sensitivity issue (renamed from RB99.csv to rb99.csv)
    assert strat.bar_num == 28096, f"Expected bar_num=28096, got {strat.bar_num}"
    assert strat.buy_count == 239, f"Expected buy_count=239, got {strat.buy_count}"
    assert strat.sell_count == 239, f"Expected sell_count=239, got {strat.sell_count}"
    assert total_trades == 268, f"Expected total_trades=268, got {total_trades}"
    assert abs(sharpe_ratio - 0.570492319408031) < 0.01, f"Expected sharpe_ratio~0.570, got {sharpe_ratio}"
    assert abs(annual_return - 0.056895728119219044) < 0.01, f"Expected annual_return~0.057, got {annual_return}"
    assert abs(max_drawdown - 0.17834085840372663) < 0.01, f"Expected max_drawdown~0.178, got {max_drawdown}"
    assert abs(final_value - 91078.02) < 100, f"Expected final_value~91078, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Keltner Channel 多合约期货策略测试")
    print("=" * 60)
    test_keltner_strategy()