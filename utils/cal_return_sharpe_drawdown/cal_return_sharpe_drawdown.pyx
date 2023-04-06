#cython: language_level=3
#distutils: language=c++
#cython: c_string_type=unicode, c_string_encoding=utf8


import cython
import numpy as np
cimport numpy as np
import pandas as pd


from libcpp.vector cimport vector
from libcpp.utility cimport move
from libcpp.string cimport string
from cython.parallel cimport prange,parallel
cimport openmp as op
cimport libc.math as cmath

DTYPE = np.float64
ctypedef np.float64_t DTYPE_t

cdef extern from "./cal_return_sharpe_drawdown.hh" namespace "itdog" nogil:
    double div(double x,double y)

    double sub(double x,double y)

    double add(double x,double y)

    double mul(double x,double y)

    double cal_max_drawdown_parallel(const double* arr, int n)
#def 

'''
@biref  将dataframe转换成vector
'''
@cython.boundscheck(False)
@cython.wraparound(False)
cdef void dataframe_to_vector(df: pd.DataFrame,vector[vector[double]]& arr):
    # 将DataFrame转换为ndarray
    cdef double[:,:] arrView = df.values
    cdef int rows = arrView.shape[0]
    cdef int cols = arrView.shape[1]
    cdef int i=0,j=0

    if rows>0 and cols>0:
        arr.reserve(cols);

        for i in range(cols):
            arr.push_back(vector[double]());
            arr[i].resize(rows);
        #for
    #if
    
    # 循环填充数据
    with nogil:
        for i in prange(cols):
            for j in range(rows):
                # printf("thread:%d is working \n",op.omp_get_thread_num())
                arr[i][j]=move(arrView[j, i])
            #for
        #for
    #with
#def


cdef inline  double mean(const double[:]& arr):
    cdef double sumRate = 0.0
    cdef int n=arr.shape[0]
    cdef int i

    for i in range(n):
        sumRate += arr[i]
    #for

    return sumRate / n
#def

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(False)
cdef inline double[:] diff(const double[:]& arr):
    cdef int n = arr.shape[0] - 1
    cdef double[:] rate = np.zeros(n, dtype=np.double)
    cdef int i

    for i in range(n):
        rate[i] = (arr[i+1] - arr[i]) / arr[i]
    #for
    return rate
#def



@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(False)
cdef inline double cal_sharpe_ratio(const double[:]& arr):
    '''
    @note 原来的代码
    '''
    #cdef np.ndarray[double] rate =  np.diff(arr)/arr[:-1] #计算收益率
    # cdef double mean = rate.mean()
    # cdef double std = rate.std(ddof=1)
    # cdef double sharpe_ratio = mean*252**0.5/std

    '''
    单线程版本
    '''
    # cdef int n =arr.shape[0]
    # cdef double[:] rate=diff(arr)
    # cdef double sum = 0.0
    # cdef double sq = 0.0
    # cdef int i

    # #pragma omp parallel for reduction(+:sum,sq)
    # for i in range(n):
    #     sum += rate[i]
    #     sq += rate[i] * rate[i]
    # #for

    # cdef double mn=div(sum,n)
    # cdef double std=cmath.sqrt((div(sq,n))-cmath.pow(mn,2))
    # cdef double ratio = div(mn * 252 ** 0.5 , std)

    cdef int n =arr.shape[0]
    cdef double[:] rate=diff(arr)
    cdef double sum = 0.0
    cdef double sq = 0.0
    cdef double mn=0.0
    cdef double std=0.0
    cdef double ratio = 0.0
    cdef int i

    with nogil,parallel(num_threads=16):
        for i in prange(n):
            sum+=rate[i]
            sq+=rate[i]*rate[i]
        #for
    #with

    mn=div(sum,n)
    std=cmath.sqrt((div(sq,n))-cmath.pow(mn,2))
    ratio = div(mn * 252 ** 0.5 , std)

    return ratio
#def

@cython.boundscheck(False)
#@cython.wraparound(False)
@cython.cdivision(False)
cdef inline double cal_average_rate(const double[:]& arr):
    '''
    @note原来的代码
    '''
    cdef double begin_value = arr[0]
    cdef double end_value = arr[-1]
    cdef double days = arr.shape[0]
    # 如果计算的实际收益率为负数的话，收益率不能超过-100%,默认最小为-99.99%
    cdef double total_rate = cmath.fmax(div(end_value - begin_value, begin_value), -0.9999)
    # cdef double total_rate = max(end_value/begin_value-1.0, -0.9999)
    # cdef double total_rate = div(end_value - begin_value, begin_value)
    # cdef double total_rate = end_value/begin_value-1.0
    # if total_rate<-0.9999:total_rate = -0.9999
    # if total_rate == -1.0:return -1.0
    # print("total rate=",total_rate)
    cdef double average_rate = cmath.pow(1 + total_rate,252/days) - 1
    return average_rate
#def

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(False)
cdef inline double cal_max_drawdown(const double[:]& arr):
    '''
    @note 原来的代码
    '''
    # cdef int index_j = np.argmax(np.array(np.maximum.accumulate(arr) - arr))
    # cdef int index_i = np.argmax(np.array(arr[:index_j]))
    # cdef double max_drawdown = (np.e ** arr[index_j] - np.e ** arr[index_i]) / np.e ** arr[index_i]


    '''
    @note 单线程代码
    '''
    # cdef int n = arr.shape[0]
    # cdef double max_drawdown = 0.0
    # cdef double cum_max = arr[0]
    # cdef double drawdown = 0.0

    # for i in range(1, n):
    #     if arr[i] > cum_max:
    #         cum_max = arr[i]
    #         drawdown = 0.0
    #     else:
    #         drawdown = div(cum_max - arr[i],cum_max)
    #         if drawdown > max_drawdown:
    #             max_drawdown = drawdown
    #         #if
    #     #if
    # #for


    '''
    @note多线程代码
    参考：https://python3-cookbook-zh.readthedocs.io/en/latest/c15/p10_wrap_existing_c_code_with_cython.html
    '''
    cdef double* arrPtr=<double*>&arr[0]
    cdef double max_drawdown=cal_max_drawdown_parallel(arrPtr, arr.shape[0])

    return max_drawdown
#def


def cal_sharpe_ratio_cy(ss:pd.Series):
    return cal_sharpe_ratio(ss.values)
#def


def cal_average_rate_cy(ss:pd.Series):
    return cal_average_rate(ss.values)
#def


def cal_max_drawdown_cy(ss:pd.Series):
    return cal_max_drawdown(ss.values)
#def

# def cal_daily_returns_cy(ss:pd.Series):
#     cdef vector[double] arr=ss.values
#     return daily_returns(arr)
#def


def main(df:pd.DataFrame):
    cdef vector[vector[double]] arr
    dataframe_to_vector(df,arr)
    return arr

cpdef cal_long_short_factor_value_cy(np.ndarray[double, ndim=1] s, double a=0.2):
    cdef np.ndarray[double] ss = s[~np.isnan(s)]
    ss.sort()
    cdef int num = int(ss.size*a)
    if num>0:
        return (ss[num-1], ss[-1*num])
    else:
        return (np.NaN, np.NaN)

cpdef cal_long_short_factor_value_cython(np.ndarray[double, ndim=1] s, double a=0.2):
    cdef np.ndarray[double] ss = s[~np.isnan(s)]
    ss.sort()
    cdef int num = int(ss.size*a)
    if num>0:
        return (ss[num-1], ss[-1*num])
    else:
        return (np.NaN, np.NaN)

cpdef cal_signals_cython(np.ndarray[double, ndim=2] factors, double percent, int hold_days):
    cdef int data_length = factors.shape[0]
    cdef int col_num = factors.shape[1]
    cdef np.ndarray[double, ndim=2] new_factors = np.zeros((data_length, col_num))
    for i in range(col_num):
        new_factors[:, i] = -0.00000000000001*i + factors[:, i]
    signal_dict = {i: cal_long_short_factor_value_cython(new_factors[i, :], percent) for i in range(data_length)}
    lower_value = np.array([signal_dict[i][0] for i in range(data_length)])
    upper_value = np.array([signal_dict[i][1] for i in range(data_length)])
    short_df = np.where(factors <= lower_value.reshape(-1, 1), -1, 0)
    long_df = np.where(factors >= upper_value.reshape(-1, 1), 1, 0)
    signals = short_df + long_df
    signals = signals[hold_days-1::hold_days]
    signals = np.concatenate([np.full((hold_days-1, col_num), np.nan), signals], axis=0)
    signals = pd.DataFrame(signals)
    signals.fillna(method='ffill', inplace=True)
    return signals.dropna(axis=0)



cpdef cal_returns_cython(dict datas, np.ndarray[DTYPE_t, ndim=2] signals):
    # 根据高开低收的数据和具体的信号，计算资产的收益率和因子值，保存到self.returns和self.factors
    # self.returns = pd.DataFrame()
    cdef list return_list = []
    cdef int i, j, len_data, len_signal, pre_signal_idx, next_signal_idx
    cdef np.ndarray[DTYPE_t, ndim=1] signal_col, pre_signal, next_signal, ret, next_open, pre_close
    cdef np.ndarray[DTYPE_t, ndim=1] next_open_pre_close_rate, close_open_rate, next_open_open_rate
    for symbol in datas:
        data = datas[symbol].values
        signal_col = signals[:, symbol]
        len_data = len(data)
        len_signal = len(signal_col)
        signal = np.zeros(len_data, dtype=DTYPE)
        for i in range(len_data):
            signal[i] = signal_col[min(i, len_signal-1)]
        pre_signal = np.concatenate(([np.nan], signal[:-1]))
        next_signal = np.concatenate((signal[1:], [np.nan]))
        pre_close = np.concatenate(([np.nan], data[:-1, 3]))
        next_open = np.concatenate((data[1:, 0], [np.nan]))
        next_open_pre_close_rate = next_open / pre_close - 1
        close_open_rate = data[:, 3] / data[:, 0] - 1
        next_open_open_rate = next_open / data[:, 0] - 1
        ret = np.where((signal != next_signal) & (signal == pre_signal), next_open_pre_close_rate, ret)
        ret = np.where((signal != pre_signal) & (signal == next_signal), close_open_rate, ret)
        ret = np.where((signal != next_signal) & (signal != pre_signal), next_open_open_rate, ret)
        new_data = ret[1:] * signal[1:] * signal[1:]
        return_list.append(new_data)
    returns = pd.concat(return_list, axis=1, join="outer")
    returns.columns = datas.keys()
    return returns

cpdef cal_total_value_cython(np.ndarray[np.float64_t, ndim=2] datas, np.ndarray[np.float64_t, ndim=2] signals, np.ndarray[np.float64_t, ndim=2] returns, int hold_days, str total_value_save_path=None):
    cdef np.ndarray[np.float64_t, ndim=2] new_df, new_signal, total_value
    cdef list value_list = []
    cdef float new_factor = 1.0
    cdef int i
    for i in range(0, (len(returns) + 2 + (hold_days - (len(returns) % hold_days))), hold_days):
        if i != 0:
            new_df = returns[i - hold_days:i]
            new_signal = signals[i - hold_days:i]
            if len(new_df) > 0:
                new_df = new_df + 1.0
                new_df = np.cumprod(new_df, axis=0) - 1.0
                new_df = new_df * new_signal
                new_df = np.delete(new_df, np.where(~new_df.any(axis=0))[0], axis=1)
                new_df = np.delete(new_df, np.where(np.isnan(new_df).any(axis=0))[0], axis=1)
                total_value = np.mean(new_df, axis=1) + 1.0
                total_value = total_value * new_factor
                new_factor = total_value[-1]
                value_list.extend(list(total_value))
    values = pd.DataFrame(value_list).rename(columns={0: 'total_value'})
    values.index = returns.index
    return values