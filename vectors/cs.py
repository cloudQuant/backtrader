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
        # 默认是日线数据，这个在计算夏普率的时候会用到，如果不是每日的，需要继承的时候进行设置
        # 小时线设置为“Hours”, 分钟线设置为"Minutes", 秒设置为"seconds"
        self.time_frame = "Days"
        # 保存total_value的地址
        self.total_value_save_path = self.params.get('total_value_save_path',None)

    def cal_alpha(self, data):
        # 生成实例的时候覆盖这个函数，用于计算具体的因子，列名为factor
        return data

    def cal_factors(self):
        # 根据自定义的alpha公式，计算因子值
        # self.factors = pd.DataFrame()
        factor_list = []
        for symbol in self.datas:
            self.symbol = symbol
            df = self.cal_alpha(self.datas[symbol])[['factor']].rename(columns={"factor": symbol})
            factor_list.append(df)
        self.factors = pd.concat(factor_list, axis=1, join="outer")

    def cal_signals(self):
        # 计算信号，默认按照一定的比例进行多空排列生成信号并持有一定时间
        percent = self.params['percent']
        hold_days = self.params['hold_days']
        factors = self.factors
        # factors = self.factors.fillna(method="ffill")
        # 计算多空信号
        col_list = sorted(factors.columns.tolist())
        factors = factors[col_list]
        data_length = len(factors)
        new_df = pd.DataFrame({col_list[i]:[-0.00000000000001*i]*data_length for i in range(len(col_list))},index=factors.index)
        # short_df = pd.DataFrame({col_list[i]:[0] * data_length for i in range(len(col_list))},index=factors.index)
        # long_df = pd.DataFrame({col_list[i]: [0] * data_length for i in range(len(col_list))}, index=factors.index)
        short_df = pd.DataFrame(index=factors.index)
        long_df = pd.DataFrame(index=factors.index)
        factors = factors + new_df
        signal_dict = factors.apply(cal_long_short_factor_value, axis=1, args=(percent,))
        # signal_dict = factors.apply(cal_long_short_factor_value_c, axis=1, args=(percent,))  # 使用Cython优化
        lower_value, upper_value = signal_dict.str
        # print(factors,signal_dict)
        for col in col_list:
            short_df[col] = np.where(factors[col] <= lower_value,-1,0)
            long_df[col] = np.where(factors[col] >= upper_value, 1, 0)
        signals = short_df + long_df
        signals = signals.shift(1)
        # 根据持有的天数对信号进行向下复制
        signals.index = range(len(signals))
        # 陈鑫博改进优化部分
        index_list = [i for i in signals.index]
        NotNan_list = [i for i in range(1, len(signals), hold_days)]
        Nan_list = list(set(index_list) - set(NotNan_list))
        signals.iloc[Nan_list] = np.nan
        signals.fillna(method='ffill', inplace=True)
        signals.index = factors.index
        self.signals = signals.dropna(axis=0)
        # print(self.signals)
        # assert 0


    # @profile
    # def cal_signals(self):
    #     self.factors.to_csv("c:/result/true_factors.csv")
    #     # 计算信号，默认按照一定的比例进行多空排列生成信号并持有一定时间
    #     percent = self.params['percent']
    #     hold_days = self.params['hold_days']
    #     factors = self.factors
    #     # 计算多空信号
    #     col_list = list(factors.columns)
    #     factors['signal_dict'] = factors.apply(cal_signal_by_percent, axis=1, args=(percent,))
    #     for col in col_list:
    #         factors[col] = factors.apply(lambda row: get_value_from_dict(col, row['signal_dict']), axis=1)
    #     # 对所有的信号进行下移一位
    #     signals = factors.shift(1).drop(columns="signal_dict")
    #     # 输出具体的信息
    #     signals.to_csv("c:/result/true_signals.csv")
    #     # 根据持有的天数对信号进行向下复制
    #     signals.index = range(len(signals))
    #     # index_list = list(signals.index)
    #     # for i in range(1, len(signals) // hold_days + 2):
    #     #     end_index = i * hold_days + 1
    #     #     if end_index >= len(signals)-1:
    #     #         end_index = len(signals)-1
    #     #     first_index = (i - 1) * hold_days + 1
    #     #     target = index_list[first_index:end_index]
    #     #     if first_index < end_index:
    #     #         signals.iloc[target, :] = signals.iloc[first_index, :]
    #     # 陈鑫博改进优化部分
    #     index_list = [i for i in signals.index]
    #     NotNan_list = [i for i in range(1, len(signals), hold_days)]
    #     Nan_list = list(set(index_list) - set(NotNan_list))
    #     signals.iloc[Nan_list] = np.nan
    #     signals.fillna(method='ffill', inplace=True)
    #     signals.index = self.factors.index
    #     self.signals = signals

    def cal_returns(self):
        # 根据高开低收的数据和具体的信号，计算资产的收益率和因子值，保存到self.returns和self.factors
        # self.returns = pd.DataFrame()
        return_list = []
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
            # # 信号变换一次
            # data['ret'] = np.where((data['signal'] != data['next_signal']) & (data['signal'] == data['pre_signal']),
            #                        data['next_open_pre_close_rate'], data['ret'])
            # data['ret'] = np.where((data['signal'] != data['pre_signal']) & (data['signal'] == data['next_signal']),
            #                        data['close_open_rate'], data['ret'])
            # # 信号变换两次
            # data['ret'] = np.where((data['signal'] != data['next_signal']) & (data['signal'] != data['pre_signal']),
            #                        data['next_open_open_rate'], data['ret'])
            # 陈鑫博改进优化部分
            condlist = [(data['signal'] != data['next_signal']) & (data['signal'] == data['pre_signal']),
                        (data['signal'] != data['pre_signal']) & (data['signal'] == data['next_signal']),
                        (data['signal'] != data['next_signal']) & (data['signal'] != data['pre_signal'])]
            choicelist = [data['next_open_pre_close_rate'], data['close_open_rate'],
                          data['next_open_open_rate']]
            data['ret'] = np.select(condlist, choicelist, default=data['ret'])

            data['ret'] = data['ret'] * data['signal'] * data['signal']
            # data = data[['ret']]
            # data.columns = [symbol]
            # data = data.dropna()
            new_data = data.loc[:, "ret"].rename(symbol).dropna()
            return_list.append(new_data)
        self.returns = pd.concat(return_list, axis=1, join="outer")
        # print(self.returns)
        # self.returns.to_csv("d:/result/test_returns.csv")

    # def cal_total_value(self):
    #     # 根据再平衡的天数计算具体的收益率
    #     # 这个计算有问题，需要计算出来每个bar的累计收益率，最后再乘以信号，最后再乘以因子
    #     hold_days = self.params['hold_days']
    #     # 复制新的returns序列并设置index
    #     returns = copy.deepcopy(self.returns)
    #     returns.index = range(len(returns))
    #     signals = copy.deepcopy(self.signals)
    #     # signals = signals.dropna()
    #     signals.index = range(len(signals))
    #
    #     # 保存每次持仓的累计收益率
    #     value_list = []
    #     new_factor = 1
    #     index_list = list(returns.index)
    #     for i in range(1, len(returns) // hold_days + 2):
    #         end_index = i * hold_days
    #         if end_index >= len(returns):
    #             end_index = len(returns)
    #         first_index = (i - 1) * hold_days
    #         target = index_list[first_index:end_index]
    #         # print(target)
    #         new_df = returns.iloc[target, :]
    #         new_signal = signals.iloc[target, :]
    #         if len(new_df) >0:
    #             # 计算收益率
    #             new_df = new_df + 1
    #             new_df = new_df.cumprod()
    #             new_df = new_df - 1
    #             new_df = new_df * new_signal
    #             # 去除每列全部等于0或者包含nan的，nan代表没上市，全部等于0代表信号是0
    #             new_df = new_df.dropna(axis=1)
    #             new_df = new_df.loc[:, ~(new_df == 0).all(axis=0)]
    #             # 计算累计净值
    #             new_df['total_value'] = new_df.mean(axis=1) + 1
    #             new_df['total_value'] = new_df['total_value'] * new_factor
    #             # 赋值并保存
    #             # 赋值并保存
    #             last_value = new_df['total_value'].tolist()
    #             new_factor = last_value[-1]
    #             value_list.append(new_df[['total_value']])
    #     # self.values = pd.concat([self.values, new_df[['total_value']]])
    #     self.values = pd.concat(value_list)
    #     self.values.index = self.returns.index
    #     # self.values.to_csv("d:/result/test_total_value.csv")
    #     sharpe_ratio, average_rate, max_drawdown = get_rate_sharpe_drawdown(self.values, time_frame=self.time_frame)
    #     # look_back_days = self.params['look_back_days']
    #     # hold_days = self.params['hold_days']
    #     # percent = self.params['percent']
    #     file_name = ""
    #     result_list = []
    #     for key in self.params:
    #         if "df" not in key:
    #             file_name = file_name + f"{key}: {self.params[key]} "
    #             result_list.append(self.params[key])
    #     file_name += f"夏普率为:{round(sharpe_ratio,3)},年化收益率为:{round(average_rate,3)},最大回撤为:{round(max_drawdown,3)}"
    #     print(file_name)
    #     result_list += [sharpe_ratio, average_rate, max_drawdown]
    #
    #     return result_list
    # @profile
    def cal_total_value(self,total_value_save_path=None):
        # 根据再平衡的天数计算具体的收益率
        hold_days = self.params['hold_days']
        # 把信号和收益率序列转化成numpy的array
        signals = np.array(self.signals.loc[self.returns.index])
        returns = np.array(self.returns)
        # 保存每次持仓的累计收益率
        value_list = []
        new_factor = 1
        # 陈鑫博改进循环
        for i in range(0, (len(returns) + 2 + (hold_days - (len(returns) % hold_days))), hold_days):
            if i != 0:
                new_df = returns[i - hold_days:i]
                new_signal = signals[i - hold_days:i]
                if len(new_df) > 0:
                    # 计算收益率
                    new_df = new_df + 1
                    new_df = new_df.cumprod(axis=0)
                    new_df = new_df - 1
                    new_df = new_df * new_signal
                    # 去除每列全部等于0或者包含nan的，nan代表没上市，全部等于0代表信号是0
                    new_df = np.delete(new_df, np.where(~new_df.any(axis=0))[0], axis=1)
                    new_df = np.delete(new_df, np.where(np.isnan(new_df).any(axis=0))[0], axis=1)
                    # 计算累计净值
                    total_value = new_df.mean(axis=1) + 1
                    total_value = total_value * new_factor
                    # 赋值并保存
                    # last_value = total_value[-1]
                    # new_factor = last_value
                    new_factor = total_value[-1]
                    value_list.extend(list(total_value))
        self.values = pd.DataFrame(value_list).rename(columns={0: 'total_value'})
        self.values.index = self.returns.index
        # 计算夏普率等指标
        sharpe_ratio, average_rate, max_drawdown = get_rate_sharpe_drawdown(self.values['total_value'])
        file_name = ""
        result_list = []
        for key in self.params:
            if "df" not in key and "save_path" not in key:
                file_name = file_name + f"{key}__{self.params[key]} "
                result_list.append(self.params[key])
        if total_value_save_path is not None:
            target_file = total_value_save_path + file_name + ".csv"
            self.values.to_csv(target_file)
        file_name += f"夏普率为__{round(sharpe_ratio, 4)}__年化收益率为:{round(average_rate, 4)}__最大回撤为:{round(max_drawdown, 4)}"
        # print(file_name)
        result_list += [sharpe_ratio, average_rate, max_drawdown]

        return result_list

    def run(self):
        self.cal_factors()
        self.cal_signals()
        self.cal_returns()
        return self.cal_total_value(self.total_value_save_path)

    def plot(self):
        # self.values[['total_value']].to_csv("d:/result/test_returns.csv")
        self.values[['total_value']].plot()
        plt.show()

    def rank_func(self, rank_func, rank_name):
        # rank函数的实现,对所有品种高开低收成交量等数据应用rank_func后的值进行排序
        """
        :param rank_func:具体的函数，以df为参数，返回一列值
        :param rank_name: 排序返回结果的名称，可以通过这个值和具体的品种名获取因子
        :return:
        :example:
        if not hasattr(self, "rank_a"):
            self.rank_func(lambda df: df.eval("-1*(1-(open/close))**2").shift(1).rolling(look_back_days).corr(
                    df['close']), "rank_a")
        data['factor'] = self.rank_a[symbol]
        """
        datas = self.datas
        symbol = self.symbol
        # print(symbol)
        look_back_days = self.params['look_back_days']
        if look_back_days == 1:
            look_back_days = 2
        begin_date = self.params["begin_date"]
        result_1 = []
        # 陈鑫博 字典循环从symbol改成key,避免symbol出现问题
        for key in self.datas:
            df = self.datas[key]
            df = df[df['trading_date'] >= pd.to_datetime(begin_date, utc=True)]
            df['func'] = rank_func(df)
            # e = df[['func']]
            # e.columns = [symbol]
            # result_1.append(e)
            result_1.append(df.loc[:,"func"].rename(key))
        df1 = pd.concat(result_1, axis=1, join="outer")
        # print("计算的因子值",df1)
        df2 = df1.rank(axis=1, ascending=True)
        # print(rank_name,df2)
        setattr(self, rank_name, df2)

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
