import pandas as pd
import numpy as np
import time
import cal_return_sharpe_drawdown as ts
# from test_sharpe import cal_sharpe_ratio, cal_average_rate, cal_max_drawdown
# import calc_lib
from my_numba_cal_performance import get_sharpe_by_numba,get_average_rate_by_numba,get_maxdrawdown_by_numba
from pyecharts import options as opts
from pyecharts.charts import Bar

def get_sharpe(data, time_frame="Days"):
    # 计算夏普率，如果是日线数据，直接进行，如果不是日线数据，需要获取每日最后一个bar的数据用于计算每日收益率，然后计算夏普率
    # 对于期货的分钟数据而言，并不是按照15：00收盘算，可能会影响一点点夏普率等指标的计算，但是影响不大。
    if time_frame!="Days":
        data.loc[:, 'date'] = data.index.date
        data = data.drop_duplicates("date", keep='last')
    if len(data)==0:
        sharpe_ratio = np.NaN
    else:
        # 假设一年的交易日为252天
        rate0 = data['total_value'].pct_change().dropna()
        sharpe_ratio = rate0.mean() * 252 ** 0.5 / rate0.std()
    # print(rate0.mean(),rate0.std())
    return sharpe_ratio

def get_average_rate(data):
    # 计算复利年化收益率
    value_list = data['total_value'].tolist()
    begin_value = value_list[0]
    end_value = value_list[-1]
    # begin_date = data.index[0]
    # end_date = data.index[-1]
    # days = (end_date - begin_date).days
    days = len(value_list)
    # print(begin_date,begin_value,end_date,end_value,1/(days/365))
    # 如果计算的实际收益率为负数的话，收益率不能超过-100%,默认最小为-99.99%
    total_rate = max((end_value - begin_value) / begin_value,-0.9999)
    # if total_rate < -1.0: return -1.0
    # print("total rate=",total_rate)
    average_rate = (1 + total_rate) ** (252 / days) - 1
    return average_rate

def get_maxdrawdown(data):
    # 计算最大回撤
    X = data['total_value']
    # 计算最大回撤，直接传递净值
    endDate = np.argmax((np.maximum.accumulate(X) - X) / np.maximum.accumulate(X))
    if endDate == 0:
        return 0, len(X), endDate
    else:
        startDate = np.argmax(X[:endDate])
    return (X[endDate] - X[startDate]) / X[startDate]
# from cal_performance import cal_performance


def test_cython():
    time_result = []
    for n in [10000,100000,1000000]:
        print(f"{n}行下数据计算夏普率的耗费时间对比")
        np.random.seed(1)
        data = pd.DataFrame({i: np.random.randn(n) for i in ['open', 'high', 'low', 'close', 'volume', "total_value"]})
        data.index = pd.date_range('1/1/2012', periods=len(data), freq='5min')
        # data.index = pd.date_range('1/1/2012', periods=len(data), freq='1d')

        # print("---------------这是原来Py脚本的算法原型---------------------")
        total_time = 0
        for i in range(100):
            a = time.perf_counter()
            data = data[['total_value']]
            # print(data)
            data1 = data.copy()
            # print("原始的python结果")
            a = time.perf_counter()
            sharpe_ratio = get_sharpe(data1)
            average_rate = get_average_rate(data1)
            max_drawdown = get_maxdrawdown(data1)
            # ("Python计算结果：",f"sharpe_ratio:{sharpe_ratio}, average_rate:{average_rate}, max_drawdown:{max_drawdown}")
            b = time.perf_counter()
            total_time +=(b-a)
            # print(f"python耗费时间为:{b - a}")
        avg_time_1 = round(total_time/100,6)
        print(f"python计算结果为：sharpe_ratio={sharpe_ratio}，average_rate={average_rate}，max_drawdown={max_drawdown}")



        # print("---------------这是原来cython的算法原型---------------------")
        total_time = 0
        for i in range(100):
            a = time.perf_counter()
            arr = data['total_value']
            sharpe_ratio = ts.cal_sharpe_ratio_cy(arr)
            average_rate = ts.cal_average_rate_cy(arr)
            max_drawdown = ts.cal_max_drawdown_cy(arr)
            # print("Cython计算结果：", f"sharpe_ratio:{sharpe_ratio}, average_rate:{average_rate}, max_drawdown:{max_drawdown}")
            b = time.perf_counter()
            total_time += (b - a)
            # print(f"cython耗费时间为:{b - a}")
        avg_time_2 = round(total_time/100,6)
        print(f"cython计算结果为：sharpe_ratio={sharpe_ratio}，average_rate={average_rate}，max_drawdown={max_drawdown}")



        # 直接c++函数三个指标计算使用的时间
        # a = time.perf_counter()
        # arr = np.ascontiguousarray(data['total_value'])
        # sharpe_ratio = calc_lib.sharpe_ratio_c(arr)
        # average_rate = calc_lib.annualized_return_c(arr)
        # max_drawdown = calc_lib.max_drawdown_c(arr)
        # print(f"c++计算结果 sharpe_ratio:{sharpe_ratio}, average_rate:{average_rate}, max_drawdown:{max_drawdown}")
        # b = time.perf_counter()
        # print(f"c++编写函数耗费时间为:{b - a}")

        # total_time = 0
        # for i in range(100):
        #     a = time.perf_counter()
        #     arr = np.array(data['total_value'])
        #     # print(s)
        #     # print(s)
        #     # sharpe_ratio,average_rate,max_drawdown= cal_performance(arr)
        #     sharpe_ratio = get_sharpe_by_numba(arr)
        #     average_rate = get_average_rate_by_numba(arr)
        #     max_drawdown = get_maxdrawdown_by_numba(arr)
        #     # print("Numba计算结果：",f"sharpe_ratio:{sharpe_ratio}, average_rate:{average_rate}, max_drawdown:{max_drawdown}")
        #     b = time.perf_counter()
        #     total_time += (b - a)
        #     # print(f"numba编写函数耗费时间为:{b - a}")
        # avg_time_3 = round(total_time/100,6)
        # print(f"numba计算结果为：sharpe_ratio={sharpe_ratio}，average_rate={average_rate}，max_drawdown={max_drawdown}")
        # time_result.append([avg_time_1,avg_time_3,avg_time_2])
        time_result.append([avg_time_1, avg_time_2])
    return time_result

if __name__ =='__main__':
    result = test_cython()
    print(result)
    c = (
        Bar()
            .add_xaxis(["1万行","10万行","100万行"])
            .add_yaxis("python", [i[0] for i in result])
            #.add_yaxis("numba", [i[1] for i in result])
            .add_yaxis("cython多线程", [i[2] for i in result])
            .reversal_axis()
            .set_series_opts(label_opts=opts.LabelOpts(position="right"))
            .set_global_opts(title_opts=opts.TitleOpts(title="耗费时间对比"))
            #.render("d:/result/夏普率耗费时间对比.html")
            .render("./夏普率耗费时间对比.html")
    )