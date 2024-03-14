import cython
import numpy as np
cimport numpy as np
import pandas as pd
from libcpp.vector cimport vector
from libcpp.utility cimport move
from libcpp.string cimport string
cimport openmp as op
cimport libc.math as cmath
DTYPE = np.float64
ctypedef np.float64_t DTYPE_t

cpdef cal_long_short_factor_value_cython(np.ndarray[double, ndim=1] s, double a=0.2):
    cdef np.ndarray[double] ss = s[~np.isnan(s)]
    ss.sort()
    cdef int num = int(ss.size*a)
    if num>0:
        return ss[num - 1], ss[-1 * num]
    else:
        return np.NaN, np.NaN

cpdef cal_long_short_signals(np.ndarray[double, ndim=2] factors, double percent, int hold_days):
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