#cython: language_level=3
#distutils: language=c++
#cython: c_string_type=unicode, c_string_encoding=utf8

import numpy as np
cimport numpy as np
import pandas as pd
import cython
from libcpp.vector cimport vector
from libcpp.utility cimport move
from libcpp.string cimport string
from cython.parallel cimport prange,parallel
cimport openmp as op
cimport libc.math as cmath


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