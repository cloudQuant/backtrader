import cython
import numpy as np
cimport numpy as np
import pandas as pd
from libcpp.vector cimport vector
from libcpp.utility cimport move
from libcpp.string cimport string
cimport openmp as op
cimport libc.math as cmath

cpdef cal_long_short_signals(np.ndarray[double, ndim=2] factors, int rows_len, int cols_len, double percent, int hold_days):
    cdef int i = 0
    cdef int num
    cdef int size
    cdef double lower_value
    cdef double upper_value
    cdef np.ndarray[double, ndim=2] signals = np.zeros((rows_len, cols_len))
    cdef np.ndarray[double, ndim=1] diff_arr = np.array([-0.00000000000001 * i for i in range(cols_len)])
    cdef np.ndarray[double, ndim=1] short_arr = np.zeros(cols_len)
    cdef np.ndarray[double, ndim=1] long_arr = np.zeros(cols_len)
    signals[0] = np.array([np.NaN for _ in range(cols_len)])
    for i in range(rows_len - 1):
        if i % hold_days == 0:
            s = factors[i,] + diff_arr
            ss = s[~np.isnan(s)]
            ss.sort()
            size = ss.size
            num = int(size * percent)
            if num > 0:
                lower_value, upper_value = ss[num - 1], ss[-1 * num]
            else:
                lower_value, upper_value = np.NaN, np.NaN
            short_arr = np.where(s <= lower_value, -1.0, 0.0)
            long_arr = np.where(s >= upper_value, 1.0, 0.0)
            signals[i + 1] = short_arr + long_arr
        else:
            signals[i + 1] = signals[i]
    return signals
