import numpy as np
from numba import njit
from numba.pycc import CC

cc = CC('my_numba_module')
cc.verbose = True
@cc.export('cal_value_by_numba', 'f8[:](f8[:], f8[:], f8[:], f8[:], f8[:], i4[:], f8, f8, f8)')
@njit
def cal_value_by_numba(open_arr, high_arr, low_arr, close_arr, volume_arr, signal_arr, commission, init_value, percent):
    # 循环计算具体的持仓，盈亏，value的情况
    # 初始化持仓，可用资金，持仓盈亏，价值
    symbol_open_price_arr = np.zeros(signal_arr.shape)
    symbol_open_value_arr = np.zeros(signal_arr.shape)
    value_arr = np.zeros(signal_arr.shape)
    now_commission = 0.0
    # print("-----------计算第一个bar相关的信号--------------")
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
    # print("-----------计算第二个bar到倒数第二个bar相关的信号--------------")
    # 从第二个bar开始计算
    for i in range(1, len(open_arr) - 1):
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
    return value_arr
# # 定义输入输出类型
# input_types = (
#     types.float64[:],  # open_arr
#     types.float64[:],  # high_arr
#     types.float64[:],  # low_arr
#     types.float64[:],  # close_arr
#     types.float64[:],  # volume_arr
#     types.int32[:],    # signal_arr
#     types.float64,     # commission
#     types.float64,     # init_value
#     types.float64      # percent
# )
# output_type = types.float64[:]
if __name__ == "__main__":
    cc.compile()
# 提前编译函数
# compiled_cal_value_by_numba = numba.compile((output_type,) + input_types)(cal_value_by_numba)

# 使用提前编译的函数
# result = compiled_cal_value_by_numba(open_arr, high_arr, low_arr, close_arr, volume_arr, signal_arr, commission, init_value, percent)