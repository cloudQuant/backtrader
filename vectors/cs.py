import copy

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import alphalens
from backtrader.vectors.cal_functions import *
# 排除的品种
remove_symbol = ["BB", "PG", "BB", "ER", "FB", "JR", "LR", "NR", "PM", "RR", "RS", "WH", "WR", "WS"]

class AlphaCs(object):
    def __init__(self, datas, params):
        '''
        :param datas: 字典格式，key是品种的名字，value是df格式，index是datetime,包含open,high,low,close,volume,openinterest
        :param params: 字典格式，key是参数名称，value是参数的值
        '''
        self.datas = datas
        self.params = params
        # 初始化后续可能使用到的属性
        self.commission = self.params.get('commission',0.0)
        self.initial_capital = self.params.get("initial_capital",1000000.0)
        self.factors = None                     # 保存因子值
        self.signals = None                     # 保存信号值
        self.values = None                      # 保存净值
        self.prices = None                      # 保存价格
        self.symbol = None                      # 保存运行的品种
        self.alphalens_factors = None           # 保存alphalens分析需要的因子数据
        # 默认是日线数据，这个在计算夏普率的时候会用到，如果不是每日的，需要继承的时候进行设置
        # 小时线设置为“Hours”, 分钟线设置为"Minutes", 秒设置为"seconds"
        self.time_frame = self.params.get("time_frame","Days")
        # 计算净值数据的保存地址，如果是None的话，代表不保存
        self.total_value_save_path = self.params.get('total_value_save_path',None)

    def cal_alpha(self, data):
        # 生成实例的时候覆盖这个函数，用于计算具体的因子，列名为factor
        return data

    # @profile
    def cal_factors(self):
        # 根据自定义的alpha公式，计算因子值
        factor_list = []
        symbol_list = sorted(self.datas.keys())
        for symbol in symbol_list:
            self.symbol = symbol
            # df = self.cal_alpha(self.datas[symbol])[['factor']].rename(columns={"factor": symbol})
            df = self.cal_alpha(self.datas[symbol])
            factor_list.append(df)
        self.factors = pd.concat(factor_list, axis=1, join="outer")
        self.factors = self.factors.fillna(method="ffill") # 增加一个填充
        return self.factors


    def cal_signals(self,factors_df,engine="numpy"):
        # 计算信号值
        if engine == "numba":
            _signals = cal_signals_by_numba.cal_signals_by_numba(factors_df.to_numpy(),self.params['percent'],self.params['hold_days'])
        else:
            _signals = cal_signals_by_numpy(self.factors.to_numpy(),self.params['percent'],self.params['hold_days'])
        return _signals,self.factors.index,self.factors.index



    def cal_values(self,datas,signals_arr,hold_days):
        commission = self.commission
        initial_capital = self.initial_capital
        # 数据行数
        signals_arr = np.delete(signals_arr,0,axis=0)
        data_rows = signals_arr.shape[0]
        data_cols = signals_arr.shape[1]
        # 初始化values_arr
        values_arr = np.zeros(signals_arr.shape)
        # 把各个品种的开盘价和收盘价数据转化成array
        opens_arr = self.params.get("opens_arr",None)
        if opens_arr is not None:
            opens_arr = self.params['opens_arr']
            closes_arr = self.params['closes_arr']
        else:
            opens_arr,closes_arr = convert_datas_to_array(datas)
        # 删除部分由于open_arr行数比signals_arr行数多的行
        delete = range(opens_arr.shape[0] - signals_arr.shape[0])
        opens_arr = np.delete(opens_arr, delete, axis=0)
        closes_arr = np.delete(closes_arr, delete, axis=0)
        # 初始化第一行的数据
        # 当前bar的信号，是根据factors计算出来每个bar的signals向下移动一位形成，意味着当前bar应该持有的仓位，1代表多，-1代表空
        sig_arr = signals_arr[0]
        # 计算这一行当中非0的元素的个数
        count = np.count_nonzero(sig_arr)
        # 计算出来每个品种开仓后的资金
        symbol_value = initial_capital / count * (1 - commission)
        # 记录每个品种的价值
        symbol_value_arr = np.array([symbol_value] * data_cols) * sig_arr * sig_arr
        # assert symbol_value_arr.sum()==initial_capital
        # 记录每个品种的开仓价
        symbol_open_price_arr = opens_arr[0]
        # 开始循环每一行,最后一行不循环，避免出现index越界
        for i in range(data_rows-1):
            # 如果当前bar持有到期，在下个bar开仓的时候需要平仓并进行新开仓，则
            if (i+1) % hold_days == 0:
                # 当前bar的信号
                sig_arr = signals_arr[i]
                # 下个bar的开盘价
                open_arr = opens_arr[i+1]
                # 计算收益率时候用到的收盘价
                symbol_close_price_arr = open_arr
                # print("初始资金分配：", symbol_value_arr)
                # 计算当前每个品种的value并保存到values_arr中
                return_arr = (symbol_close_price_arr-symbol_open_price_arr)/symbol_open_price_arr*sig_arr
                # print("计算得到的return_arr",return_arr)
                symbol_value_arr_cur = (1-commission)*symbol_value_arr*(1.0+return_arr)
                values_arr[i] =  symbol_value_arr_cur
                # 计算接下来预计要分给每个品种的资金
                new_sig_arr = signals_arr[i + 1]
                total_value_val =  np.nansum(symbol_value_arr_cur)
                count = np.count_nonzero(new_sig_arr)
                symbol_value = (1-commission)*total_value_val / count
                symbol_value_arr = np.array([symbol_value] * data_cols)*new_sig_arr*new_sig_arr
                # 保存开仓的信号
                symbol_open_price_arr = open_arr

            else:
                sig_arr = signals_arr[i]
                symbol_close_price_arr = closes_arr[i]
                return_arr = (symbol_close_price_arr - symbol_open_price_arr) / symbol_open_price_arr * sig_arr
                symbol_value_arr_cur = symbol_value_arr * (1 + return_arr)
                values_arr[i] = symbol_value_arr_cur

        # 最后一行的数据
        sig_arr = signals_arr[data_rows-1]
        close_arr = closes_arr[data_rows-1]
        return_arr = (symbol_close_price_arr - symbol_open_price_arr) / symbol_open_price_arr * sig_arr
        # print("计算得到的return_arr",return_arr)
        symbol_value_arr_cur = symbol_value_arr * (1 + return_arr)
        values_arr[data_rows-1] = symbol_value_arr_cur
        total_value_arr = np.nansum(values_arr,axis=1)
        return total_value_arr


    def cal_performance(self,total_value_arr,index_list,total_value_save_path=None):
        # print(total_value_arr)
        values_df = pd.DataFrame(total_value_arr).rename(columns={0: 'total_value'})
        values_df.index = index_list[1:]
        # 计算夏普率等指标,如果是日数据，直接计算，如果是分钟数据，抽样成日之后计算
        if self.time_frame == "Days":
            sharpe_ratio, average_rate, max_drawdown = get_rate_sharpe_drawdown(values_df['total_value'])
        else:
            values_df['date'] = values_df.index.date
            values_df = values_df.drop_duplicates(["date"],keep="last")
            sharpe_ratio, average_rate, max_drawdown = get_rate_sharpe_drawdown(values_df['total_value'])
        file_name = ""
        result_list = []
        for key in self.params:
            if "df" not in key and "save_path" not in key and "opens_arr" not in key and "closes_arr" not in key:
                file_name = file_name + f"{key}__{self.params[key]} "
                result_list.append(self.params[key])
        if total_value_save_path is not None:
            target_file = total_value_save_path + file_name + ".csv"
            self.values.to_csv(target_file)
        file_name += f"夏普率为__{round(sharpe_ratio, 4)}__年化收益率为:{round(average_rate, 4)}__最大回撤为:{round(max_drawdown, 4)}"
        print(file_name)
        result_list += [sharpe_ratio, average_rate, max_drawdown]

        return result_list


    def run(self):
        factors_df = self.cal_factors()
        _signals_arr,index_list,col_list = self.cal_signals(factors_df)
        total_value_arr = self.cal_values(self.datas, _signals_arr, self.params['hold_days'])
        return self.cal_performance(total_value_arr,index_list,self.total_value_save_path)

    def plot(self):
        # self.values[['total_value']].to_csv("d:/result/test_returns.csv")
        self.values[['total_value']].plot()
        plt.show()

    def rank_func(self, rank_func, rank_name):
        # rank函数的实现,对所有品种高开低收成交量等数据应用rank_func后的值进行排序
        """
        :param rank_func:具体的函数，以df为参数，返回一列值
        :param rank_name: 排序返回结果的名称，可以通过这个值和具体的品种名获取因子
        :return:
        :example:
        if not hasattr(self, "rank_a"):
            self.rank_func(lambda df: df.eval("-1*(1-(open/close))**2").shift(1).rolling(look_back_days).corr(
                    df['close']), "rank_a")
        data['factor'] = self.rank_a[symbol]
        """
        datas = self.datas
        symbol = self.symbol
        # print(symbol)
        look_back_days = self.params['look_back_days']
        if look_back_days == 1:
            look_back_days = 2
        begin_date = self.params["begin_date"]
        result_1 = []
        # 陈鑫博 字典循环从symbol改成key,避免symbol出现问题
        for key in self.datas:
            df = self.datas[key]
            df = df[df['trading_date'] >= pd.to_datetime(begin_date, utc=True)]
            df['func'] = rank_func(df)
            # e = df[['func']]
            # e.columns = [symbol]
            # result_1.append(e)
            result_1.append(df.loc[:,"func"].rename(key))
        df1 = pd.concat(result_1, axis=1, join="outer")
        # print("计算的因子值",df1)
        df2 = df1.rank(axis=1, ascending=True)
        # print(rank_name,df2)
        setattr(self, rank_name, df2)

    def run_alphalens(self,
                      groupby=None,
                      binning_by_group=False,
                      quantiles=5,
                      bins=None,
                      periods=(1, 5, 10),
                      filter_zscore=20,
                      groupby_labels=None,
                      max_loss=0.35,
                      zero_aware=False,
                      cumulative_returns=True,
                      long_short=True,
                      group_neutral=False,
                      by_group=False):
        self.alphalens_factors = pd.DataFrame()
        self.prices = pd.DataFrame()
        for symbol in self.datas:
            self.symbol = symbol
            # look_back_days = self.params['look_back_days']
            df = self.datas[symbol]
            # print("cs", symbol)
            df = self.cal_alpha(df)
            df['asset'] = symbol
            new_df = df[['close']]
            new_df.columns = [symbol]
            self.prices = pd.concat([self.prices, new_df], axis=1, join="outer")
            df = df[['trading_date', 'asset', 'factor']]
            self.alphalens_factors = pd.concat([self.alphalens_factors, df])
        self.alphalens_factors = self.alphalens_factors.sort_values(by=['trading_date', 'asset'])
        self.alphalens_factors = self.alphalens_factors.set_index(['trading_date', 'asset'])
        # print(self.alphalens_factors.tail())
        # print(self.prices.tail())
        # self.alphalens_factors.to_csv("d:/result/test_factor.csv")
        data = alphalens.utils.get_clean_factor_and_forward_returns(self.alphalens_factors, self.prices,
                                                                    groupby=groupby,
                                                                    binning_by_group=binning_by_group,
                                                                    quantiles=quantiles,
                                                                    bins=bins,
                                                                    periods=periods,
                                                                    filter_zscore=filter_zscore,
                                                                    groupby_labels=groupby_labels,
                                                                    max_loss=max_loss,
                                                                    zero_aware=zero_aware,
                                                                    cumulative_returns=cumulative_returns)

        alphalens.tears.create_full_tear_sheet(data, long_short=long_short, group_neutral=group_neutral,
                                               by_group=by_group)
