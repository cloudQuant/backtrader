"""国债期货MACD策略测试用例

使用中金所期货合约数据测试MACD策略
- 使用 PandasDirectData 加载期货数据
- 基于MACD指标的期货策略，支持移仓换月
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


class TreasuryFuturesMacdStrategy(bt.Strategy):
    # 策略作者
    author = 'yunjinqi'
    # 策略的参数
    params = (("period_me1", 10),
              ("period_me2", 20),
              ("period_dif", 9),

              )

    # log相应的信息
    def log(self, txt, dt=None):
        ''' Logging function fot this strategy'''
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    # 初始化策略的数据
    def __init__(self):
        # 基本上常用的部分属性变量
        self.bar_num = 0  # next运行了多少个bar
        self.buy_count = 0
        self.sell_count = 0
        self.current_date = None  # 当前交易日
        # 计算macd指标
        self.ema_1 = bt.indicators.ExponentialMovingAverage(self.datas[0].close, period=self.p.period_me1)
        self.ema_2 = bt.indicators.ExponentialMovingAverage(self.datas[0].close, period=self.p.period_me2)
        self.dif = self.ema_1 - self.ema_2
        self.dea = bt.indicators.ExponentialMovingAverage(self.dif, period=self.p.period_dif)
        self.macd = (self.dif - self.dea) * 2
        # 保存现在持仓的合约是哪一个
        self.holding_contract_name = None

    def prenext(self):
        # 由于期货数据有几千个，每个期货交易日期不同，并不会自然进入next
        # 需要在每个prenext中调用next函数进行运行
        self.next()
        # pass

    # 在next中添加相应的策略逻辑
    def next(self):
        # 每次运行一次，bar_num自然加1,并更新交易日
        self.current_date = bt.num2date(self.datas[0].datetime[0])
        self.bar_num += 1
        # self.log(f"{self.bar_num},{self.datas[0]._name},{self.broker.getvalue()}")
        # self.log(f"{self.ema_1[0]},{self.ema_2[0]},{self.dif[0]},{self.dea[0]},{self.macd[0]}")
        data = self.datas[0]
        # 开仓，先平后开
        # 平多
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size > 0 and \
                data.close[0] < self.ema_1[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.holding_contract_name = None
        # 平空
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size < 0 and \
                data.close[0] > self.ema_1[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.holding_contract_name = None

        # 开多
        if self.holding_contract_name is None and self.ema_1[-1] < self.ema_2[-1] and self.ema_1[0] > self.ema_2[0] and \
                self.macd[0] > 0:
            dominant_contract = self.get_dominant_contract()
            next_data = self.getdatabyname(dominant_contract)
            self.buy(next_data, size=1)
            self.buy_count += 1
            self.holding_contract_name = dominant_contract

        # 开空
        if self.holding_contract_name is None and self.ema_1[-1] > self.ema_2[-1] and self.ema_1[0] < self.ema_2[0] and \
                self.macd[0] < 0:
            dominant_contract = self.get_dominant_contract()
            next_data = self.getdatabyname(dominant_contract)
            self.sell(next_data, size=1)
            self.sell_count += 1
            self.holding_contract_name = dominant_contract

        # 移仓换月
        if self.holding_contract_name is not None:
            dominant_contract = self.get_dominant_contract()
            # 如果出现了新的主力合约，那么就开始换月
            if dominant_contract != self.holding_contract_name:
                # 下个主力合约
                next_data = self.getdatabyname(dominant_contract)
                # 当前合约持仓大小及数据
                size = self.getpositionbyname(self.holding_contract_name).size  # 持仓大小
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

        # 以持仓量最大的合约作为主力合约,返回数据的名称
        # 可以根据需要，自己定义主力合约怎么计算

        # 获取当前在交易的品种
        target_datas = []
        for data in self.datas[1:]:
            # self.log(self.current_date)
            # self.log(bt.num2date(data.datetime[0]))
            try:
                data_date = bt.num2date(data.datetime[0])
                # self.log(f"{data._name},{data_date}")
                if self.current_date == data_date:
                    target_datas.append([data._name, data.openinterest[0]])
            except:
                self.log(f"{data._name}还未上市交易")

        target_datas = sorted(target_datas, key=lambda x: x[1])
        print(target_datas)
        return target_datas[-1][0]

    def notify_order(self, order):

        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Rejected:
            self.log(f"Rejected : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Margin:
            self.log(f"Margin : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Cancelled:
            self.log(f"Concelled : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Partial:
            self.log(f"Partial : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    f" BUY : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

            else:  # Sell
                self.log(
                    f" SELL : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

    def notify_trade(self, trade):
        # 一个trade结束的时候输出信息
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
            # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def stop(self):
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


def load_futures_data(variety: str = "T"):
    """加载期货数据并构建指数合约
    
    Args:
        variety: 品种代码，默认为T（国债期货）
    
    Returns:
        index_df: 指数合约DataFrame
        data: 原始数据DataFrame
    """
    data = pd.read_csv(resolve_data_path("中金所期货合约数据.csv"), index_col=0)
    data = data[data['variety'] == variety]
    data['datetime'] = pd.to_datetime(data['date'], format="%Y%m%d")
    data = data.dropna()
    
    # 根据持仓量加权合成指数合约
    result = []
    for index, df in data.groupby("datetime"):
        total_open_interest = df['open_interest'].sum()
        open_price = (df['open'] * df['open_interest']).sum() / total_open_interest
        high_price = (df['high'] * df['open_interest']).sum() / total_open_interest
        low_price = (df['low'] * df['open_interest']).sum() / total_open_interest
        close_price = (df['close'] * df['open_interest']).sum() / total_open_interest
        volume = (df['volume'] * df['open_interest']).sum() / total_open_interest
        open_interest = df['open_interest'].mean()
        result.append([index, open_price, high_price, low_price, close_price, volume, open_interest])
    
    index_df = pd.DataFrame(result, columns=['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest'])
    index_df.index = pd.to_datetime(index_df['datetime'])
    index_df = index_df.drop(["datetime"], axis=1)
    
    return index_df, data


def test_treasury_futures_macd_strategy():
    """测试国债期货MACD策略
    
    使用中金所期货合约数据进行回测
    """
    cerebro = bt.Cerebro(stdstats=True)

    # 加载期货数据
    print("正在加载期货数据...")
    index_df, data = load_futures_data("T")
    print(f"指数数据范围: {index_df.index[0]} 至 {index_df.index[-1]}, 共 {len(index_df)} 条")

    # 加载指数合约
    feed = bt.feeds.PandasDirectData(dataname=index_df)
    cerebro.adddata(feed, name='index')
    comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
    cerebro.broker.addcommissioninfo(comm, name="index")

    # 加载具体合约数据
    contract_count = 0
    for symbol, df in data.groupby("symbol"):
        df.index = pd.to_datetime(df['datetime'])
        df = df[['open', 'high', 'low', 'close', 'volume', 'open_interest']]
        df.columns = ['open', 'high', 'low', 'close', 'volume', 'openinterest']
        feed = bt.feeds.PandasDirectData(dataname=df)
        cerebro.adddata(feed, name=symbol)
        comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
        cerebro.broker.addcommissioninfo(comm, name=symbol)
        contract_count += 1
    
    print(f"成功加载 {contract_count} 个合约")

    # 设置初始资金
    cerebro.broker.setcash(1000000.0)

    # 添加策略
    cerebro.addstrategy(TreasuryFuturesMacdStrategy, period_me1=10, period_me2=20, period_dif=9)

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
    print("国债期货MACD策略回测结果:")
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
    assert strat.bar_num == 1990, f"Expected bar_num=1990, got {strat.bar_num}"
    assert strat.buy_count == 38, f"Expected buy_count=38, got {strat.buy_count}"
    assert strat.sell_count == 38, f"Expected sell_count=38, got {strat.sell_count}"
    assert total_trades == 90, f"Expected total_trades=90, got {total_trades}"
    assert abs(sharpe_ratio - (-700.977360693882)) < 1e-6, f"Expected sharpe_ratio=-700.977360693882, got {sharpe_ratio}"
    assert abs(annual_return - (-2.2430503547013427e-06)) < 1e-12, f"Expected annual_return=-2.2430503547013427e-06, got {annual_return}"
    assert abs(max_drawdown - 6.587175196273877e-05) < 1e-9, f"Expected max_drawdown=6.587175196273877e-05, got {max_drawdown}"
    assert abs(final_value - 999982.2871600012) < 0.01, f"Expected final_value=999982.2871600012, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("国债期货MACD策略测试")
    print("=" * 60)
    test_treasury_futures_macd_strategy()
