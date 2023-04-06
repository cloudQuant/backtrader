from numba import njit, config, guvectorize
from numba.pycc import CC
import numpy as np

# @njit
# def cal_signals_by_numba(factors_arr, percent, hold_days):
#     signals = np.zeros(factors_arr.shape)
#     data_length = factors_arr.shape[0]
#     col_len = factors_arr.shape[1]
#     diff_arr = np.array([-0.00000000000001 * i for i in range(col_len)])
#     short_arr = np.zeros(col_len)
#     long_arr = np.zeros(col_len)
#     signals[0] = np.array([np.NaN for i in range(col_len)])
#     for i in range(data_length - 1):
#         if i % hold_days == 0.0:
#             s = factors_arr[i,] + diff_arr
#             ss = s[~np.isnan(s)]
#             ss.sort()
#             num = int(ss.size * percent)
#             if num > 0:
#                 lower_value, upper_value = ss[num - 1], ss[-1 * num]
#             else:
#                 lower_value, upper_value = np.NaN, np.NaN
#
#             short_arr = np.where(s <= lower_value, -1.0, 0.0)
#             long_arr = np.where(s >= upper_value, 1.0, 0.0)
#             signals[i+1] = short_arr + long_arr
#         else:
#             signals[i+1] = signals[i]
#     return signals

@njit
def cal_signals_by_numba(factors_arr, percent, hold_days):
    signals = np.zeros(factors_arr.shape)
    data_length = factors_arr.shape[0]
    col_len = factors_arr.shape[1]
    diff_arr = np.array([-0.00000000000001 * i for i in range(col_len)])
    short_arr = np.zeros(col_len)
    long_arr = np.zeros(col_len)
    signals[0] = np.array([np.NaN for i in range(col_len)])
    for i in range(data_length - 1):
        if i % hold_days == 0.0:
            s = factors_arr[i,] + diff_arr
            ss = s[~np.isnan(s)]
            ss.sort()
            num = int(ss.size * percent)
            if num > 0:
                lower_value, upper_value = ss[num - 1], ss[-1 * num]
            else:
                lower_value, upper_value = np.NaN, np.NaN

            short_arr = np.where(s <= lower_value, -1.0, 0.0)
            long_arr = np.where(s >= upper_value, 1.0, 0.0)
            signals[i+1] = short_arr + long_arr
        else:
            signals[i+1] = signals[i]
    return signals

if __name__ == "__main__":
    cc = CC('cal_signals_by_numba')
    cc.export('cal_signals_by_numba', 'f8[:,:](f8[:,:], f8, f8)')(cal_signals_by_numba)
    cc.compile()
