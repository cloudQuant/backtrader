#cython: language_level=3
#distutils:language=c++
#cython: c_string_type=unicode, c_string_encoding=utf8
cimport numpy as np
cimport cython
from libcpp.vector cimport vector
from libc.stdlib cimport malloc, free

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(True)
@cython.nonecheck(False)
@cython.initializedcheck(False)
def cal_value_by_cython(np.ndarray[double, ndim=1] open_arr,
                        np.ndarray[double, ndim=1] high_arr,
                        np.ndarray[double, ndim=1] low_arr,
                        np.ndarray[double, ndim=1] close_arr,
                        np.ndarray[double, ndim=1] volume_arr,
                        np.ndarray[int, ndim=1] signal_arr,
                        double commission, double init_value, double percent):
    # 循环计算具体的持仓，盈亏，value的情况
    # 初始化持仓，可用资金，持仓盈亏，价值
    cdef int n = signal_arr.shape[0]
    cdef double *symbol_open_price_arr = <double*>malloc(n * sizeof(double))
    cdef double *symbol_open_value_arr = <double*>malloc(n * sizeof(double))
    cdef double *value_arr = <double*>malloc(n * sizeof(double))
    cdef double now_commission = 0.0
    cdef int i
    cdef int pre_signal
    cdef int now_signal
    cdef double open_price
    cdef double open_value
    cdef double value_change
    # 计算第一个bar的信号
    now_signal = signal_arr[0]
    # 如果第一个bar的信号是0的话
    if now_signal == 0:
        symbol_open_price_arr[0] = open_arr[1]
        symbol_open_value_arr[0] = init_value
        value_arr[0] = init_value
    # 如果第一个bar的信号不是0的话，需要准备开仓，计算手续费
    else:
        open_price = open_arr[1]
        open_value = init_value
        now_commission = open_value * percent * commission
        value_arr[0] = open_value - now_commission
        symbol_open_price_arr[0] = open_price
        symbol_open_value_arr[0] = open_value

    # 从第二个bar开始计算

    for i in range(1, n - 1):
        pre_signal = signal_arr[i - 1]
        now_signal = signal_arr[i]
        # 如果信号保持不变
        if pre_signal == now_signal:
            # 如果信号不是0
            if pre_signal != 0:
                # 开仓价格
                open_price = symbol_open_price_arr[i - 1]
                # 开仓使用资金
                open_value = symbol_open_value_arr[i - 1]
                # 开仓时的账户资金
                symbol_open_value_arr[i] = open_value
                # 保存开仓价格
                symbol_open_price_arr[i] = open_price
                # 价值变化
                value_change = (close_arr[i] - open_price) / open_price * pre_signal * open_value * percent
                # 当前的价格
                value_arr[i] = open_value + value_change - now_commission

            else:
                value_arr[i] = value_arr[i - 1]
        # 如果信号发生了变化
        if pre_signal != now_signal:
            # 如果前一个信号不是0，现在是0了，代表这个bar出现平仓信号，下个bar平仓
            if pre_signal != 0 and now_signal == 0:
                open_price = symbol_open_price_arr[i - 1]
                open_value = symbol_open_value_arr[i - 1]
                value_change = (open_arr[i + 1] - open_price) / open_price * pre_signal * open_value * percent
                value_arr[i] = open_value + value_change - now_commission
                now_commission = open_arr[i + 1] / open_price * open_value * percent * commission
                value_arr[i] = value_arr[i] - now_commission
                symbol_open_price_arr[i] = 0
                symbol_open_value_arr[i] = 0

            # 如果前一个信号是0，但是现在不是0了，代表这个bar要新开仓
            if pre_signal == 0 and now_signal != 0:
                open_price = open_arr[i + 1]
                open_value = value_arr[i - 1]
                now_commission = open_value * percent * commission
                value_arr[i] = open_value - now_commission
                symbol_open_price_arr[i] = open_price
                symbol_open_value_arr[i] = open_value
            # 如果前后信号都不等于0，但是信号不一样，代表要反手进行交易
            if pre_signal * now_signal == -1:
                # 平旧仓位
                open_price = symbol_open_price_arr[i - 1]
                open_value = symbol_open_value_arr[i - 1]
                value_change = (open_arr[i + 1] - open_price) / open_price * pre_signal * open_value * percent
                value_arr[i] = value_arr[i - 1] + value_change - now_commission
                # 新开仓
                open_value = value_arr[i]
                now_commission = open_value * percent * commission
                value_arr[i] = open_value - now_commission
                symbol_open_price_arr[i] = open_arr[i + 1]
                symbol_open_value_arr[i] = open_value
    # print("-----------计算最后一个bar相关的信号--------------")
    # 如果是最后一个bar,按照收盘价进行平仓
    pre_signal = signal_arr[i]
    now_signal = signal_arr[i + 1]
    if now_signal == pre_signal:
        if pre_signal == 0:
            value_arr[i + 1] = value_arr[i]
        else:
            open_price = symbol_open_price_arr[i]
            open_value = symbol_open_value_arr[i]
            symbol_open_price_arr[i + 1] = open_price
            value_change = (close_arr[i + 1] - open_price) / open_price * pre_signal * open_value * percent
            value_arr[i + 1] = open_value + value_change
            symbol_open_value_arr[i + 1] = open_value

    else:
        value_arr[i + 1] = value_arr[i]

    # 释放内存
    free(symbol_open_price_arr)
    free(symbol_open_value_arr)
    cdef np.ndarray[double, ndim=1] new_value_arr = open_arr
    for i in range(n):
        new_value_arr[i] = value_arr[i]
    return new_value_arr

