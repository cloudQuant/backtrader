import pandas as pd
import numpy as np

def get_sharpe(data, time_frame="Days"):
    # 计算夏普率，如果是日线数据，直接进行，如果不是日线数据，需要获取每日最后一个bar的数据用于计算每日收益率，然后计算夏普率
    # 对于期货的分钟数据而言，并不是按照15：00收盘算，可能会影响一点点夏普率等指标的计算，但是影响不大。
    if time_frame!="Days":
        data.loc[:, 'date'] = data.index.date
        data = data.drop_duplicates("date", keep='last')
    if len(data)==0:
        sharpe_ratio = np.NaN
    else:
        # 假设一年的交易日为252天
        rate0 = data['total_value'].pct_change().dropna()
        sharpe_ratio = rate0.mean() * 252 ** 0.5 / rate0.std()
    return sharpe_ratio

def get_average_rate(data):
    # 计算复利年化收益率
    value_list = data['total_value'].tolist()
    begin_value = value_list[0]
    end_value = value_list[-1]
    begin_date = data.index[0]
    end_date = data.index[-1]
    days = (end_date - begin_date).days
    # print(begin_date,begin_value,end_date,end_value,1/(days/365))
    # 如果计算的实际收益率为负数的话，收益率不能超过-100%,默认最小为-99.99%
    total_rate = max((end_value - begin_value) / begin_value, -0.9999)
    average_rate = (1 + total_rate) ** (365 / days) - 1
    return average_rate

def get_maxdrawdown_old(data):
    # 计算最大回撤
    data.loc[:, 'rate1'] = np.log(data['total_value'] / data['total_value'].shift(1))
    df = data['rate1'].cumsum().dropna()
    try:
        index_j = np.argmax(np.array(np.maximum.accumulate(df) - df))
        index_i = np.argmax(np.array(df[:index_j]))  # 开始位置
        max_drawdown = (np.e ** df[index_j] - np.e ** df[index_i]) / np.e ** df[index_i]
    except:
        max_drawdown = np.nan
    return max_drawdown

def get_maxdrawdown(data):
    X = data['total_value']
    # 计算最大回撤，直接传递净值
    endDate = np.argmax((np.maximum.accumulate(X) - X) / np.maximum.accumulate(X))
    if endDate == 0:
        return 0, len(X), endDate
    else:
        startDate = np.argmax(X[:endDate])

    return (X[endDate]- X[startDate]) / X[startDate]

def get_rate_sharpe_drawdown(data,time_frame="Days"):
    # 计算夏普率，复利年化收益率，最大回撤率
    sharpe_ratio = get_sharpe(data, time_frame=time_frame)
    average_rate = get_average_rate(data)
    max_drawdown = get_maxdrawdown(data)
    return sharpe_ratio, average_rate, max_drawdown

# 计算持有多头的时候最小的factor值
def cal_long_short_factor_value(s,a=0.2):
    if isinstance(s, pd.Series):
        s = s.dropna().sort_values()
        num = int(len(s)*a)
        if num>0:
            return [s[num-1], s[-1*num]]
        else:
            return [np.NaN, np.NaN]

def cal_signal_by_percent(s, a=0.2):
    # 采用这种方法排序的时候，如果两个因子的值是一样的，从小到大排列的时候，会按照品种字母靠前的进行排列
    s = s.dropna()
    num = int(len(s) * a)
    s = s.sort_values()
    s = list(zip(s.index, s))
    signal_dict = {}
    long_signal_list = s[-num:]
    short_signal_list = s[:num]
    signal_dict.update({i[0]: 1 for i in long_signal_list})
    signal_dict.update({i[0]: -1 for i in short_signal_list})
    return signal_dict

# 计算分位数的值
def cal_quantile(s, a=0.2):
    if isinstance(s, pd.Series):
        return s.dropna().quantile(a)
    else:
        print(s)




def get_value_from_dict(a, b):
    return b.get(a, 0)


# 计算平均收益率
def cal_mean(s):
    if isinstance(s, pd.Series):
        s = s.dropna().mean()
        return s
    else:
        print(s)


# 根据信号值计算具体的收益率，剔除部分信号值一样的bar,每次使用一倍资金
def cal_factor_return_by_percent(data):
    # 对ret进行修改，当signal发生变化的时候，对发生变化的两根bar调整收益率
    # 当前信号
    data.loc[:, "signal"] = data['signal'].shift(1)
    # 前一个信号
    data.loc[:, "pre_signal"] = data['signal'].shift(1)
    # 下个信号
    data.loc[:, "next_signal"] = data['signal'].shift(-1)
    # 删除信号相同的bar
    data = data[data['signal'] != data['pre_signal']]
    # 获取最后收盘价
    last_close = list(data['close'])[-1]
    data['next_open'] = data['open'].shift(-1)
    data.loc[list(data.index)[-1], 'next_open'] = last_close
    # 计算每次交易的价格收益率
    data['ret'] = (data['next_open'] - data['open']) / data['open']
    # 计算每次交易信号的收益率
    data.loc[:, 'return'] = data['ret'] * data['signal']
    # 单个bar的收益率转换成多个bar的收益率
    data.loc[:, "new_return"] = data['return'] + 1
    # data.loc[:, 'return'] = data['ret'].shift(1) * data['signal']
    # data.loc[:, 'sum_ret'] = data['return'].cumsum()
    # 计算累计乘
    data.loc[:, 'total_value'] = data['new_return'].cumprod()
    # data.to_csv("d:/result/test_ts.csv")
    data = data.drop(['return', 'new_return', 'pre_signal', 'signal', 'next_signal', 'next_open'], axis=1)
    data = data.dropna()
    return data


# 根据信号值计算具体的收益率，剔除部分信号值一样的bar,每次使用固定资金
def cal_factor_return_by_value(data):
    # 对ret进行修改，当signal发生变化的时候，对发生变化的两根bar调整收益率
    # 当前信号
    data.loc[:, "signal"] = data['signal'].shift(1)
    # 前一个信号
    data.loc[:, "pre_signal"] = data['signal'].shift(1)
    # 下个信号
    data.loc[:, "next_signal"] = data['signal'].shift(-1)
    # 删除信号相同的bar
    data = data[data['signal'] != data['pre_signal']]
    # 获取最后收盘价
    last_close = list(data['close'])[-1]
    data['next_open'] = data['open'].shift(-1)
    data.loc[list(data.index)[-1], 'next_open'] = last_close
    # 计算每次交易的价格收益率
    data['ret'] = (data['next_open'] - data['open']) / data['open']
    # 计算每次交易信号的收益率
    data.loc[:, 'return'] = data['ret'] * data['signal']
    # 单个bar的收益率转换成多个bar的收益率
    data.loc[:, "new_return"] = data['return']
    # data.loc[:, 'return'] = data['ret'].shift(1) * data['signal']
    # data.loc[:, 'sum_ret'] = data['return'].cumsum()
    # 计算累计乘
    data.loc[:, 'total_value'] = data['new_return'].cumsum() + 1
    # data.to_csv("d:/result/test_ts.csv")
    data = data.drop(['return', 'new_return', 'pre_signal', 'signal', 'next_signal', 'next_open'], axis=1)
    data = data.dropna()
    return data


# 根据高开低收的数据和具体的信号，计算收益率、累计收益率和净值
def cal_factor_return(data):
    # 对ret进行修改，当signal发生变化的时候，对发生变化的两根bar调整收益率
    # 当前信号
    data.loc[:, "signal"] = data['signal'].shift(1)
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

    # 计算每个bar的收益率
    data.loc[:, 'return'] = data['ret'] * data['signal']
    # 单个bar的收益率转换成多个bar的收益率
    data.loc[:, "new_return"] = data['return'] + 1
    # data.loc[:, 'return'] = data['ret'].shift(1) * data['signal']
    # data.loc[:, 'sum_ret'] = data['return'].cumsum()
    # 计算累计乘
    data.loc[:, 'total_value'] = data['new_return'].cumprod()
    # data.to_csv("d:/result/test_ts_1.csv")
    data = data.drop(['return', 'new_return', 'pre_signal', 'signal', 'next_signal', 'next_open', 'pre_close'], axis=1)
    data = data.dropna()
    # data.to_csv("d:/result/test_ts.csv")
    return data


# 根据开盘价计算每个bar的收益率
def cal_factor_return_by_open(data):
    # 对ret进行修改，当signal发生变化的时候，对发生变化的两根bar调整收益率
    # 当前信号
    data.loc[:, "signal"] = data['signal'].shift(1)
    # 前一个信号
    data.loc[:, "pre_signal"] = data['signal'].shift(1)
    # 下个信号
    data.loc[:, "next_signal"] = data['signal'].shift(-1)
    # # 删除信号相同的bar
    # data = data[data['signal'] != data['pre_signal']]
    # 获取最后收盘价
    last_close = list(data['close'])[-1]
    data['next_open'] = data['open'].shift(-1)
    data.loc[list(data.index)[-1], 'next_open'] = last_close
    # 计算每次交易的价格收益率
    data['ret'] = (data['next_open'] - data['open']) / data['open']
    # 计算每个bar的收益率
    data.loc[:, 'return'] = data['ret'] * data['signal']
    # 单个bar的收益率转换成多个bar的收益率
    data.loc[:, "new_return"] = data['return'] + 1
    # data.loc[:, 'return'] = data['ret'].shift(1) * data['signal']
    # data.loc[:, 'sum_ret'] = data['return'].cumsum()
    # 计算累计乘
    data.loc[:, 'total_value'] = data['new_return'].cumprod()
    # data.to_csv("d:/result/test_ts_1.csv")
    data = data.drop(['return', 'new_return', 'pre_signal', 'signal', 'next_signal', 'next_open'], axis=1)
    data = data.dropna()
    return data


def get_symbol(contract_name):
    # 根据具体的期货合约获取标的资产的代码
    """
    返回的数据是：大写字母
    输入的数据是具体的合约，如：A0501.XDCE，返回A
    """
    return ''.join([i for i in contract_name.split('.')[0] if i.isalpha()]).upper()



