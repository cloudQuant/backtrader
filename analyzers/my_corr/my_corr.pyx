#cython: language_level=3
#distutils:language=c++
#cython: c_string_type=unicode, c_string_encoding=utf8

from libcpp.vector cimport vector
from libcpp.string cimport string
from libcpp.utility cimport move
cimport libc.math as cmath
from libc.stdlib cimport malloc,free

import time
import numpy as np
cimport numpy as np
import pandas as pd
cimport cython


#from cython.parallel cimport prange,parallel

ctypedef enum Mode:
    mean #相关系数矩阵中的平均值
    max  #相关系数矩阵中的最大值
    min  #相关系数矩阵中的最小值
    midian  #中位数
    last #相关系数矩阵中的最后一个

cdef extern from "corr.hh" nogil:
    # double pearson_corr(const vector[vector[double]]& data,Mode mode=Mode.mean)
    # double calc_corr(const vector[vector[double]]& mv)
    double calc_corr(const vector[vector[double]]& mv)



'''
@brief 该函数用于将列名为string类型的dataframe转换成vector
将pandas的各个series转换成C++的vector
'''
cdef vector[vector[double]] colname_series_to_vector(df:pd.DataFrame):
    cdef vector[string] colNames=df.columns.values
    cdef int i,j
    cdef str name

    cdef vector[vector[double]] samples

    for i in range(colNames.size()):
        name=colNames[i]
        samples.push_back(df[name].values)
    #for
    return move(samples)
#def

'''
@brief 该函数用于将列名为int类型的dataframe转换成vector
将pandas的各个series转换成C++的vector
'''
cdef vector[vector[double]] digit_name_series_to_vector(df:pd.DataFrame):
    cdef vector[int] colDigits=df.columns.values
    cdef int i,j
    cdef int num

    cdef vector[vector[double]] samples

    for i in range(colDigits.size()):
        num=colDigits[i]
        samples.push_back(df[num].values)
    #for
    return move(samples)
#def


cdef void dataframe_to_vectors(np.ndarray[np.double_t, ndim=2] arr,vector[vector[double]]& result):
    cdef int rows = arr.shape[0]
    cdef int cols = arr.shape[1]
    cdef int i,j

    cdef vector[double] row

    for i in range(rows):
        row = vector[double]()
        for j in range(cols):
            row.push_back(arr[i][j])
        #for
        result[i] = move(row)
    #for
#def

def main(df):
    a = time.perf_counter()
    # cdef double avgCorr = itdog.calc_corr(digit_name_series_to_vector(df))
    avgCorr = calc_corr(digit_name_series_to_vector(df))
    b = time.perf_counter()
    print(f"耗费时间为:{b - a}")
    print(f"average correlation is {avgCorr}")
    return avgCorr
#def


