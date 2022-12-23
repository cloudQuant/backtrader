import copy

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import alphalens
from backtrader.vectors.cal_performance import *

# 排除的品种
remove_symbol = ["BB", "PG", "BB", "ER", "FB", "JR", "LR", "NR", "PM", "RR", "RS", "WH", "WR", "WS"]


class AlphaCs(object):
    def __init__(self, datas, params):
        # datas是字典格式，key是品种的名字，value是df格式，index是datetime,包含open,high,low,close,volume,openinterest
        self.datas = datas
        self.params = params
        # 初始化后续可能使用到的属性
        self.factors = None
        self.signals = None
        self.returns = None
        self.values = None
        self.prices = None
        self.symbol = None
        self.alphalens_factors = None

    def cal_alpha(self, data):
        # 生成实例的时候覆盖这个函数，用于计算具体的因子，列名为factor
        return data

    def cal_factors(self):
        # 这个目前看也是没问题的
        # 根据自定义的alpha公式，计算因子值
        self.factors = pd.DataFrame()
        for symbol in self.datas:
            self.symbol = symbol
            # print("cal_factors", self.symbol)
            df = self.datas[symbol]
            df = self.cal_alpha(df)
            df = df[['factor']]
            df.columns = [symbol]
            self.factors = pd.concat([self.factors, df], axis=1, join="outer")
        # self.factors.to_csv("d:/result/test_factors.csv")

    def cal_signals(self):
        # 计算得到的信号已经和backtrader进行过对比,两者关于信号是一致的，目前暂时没有发现这个函数有问题，后期可能需要改进算法，提高运算效率
        # 计算信号，默认按照一定的比例进行多空排列生成信号并持有一定时间
        percent = self.params['percent']
        hold_days = self.params['hold_days']
        factors = self.factors
        # 计算多空信号,此处计算多空的方式存在问题，可能导致多空品种个数不一致,尝试使用新的方法
        col_list = list(factors.columns)
        factors['signal_dict'] = factors.apply(cal_signal_by_percent, axis=1, args=(percent,))
        for col in col_list:
            factors[col] = factors.apply(lambda row: get_value_from_dict(col, row['signal_dict']), axis=1)
        # 对所有的信号进行下移一位
        # signals = copy.deepcopy(factors)
        # signals = signals.drop("signal_dict", axis=1)
        # for col in col_list:
        #     signals[col] = signals[col].shift(1)
        signals = factors.shift(1).drop(columns="signal_dict")
        # assert signals.equals(signals_1)
        signals.index = range(len(signals))
        # signals.to_csv("d:/result/true_signal.csv")
        # 对多空信号进行处理
        index_list = list(signals.index)
        for i in range(1, len(signals) // hold_days + 2):
            end_index = i * hold_days + 1
            if end_index >= len(signals):
                end_index = len(signals)
            first_index = (i - 1) * hold_days + 1
            target = index_list[first_index:end_index]
            # print(first_index, end_index, target)
            if first_index == end_index:
                pass
            else:
                # print(first_index, target, signals)
                signals.iloc[target, :] = signals.iloc[first_index, :]
        signals.index = self.factors.index
        # signals.to_csv("d:/result/test_signal.csv")
        self.signals = signals
        # self.signals.to_csv("d:/result/test_signals.csv")

    def cal_returns(self):
        # 经过测试，signal和return计算结果都是和backtrader计算结果保持一致，那出问题的部分应该就是total_value部分的计算了
        # 根据高开低收的数据和具体的信号，计算资产的收益率和因子值，保存到self.returns和self.factors
        self.returns = pd.DataFrame()
        for symbol in self.datas:
            self.symbol = symbol
            data = self.datas[symbol]
            signal_df = self.signals[[symbol]]
            signal_df.columns = ['signal']
            data = pd.concat([data, signal_df], axis=1, join="inner")
            # data['signal'] = self.signals[symbol]
            # 前一个信号
            data.loc[:, "pre_signal"] = data['signal'].shift(1)
            # 下个信号
            data.loc[:, "next_signal"] = data['signal'].shift(-1)
            # # 删除信号相同的bar
            # data = data[data['signal'] != data['pre_signal']]
            # 计算收益率
            data['ret'] = data['close'].pct_change()
            # print(a)
            data['next_open'] = data['open'].shift(-1)
            # 上一个收盘价
            data.loc[:, "pre_close"] = data['close'].shift(1)
            # 前一个收盘价到下个开盘价之间的收益率
            data.loc[:, "next_open_pre_close_rate"] = data['next_open'] / data['pre_close'] - 1
            # 当前开盘到收盘的收益率
            data.loc[:, "close_open_rate"] = data['close'] / data['open'] - 1
            # 当前开盘价到下个开盘价的收益率
            data.loc[:, "next_open_open_rate"] = data['next_open'] / data['open'] - 1
            # 对信号收益率进行修改，逻辑比较绕，手写出来，一点点梳理
            # 信号变换一次
            data['ret'] = np.where((data['signal'] != data['next_signal']) & (data['signal'] == data['pre_signal']),
                                   data['next_open_pre_close_rate'], data['ret'])
            data['ret'] = np.where((data['signal'] != data['pre_signal']) & (data['signal'] == data['next_signal']),
                                   data['close_open_rate'], data['ret'])
            # 信号变换两次
            data['ret'] = np.where((data['signal'] != data['next_signal']) & (data['signal'] != data['pre_signal']),
                                   data['next_open_open_rate'], data['ret'])

            data['ret'] = data['ret'] * data['signal'] * data['signal']
            data = data[['ret']]
            data.columns = [symbol]
            data = data.dropna()
            self.returns = pd.concat([self.returns, data], axis=1, join="outer")
        # self.returns.to_csv("d:/result/test_returns.csv")

    def cal_total_value(self):
        # 根据再平衡的天数计算具体的收益率
        # 这个计算有问题，需要计算出来每个bar的累计收益率，最后再乘以信号，最后再乘以因子
        hold_days = self.params['hold_days']
        # 复制新的returns序列并设置index
        returns = copy.deepcopy(self.returns)
        returns.index = range(len(returns))
        signals = copy.deepcopy(self.signals)
        signals = signals.dropna()
        signals.index = range(len(signals))
        # 保存每次持仓的累计收益率
        self.values = pd.DataFrame()
        new_factor = 1
        index_list = list(returns.index)
        for i in range(1, len(returns) // hold_days + 2):
            end_index = i * hold_days
            if end_index >= len(returns):
                end_index = len(returns)
            first_index = (i - 1) * hold_days
            target = index_list[first_index:end_index]
            # print(target)
            new_df = returns.iloc[target, :]
            new_signal = signals.iloc[target, :]
            new_df = new_df + 1
            new_df = new_df.cumprod()
            new_df = new_df - 1
            # 去除所有列都是0的列
            new_df = new_df.dropna(axis=1)
            new_df = new_df.loc[:, ~(new_df == 0).all(axis=0)]
            # print(new_df)
            # print(new_signal)
            for col in new_df.columns:
                signal_list = new_signal[col].unique()
                # print(col,signal_list)
                # assert len(signal_list) == 1
                signal = signal_list[0]
                new_df.loc[:, col] = new_df[col] * signal
            # print(i, new_factor, new_df)
            new_df['total_value'] = new_df.mean(axis=1) + 1
            new_df['total_value'] = new_df['total_value'] * new_factor
            # new_df.to_csv(f"d:/result/{i}_returns.csv")
            # assert 0
            last_value = list(new_df['total_value'])[-1]
            new_factor = last_value
            self.values = pd.concat([self.values, new_df[['total_value']]])
        self.values.index = self.returns.index
        # self.values.to_csv("d:/result/test_total_value.csv")
        sharpe_ratio, average_rate, max_drawdown = get_rate_sharpe_drawdown(self.values)
        # look_back_days = self.params['look_back_days']
        # hold_days = self.params['hold_days']
        # percent = self.params['percent']
        file_name = ""
        result_list = []
        for key in self.params:
            file_name = file_name + f"{key}: {self.params[key]} "
            result_list.append(self.params[key])
        file_name += f"夏普率为:{sharpe_ratio},年化收益率为:{average_rate},最大回撤为:{max_drawdown}"
        print(file_name)
        result_list += [sharpe_ratio, average_rate, max_drawdown]

        return result_list

    def run(self):
        self.cal_factors()
        self.cal_signals()
        self.cal_returns()
        return self.cal_total_value()

    def plot(self):
        self.values[['total_value']].to_csv("d:/result/test_returns.csv")
        self.values[['total_value']].plot()
        plt.show()

    def run_alphalens(self,
                      groupby=None,
                      binning_by_group=False,
                      quantiles=5,
                      bins=None,
                      periods=(1, 5, 10),
                      filter_zscore=20,
                      groupby_labels=None,
                      max_loss=0.35,
                      zero_aware=False,
                      cumulative_returns=True,
                      long_short=True,
                      group_neutral=False,
                      by_group=False):
        self.alphalens_factors = pd.DataFrame()
        self.prices = pd.DataFrame()
        for symbol in self.datas:
            self.symbol = symbol
            # look_back_days = self.params['look_back_days']
            df = self.datas[symbol]
            # print("cs", symbol)
            df = self.cal_alpha(df)
            df['asset'] = symbol
            new_df = df[['close']]
            new_df.columns = [symbol]
            self.prices = pd.concat([self.prices, new_df], axis=1, join="outer")
            df = df[['trading_date', 'asset', 'factor']]
            self.alphalens_factors = pd.concat([self.alphalens_factors, df])
        self.alphalens_factors = self.alphalens_factors.sort_values(by=['trading_date', 'asset'])
        self.alphalens_factors = self.alphalens_factors.set_index(['trading_date', 'asset'])
        # print(self.alphalens_factors.tail())
        # print(self.prices.tail())
        # self.alphalens_factors.to_csv("d:/result/test_factor.csv")
        data = alphalens.utils.get_clean_factor_and_forward_returns(self.alphalens_factors, self.prices,
                                                                    groupby=groupby,
                                                                    binning_by_group=binning_by_group,
                                                                    quantiles=quantiles,
                                                                    bins=bins,
                                                                    periods=periods,
                                                                    filter_zscore=filter_zscore,
                                                                    groupby_labels=groupby_labels,
                                                                    max_loss=max_loss,
                                                                    zero_aware=zero_aware,
                                                                    cumulative_returns=cumulative_returns)

        alphalens.tears.create_full_tear_sheet(data, long_short=long_short, group_neutral=group_neutral,
                                               by_group=by_group)
