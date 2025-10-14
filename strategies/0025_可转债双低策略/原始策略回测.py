import sys
import pandas as pd
import numpy as np
import backtrader as bt


class ExtendPandasFeed(bt.feeds.PandasData):
    """
    扩展的Pandas数据源，添加可转债特有的字段
    
    重要说明：
    当DataFrame使用 set_index('datetime') 后，datetime列变成索引而非数据列。
    因此列索引需要从0开始重新计算，不包括datetime。
    
    DataFrame结构（set_index后）：
    - 索引：datetime
    - 列0：open
    - 列1：high
    - 列2：low
    - 列3：close
    - 列4：volume
    - 列5：pure_bond_value
    - 列6：convert_value
    - 列7：pure_bond_premium_rate
    - 列8：convert_premium_rate
    """
    params = (
        ('datetime', None),  # datetime是索引，不是数据列
        ('open', 0),         # 第1列 -> 索引0
        ('high', 1),         # 第2列 -> 索引1
        ('low', 2),          # 第3列 -> 索引2
        ('close', 3),        # 第4列 -> 索引3
        ('volume', 4),       # 第5列 -> 索引4
        ('openinterest', -1),  # 不存在该列
        ('pure_bond_value', 5),  # 第6列 -> 索引5
        ('convert_value', 6),  # 第7列 -> 索引6
        ('pure_bond_premium_rate', 7),  # 第8列 -> 索引7
        ('convert_premium_rate', 8)  # 第9列 -> 索引8
    )
    
    # 定义扩展的数据线
    lines = ('pure_bond_value', 'convert_value', 'pure_bond_premium_rate', 'convert_premium_rate')

def clean_data():
    """清洗可转债数据"""
    df = pd.read_csv('bond_merged_all_data.csv')
    df.columns = ['symbol', 'bond_symbol', 'datetime', 'open', 'high', 'low', 'close', 'volume',
                    'pure_bond_value','convert_value','pure_bond_premium_rate','convert_premium_rate']
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    datas = {}
    for symbol, data in df.groupby('symbol'):
        data = data.set_index('datetime')
        data = data.drop(['symbol', 'bond_symbol'],axis=1)
        data = data.dropna()
        datas[symbol] = data.astype("float")
    
    return datas





class BondConvertTwoFactor(bt.Strategy):
    # params = (('short_window',10),('long_window',60))
    params = (("first_factor_weight", 0.5),
              ("second_factor_weight", 0.5),
              ("choose_percent", 0.2),
              ("hold_days", 22)
              )

    def log(self, txt, dt=None):
        """log信息的功能"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        # 一般用于计算指标或者预先加载数据，定义变量使用
        pass

    def next(self):
        # 得到当前的数据,并输出必要信息
        data = self.datas[0]
        self.log(f"close:{data.close[0]},fx_type:{data.pure_bond_premium_rate[0]}, fx_price:{data.convert_premium_rate[0]}")



    # def notify_order(self, order):
    #     if order.status in [order.Submitted, order.Accepted]:
    #         # order被提交和接受
    #         return
    #     if order.status == order.Rejected:
    #         self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
    #     if order.status == order.Margin:
    #         self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
    #     if order.status == order.Cancelled:
    #         self.log(f"order is concelled : order_ref:{order.ref}  order_info:{order.info}")
    #     if order.status == order.Partial:
    #         self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
    #     # Check if an order has been completed
    #     # Attention: broker could reject order if not enougth cash
    #     if order.status == order.Completed:
    #         if order.isbuy():
    #             self.log("buy result : buy_price : {} , buy_cost : {} , commission : {}".format(
    #                 order.executed.price, order.executed.value, order.executed.comm))
    #
    #         else:  # Sell
    #             self.log("sell result : sell_price : {} , sell_cost : {} , commission : {}".format(
    #                 order.executed.price, order.executed.value, order.executed.comm))
    #
    # def notify_trade(self, trade):
    #     # 一个trade结束的时候输出信息
    #     if trade.isclosed:
    #         self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
    #             trade.getdataname(), trade.pnl, trade.pnlcomm))
    #     if trade.isopen:
    #         self.log('open symbol is : {} , price : {} '.format(
    #             trade.getdataname(), trade.price))


def run_test_strategy(max_bonds=None, stdstats=True):
    """
    运行可转债双低策略回测
    
    参数:
        max_bonds: 最大添加的可转债数量，None表示添加所有。用于测试时可设置较小值
        stdstats: 是否启用标准统计观察者（默认True）
                 True: 显示现金、市值、买卖点等标准统计
                 False: 禁用标准统计，可能稍微提升性能
    """
    # 添加cerebro
    # 修复说明：之前需要设置stdstats=False是因为ExtendPandasFeed的列索引定义错误
    # 现已修复，可以正常使用stdstats=True
    cerebro = bt.Cerebro(stdstats=stdstats)
    
    # 添加策略
    cerebro.addstrategy(BondConvertTwoFactor)
    
    # 添加指数数据
    print("正在加载指数数据...")
    index_data = pd.read_csv('bond_index_000000.csv')
    index_data.index = pd.to_datetime(index_data['datetime'])
    index_data = index_data.drop(['datetime'], axis=1)
    print(f"指数数据范围: {index_data.index[0]} 至 {index_data.index[-1]}, 共 {len(index_data)} 条")
    
    feed = ExtendPandasFeed(dataname=index_data)
    cerebro.adddata(feed, name='000000')
    
    # 清洗数据并添加可转债数据
    print("\n正在加载可转债数据...")
    datas = clean_data()
    print(f"总共有 {len(datas)} 只可转债")
    
    added_count = 0
    for symbol, data in datas.items():
        if len(data) > 30:
            # 如果设置了最大数量限制，达到限制后停止添加
            if max_bonds is not None and added_count >= max_bonds:
                break
                
            feed = ExtendPandasFeed(dataname=data)
            # 添加合约数据
            cerebro.adddata(feed, name=symbol)
            added_count += 1
            
            # 每添加100个打印一次进度
            if added_count % 100 == 0:
                print(f"已添加 {added_count} 只可转债...")
    
    print(f"\n成功添加 {added_count} 只可转债数据")
    
    # 添加资金
    cerebro.broker.setcash(100000.0)
    # 设置佣金
    cerebro.broker.setcommission(commission=0.0001)
    
    print("\n开始运行回测...")
    # 开始运行（在循环外，只运行一次）
    results = cerebro.run()
    
    # 打印最终价值
    final_value = cerebro.broker.getvalue()
    print(f"\n回测完成！")
    print(f"初始资金: 100000.00")
    print(f"最终价值: {final_value:.2f}")
    print(f"总收益: {final_value - 100000:.2f}")
    print(f"收益率: {(final_value / 100000 - 1) * 100:.2f}%")
    
    return results


if __name__ == "__main__":
    # 如果需要生成指数数据，取消下面的注释
    # from 清洗数据 import generate_index_data
    # generate_index_data(input_file='bond_merged_all_data.csv', output_file='bond_index_000000.csv')
    
    # 运行回测策略
    # 参数说明:
    #   max_bonds=None: 添加所有可转债（可能比较慢）
    #   max_bonds=50: 只添加前50只可转债（用于快速测试）
    #   max_bonds=200: 添加200只可转债（推荐用于正式回测）
    
    print("="*60)
    print("可转债双低策略回测系统")
    print("="*60)
    
    # 运行回测 - 添加所有可转债
    # 注意：由于有958只可转债，运行可能需要较长时间
    run_test_strategy(max_bonds=None)
    
    print("\n" + "="*60)
    print("回测结束")
    print("="*60)
