from numba import njit
from numba.pycc import CC
import numpy as np
# import math

cc = CC('my_numba_cal_performance')
# Uncomment the following line to print out the compilation steps
#cc.verbose = True


@cc.export('get_sharpe', 'f8(f8[:])')
def get_sharpe(arr):
    # 计算夏普率，如果是日线数据，直接进行，如果不是日线数据，需要获取每日最后一个bar的数据用于计算每日收益率，然后计算夏普率
    # 对于期货的分钟数据而言，并不是按照15：00收盘算，可能会影响一点点夏普率等指标的计算，但是影响不大。
    # rate = (arr[1:] - arr[:-1]) / arr[:-1]
    arr_len = len(arr)
    new_array = np.empty(arr_len-1)
    for i in range(arr_len):
        new_array[i] = (arr[i+1] - arr[i])/arr[i]
    #v_mean = np.mean(rate)
    v_mean = sum(new_array) / (arr_len-1)
    v_sum = 0
    for x in new_array:
        v_sum+=(x - v_mean) ** 2
    variance = v_sum / (arr_len - 2)
    std_dev = variance**0.5
    # std = 1.0
    # print(v_mean,std_dev)
    return v_mean*252**0.5/std_dev

@cc.export('get_average_rate', 'f8(f8[:])')
def get_average_rate(arr):
    # 计算复利年化收益率
    arr_len = len(arr)
    begin_value = arr[0]
    end_value = arr[arr_len-1]
    total_rate = max((end_value - begin_value) / begin_value, -0.9999)
    return (1 + total_rate) ** (365 / arr_len) - 1

@cc.export('get_maxdrawdown', 'f8(f8[:])')
def get_maxdrawdown(arr):
    # 计算最大回撤，直接传递净值
    arr_len = len(arr)
    r = np.empty(arr_len)
    t = -np.inf
    for i in range(arr_len):
        t = max(t, arr[i])
        r[i] = t
    a = r - arr
    b = a/r
    e = np.argmax(b)
    if e == 0:
        return 0.0
    else:
        s = np.argmax(arr[:e])

    return (arr[e] - arr[s]) / arr[s]

if __name__ == "__main__":
    cc.compile()