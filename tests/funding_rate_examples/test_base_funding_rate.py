import datetime
import pandas as pd
import backtrader as bt
import matplotlib.pyplot as plt
from pathlib import Path
from backtrader.comminfo import ComminfoFundingRate


# 在交易信息之外，额外增加了其他指标，
class GenericFundingRateCsv(bt.feeds.GenericCSVData):
    # 增加两个line,每个line的名称，就是csv文件中，额外增加的列的名称
    lines = ('quote_volume',
             'count',
             'taker_buy_volume',
             'taker_buy_quote_volume',
             'mark_price_open',
             'mark_price_close',
             'current_funding_rate',
             )

    # 具体每个新增加的变量index是多少，要根据自己的csv文件去决定，从0开始数
    params = (('quote_volume', 6),
              ('count', 7),
              ('taker_buy_volume', 8),
              ('taker_buy_quote_volume', 9),
              ('mark_price_open', 10),
              ('mark_price_close', 11),
              ('current_funding_rate', 12),
              )


def get_data_root(symbol):
    # 获取当前文件的绝对路径
    current_file_path = Path(__file__).resolve()
    # 获取当前文件所在的目录
    current_dir_path = current_file_path.parent
    # 获取上一级目录
    parent_dir_path = current_dir_path.parent
    # 拼接上一级目录和datas目录
    data_root = parent_dir_path.joinpath('datas')
    # 拼接datas目录和symbol文件名
    data_file_path = data_root.joinpath(f"fake_kline_{symbol}.csv")
    print("data_file_path", data_file_path)
    return data_file_path

# 我们使用的时候，直接用我们新的类读取数据就可以了。
class FundingRateStrategy(bt.Strategy):
    params = ()

    def log(self, txt, dt=None):
        """Logging function fot this strategy"""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        self.bar_num = 0
        # self.gas_avg_funding_rate = bt.indicators.SMA(
        #     self.getdatabyname("gasusdt").current_funding_rate, period=30)
        # self.token_avg_funding_rate = bt.indicators.SMA(
        #     self.getdatabyname("tokenusdt").current_funding_rate, period=30)
        self.data_name_list = ["gasusdt", "tokenusdt"]

    def prenext(self):
        pass
        # for name in self.data_name_list:
        #     data = self.getdatabyname(name)
        #     self.log(
        #         f"data_name: {data._name}, "
        #         f"close:{data.close[0]},"
        #         f"funding_rate:{data.current_funding_rate[0]},")

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # order被提交和接受
            return
        if order.status == order.Rejected:
            self.log(f"order is rejected : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Margin:
            self.log(f"order need more margin : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Cancelled:
            self.log(f"order is cancelled : order_ref:{order.ref}  order_info:{order.info}")
        if order.status == order.Partial:
            self.log(f"order is partial : order_ref:{order.ref}  order_info:{order.info}")
        # Check if an order has been completed
        # Attention: broker could reject order if not enougth cash
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"{order.data._name} buy order : "
                         f"price : {round(order.executed.price, 6)} , "
                         f"size : {round(order.executed.size, 6)} , "
                         f"margin : {round(order.executed.value, 6)} , "
                         f"cost : {round(order.executed.comm, 6)}")

            else:  # Sell
                self.log(f"{order.data._name} sell order : "
                         f"price : {round(order.executed.price, 6)} , "
                         f"size : {round(order.executed.size, 6)} , "
                         f"margin : {round(order.executed.value, 6)} , "
                         f"cost : {round(order.executed.comm, 6)}")

    def notify_trade(self, trade):
        # 一个trade结束的时候输出信息
        if trade.isclosed:
            self.log(f'closed symbol is : {trade.getdataname()} , '
                     f'total_profit : {round(trade.pnl, 6)} , '
                     f'net_profit : {round(trade.pnlcomm, 6)}')
        if trade.isopen:
            self.log(f'open symbol is : {trade.getdataname()} , price : {trade.price} ')

    def next(self):
        # 有一些简化的高级用法并没有使用，只是为了展示一些基础用法
        # 当进行交易的时候，需要根据条件买卖fake_gasusdt和fake_tokenusdt
        self.bar_num += 1
        # for name in self.data_name_list:
        #     data = self.getdatabyname(name)
        #     self.log(
        #         f"data_name: {data._name}, "
        #         f"close:{data.close[0]},"
        #         f"funding_rate:{data.current_funding_rate[0]},")
        # 如果当前持仓是0
        gas_data = self.getdatabyname("gasusdt")
        token_data = self.getdatabyname("tokenusdt")
        gas_position = self.getposition(gas_data).size
        token_position = self.getposition(token_data).size
        total_value = self.broker.getvalue()
        gas_price = gas_data.close[0]
        token_price = token_data.close[0]
        # 如果当前持仓是0，且当前的资金费率大于平均资金费率，则买入
        if gas_position == 0 and token_position == 0:
            target_gas_size = 1000000 / gas_price
            target_token_size = 1000000 / token_price
            self.log(f"total_value = {total_value} , ")
            self.sell(data=token_data, size=target_token_size)
            self.buy(data=gas_data, size=target_gas_size)
            # self.log(f"gas_avg_funding_rate = {self.gas_avg_funding_rate[0]}")
            # self.log(f"token_avg_funding_rate = {self.token_avg_funding_rate[0]}")
            # 如果当前gas的平均资金费率大于token的平均资金费率，则卖出gas，买入token
            # if self.gas_avg_funding_rate[0] > self.token_avg_funding_rate[0]:
            #     self.sell(data=gas_data, size=target_gas_size)
            #     self.buy(data=token_data, size=target_token_size)
            # 为了产生资金费率，同步买入虚拟的gas和token

            # 如果当前token的平均资金费率大于gas的平均资金费率，则卖出token，买入gas
            # elif self.token_avg_funding_rate[0] > self.gas_avg_funding_rate[0]:
            #     self.sell(data=token_data, size=target_token_size)
            #     self.buy(data=gas_data, size=target_gas_size)
        if gas_position != 0 or token_position != 0:
            try:
                _gas_price = gas_data.close[2]
                _token_price = gas_data.close[2]
            except Exception as e:
                self.log(e)
                self.close(gas_data)
                self.close(token_data)
                self.log(f"{gas_data._name} close position")
                self.log(f"{token_data._name} close position")
        # elif gas_position < 0 and self.gas_avg_funding_rate[0] < self.token_avg_funding_rate[0]:
        #     # 如果当前gas的平均资金费率大于token的平均资金费率，平仓，反向卖出
        #     self.buy(gas_data, size=abs(gas_position))
        #     self.sell(token_data, size=abs(token_position))
        #     target_gas_size = 1000000 / gas_price
        #     target_token_size = 1000000 / token_price
        #     self.sell(data=token_data, size=target_token_size)
        #     self.buy(data=gas_data, size=target_gas_size)
        # elif gas_position > 0 and self.gas_avg_funding_rate[0] > self.token_avg_funding_rate[0]:
        #     # self.close(gas_data)
        #     # self.close(token_data)
        #     self.sell(gas_data, size=abs(gas_position))
        #     self.buy(gas_data, size=abs(token_position))
        #     target_gas_size = 1000000 / gas_price
        #     target_token_size = 1000000 / token_price
        #     self.sell(data=gas_data, size=target_gas_size)
        #     self.buy(data=token_data, size=target_token_size)


def run_strategy():
    cerebro = bt.Cerebro()
    symbol_list = ["gasusdt", "tokenusdt"]
    for symbol in symbol_list:
        # 由于是datetime，所以要添加一个参数，使得backtrader能够识别的日期和csv文件中的日期格式是一样的
        # data_path = "../datas/merge_kline_and_funding_rate_" + symbol + ".csv"
        data_file_path = get_data_root(symbol)
        gas_feed = GenericFundingRateCsv(dataname=data_file_path,
                                         **{"dtformat": "%Y-%m-%d %H:%M:%S",
                                            "timeframe": bt.TimeFrame.Minutes,
                                            "compression": 60,
                                            # "fromdate": datetime.datetime(2024, 11, 15)
                                            })
        # 添加gasusdt数据到cerebro
        cerebro.adddata(gas_feed, name=symbol)
        # 添加手续费，按照万分之六收取
        comm = ComminfoFundingRate(commission=0.0000, margin=0.10, mult=1)
        cerebro.broker.addcommissioninfo(comm, name=symbol)

    # 设置初始资金为100万
    cerebro.broker.setcash(1000000.0)
    # 添加策略
    cerebro.addstrategy(FundingRateStrategy)
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name='my_value')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='my_sharpe')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='my_returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='my_drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='my_trade_analyzer')

    # cerebro.addanalyzer(bt.analyzers.PyFolio)
    # 运行回测
    results = cerebro.run()
    # sharpe_ratio = results[0].analyzers.my_sharpe.get_analysis()['sharperatio']
    # annual_return = results[0].analyzers.my_returns.get_analysis()['rnorm']
    # max_drawdown = results[0].analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    # trade_num = results[0].analyzers.my_trade_analyzer.get_analysis()['total']['total']
    value_df = pd.DataFrame([results[0].analyzers.my_value.get_analysis()]).T
    value_df.columns = ['value']
    value_df['datetime'] = pd.to_datetime(value_df.index)
    value_df.index = value_df['datetime']
    value_df['date'] = [i.date() for i in value_df['datetime']]
    value_df = value_df.drop_duplicates("date", keep="last")
    value_df = value_df[['value']]
    return value_df
    # value_df.plot()
    # plt.show()
    # 画图
    # cerebro.plot()


def get_expected_value():
    # 读取数据
    gas_data_file_path = get_data_root("gasusdt")
    token_data_file_path = get_data_root("tokenusdt")
    init_gas_data = pd.read_csv(gas_data_file_path, index_col=0)
    init_token_data = pd.read_csv(token_data_file_path, index_col=0)

    # 找到两个数据集的共同起始日期+1
    begin_date = max(init_gas_data.index[1], init_token_data.index[1])

    # 从共同起始日期开始切片
    gas_data = init_gas_data.loc[begin_date:].copy()  # 使用 .copy() 避免 SettingWithCopyWarning
    token_data = init_token_data.loc[begin_date:].copy()  # 使用 .copy() 避免 SettingWithCopyWarning
    # print(gas_data.head(2))
    # print(token_data.head(2))
    # 计算 next_funding_rate 和 value
    gas_data['next_funding_rate'] = gas_data['current_funding_rate'].shift(-1)
    gas_data['value'] = -1 * gas_data['next_funding_rate'] * 1000000

    token_data['next_funding_rate'] = token_data['current_funding_rate'].shift(-1)
    token_data['value'] = -1 * token_data['next_funding_rate'] * (-1000000)

    # 填充 NaN 值
    gas_data['value'] = gas_data['value'].fillna(0)
    token_data['value'] = token_data['value'].fillna(0)

    # 创建一个新的 DataFrame
    df = pd.DataFrame(index=init_gas_data.index)
    df['value'] = gas_data['value'] + token_data['value']
    df['value'] = df['value'].fillna(0)
    # df.to_csv("expected_value_daily.csv")

    # 计算累积值
    df['cumsum_value'] = df['value'].cumsum()
    df['cumsum_value'] = df['cumsum_value'] + 1000000

    # 处理日期
    df['datetime'] = pd.to_datetime(df.index)
    df['date'] = df['datetime'].dt.date

    # 去重并保留最后一个值
    df = df.drop_duplicates("date", keep="last")

    # 选择需要的列
    df = df[['cumsum_value']]
    df.columns = ['value']
    # df.to_csv("expected_value.csv")
    return df


def test_base_funding_rate():
    actual_value_df = run_strategy()
    actual_value_list = actual_value_df['value'].tolist()
    expected_value_df = get_expected_value()
    expected_value_list = expected_value_df['value'].tolist()
    for actual_value, expected_value in zip(actual_value_list, expected_value_list):
        assert abs(actual_value - expected_value) < 1e-6

    # assert actual_value_df['value'].tolist() == expected_value_df['value'].tolist()


if __name__ == '__main__':
    test_base_funding_rate()
