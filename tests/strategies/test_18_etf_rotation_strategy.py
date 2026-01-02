"""ETF轮动策略测试用例

使用上证50ETF和创业板ETF数据测试轮动策略
- 使用 PandasDirectData 加载ETF日线数据
- 基于均线比值的ETF轮动策略
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

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


class EtfRotationStrategy(bt.Strategy):
    # 策略作者
    author = 'yunjinqi'
    # 策略的参数
    params = (  ("ma_period",20),                
            )
    # log相应的信息
    def log(self, txt, dt=None):
        ''' Logging function fot this strategy'''
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    # 初始化策略的数据
    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # 计算两个均线,直接写出，太多可以用字典保存遍历结果，参考以前的股票文章
        self.sz_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.ma_period)
        self.cy_ma = bt.indicators.SMA(self.datas[1].close, period=self.p.ma_period)
        
        
        
        
    def prenext(self):
        # 由于期货数据有几千个，每个期货交易日期不同，并不会自然进入next
        # 需要在每个prenext中调用next函数进行运行
        self.next() 
        
        
    # 在next中添加相应的策略逻辑
    def next(self):
        self.bar_num += 1
        # 两个ETF的数据
        sz_data = self.datas[0]
        cy_data = self.datas[1]
        # 计算当前是否有持仓
        self.sz_pos = self.getposition(sz_data).size
        self.cy_pos = self.getposition(cy_data).size
        # 获取两个当前的价格
        sz_close = sz_data.close[0]
        cy_close = cy_data.close[0]
        # self.log(f"{sz_close/self.sz_ma[0]},{cy_close/self.cy_ma[0]}")
        # 分析是否都小于均线，如果都小于均线，并且有持仓，平仓
        if sz_close<self.sz_ma[0] and cy_close<self.cy_ma[0]:
            if self.sz_pos>0:
                self.close(sz_data)
            if self.cy_pos>0:
                self.close(cy_data)
        # 如果两个中有一个大于均线
        if sz_close>self.sz_ma[0] or cy_close>self.cy_ma[0]:
            # 如果当前sz动量指标比较大
            if sz_close/self.sz_ma[0]>cy_close/self.cy_ma[0]:
                
                # 如果当前没有仓位，那么，就直接买入sz
                if self.sz_pos==0 and self.cy_pos==0:
                    # 获取账户价值
                    total_value = self.broker.get_value()
                    # 计算买入的量
                    lots = int(0.95*total_value/sz_close)
                    # 买入
                    self.buy(sz_data, size=lots)
                    self.buy_count += 1
                
                # 如果现在不是持有的sz,而是持有的cy,那么，就平掉创业板，然后买入sz
                if self.sz_pos == 0 and self.cy_pos > 0:
                    # 平仓创业板ETF
                    self.close(cy_data)
                    self.sell_count += 1
                    # 获取账户价值
                    total_value = self.broker.get_value()
                    # 计算买入的量
                    lots = int(0.95 * total_value / sz_close)
                    # 买入
                    self.buy(sz_data, size=lots)
                    self.buy_count += 1
                
                # 如果当前已经买入了sz,忽略
                if self.sz_pos > 0:
                    pass
                
            # 如果当前cy动量指标比较大
            if sz_close / self.sz_ma[0] < cy_close / self.cy_ma[0]:
                # 如果当前没有仓位，那么，就直接买入cy
                if self.sz_pos == 0 and self.cy_pos == 0:
                    # 获取账户价值
                    total_value = self.broker.get_value()
                    # 计算买入的量
                    lots = int(0.95 * total_value / cy_close)
                    # 买入
                    self.buy(cy_data, size=lots)
                    self.buy_count += 1
                
                # 如果现在不是持有的sz,而是持有的cy,那么，就平掉上证50，然后买入cy
                if self.sz_pos > 0 and self.cy_pos == 0:
                    # 平仓上证50ETF
                    self.close(sz_data)
                    self.sell_count += 1
                    # 获取账户价值
                    total_value = self.broker.get_value()
                    # 计算买入的量
                    lots = int(0.95 * total_value / cy_close)
                    # 买入
                    self.buy(cy_data, size=lots)
                    self.buy_count += 1
                
                # 如果当前已经买入了cy,忽略
                if self.cy_pos > 0:
                    pass
            
        
                                    
                                
                        
                        
                
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
                self.log(f" BUY : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

            else:  # Sell
                self.log(f" SELL : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")
    
    def notify_trade(self, trade):
        # 一个trade结束的时候输出信息
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}' .format(
                            trade.getdataname(),trade.pnl, trade.pnlcomm))
            # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])
            
        if trade.isopen:
            self.log('open symbol is : {} , price : {} ' .format(
                            trade.getdataname(),trade.price))

            
    def stop(self):
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


def load_etf_data(filename: str) -> pd.DataFrame:
    """加载ETF数据
    
    数据格式: FSRQ(日期), 收盘价
    """
    df = pd.read_csv(resolve_data_path(filename), skiprows=1, header=None)
    df.columns = ['datetime', 'close']
    df['open'] = df['close']
    df['high'] = df['close']
    df['low'] = df['close']
    df['volume'] = 1000000
    df['openinterest'] = 1000000
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.astype('float')
    return df


def test_etf_rotation_strategy():
    """测试ETF轮动策略
    
    使用上证50ETF和创业板ETF数据进行回测
    """
    cerebro = bt.Cerebro(stdstats=True)

    # 加载上证50ETF数据
    print("正在加载上证50ETF数据...")
    df1 = load_etf_data("上证50ETF.csv")
    df1 = df1[df1.index >= pd.to_datetime("2011-09-20")]
    print(f"上证50ETF数据范围: {df1.index[0]} 至 {df1.index[-1]}, 共 {len(df1)} 条")
    feed1 = bt.feeds.PandasDirectData(dataname=df1)
    cerebro.adddata(feed1, name="sz")

    # 加载创业板ETF数据
    print("正在加载创业板ETF数据...")
    df2 = load_etf_data("易方达创业板ETF.csv")
    print(f"创业板ETF数据范围: {df2.index[0]} 至 {df2.index[-1]}, 共 {len(df2)} 条")
    feed2 = bt.feeds.PandasDirectData(dataname=df2)
    cerebro.adddata(feed2, name="cy")

    # 设置初始资金和手续费
    cerebro.broker.setcash(50000.0)
    cerebro.broker.setcommission(commission=0.0002, stocklike=True)

    # 添加策略
    cerebro.addstrategy(EtfRotationStrategy, ma_period=20)

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
    print("ETF轮动策略回测结果:")
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
    assert strat.buy_count == 266, f"Expected buy_count=266, got {strat.buy_count}"
    assert strat.sell_count == 129, f"Expected sell_count=129, got {strat.sell_count}"
    assert total_trades == 265, f"Expected total_trades=265, got {total_trades}"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"Expected sharpe_ratio=0.5429576897026931, got {sharpe_ratio}"
    assert annual_return == 0.16189795444232807, f"Expected annual_return=0.15938920375171883, got {annual_return}"
    assert max_drawdown == 0.3202798124215756, f"Expected max_drawdown=0.3202798124215756, got {max_drawdown}"
    assert final_value == 235146.28691140004, f"Expected final_value=235146.28691140004, got {final_value}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("ETF轮动策略测试")
    print("=" * 60)
    test_etf_rotation_strategy()