#cython: language_level=3
#distutils: language=c++
#cython: c_string_type=unicode, c_string_encoding=utf8
import cython
import numpy as np
cimport numpy as np
# import pandas as pd
# from libcpp.vector cimport vector
# from libcpp.utility cimport move
# from libcpp.string cimport string
# cimport openmp as op
cimport libc.math as cmath
DTYPE = np.float64
ctypedef np.float64_t DTYPE_t
# '''
# @  将dataframe转换成vector
# '''
# @cython.boundscheck(False)
# @cython.wraparound(False)
# cdef void dataframe_to_vector(df, vector[vector[double]]& arr):
#     # 将DataFrame转换为ndarray
#     cdef double[:,:] arrView = df.values
#     cdef int rows = arrView.shape[0]
#     cdef int cols = arrView.shape[1]
#     cdef int i=0,j=0
#
#     if rows>0 and cols>0:
#         arr.reserve(cols)
#
#         for i in range(cols):
#             arr.push_back(vector[double]())
#             arr[i].resize(rows)
#         #for
#     #if
#
#     # 循环填充数据
#     for i in range(cols):
#         for j in range(rows):
#             # printf("thread:%d is working \n",op.omp_get_thread_num())
#             arr[i][j]=move(arrView[j, i])
#         #for
#     #for
#     #with
# #def


cdef inline double mean(const double[:]& arr):
    cdef double sum_value = 0.0
    cdef int n=arr.shape[0]
    cdef int i
    for i in range(n):
        sum_value += arr[i]
    return sum_value / n
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
cpdef inline double cal_sharpe_ratio(np.ndarray[double, ndim=1] arr):
    """
    @note 原来的代码
    """
    #cdef np.ndarray[double] rate =  np.diff(arr)/arr[:-1] #计算收益率
    # cdef double mean = rate.mean()
    # cdef double std = rate.std(ddof=1)
    # cdef double sharpe_ratio = mean*252**0.5/std
    '''
    单线程版本
    '''
    cdef int n =arr.shape[0]
    cdef double[:] rate=diff(arr)
    cdef double sum = 0.0
    cdef double sq = 0.0
    cdef int i
    for i in range(n):
        sum += rate[i]
        sq += rate[i] * rate[i]
    cdef double mn= sum/n
    cdef double std=cmath.sqrt(sq/n-cmath.pow(mn,2))
    cdef double ratio = mn * 252 ** 0.5/std
    return ratio
#def

@cython.boundscheck(False)
#@cython.wraparound(False)
@cython.cdivision(False)
cpdef inline double cal_average_rate(np.ndarray[double, ndim=1] arr):
    """
    @note原来的代码
    """
    cdef double begin_value = arr[0]
    cdef double end_value = arr[-1]
    cdef double days = arr.shape[0]
    # 如果计算的实际收益率为负数的话，收益率不能超过-100%,默认最小为-99.99%
    cdef double total_rate = cmath.fmax((end_value - begin_value)/begin_value, -0.9999)
    cdef double average_rate = cmath.pow(1 + total_rate,252/days) - 1
    return average_rate
#def

@cython.boundscheck(False)
@cython.wraparound(False)
@cython.cdivision(False)
cpdef inline double cal_max_drawdown(np.ndarray[double, ndim=1] arr):
    # cdef int index_j = np.argmax(np.array(np.maximum.accumulate(arr) - arr))
    # cdef int index_i = np.argmax(np.array(arr[:index_j]))
    # cdef double max_drawdown = (np.e ** arr[index_j] - np.e ** arr[index_i]) / np.e ** arr[index_i]
    cdef int n = arr.shape[0]
    cdef double max_drawdown = 0.0
    cdef double cum_max = arr[0]
    cdef double drawdown = 0.0

    for i in range(1, n):
        if arr[i] > cum_max:
            cum_max = arr[i]
            drawdown = 0.0
        else:
            drawdown = (cum_max - arr[i])/cum_max
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            #if
        #if
    #for
    return max_drawdown
#def






