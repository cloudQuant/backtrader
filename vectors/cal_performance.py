import pandas as pd
import numpy as np

try:
    # 修复因版本问题导致的numba函数不能使用，目前numba不能用在python3.11上
    from my_numba_cal_performance import get_sharpe_by_numba,get_average_rate_by_numba,get_maxdrawdown_by_numba #从numba编译之后的函数，比普通的python函数快4-10倍
    def get_rate_sharpe_drawdown(arr):
        # 计算夏普率、复利年化收益率、最大回撤率
        # arr是每日的净值序列
        if isinstance(arr,pd.Series):
            arr = arr.to_numpy()
        return [get_sharpe_by_numba(arr),get_average_rate_by_numba(arr),get_maxdrawdown_by_numba(arr)]
    def get_sharpe(arr):
        # 计算夏普率
        # arr是每日的净值序列
        return get_sharpe_by_numba(arr)

    def get_average_rate(arr):
        # 计算复利年化收益率
        # arr是每日的净值序列
        return get_average_rate_by_numba(arr)

    def get_maxdrawdown(arr):
        # 计算最大回撤率
        # arr是每日的净值序列
        return get_maxdrawdown_by_numba(arr)
except:
    def get_sharpe(data):
        # 计算夏普率，如果是日线数据，直接进行，如果不是日线数据，需要获取每日最后一个bar的数据用于计算每日收益率，然后计算夏普率
        # 对于期货的分钟数据而言，并不是按照15：00收盘算，可能会影响一点点夏普率等指标的计算，但是影响不大。
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

    # def get_maxdrawdown_old(data):
    #     # 计算最大回撤
    #     data.loc[:, 'rate1'] = np.log(data['total_value'] / data['total_value'].shift(1))
    #     df = data['rate1'].cumsum().dropna()
    #     try:
    #         index_j = np.argmax(np.array(np.maximum.accumulate(df) - df))
    #         index_i = np.argmax(np.array(df[:index_j]))  # 开始位置
    #         max_drawdown = (np.e ** df[index_j] - np.e ** df[index_i]) / np.e ** df[index_i]
    #     except:
    #         max_drawdown = np.nan
    #     return max_drawdown

    def get_maxdrawdown(data):
        X = data['total_value']
        # 计算最大回撤，直接传递净值
        endDate = np.argmax((np.maximum.accumulate(X) - X) / np.maximum.accumulate(X))
        if endDate == 0:
            return np.NaN
        else:
            startDate = np.argmax(X[:endDate])

        return (X[endDate]- X[startDate]) / X[startDate]

    def get_rate_sharpe_drawdown(arr):
        # 计算夏普率、复利年化收益率、最大回撤率
        # arr是每日的净值序列
        return [get_sharpe(arr),get_average_rate(arr),get_maxdrawdown(arr)]

def get_symbol(contract_name):
    # 根据具体的期货合约获取标的资产的代码
    """
    返回的数据是：大写字母
    输入的数据是具体的合约，如：A0501.XDCE，返回A
    """
    return ''.join([i for i in contract_name.split('.')[0] if i.isalpha()]).upper()


