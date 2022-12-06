import pandas as pd
import numpy as np
import os
import copy
import matplotlib.pyplot as plt
from backtrader.vectors.cal_performance import  get_symbol, get_rate_sharpe_drawdown
# 排除的品种
remove_symbol = ["BB", "PG", "BB", "ER", "FB", "JR", "LR", "NR", "PM", "RR", "RS", "WH", "WR", "WS"]

class AlphaCs(object):
    def __init__(self, datas, params):
        # datas是字典格式，key是品种的名字，value是df格式，index是datetime,包含open,high,low,close,volume,openinterest
        self.datas = datas
        self.params = params

    def cal_alpha(self):
        pass

    # 计算信号，默认按照一定的比例进行多空排列
    def cal_signal(self):
        percent = self.params['percent']
        hold_days = self.params['hold_days']
        factors = self.factors
        # 计算多空信号
        col_list = list(factors.columns)
        factors['low'] = factors.apply(self.cal_quantile, axis=1, args=(percent,))
        factors['high'] = factors.apply(self.cal_quantile, axis=1, args=(1-percent,))
        result = []
        for col in col_list:
            a = np.where(factors[col] <= factors['low'], -1, 0)
            b = np.where(factors[col] >= factors['high'], 1, 0)
            c = a + b
            result.append(c)
        factors = pd.DataFrame(result).T
        factors.columns = col_list
        # 对多空信号进行处理
        index_list = list(factors.index)
        for i in range(len(factors) // hold_days + 1, 0, -1):
            end_index = i * hold_days + 1
            if end_index >= len(factors):
                end_index = len(factors)
            first_index = (i - 1) * hold_days
            target = index_list[first_index:end_index]
            # print(target)
            factors.iloc[target, :] = factors.iloc[first_index, :]
        factors.index = self.returns.index
        self.factors = factors

    # 根据高开低收的数据和具体的信号，计算资产的收益率和因子值，保存到self.returns和self.factors
    def cal_factor_return(self):
        look_back_days = self.params['look_back_days']
        self.factors = pd.DataFrame()
        self.returns = pd.DataFrame()
        for symbol in self.datas:
            df = self.datas[symbol]
            df['ret'] = df['close'].pct_change()
            # df['ret'] = df['ret'].shift(1)
            df = self.cal_alpha(df)
            df['asset'] = symbol
            df = df.dropna()
            new_df = df[['ret']]
            new_df.columns = [symbol]
            self.returns = pd.concat([self.returns, new_df], axis=1, join="outer")
            df = df[['factor']]
            df.columns = [symbol]
            self.factors = pd.concat([self.factors, df], axis=1, join="outer")

    # 计算分位数的值
    def cal_quantile(self, s, a=0.2):
        if isinstance(s, pd.Series):
            return s.dropna().quantile(a)
        else:
            print(s)


    # 根据收益和signal计算最终的收益率
    def cal_last_return(self):
        for col in self.returns.columns:
            self.returns[col] = self.returns[col] * self.factors[col]
        self.returns['ret'] = self.returns.mean(axis=1)
        self.returns['total_value'] = self.returns['ret'].cumsum() + 1
        self.returns.index.name = "datetime"
        sharpe_ratio, average_rate, max_drawdown = get_rate_sharpe_drawdown(self.returns[['total_value']])
        print(f"夏普率为:{sharpe_ratio},年化收益率为:{average_rate},最大回撤为:{max_drawdown}")
        look_back_days = self.params['look_back_days']
        hold_days = self.params['hold_days']
        percent = self.params['percent']
        return [look_back_days, hold_days, percent, sharpe_ratio, average_rate, max_drawdown]

    def run(self, plot=False):
        self.cal_factor_return()
        self.cal_signal()
        return self.cal_last_return()

    def plot(self):
        self.returns[['total_value']].plot()
        plt.show()

