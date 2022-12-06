import pandas as pd
import numpy as np


# 计算分位数的值
def cal_quantile(s, a=0.2):
    if isinstance(s, pd.Series):
        return s.dropna().quantile(a)
    else:
        print(s)


# 根据高开低收的数据和具体的信号，计算收益率、累计收益率和净值
def cal_factor_return(data):
    data.loc[:, 'return'] = data['ret'] * data['signal']
    data.loc[:, 'sum_ret'] = data['return'].cumsum()
    data.loc[:, 'total_value'] = data['sum_ret'] + 1
    data = data.drop(['return', 'sum_ret'], axis=1)
    return data


def get_symbol(contract_name):
    # 根据具体的期货合约获取标的资产的代码
    """
    返回的数据是：大写字母
    输入的数据是具体的合约，如：A0501.XDCE，返回A
    """
    return ''.join([i for i in contract_name.split('.')[0] if i.isalpha()]).upper()


def get_rate_sharpe_drawdown(data):
    # 计算夏普率，复利年化收益率，最大回撤率
    # 对于小于日线周期的，抽取每日最后的value作为一个交易日的最终的value，
    # 对于期货的分钟数据而言，并不是按照15：00收盘算，可能会影响一点点夏普率等指标的计算，但是影响不大。
    # 判断数据中是否有nan
    data = data[['total_value']]
    data = data.copy()
    # print(data.isnull().values.any())
    # if data.isnull().values.any():
    #     assert 0
    #     print(data)
    #     print(data.isnull().values.any())
    data.loc[:, 'date'] = [i.date() for i in data.index]
    data1 = data.drop_duplicates("date", keep='last')
    # data1.index = pd.to_datetime(data1['date'])
    data1['pre_total_value'] = data1['total_value'].shift(1)
    data1 = data1.dropna()
    # print(data1)
    if len(data1) == 0:
        return np.NaN, np.NaN, np.NaN
    # 假设一年的交易日为252天
    data1.loc[:, 'rate1'] = np.log(data1['total_value'] / data1['pre_total_value'])

    # data['rate2']=data['total_value'].pct_change()
    data1 = data1.dropna()
    sharpe_ratio = data1['rate1'].mean() * 252 ** 0.5 / (data1['rate1'].std())
    # 年化收益率为：
    value_list = list(data['total_value'])
    begin_value = value_list[0]
    end_value = value_list[-1]
    begin_date = data.index[0]
    end_date = data.index[-1]
    days = (end_date - begin_date).days
    # print(begin_date,begin_value,end_date,end_value,1/(days/365))
    # 如果计算的实际收益率为负数的话，就默认为最大为0,收益率不能为负数
    total_rate = max((end_value - begin_value) / begin_value, -0.9999)
    average_rate = (1 + total_rate) ** (1 / (days / 365)) - 1
    # 计算最大回撤
    data['pre_total_value'] = data['total_value'].shift(1)
    data.loc[:, 'rate1'] = np.log(data['total_value'] / data['pre_total_value'])

    df = data['rate1'].cumsum().dropna()
    index_j = np.argmax(np.array(np.maximum.accumulate(df) - df))
    index_i = np.argmax(np.array(df[:index_j]))  # 开始位置
    # print("最大回撤开始时间",index_i)
    max_drawdown = (np.e ** df[index_j] - np.e ** df[index_i]) / np.e ** df[index_i]

    return sharpe_ratio, average_rate, max_drawdown
