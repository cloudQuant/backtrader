# from numba import njit
from numba.pycc import CC
import numpy as np

cc = CC('calculation_by_numba')


@cc.export('cal_long_short_signals', 'f8[:,:](f8[:,:], f8, int64)')
def cal_long_short_signals(factors_arr, percent, hold_days):
    signals = np.zeros(factors_arr.shape)
    data_length = factors_arr.shape[0]
    col_len = factors_arr.shape[1]
    diff_arr = np.array([-0.00000000000001 * i for i in range(col_len)])
    short_arr = np.zeros(col_len)
    long_arr = np.zeros(col_len)
    signals[0] = np.array([np.NaN for _ in range(col_len)])
    for i in range(data_length - 1):
        if i % hold_days == 0:
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
            signals[i + 1] = short_arr + long_arr
        else:
            signals[i + 1] = signals[i]
    # signals = np.delete(signals,0,axis=0)
    return signals


if __name__ == "__main__":
    cc.compile()
