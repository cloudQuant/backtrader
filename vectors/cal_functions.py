import pandas as pd
import numpy as np
from backtrader.utils.cal_return_sharpe_drawdown import cal_return_sharpe_drawdown as ts

# 调用cal_return_sharpe_drawdown需要先去文件夹中编译cal_return_sharpe_drawdown，计算三个指标的速度比python提高了16.5倍左右
def get_rate_sharpe_drawdown(arr):
    # 计算夏普率、复利年化收益率、最大回撤率
    # arr是每日的净值序列
    # if isinstance(arr, pd.Series):
    #     arr = arr.to_numpy()
    return [ts.cal_sharpe_ratio_cy(arr), ts.cal_average_rate_cy(arr), ts.cal_max_drawdown_cy(arr)]

def get_sharpe(arr):
    # 计算夏普率
    # arr是每日的净值序列
    return ts.cal_sharpe_ratio_cy(arr)

def get_average_rate(arr):
    # 计算复利年化收益率
    # arr是每日的净值序列
    return ts.cal_average_rate_cy(arr)

def get_maxdrawdown(arr):
    # 计算最大回撤率
    # arr是每日的净值序列
    return ts.cal_max_drawdown_cy(arr)

def get_symbol(contract_name):
    # 根据具体的期货合约获取标的资产的代码
    """
    返回的数据是：大写字母
    输入的数据是具体的合约，如：A0501.XDCE，返回A
    """
    return ''.join([i for i in contract_name.split('.')[0] if i.isalpha()]).upper()

# 计算持有多头的时候最小的factor值
def cal_long_short_factor_value(s,a=0.2):
    if isinstance(s, pd.Series):
        s = s.dropna().sort_values()
        num = int(len(s)*a)
        if num>0:
            return [s[num-1], s[-1*num]]
        else:
            return [np.NaN, np.NaN]

def cal_long_short_factor_value_c(s, a = 0.2):
    s = s.values
    return ts.cal_long_short_factor_value_cy(s, a)

# 使用numpy计算具体的信号
def cal_signals_by_numpy(factors_arr, percent, hold_days):
    signals = np.zeros(factors_arr.shape)
    data_length = factors_arr.shape[0]
    col_len = factors_arr.shape[1]
    diff_arr = np.array([-0.00000000000001 * i for i in range(col_len)])
    short_arr = np.zeros(col_len)
    long_arr = np.zeros(col_len)
    signals[0] = np.array([np.NaN for i in range(col_len)])
    for i in range(data_length - 1):
        if i % hold_days == 0:
            s = factors_arr[i,] + diff_arr
            ss = s[~np.isnan(s)]
            ss.sort()
            num = int(ss.size * percent)
            if num > 0:
                lower_value, upper_value = ss[num - 1], ss[-1 * num]
            else:
                lower_value, upper_value = np.NaN, np.NaN

            short_arr = np.where(s <= lower_value, -1, 0)
            long_arr = np.where(s >= upper_value, 1, 0)
            signals[i+1] = short_arr + long_arr
        else:
            signals[i+1] = signals[i]
    # signals = np.delete(signals,0,axis=0)
    return signals

# 把datas合并生成具体的array
def convert_datas_to_array(datas):
    # 把各个品种的开盘价和收盘价数据转化成array
    open_list = []
    close_list = []
    symbol_list = sorted(datas.keys())
    for symbol in symbol_list:
        open_list.append(datas[symbol].loc[:, "open"])
        close_list.append(datas[symbol].loc[:, "close"])

    opens_arr = pd.concat(open_list, join="outer", axis=1).fillna(method="ffill").to_numpy()
    closes_arr = pd.concat(close_list, join="outer", axis=1).fillna(method="ffill").to_numpy()

    return opens_arr,closes_arr

# def get_sharpe(data):
#         # 计算夏普率，如果是日线数据，直接进行，如果不是日线数据，需要获取每日最后一个bar的数据用于计算每日收益率，然后计算夏普率
#         # 对于期货的分钟数据而言，并不是按照15：00收盘算，可能会影响一点点夏普率等指标的计算，但是影响不大。
#         # 假设一年的交易日为252天
#         rate0 = data['total_value'].pct_change().dropna()
#         sharpe_ratio = rate0.mean() * 252 ** 0.5 / rate0.std()
#         return sharpe_ratio
#
# def get_average_rate(data):
#         # 计算复利年化收益率
#         value_list = data['total_value'].tolist()
#         begin_value = value_list[0]
#         end_value = value_list[-1]
#         begin_date = data.index[0]
#         end_date = data.index[-1]
#         days = (end_date - begin_date).days
#         # print(begin_date,begin_value,end_date,end_value,1/(days/365))
#         # 如果计算的实际收益率为负数的话，收益率不能超过-100%,默认最小为-99.99%
#         total_rate = max((end_value - begin_value) / begin_value, -0.9999)
#         average_rate = (1 + total_rate) ** (365 / days) - 1
#         return average_rate
#
#     # def get_maxdrawdown_old(data):
#     #     # 计算最大回撤
#     #     data.loc[:, 'rate1'] = np.log(data['total_value'] / data['total_value'].shift(1))
#     #     df = data['rate1'].cumsum().dropna()
#     #     try:
#     #         index_j = np.argmax(np.array(np.maximum.accumulate(df) - df))
#     #         index_i = np.argmax(np.array(df[:index_j]))  # 开始位置
#     #         max_drawdown = (np.e ** df[index_j] - np.e ** df[index_i]) / np.e ** df[index_i]
#     #     except:
#     #         max_drawdown = np.nan
#     #     return max_drawdown
#
# def get_maxdrawdown(data):
#         X = data['total_value']
#         # 计算最大回撤，直接传递净值
#         endDate = np.argmax((np.maximum.accumulate(X) - X) / np.maximum.accumulate(X))
#         if endDate == 0:
#             return np.NaN
#         else:
#             startDate = np.argmax(X[:endDate])
#
#         return (X[endDate]- X[startDate]) / X[startDate]
#
# def get_rate_sharpe_drawdown(arr):
#         # 计算夏普率、复利年化收益率、最大回撤率
#         # arr是每日的净值序列
#         return [get_sharpe(arr),get_average_rate(arr),get_maxdrawdown(arr)]




