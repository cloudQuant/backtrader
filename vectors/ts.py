# import copy
import pandas as pd
# import numpy as np
# import numpy as np
# import matplotlib.pyplot as plt
from backtrader.vectors.cal_performance import cal_factor_return, get_rate_sharpe_drawdown
from pyecharts import options as opts
# from pyecharts.commons.utils import JsCode
from pyecharts.charts import Kline, Line, Bar, Grid
# from pyecharts.globals import SymbolType
# from typing import List, Union
from pyecharts.faker import Faker
import warnings

warnings.filterwarnings("ignore")


# 创建一个时间序列的类，用于采用向量的方法计算时间序列的
class AlphaTs(object):
    # 传入具体的数据和函数进行初始化
    def __init__(self, datas, params):
        # datas是字典格式，key是品种的名字，value是df格式，index是datetime,包含open,high,low,close,volume,openinterest
        # params是测试的时候使用的参数
        self.datas = datas
        self.params = params

    def cal_alpha(self, data):
        pass

    def cal_signal(self, data):
        pass

    # 计算具体的alpha值并根据具体的alpha值计算信号，并计算具体的收益
    def cal_alpha_signal_return(self):
        datas = {}
        for key in self.datas:
            df = self.datas[key]
            df = self.cal_alpha(df)
            df = self.cal_signal(df)
            df = cal_factor_return(df)
            datas[key] = df
        self.datas = datas

    def run(self):
        self.cal_alpha_signal_return()
        # 计算各个品种的夏普率之类的数据，保存到结果中
        result = []
        for key in self.datas:
            # print(key)
            sharpe_ratio, average_rate, max_drawdown = get_rate_sharpe_drawdown(self.datas[key])
            result.append([key, sharpe_ratio, average_rate, max_drawdown])
        result_df = pd.DataFrame(result, columns=['symbol', 'sharpe_ratio', 'average_rate', 'max_drawdown'])
        return result_df

    # 打印某个品种的信号
    def plot_signal(self, symbol, save_path=""):
        data = self.datas[symbol]
        datetime_list = list(data.index)
        open_list = list(data['open'])
        high_list = list(data['high'])
        low_list = list(data['low'])
        close_list = list(data['close'])
        volume_list = list(data['volume'])
        # openinterest_list = list(data['open_interest'])
        x_data = datetime_list
        y_data = [[m, n, x, y, z] for m, n, x, y, z in zip(open_list, close_list, low_list, high_list, volume_list)]
        color_list = [1 if m < n else -1 for m, n, x, y, z in
                      zip(open_list, close_list, low_list, high_list, volume_list)]
        index_list = list(range(len(x_data)))
        vol_data = [[x, y, z] for x, y, z in zip(index_list, volume_list, color_list)]
        # 画出来具体的K线
        kline = (
            Kline()
            .add_xaxis(xaxis_data=x_data)
            .add_yaxis(
                series_name=symbol,
                y_axis=y_data,
                itemstyle_opts=opts.ItemStyleOpts(
                    color="#ef232a",
                    color0="#14b143",
                    border_color="#ef232a",
                    border_color0="#14b143",
                ),
                markpoint_opts=opts.MarkPointOpts(

                    data=[
                        opts.MarkPointItem(type_="max", name="最大值"),
                        opts.MarkPointItem(type_="min", name="最小值"),
                    ]
                )
            )
            .set_global_opts(
                legend_opts=opts.LegendOpts(
                    is_show=False, pos_bottom=10, pos_left="center"
                ),
                datazoom_opts=[
                    opts.DataZoomOpts(
                        is_show=False,
                        type_="inside",
                        xaxis_index=[0, 1],
                        range_start=98,
                        range_end=100,
                    ),
                    opts.DataZoomOpts(
                        is_show=True,
                        xaxis_index=[0, 1],
                        type_="slider",
                        pos_top="85%",
                        range_start=98,
                        range_end=100,
                    ),
                ],
                yaxis_opts=opts.AxisOpts(
                    is_scale=True,
                    splitarea_opts=opts.SplitAreaOpts(
                        is_show=True, areastyle_opts=opts.AreaStyleOpts(opacity=1)
                    ),
                ),
                tooltip_opts=opts.TooltipOpts(
                    trigger="axis",
                    axis_pointer_type="cross",
                    background_color="rgba(245, 245, 245, 0.8)",
                    border_width=1,
                    border_color="#ccc",
                    textstyle_opts=opts.TextStyleOpts(color="#000"),
                ),
                visualmap_opts=opts.VisualMapOpts(
                    is_show=False,
                    dimension=2,
                    series_index=5,
                    is_piecewise=True,
                    pieces=[
                        {"value": 1, "color": "#00da3c"},
                        {"value": -1, "color": "#ec0000"},
                    ],
                ),
                axispointer_opts=opts.AxisPointerOpts(
                    is_show=True,
                    link=[{"xAxisIndex": "all"}],
                    label=opts.LabelOpts(background_color="#777"),
                ),
                brush_opts=opts.BrushOpts(
                    x_axis_index="all",
                    brush_link="all",
                    out_of_brush={"colorAlpha": 0.1},
                    brush_type="lineX",
                ),
            )
        )

        # 分析bar的颜色，并进行设置
        y = []
        for idx, item in enumerate(vol_data):
            # print(idx, item)
            t = item[2]
            if t > 0:
                y.append(
                    opts.BarItem(
                        name="volume",
                        value=item[1],
                        itemstyle_opts=opts.ItemStyleOpts(color="red"),
                    )
                )
            else:
                y.append(
                    opts.BarItem(
                        name="volume",
                        value=item[1],
                        itemstyle_opts=opts.ItemStyleOpts(color="green"),
                    )
                )
        bar = (
            Bar()
            .add_xaxis(xaxis_data=x_data)
            .add_yaxis(
                series_name="Volume",
                y_axis=y,
                xaxis_index=1,
                yaxis_index=1,
                label_opts=opts.LabelOpts(is_show=False),
                category_gap=0,
                color=Faker.rand_color())

            .set_global_opts(
                xaxis_opts=opts.AxisOpts(
                    type_="category",
                    is_scale=True,
                    grid_index=1,
                    boundary_gap=False,
                    axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                    axistick_opts=opts.AxisTickOpts(is_show=False),
                    splitline_opts=opts.SplitLineOpts(is_show=False),
                    axislabel_opts=opts.LabelOpts(is_show=False),
                    split_number=20,
                    min_="dataMin",
                    max_="dataMax",
                ),
                yaxis_opts=opts.AxisOpts(
                    grid_index=1,
                    is_scale=True,
                    split_number=2,
                    axislabel_opts=opts.LabelOpts(is_show=False),
                    axisline_opts=opts.AxisLineOpts(is_show=False),
                    axistick_opts=opts.AxisTickOpts(is_show=False),
                    splitline_opts=opts.SplitLineOpts(is_show=False),
                ),
                legend_opts=opts.LegendOpts(is_show=False),
            )
        )

        # 画出来具体的交易的线段
        first_signal = None
        first_datetime = None
        first_high = None
        first_low = None
        # print(data[['signal']])
        data.to_csv("测试signal.csv")
        for datetime_, signal, high_, low_ in zip(data.index, data['signal'], data['high'], data['low']):
            if first_signal is None:
                first_signal = signal
                first_datetime = datetime_
                first_high = high_
                first_low = low_
            print(f"first_datetime:{first_datetime},first_signal:{first_signal}, datetime:{datetime_},signal:{signal}")
            # 如果信号发生了变化,画出来具体的线段
            if signal != first_signal:

                if first_signal == 1:
                    long_line = (
                        Line()
                        .add_xaxis(xaxis_data=[first_datetime, datetime_])
                        .add_yaxis(
                            series_name="long_signal",
                            y_axis=[first_low * 0.99, high_ * 1.01],
                            is_smooth=False,
                            # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
                            linestyle_opts=opts.LineStyleOpts(color="red", width=5, type_='dotted'),
                            label_opts=opts.LabelOpts(is_show=False),
                            symbol='arrow'
                        )
                        .set_global_opts(
                            xaxis_opts=opts.AxisOpts(
                                type_="category",
                                grid_index=1,
                                axislabel_opts=opts.LabelOpts(is_show=False),
                            ),
                            yaxis_opts=opts.AxisOpts(
                                grid_index=1,
                                split_number=3,
                                axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                                axistick_opts=opts.AxisTickOpts(is_show=False),
                                splitline_opts=opts.SplitLineOpts(is_show=False),
                                axislabel_opts=opts.LabelOpts(is_show=True),
                            ),
                        )
                    )
                    kline = kline.overlap(long_line)
                if first_signal == -1:
                    # 测试
                    short_line = (
                        Line()
                        .add_xaxis(xaxis_data=[first_datetime, datetime_])
                        .add_yaxis(
                            series_name="short_signal",
                            y_axis=[first_high * 1.01, low_ * 0.99],
                            is_smooth=False,
                            # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
                            linestyle_opts=opts.LineStyleOpts(color="green", width=5, type_='dotted'),
                            label_opts=opts.LabelOpts(is_show=False),
                            symbol='arrow'
                        )
                        .set_global_opts(
                            xaxis_opts=opts.AxisOpts(
                                type_="category",
                                grid_index=1,
                                axislabel_opts=opts.LabelOpts(is_show=False),
                            ),
                            yaxis_opts=opts.AxisOpts(
                                grid_index=1,
                                split_number=3,
                                axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                                axistick_opts=opts.AxisTickOpts(is_show=False),
                                splitline_opts=opts.SplitLineOpts(is_show=False),
                                axislabel_opts=opts.LabelOpts(is_show=True),
                            ),
                        )
                    )
                    kline = kline.overlap(short_line)
                first_signal = signal
                first_datetime = datetime_
                first_high = high_
                first_low = low_

        # Grid Overlap + Bar
        grid_chart = Grid(
            init_opts=opts.InitOpts(
                width="2000px",
                height="1000px",
                animation_opts=opts.AnimationOpts(animation=False),
            )
        )
        grid_chart.add(
            kline,
            grid_opts=opts.GridOpts(pos_left="10%", pos_right="8%", height="50%"),
        )
        grid_chart.add(
            bar,
            grid_opts=opts.GridOpts(
                pos_left="10%", pos_right="8%", pos_top="63%", height="16%"
            ),
        )

        grid_chart.render(save_path + f"{symbol}_ts_signal.html")
