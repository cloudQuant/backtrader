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
cimport openmp as op
cimport libc.math as cmath
DTYPE = np.float64
ctypedef np.float64_t DTYPE_t

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