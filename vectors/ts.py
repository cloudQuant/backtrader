# import copy
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from backtrader.vectors.cal_functions import *
import warnings
warnings.filterwarnings("ignore")


# 创建一个时间序列的类，用于快速计算具体策略的收益情况
class AlphaTs(object):
    # 传入具体的数据和函数进行初始化
    def __init__(self, datetime_arr,open_arr, high_arr, low_arr, close_arr, volume_arr,
                 params, signal_arr=None,engine="python"):
        # datas是字典格式，key是品种的名字，value是df格式，index是datetime,包含open,high,low,close,volume,openinterest
        # params是测试的时候使用的参数
        self.datetime_arr = datetime_arr
        self.open_arr = open_arr
        self.high_arr = high_arr
        self.low_arr = low_arr
        self.close_arr = close_arr
        self.volume_arr = volume_arr
        self.params = params
        self.signal_arr = signal_arr
        self.commission = params.get("commission",None)
        self.init_value = params.get("init_value",None)
        self.percent = params.get("percent",None)
        self.engine = engine

    def cal_signal(self):
        pass

    # 计算具体的alpha值并根据具体的alpha值计算信号，并计算具体的收益
    def cal_value(self):
        if self.commission is None:
            commission = 0.0
        else:
            commission = self.commission
        if self.init_value is None:
            init_value = 1000000
        else:
            init_value = self.init_value
        if self.percent is None:
            percent=1.0
        else:
            percent = self.percent
        # 如果传入的signal_arr是None的话，就自己计算一下signal
        if self.signal_arr is None:
            self.signal_arr = self.cal_signal()
        # 如果传入的signal_arr不是None的话，就计算具体的value
        if self.engine == "python":
            value_arr = self._cal_value(self.open_arr, self.high_arr, self.low_arr, self.close_arr,self.volume_arr,
                                        self.signal_arr, commission=commission, init_value=init_value,percent=percent)
        if self.engine == "numba":
            # from backtrader.utils.ts_cal_value.cal_value_by_numba import cal_value_by_numba
            from backtrader.utils.ts_cal_value.my_numba_module import cal_value_by_numba
            value_arr = cal_value_by_numba(self.open_arr, self.high_arr, self.low_arr, self.close_arr,self.volume_arr,
                                        self.signal_arr, commission, init_value, percent)
        if self.engine == "cython":
            from backtrader.utils.ts_cal_value_cython.my_cython_module import cal_value_by_cython
            value_arr = cal_value_by_cython(self.open_arr, self.high_arr, self.low_arr, self.close_arr, self.volume_arr,
                                           self.signal_arr, commission, init_value, percent)
        return value_arr

    def _cal_value(self, open_arr, high_arr, low_arr, close_arr,volume_arr,
                   signal_arr, commission, init_value,percent=1.0):
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
        if now_signal ==0:
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
        for i in range(1,len(open_arr)-1):
            pre_signal = signal_arr[i-1]
            now_signal = signal_arr[i]
            # 如果信号保持不变
            if pre_signal == now_signal:
                # 如果信号不是0
                if pre_signal!=0:
                    # 开仓价格
                    open_price = symbol_open_price_arr[i-1]
                    # 开仓使用资金
                    open_value = symbol_open_value_arr[i-1]
                    # 开仓时的账户资金
                    symbol_open_value_arr[i] = open_value
                    # 保存开仓价格
                    symbol_open_price_arr[i] = open_price
                    # 价值变化
                    value_change = (close_arr[i] - open_price)/open_price*pre_signal*open_value*percent
                    # 当前的价格
                    value_arr[i] = open_value + value_change - now_commission
                    # print("-----------------------------")
                    # print("datatime:",self.datetime_arr[i])
                    # print("当前进入pre_signal==now_signal")
                    # print("open_price", open_price)
                    # print("open_value",open_value)
                    # print("value_change:",value_change)
                    # print("now value:",value_arr[i])
                    # print("-----------------------------")
                else:
                    value_arr[i] = value_arr[i-1]
            # 如果信号发生了变化
            if pre_signal != now_signal:
                # 如果前一个信号不是0，现在是0了，代表这个bar出现平仓信号，下个bar平仓
                if pre_signal!=0 and now_signal==0:
                    open_price = symbol_open_price_arr[i - 1]
                    open_value = symbol_open_value_arr[i - 1]
                    value_change = (open_arr[i+1] - open_price) / open_price * pre_signal * open_value*percent
                    value_arr[i] = open_value + value_change - now_commission
                    now_commission = open_arr[i+1]/open_price * open_value*percent*commission
                    value_arr[i] = value_arr[i] - now_commission
                    symbol_open_price_arr[i] = 0
                    symbol_open_value_arr[i] = 0
                    # print("-----------------------------")
                    # print("datatime:", self.datetime_arr[i])
                    # print("当前进入pre_signal!=0 and now_signal==0")
                    # print("open_price",open_price)
                    # print("open_value", open_value)
                    # print("value_change:", value_change)
                    # print("now value:", value_arr[i])
                    # print("-----------------------------")
                # 如果前一个信号是0，但是现在不是0了，代表这个bar要新开仓
                if pre_signal==0 and now_signal!=0:
                    open_price = open_arr[i+1]
                    open_value = value_arr[i-1]
                    now_commission = open_value * percent * commission
                    value_arr[i] = open_value-now_commission
                    symbol_open_price_arr[i] = open_price
                    symbol_open_value_arr[i] = open_value
                    # print("-----------------------------")
                    # print("datatime:", self.datetime_arr[i])
                    # print("当前进入pre_signal==0 and now_signal!=0")
                    # print("open_price", open_price)
                    # print("open_value", open_value)
                    # print("now value:", value_arr[i])
                    # print("-----------------------------")
                # 如果前后信号都不等于0，但是信号不一样，代表要反手进行交易
                if pre_signal*now_signal==-1:
                    # 平旧仓位
                    open_price = symbol_open_price_arr[i - 1]
                    open_value = symbol_open_value_arr[i - 1]
                    value_change = (open_arr[i + 1] - open_price) / open_price * pre_signal * open_value*percent
                    value_arr[i] = value_arr[i - 1] + value_change - now_commission
                    # 新开仓
                    open_value = value_arr[i]
                    now_commission = open_value * percent * commission
                    value_arr[i] = open_value-now_commission
                    symbol_open_price_arr[i] = open_arr[i+1]
                    symbol_open_value_arr[i] = open_value
                    # print("-----------------------------")
                    # print("datatime:", self.datetime_arr[i])
                    # print("当前进入pre_signal*now_signal==-1")
                    # print("open_price", open_price)
                    # print("open_value", open_value)
                    # print("value_change:", value_change)
                    # print("now value:", value_arr[i])
                    # print("-----------------------------")
        # print("-----------计算最后一个bar相关的信号--------------")
        # 如果是最后一个bar,按照收盘价进行平仓
        pre_signal = signal_arr[i]
        now_signal = signal_arr[i+1]
        if now_signal==pre_signal:
            if pre_signal==0:
                value_arr[i + 1] = value_arr[i]
            else:
                open_price = symbol_open_price_arr[i]
                open_value = symbol_open_value_arr[i]
                symbol_open_price_arr[i+1] = open_price
                value_change = (close_arr[i+1] - open_price) / open_price * pre_signal * open_value*percent
                value_arr[i+1] = open_value + value_change
                symbol_open_value_arr[i+1] = open_value
                # print("-----------------------------")
                # print("datatime:", self.datetime_arr[i+1])
                # print("当前进入pre_signal*now_signal==-1")
                # print("open_price", open_price)
                # print("open_value", open_value)
                # print("value_change:", value_change)
                # print("now value:", value_arr[i+1])
                # print("-----------------------------")
        else:
            value_arr[i + 1] = value_arr[i]
        return value_arr

    def run(self):
        value_arr = self.cal_value()
        value_df = pd.DataFrame(value_arr,index=self.datetime_arr,columns=['total_value'])
        # print(value_df)
        sharpe_ratio, average_rate, max_drawdown = get_rate_sharpe_drawdown(value_df['total_value'])
        # print(f"sharpe_ratio:{sharpe_ratio}, average_rate:{average_rate}, max_drawdown:{max_drawdown}")
        return value_df


