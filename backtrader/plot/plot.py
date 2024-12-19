#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
###############################################################################
#
# Copyright (C) 2015-2020 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import bisect
import collections
import time
import datetime
import itertools
import math
import operator
import os
import sys

import matplotlib
import pandas as pd
import numpy as np  # guaranteed by matplotlib
import matplotlib.dates as mdates
import matplotlib.font_manager as mfontmgr
import matplotlib.legend as mlegend
import matplotlib.ticker as mticker
import backtrader as bt
import dash
from dash import dcc
from dash import html

from dash.dependencies import Input, Output
# from jupyter_plotly_dash import JupyterDash

from collections import OrderedDict

from ..utils.py3 import range, with_metaclass, string_types, integer_types
from .. import AutoInfoClass, MetaParams, TimeFrame, date2num

from .finance import plot_candlestick, plot_ohlc, plot_volume, plot_lineonclose
from .formatters import (MyVolFormatter, MyDateFormatter, getlocator)
from . import locator as loc
from .multicursor import MultiCursor
from .scheme import PlotScheme
from .utils import tag_box_style

import plotly as py
import plotly.graph_objs as go
import plotly.express as px
import plotly.offline as py
import plotly.figure_factory as ff
import copy


def cal_macd_system(data, short_=26, long_=12, m=9):
    '''
    data是包含高开低收成交量的标准dataframe
    short_,long_,m分别是macd的三个参数
    返回值是包含原始数据和diff,dea,macd三个列的dataframe
    '''
    data['diff'] = data['close'].ewm(adjust=False, alpha=2 / (short_ + 1), ignore_na=True).mean() - \
                   data['close'].ewm(adjust=False, alpha=2 / (long_ + 1), ignore_na=True).mean()
    data['dea'] = data['diff'].ewm(adjust=False, alpha=2 / (m + 1), ignore_na=True).mean()
    data['macd'] = 2 * (data['diff'] - data['dea'])
    return data


def split_data(df) -> dict:
    datas = list(zip(df['open'], df['close'], df['low'], df['high'], df['volume'], df['up_bar']))
    times = list(df.index)
    vols = list(df['volume'])
    macds = list(df['macd'])
    difs = list(df['diff'])
    deas = list(df['dea'])

    return {
        "datas": datas,
        "times": times,
        "vols": vols,
        "macds": macds,
        "difs": difs,
        "deas": deas,
    }


def get_up_scatter(df):
    # 标记出上涨的点，格式是列表，列表里面是（时间、最低价)组成的元组
    mark_line_data = []
    first_swing = None
    pre_index = None
    pre_low = None
    pre_high = None
    for index, row in df.iterrows():
        up_bar = row['up_bar']
        dn_bar = row['dn_bar']
        out_bar = row['out_bar']
        in_bar = row['in_bar']
        high = row['high']
        low = row['low']
        if first_swing is None:
            if up_bar == 1:
                first_swing = "up"
            if dn_bar == 1:
                first_swing = "dn"
        if first_swing == "up" and dn_bar == 1:
            # mark_line_data.append([index, high])
            first_swing = "dn"
        if first_swing == "dn" and up_bar == 1:
            mark_line_data.append([pre_index, pre_low])
            first_swing = "up"
        pre_index = index
        pre_low = low
        pre_high = high
        # print(mark_line_data[:10])
    return mark_line_data


def get_dn_scatter(df):
    # 标记出下跌的点，格式是列表，列表里面是（时间、最高价)组成的元组
    mark_line_data = []
    first_swing = None
    pre_index = None
    pre_low = None
    pre_high = None
    for index, row in df.iterrows():
        up_bar = row['up_bar']
        dn_bar = row['dn_bar']
        out_bar = row['out_bar']
        in_bar = row['in_bar']
        high = row['high']
        low = row['low']
        if first_swing is None:
            if up_bar == 1:
                first_swing = "up"
            if dn_bar == 1:
                first_swing = "dn"
        if first_swing == "up" and dn_bar == 1:
            mark_line_data.append([pre_index, pre_high])
            first_swing = "dn"
        if first_swing == "dn" and up_bar == 1:
            # mark_line_data.append([index, low])
            first_swing = "up"
        pre_index = index
        pre_low = low
        pre_high = high
    # print(mark_line_data[:10])
    return mark_line_data


def get_valid_point(df):
    valid_dn_point_list = []
    valid_up_point_list = []
    dn_point_point_list = []
    up_point_point_list = []
    first_swing = None
    pre_index = None
    pre_low = None
    pre_high = None
    for index, row in df.iterrows():
        up_bar = row['up_bar']
        dn_bar = row['dn_bar']
        high = row['high']
        low = row['low']
        if first_swing is None:
            if up_bar == 1:
                first_swing = "up"
            if dn_bar == 1:
                first_swing = "dn"
        if first_swing == "up" and dn_bar == 1:
            dn_point_point_list.append([pre_index, pre_high])
            first_swing = "dn"
            if len(dn_point_point_list) > 1 and len(up_point_point_list) > 1:
                pre_pre_high = dn_point_point_list[-2][1]
                # 如果当前的最高点大于前一个最高点，那么前一个上升拐点至少是一个测试点
                if pre_high > pre_pre_high:
                    # 尝试获取前一个dn_point的最高价和前前一个dn_point的最高价
                    pre_1_index, pre_1_low = up_point_point_list[-1]
                    pre_2_index, pre_2_low = up_point_point_list[-2]
                    # 如果前一个拐点是上升的
                    if pre_1_low < pre_2_low:
                        valid_up_point_list.append([pre_1_index, pre_1_low])

        if first_swing == "dn" and up_bar == 1:
            up_point_point_list.append([pre_index, pre_low])
            first_swing = "up"
            # 获取前一个up_point
            if len(dn_point_point_list) > 1 and len(up_point_point_list) > 1:
                pre_pre_low = up_point_point_list[-2][1]
                # 如果当前的最低点小于前一个最低点,那么前一个最高价就是测试点
                if pre_low < pre_pre_low:
                    # 尝试获取前一个dn_point的最高价和前前一个dn_point的最高价
                    pre_1_index, pre_1_high = dn_point_point_list[-1]
                    pre_2_index, pre_2_high = dn_point_point_list[-2]
                    # 如果前一个拐点是上升的
                    if pre_1_high > pre_2_high:
                        valid_dn_point_list.append([pre_1_index, pre_1_high])

        pre_index = index
        pre_low = low
        pre_high = high
    # print(mark_line_data[:10])
    return valid_dn_point_list, valid_up_point_list


def draw_chart(data, df, bk_list, bp_list, sk_list, sp_list):
    kline = (
        Kline()
            .add_xaxis(xaxis_data=data["times"])
            .add_yaxis(
            series_name="",
            y_axis=data["datas"],
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
            ),
            # markline_opts = opts.MarkLineOpts(
            #     label_opts=opts.LabelOpts(
            #         position="middle", color="blue", font_size=15
            #     ),
            #     data=split_data_part(),
            #     symbol=["circle", "none"],
            # ),
        )

            .set_series_opts(
            # 为了不影响标记点，这里把标签关掉
            label_opts=opts.LabelOpts(is_show=False),
            markpoint_opts=opts.MarkPointOpts(
                data=[
                    opts.MarkPointItem(type_="min", name="y轴最小", value_index=1),
                    opts.MarkPointItem(type_="max", name="y轴最大", value_index=1)
                ]))

            .set_global_opts(
            title_opts=opts.TitleOpts(title="K线周期图表", pos_left="0"),
            xaxis_opts=opts.AxisOpts(
                type_="category",
                is_scale=True,
                boundary_gap=False,
                axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                splitline_opts=opts.SplitLineOpts(is_show=False),
                split_number=20,
                min_="dataMin",
                max_="dataMax",
            ),
            yaxis_opts=opts.AxisOpts(
                is_scale=True, splitline_opts=opts.SplitLineOpts(is_show=True)
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis", axis_pointer_type="line"),
            datazoom_opts=[
                opts.DataZoomOpts(
                    is_show=False, type_="inside", xaxis_index=[0, 0], range_end=100
                ),
                opts.DataZoomOpts(
                    is_show=True, xaxis_index=[0, 1], pos_top="97%", range_end=100
                ),
                opts.DataZoomOpts(is_show=False, xaxis_index=[0, 2], range_end=100),
            ],
            # 三个图的 axis 连在一块
            # axispointer_opts=opts.AxisPointerOpts(
            #     is_show=True,
            #     link=[{"xAxisIndex": "all"}],
            #     label=opts.LabelOpts(background_color="#777"),
            # ),
        )
    )
    esc = get_up_scatter(df)
    esc_dn = get_dn_scatter(df)

    all_up_dn = esc + esc_dn
    all_up_dn_sorted = sorted(all_up_dn, key=lambda x: x[0])
    line_index = [i[0] for i in all_up_dn_sorted]
    line_value = [i[1] for i in all_up_dn_sorted]

    kline_line = (
        Line()
            .add_xaxis(xaxis_data=line_index)
            .add_yaxis(
            series_name="波",
            y_axis=line_value,
            is_smooth=False,
            # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
            linestyle_opts=opts.LineStyleOpts(color="black", width=4, type_="dashed"),
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
    # Overlap Kline + Line
    overlap_kline_line = kline.overlap(kline_line)

    # 尝试画出来支撑线
    valid_dn_point_list, valid_up_point_list = get_valid_point(df)
    print(len(valid_dn_point_list), len(valid_up_point_list))
    es = (EffectScatter()
          .add_xaxis([i[0] for i in valid_up_point_list])
          .add_yaxis("", [i[1] for i in valid_up_point_list], symbol=SymbolType.TRIANGLE))
    # overlap_kline_line = kline
    overlap_kline_line = overlap_kline_line.overlap(es)

    es_dn = (EffectScatter()
             .add_xaxis([i[0] for i in valid_dn_point_list])
             .add_yaxis("", [i[1] for i in valid_dn_point_list], symbol=SymbolType.DIAMOND))
    # overlap_kline_line = kline
    overlap_kline_line = overlap_kline_line.overlap(es_dn)

    # 尝试给支撑增加一些支撑线
    for d1, d2 in zip(valid_dn_point_list[:-1], valid_dn_point_list[1:]):
        # print(d1,d2)
        dn_line = (
            Line()
                .add_xaxis(xaxis_data=[d1[0], d2[0]])
                .add_yaxis(
                series_name="支撑",
                y_axis=[d1[1], d2[1]],
                is_smooth=False,
                # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
                linestyle_opts=opts.LineStyleOpts(color="green", width=2, type_='dotted'),
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
        overlap_kline_line = kline.overlap(dn_line)

    for d1, d2 in zip(valid_up_point_list[:-1], valid_up_point_list[1:]):
        # print(d1,d2)
        dn_line = (
            Line()
                .add_xaxis(xaxis_data=[d1[0], d2[0]])
                .add_yaxis(
                series_name="支撑",
                y_axis=[d1[1], d2[1]],
                is_smooth=False,
                # linestyle_opts=opts.LineStyleOpts(opacity=0.5),
                linestyle_opts=opts.LineStyleOpts(color="red", width=2, type_='dotted'),
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
        overlap_kline_line = kline.overlap(dn_line)

    # 添加买卖点
    # 开多
    bk_df = df[df.index.isin([str(i[0]) for i in bk_list])]
    bk_c = (
        EffectScatter()
            .add_xaxis(bk_df.index)
            .add_yaxis("", bk_df.low, color="red", symbol='image://c:/result/img/开多.png', symbol_size=10)
            .set_global_opts(
            title_opts=opts.TitleOpts(title="buy")
        )
    )
    overlap_kline_line = kline.overlap(bk_c)
    # 平多
    bp_df = df[df.index.isin([str(i[0]) for i in bp_list])]
    bp_c = (
        EffectScatter()
            .add_xaxis(bp_df.index)
            .add_yaxis("", bp_df.high, color="green", symbol='image://c:/result/img/平多.png', symbol_size=10)
            .set_global_opts(
            title_opts=opts.TitleOpts(title="=sell")
        )
    )
    overlap_kline_line = kline.overlap(bp_c)
    # 做多的线段
    for bk, bp in zip([str(i[0]) for i in bk_list], [str(i[0]) for i in bp_list]):
        # print(bk,bk)
        try:
            bk_df = df[df.index >= bk]
            new_bk = list(bk_df.index)[1]
            bk_price = list(bk_df['open'])[1]
            bp_df = df[df.index >= bp]
            new_bp = list(bp_df.index)[1]
            bp_price = list(bp_df['open'])[1]
            print("做多信号", [bk, new_bk, bp, new_bp], [bk_price, bp_price])
            # 测试
            long_line = (
                Line()
                    .add_xaxis(xaxis_data=[bk, bp])
                    .add_yaxis(
                    series_name="long_signal",
                    y_axis=[bk_price, bp_price],
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
            overlap_kline_line = kline.overlap(long_line)
        except:
            print("有些信号没有对齐")

    sk_df = df[df.index.isin([str(i[0]) for i in sk_list])]
    sk_c = (
        EffectScatter()
            .add_xaxis(sk_df.index)
            .add_yaxis("", sk_df.high, color="green", symbol='image://c:/result/img/开空.png', symbol_size=10)
            .set_global_opts(
            title_opts=opts.TitleOpts(title="sellshort")
        )
    )
    overlap_kline_line = kline.overlap(sk_c)

    sp_df = df[df.index.isin([str(i[0]) for i in sp_list])]
    sp_c = (
        EffectScatter()
            .add_xaxis(sp_df.index)
            .add_yaxis("", sp_df.low, color="red", symbol='image://c:/result/img/平空.png', symbol_size=10)
            .set_global_opts(
            title_opts=opts.TitleOpts(title="buytocover")
        )
    )
    overlap_kline_line = kline.overlap(sp_c)

    # 做空的线段
    for sk, sp in zip([str(i[0]) for i in sk_list], [str(i[0]) for i in sp_list]):
        try:
            sk_df = df[df.index >= sk]
            sk = list(sk_df.index)[1]
            sk_price = list(sk_df['open'])[1]
            sp_df = df[df.index >= sp]
            sp = list(sp_df.index)[1]
            sp_price = list(sp_df['open'])[1]
            print("做空信号", [sk, sp], [sk_price, sp_price])
            # 测试
            short_line = (
                Line()
                    .add_xaxis(xaxis_data=[sk, sp])
                    .add_yaxis(
                    series_name="short_signal",
                    y_axis=[sk_price, sp_price],
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
            overlap_kline_line = kline.overlap(short_line)
        except:
            print("空头信号出错")
            # Bar-1
    bar_1 = (
        Bar()
            .add_xaxis(xaxis_data=data["times"])
            .add_yaxis(
            series_name="Volumn",
            y_axis=data["vols"],
            xaxis_index=1,
            yaxis_index=1,
            label_opts=opts.LabelOpts(is_show=False),
            # 根据 echarts demo 的原版是这么写的
            # itemstyle_opts=opts.ItemStyleOpts(
            #     color=JsCode("""
            #     function(params) {
            #         var colorList;
            #         if (data.datas[params.dataIndex][1]>data.datas[params.dataIndex][0]) {
            #           colorList = '#ef232a';
            #         } else {
            #           colorList = '#14b143';
            #         }
            #         return colorList;
            #     }
            #     """)
            # )
            # 改进后在 grid 中 add_js_funcs 后变成如下
            itemstyle_opts=opts.ItemStyleOpts(
                color=JsCode(
                    """
                function(params) {
                    var colorList;
                    if (barData[params.dataIndex][1] > barData[params.dataIndex][0]) {
                        colorList = '#ef232a';
                    } else {
                        colorList = '#14b143';
                    }
                    return colorList;
                }
                """
                )
            ),
        )
            .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                type_="category",
                grid_index=1,
                axislabel_opts=opts.LabelOpts(is_show=False),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )

    # Bar-2 (Overlap Bar + Line)
    bar_2 = (
        Bar()
            .add_xaxis(xaxis_data=data["times"])
            .add_yaxis(
            series_name="MACD",
            y_axis=data["macds"],
            xaxis_index=2,
            yaxis_index=2,
            label_opts=opts.LabelOpts(is_show=False),
            itemstyle_opts=opts.ItemStyleOpts(
                color=JsCode(
                    """
                        function(params) {
                            var colorList;
                            if (params.data >= 0) {
                              colorList = '#ef232a';
                            } else {
                              colorList = '#14b143';
                            }
                            return colorList;
                        }
                        """
                )
            ),
        )
            .set_global_opts(
            xaxis_opts=opts.AxisOpts(
                type_="category",
                grid_index=2,
                axislabel_opts=opts.LabelOpts(is_show=False),
            ),
            yaxis_opts=opts.AxisOpts(
                grid_index=2,
                split_number=4,
                axisline_opts=opts.AxisLineOpts(is_on_zero=False),
                axistick_opts=opts.AxisTickOpts(is_show=False),
                splitline_opts=opts.SplitLineOpts(is_show=False),
                axislabel_opts=opts.LabelOpts(is_show=True),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )

    line_2 = (
        Line()
            .add_xaxis(xaxis_data=data["times"])
            .add_yaxis(
            series_name="DIF",
            y_axis=data["difs"],
            xaxis_index=2,
            yaxis_index=2,
            label_opts=opts.LabelOpts(is_show=False),
        )
            .add_yaxis(
            series_name="DIF",
            y_axis=data["deas"],
            xaxis_index=2,
            yaxis_index=2,
            label_opts=opts.LabelOpts(is_show=False),
        )
            .set_global_opts(legend_opts=opts.LegendOpts(is_show=False))
    )
    # 最下面的柱状图和折线图
    overlap_bar_line = bar_2.overlap(line_2)

    # 最后的 Grid
    grid_chart = Grid(init_opts=opts.InitOpts(width="1400px", height="800px"))

    # 这个是为了把 data.datas 这个数据写入到 html 中,还没想到怎么跨 series 传值
    # demo 中的代码也是用全局变量传的
    grid_chart.add_js_funcs("var barData = {}".format(data["datas"]))

    # K线图和 MA5 的折线图
    grid_chart.add(
        overlap_kline_line,
        grid_opts=opts.GridOpts(pos_left="3%", pos_right="1%", height="60%"),
    )
    # Volumn 柱状图
    grid_chart.add(
        bar_1,
        grid_opts=opts.GridOpts(
            pos_left="3%", pos_right="1%", pos_top="71%", height="10%"
        ),
    )
    # MACD DIFS DEAS
    grid_chart.add(
        overlap_bar_line,
        grid_opts=opts.GridOpts(
            pos_left="3%", pos_right="1%", pos_top="82%", height="14%"
        ),
    )
    grid_chart.render("c:/result/test_price_action_kline_chart.html")


class PInfo(object):
    def __init__(self, sch):
        self.sch = sch
        self.nrows = 0
        self.row = 0
        self.clock = None
        self.x = None
        self.xlen = 0
        self.sharex = None
        self.figs = list()
        self.cursors = list()
        self.daxis = collections.OrderedDict()
        self.vaxis = list()
        self.zorder = dict()
        self.coloridx = collections.defaultdict(lambda: -1)
        self.handles = collections.defaultdict(list)
        self.labels = collections.defaultdict(list)
        self.legpos = collections.defaultdict(int)

        self.prop = mfontmgr.FontProperties(size=self.sch.subtxtsize)

    def newfig(self, figid, numfig, mpyplot):
        fig = mpyplot.figure(figid + numfig)
        self.figs.append(fig)
        self.daxis = collections.OrderedDict()
        self.vaxis = list()
        self.row = 0
        self.sharex = None
        return fig

    def nextcolor(self, ax):
        self.coloridx[ax] += 1
        return self.coloridx[ax]

    def color(self, ax):
        return self.sch.color(self.coloridx[ax])

    def zordernext(self, ax):
        z = self.zorder[ax]
        if self.sch.zdown:
            return z * 0.9999
        return z * 1.0001

    def zordercur(self, ax):
        return self.zorder[ax]


class Plot_OldSync(with_metaclass(MetaParams, object)):
    params = (('scheme', PlotScheme()),)

    def __init__(self, **kwargs):
        for pname, pvalue in kwargs.items():
            setattr(self.p.scheme, pname, pvalue)

    def drawtag(self, ax, x, y, facecolor, edgecolor, alpha=0.9, **kwargs):

        txt = ax.text(x, y, '%.2f' % y, va='center', ha='left',
                      fontsize=self.pinf.sch.subtxtsize,
                      bbox=dict(boxstyle=tag_box_style,
                                facecolor=facecolor,
                                edgecolor=edgecolor,
                                alpha=alpha),
                      # 3.0 is the minimum default for text
                      zorder=self.pinf.zorder[ax] + 3.0,
                      **kwargs)

    def plot(self, strategy, figid=0, numfigs=1, iplot=True,
             start=None, end=None, **kwargs):
        # pfillers={}):
        if not strategy.datas:
            return

        if not len(strategy):
            return

        if iplot:
            if 'ipykernel' in sys.modules:
                matplotlib.use('nbagg')

        # this import must not happen before matplotlib.use
        import matplotlib.pyplot as mpyplot
        self.mpyplot = mpyplot

        self.pinf = PInfo(self.p.scheme)
        self.sortdataindicators(strategy)
        self.calcrows(strategy)

        st_dtime = strategy.lines.datetime.plot()
        if start is None:
            start = 0
        if end is None:
            end = len(st_dtime)

        if isinstance(start, datetime.date):
            start = bisect.bisect_left(st_dtime, date2num(start))

        if isinstance(end, datetime.date):
            end = bisect.bisect_right(st_dtime, date2num(end))

        if end < 0:
            end = len(st_dtime) + 1 + end  # -1 =  len() -2 = len() - 1

        slen = len(st_dtime[start:end])
        d, m = divmod(slen, numfigs)
        pranges = list()
        for i in range(numfigs):
            a = d * i + start
            if i == (numfigs - 1):
                d += m  # add remainder to last stint
            b = a + d

            pranges.append([a, b, d])

        figs = []

        for numfig in range(numfigs):
            # prepare a figure
            fig = self.pinf.newfig(figid, numfig, self.mpyplot)
            figs.append(fig)

            self.pinf.pstart, self.pinf.pend, self.pinf.psize = pranges[numfig]
            self.pinf.xstart = self.pinf.pstart
            self.pinf.xend = self.pinf.pend

            self.pinf.clock = strategy
            self.pinf.xreal = self.pinf.clock.datetime.plot(
                self.pinf.pstart, self.pinf.psize)
            self.pinf.xlen = len(self.pinf.xreal)
            self.pinf.x = list(range(self.pinf.xlen))
            # self.pinf.pfillers = {None: []}
            # for key, val in pfillers.items():
            #     pfstart = bisect.bisect_left(val, self.pinf.pstart)
            #     pfend = bisect.bisect_right(val, self.pinf.pend)
            #     self.pinf.pfillers[key] = val[pfstart:pfend]

            # Do the plotting
            # Things that go always at the top (observers)
            self.pinf.xdata = self.pinf.x
            for ptop in self.dplotstop:
                self.plotind(None, ptop, subinds=self.dplotsover[ptop])

            # Create the rest on a per data basis
            dt0, dt1 = self.pinf.xreal[0], self.pinf.xreal[-1]
            for data in strategy.datas:
                if not data.plotinfo.plot:
                    continue

                self.pinf.xdata = self.pinf.x
                xd = data.datetime.plotrange(self.pinf.xstart, self.pinf.xend)
                if len(xd) < self.pinf.xlen:
                    self.pinf.xdata = xdata = []
                    xreal = self.pinf.xreal
                    dts = data.datetime.plot()
                    xtemp = list()
                    for dt in (x for x in dts if dt0 <= x <= dt1):
                        dtidx = bisect.bisect_left(xreal, dt)
                        xdata.append(dtidx)
                        xtemp.append(dt)

                    self.pinf.xstart = bisect.bisect_left(dts, xtemp[0])
                    self.pinf.xend = bisect.bisect_right(dts, xtemp[-1])

                for ind in self.dplotsup[data]:
                    self.plotind(
                        data,
                        ind,
                        subinds=self.dplotsover[ind],
                        upinds=self.dplotsup[ind],
                        downinds=self.dplotsdown[ind])

                self.plotdata(data, self.dplotsover[data])

                for ind in self.dplotsdown[data]:
                    self.plotind(
                        data,
                        ind,
                        subinds=self.dplotsover[ind],
                        upinds=self.dplotsup[ind],
                        downinds=self.dplotsdown[ind])

            cursor = MultiCursor(
                fig.canvas, list(self.pinf.daxis.values()),
                useblit=True,
                horizOn=True, vertOn=True,
                horizMulti=False, vertMulti=True,
                horizShared=True, vertShared=False,
                color='black', lw=1, ls=':')

            self.pinf.cursors.append(cursor)

            # Put the subplots as indicated by hspace
            fig.subplots_adjust(hspace=self.pinf.sch.plotdist,
                                top=0.98, left=0.05, bottom=0.05, right=0.95)

            laxis = list(self.pinf.daxis.values())

            # Find last axis which is not a twinx (date locator fails there)
            i = -1
            while True:
                lastax = laxis[i]
                if lastax not in self.pinf.vaxis:
                    break

                i -= 1

            self.setlocators(lastax)  # place the locators/fmts

            # Applying fig.autofmt_xdate if the data axis is the last one
            # breaks the presentation of the date labels. why?
            # Applying the manual rotation with setp cures the problem
            # but the labels from all axis but the last have to be hidden
            for ax in laxis:
                self.mpyplot.setp(ax.get_xticklabels(), visible=False)

            self.mpyplot.setp(lastax.get_xticklabels(), visible=True,
                              rotation=self.pinf.sch.tickrotation)

            # Things must be tight along the x axis (to fill both ends)
            axtight = 'x' if not self.pinf.sch.ytight else 'both'
            # self.mpyplot.xticks(pd.date_range(start,end),rotation=90)
            self.mpyplot.autoscale(enable=True, axis=axtight, tight=True)

        return figs

    def setlocators(self, ax):
        comp = getattr(self.pinf.clock, '_compression', 1)
        tframe = getattr(self.pinf.clock, '_timeframe', TimeFrame.Days)

        if self.pinf.sch.fmt_x_data is None:
            if tframe == TimeFrame.Years:
                fmtdata = '%Y'
            elif tframe == TimeFrame.Months:
                fmtdata = '%Y-%m'
            elif tframe == TimeFrame.Weeks:
                fmtdata = '%Y-%m-%d'
            elif tframe == TimeFrame.Days:
                fmtdata = '%Y-%m-%d'
            elif tframe == TimeFrame.Minutes:
                fmtdata = '%Y-%m-%d %H:%M'
            elif tframe == TimeFrame.Seconds:
                fmtdata = '%Y-%m-%d %H:%M:%S'
            elif tframe == TimeFrame.MicroSeconds:
                fmtdata = '%Y-%m-%d %H:%M:%S.%f'
            elif tframe == TimeFrame.Ticks:
                fmtdata = '%Y-%m-%d %H:%M:%S.%f'
        else:
            fmtdata = self.pinf.sch.fmt_x_data

        fordata = MyDateFormatter(self.pinf.xreal, fmt=fmtdata)
        for dax in self.pinf.daxis.values():
            dax.fmt_xdata = fordata

        # Major locator / formatter
        locmajor = loc.AutoDateLocator(self.pinf.xreal)
        ax.xaxis.set_major_locator(locmajor)
        if self.pinf.sch.fmt_x_ticks is None:
            autofmt = loc.AutoDateFormatter(self.pinf.xreal, locmajor)
        else:
            autofmt = MyDateFormatter(self.pinf.xreal,
                                      fmt=self.pinf.sch.fmt_x_ticks)
        ax.xaxis.set_major_formatter(autofmt)

    def calcrows(self, strategy):
        # Calculate the total number of rows
        rowsmajor = self.pinf.sch.rowsmajor
        rowsminor = self.pinf.sch.rowsminor
        nrows = 0

        datasnoplot = 0
        for data in strategy.datas:
            if not data.plotinfo.plot:
                # neither data nor indicators nor volume add rows
                datasnoplot += 1
                self.dplotsup.pop(data, None)
                self.dplotsdown.pop(data, None)
                self.dplotsover.pop(data, None)

            else:
                pmaster = data.plotinfo.plotmaster
                if pmaster is data:
                    pmaster = None
                if pmaster is not None:
                    # data doesn't add a row, but volume may
                    if self.pinf.sch.volume:
                        nrows += rowsminor
                else:
                    # data adds rows, volume may
                    nrows += rowsmajor
                    if self.pinf.sch.volume and not self.pinf.sch.voloverlay:
                        nrows += rowsminor

        if False:
            # Datas and volumes
            nrows += (len(strategy.datas) - datasnoplot) * rowsmajor
            if self.pinf.sch.volume and not self.pinf.sch.voloverlay:
                nrows += (len(strategy.datas) - datasnoplot) * rowsminor

        # top indicators/observers
        nrows += len(self.dplotstop) * rowsminor

        # indicators above datas
        nrows += sum(len(v) for v in self.dplotsup.values())
        nrows += sum(len(v) for v in self.dplotsdown.values())

        self.pinf.nrows = nrows

    def newaxis(self, obj, rowspan):
        ax = self.mpyplot.subplot2grid(
            (self.pinf.nrows, 1), (self.pinf.row, 0),
            rowspan=rowspan, sharex=self.pinf.sharex)

        # update the sharex information if not available
        if self.pinf.sharex is None:
            self.pinf.sharex = ax

        # update the row index with the taken rows
        self.pinf.row += rowspan

        # save the mapping indicator - axis and return
        self.pinf.daxis[obj] = ax

        # Activate grid in all axes if requested
        ax.yaxis.tick_right()
        ax.grid(self.pinf.sch.grid, which='both')

        return ax

    def plotind(self, iref, ind,
                subinds=None, upinds=None, downinds=None,
                masterax=None):

        sch = self.p.scheme

        # check subind
        subinds = subinds or []
        upinds = upinds or []
        downinds = downinds or []

        # plot subindicators on self with independent axis above
        for upind in upinds:
            self.plotind(iref, upind)

        # Get an axis for this plot
        ax = masterax or self.newaxis(ind, rowspan=self.pinf.sch.rowsminor)

        indlabel = ind.plotlabel()

        # Scan lines quickly to find out if some lines have to be skipped for
        # legend (because matplotlib reorders the legend)
        toskip = 0
        for lineidx in range(ind.size()):
            line = ind.lines[lineidx]
            linealias = ind.lines._getlinealias(lineidx)
            lineplotinfo = getattr(ind.plotlines, '_%d' % lineidx, None)
            if not lineplotinfo:
                lineplotinfo = getattr(ind.plotlines, linealias, None)
            if not lineplotinfo:
                lineplotinfo = AutoInfoClass()
            pltmethod = lineplotinfo._get('_method', 'plot')
            if pltmethod != 'plot':
                toskip += 1 - lineplotinfo._get('_plotskip', False)

        if toskip >= ind.size():
            toskip = 0

        for lineidx in range(ind.size()):
            line = ind.lines[lineidx]
            linealias = ind.lines._getlinealias(lineidx)

            lineplotinfo = getattr(ind.plotlines, '_%d' % lineidx, None)
            if not lineplotinfo:
                lineplotinfo = getattr(ind.plotlines, linealias, None)

            if not lineplotinfo:
                lineplotinfo = AutoInfoClass()

            if lineplotinfo._get('_plotskip', False):
                continue

            # Legend label only when plotting 1st line
            if masterax and not ind.plotinfo.plotlinelabels:
                label = indlabel * (not toskip) or '_nolegend'
            else:
                label = (indlabel + '\n') * (not toskip)
                label += lineplotinfo._get('_name', '') or linealias

            toskip -= 1  # one line less until legend can be added

            # plot data
            lplot = line.plotrange(self.pinf.xstart, self.pinf.xend)

            # Global and generic for indicator
            if self.pinf.sch.linevalues and ind.plotinfo.plotlinevalues:
                plotlinevalue = lineplotinfo._get('_plotvalue', True)
                if plotlinevalue and not math.isnan(lplot[-1]):
                    label += ' %.2f' % lplot[-1]

            plotkwargs = dict()
            linekwargs = lineplotinfo._getkwargs(skip_=True)

            if linekwargs.get('color', None) is None:
                if not lineplotinfo._get('_samecolor', False):
                    self.pinf.nextcolor(ax)
                plotkwargs['color'] = self.pinf.color(ax)

            plotkwargs.update(dict(aa=True, label=label))
            plotkwargs.update(**linekwargs)

            if ax in self.pinf.zorder:
                plotkwargs['zorder'] = self.pinf.zordernext(ax)

            pltmethod = getattr(ax, lineplotinfo._get('_method', 'plot'))

            xdata, lplotarray = self.pinf.xdata, lplot
            if lineplotinfo._get('_skipnan', False):
                # Get the full array and a mask to skipnan
                lplotarray = np.array(lplot)
                lplotmask = np.isfinite(lplotarray)

                # Get both the axis and the data masked
                lplotarray = lplotarray[lplotmask]
                xdata = np.array(xdata)[lplotmask]

            plottedline = pltmethod(xdata, lplotarray, **plotkwargs)
            try:
                plottedline = plottedline[0]
            except:
                # Possibly a container of artists (when plotting bars)
                pass

            self.pinf.zorder[ax] = plottedline.get_zorder()

            vtags = lineplotinfo._get('plotvaluetags', True)
            if self.pinf.sch.valuetags and vtags:
                linetag = lineplotinfo._get('_plotvaluetag', True)
                if linetag and not math.isnan(lplot[-1]):
                    # line has valid values, plot a tag for the last value
                    self.drawtag(ax, len(self.pinf.xreal), lplot[-1],
                                 facecolor='white',
                                 edgecolor=self.pinf.color(ax))

            farts = (('_gt', operator.gt), ('_lt', operator.lt), ('', None),)
            for fcmp, fop in farts:
                fattr = '_fill' + fcmp
                fref, fcol = lineplotinfo._get(fattr, (None, None))
                if fref is not None:
                    y1 = np.array(lplot)
                    if isinstance(fref, integer_types):
                        y2 = np.full_like(y1, fref)
                    else:  # string, naming a line, nothing else is supported
                        l2 = getattr(ind, fref)
                        prl2 = l2.plotrange(self.pinf.xstart, self.pinf.xend)
                        y2 = np.array(prl2)
                    kwargs = dict()
                    if fop is not None:
                        kwargs['where'] = fop(y1, y2)

                    falpha = self.pinf.sch.fillalpha
                    if isinstance(fcol, (list, tuple)):
                        fcol, falpha = fcol

                    ax.fill_between(self.pinf.xdata, y1, y2,
                                    facecolor=fcol,
                                    alpha=falpha,
                                    interpolate=True,
                                    **kwargs)

        # plot subindicators that were created on self
        for subind in subinds:
            self.plotind(iref, subind, subinds=self.dplotsover[subind],
                         masterax=ax)

        if not masterax:
            # adjust margin if requested ... general of particular
            ymargin = ind.plotinfo._get('plotymargin', 0.0)
            ymargin = max(ymargin, self.pinf.sch.yadjust)
            if ymargin:
                ax.margins(y=ymargin)

            # Set specific or generic ticks
            yticks = ind.plotinfo._get('plotyticks', [])
            if not yticks:
                yticks = ind.plotinfo._get('plotyhlines', [])

            if yticks:
                ax.set_yticks(yticks)
            else:
                locator = mticker.MaxNLocator(nbins=4, prune='both')
                ax.yaxis.set_major_locator(locator)

            # Set specific hlines if asked to
            hlines = ind.plotinfo._get('plothlines', [])
            if not hlines:
                hlines = ind.plotinfo._get('plotyhlines', [])
            for hline in hlines:
                ax.axhline(hline, color=self.pinf.sch.hlinescolor,
                           ls=self.pinf.sch.hlinesstyle,
                           lw=self.pinf.sch.hlineswidth)

            if self.pinf.sch.legendind and \
                    ind.plotinfo._get('plotlegend', True):

                handles, labels = ax.get_legend_handles_labels()
                # Ensure that we have something to show
                if labels:
                    # location can come from the user
                    loc = ind.plotinfo.legendloc or self.pinf.sch.legendindloc

                    # Legend done here to ensure it includes all plots
                    legend = ax.legend(loc=loc,
                                       numpoints=1, frameon=False,
                                       shadow=False, fancybox=False,
                                       prop=self.pinf.prop)

                    # legend.set_title(indlabel, prop=self.pinf.prop)
                    # hack: if title is set. legend has a Vbox for the labels
                    # which has a default "center" set
                    legend._legend_box.align = 'left'

        # plot subindicators on self with independent axis below
        for downind in downinds:
            self.plotind(iref, downind)

    def plotvolume(self, data, opens, highs, lows, closes, volumes, label):
        pmaster = data.plotinfo.plotmaster
        if pmaster is data:
            pmaster = None
        voloverlay = (self.pinf.sch.voloverlay and pmaster is None)

        # if sefl.pinf.sch.voloverlay:
        if voloverlay:
            rowspan = self.pinf.sch.rowsmajor
        else:
            rowspan = self.pinf.sch.rowsminor

        ax = self.newaxis(data.volume, rowspan=rowspan)

        # if self.pinf.sch.voloverlay:
        if voloverlay:
            volalpha = self.pinf.sch.voltrans
        else:
            volalpha = 1.0

        maxvol = volylim = max(volumes)
        if maxvol:

            # Plot the volume (no matter if as overlay or standalone)
            vollabel = label
            volplot, = plot_volume(ax, self.pinf.xdata, opens, closes, volumes,
                                   colorup=self.pinf.sch.volup,
                                   colordown=self.pinf.sch.voldown,
                                   alpha=volalpha, label=vollabel)

            nbins = 6
            prune = 'both'
            # if self.pinf.sch.voloverlay:
            if voloverlay:
                # store for a potential plot over it
                nbins = int(nbins / self.pinf.sch.volscaling)
                prune = None

                volylim /= self.pinf.sch.volscaling
                ax.set_ylim(0, volylim, auto=True)
            else:
                # plot a legend
                handles, labels = ax.get_legend_handles_labels()
                if handles:
                    # location can come from the user
                    loc = data.plotinfo.legendloc or self.pinf.sch.legendindloc

                    # Legend done here to ensure it includes all plots
                    legend = ax.legend(loc=loc,
                                       numpoints=1, frameon=False,
                                       shadow=False, fancybox=False,
                                       prop=self.pinf.prop)

            locator = mticker.MaxNLocator(nbins=nbins, prune=prune)
            ax.yaxis.set_major_locator(locator)
            ax.yaxis.set_major_formatter(MyVolFormatter(maxvol))

        if not maxvol:
            ax.set_yticks([])
            return None

        return volplot

    def plotdata(self, data, indicators):
        for ind in indicators:
            upinds = self.dplotsup[ind]
            for upind in upinds:
                self.plotind(data, upind,
                             subinds=self.dplotsover[upind],
                             upinds=self.dplotsup[upind],
                             downinds=self.dplotsdown[upind])

        opens = data.open.plotrange(self.pinf.xstart, self.pinf.xend)
        highs = data.high.plotrange(self.pinf.xstart, self.pinf.xend)
        lows = data.low.plotrange(self.pinf.xstart, self.pinf.xend)
        closes = data.close.plotrange(self.pinf.xstart, self.pinf.xend)
        volumes = data.volume.plotrange(self.pinf.xstart, self.pinf.xend)

        vollabel = 'Volume'
        pmaster = data.plotinfo.plotmaster
        if pmaster is data:
            pmaster = None

        datalabel = ''
        if hasattr(data, '_name') and data._name:
            datalabel += data._name

        voloverlay = (self.pinf.sch.voloverlay and pmaster is None)

        if not voloverlay:
            vollabel += ' ({})'.format(datalabel)

        # if self.pinf.sch.volume and self.pinf.sch.voloverlay:
        axdatamaster = None
        if self.pinf.sch.volume and voloverlay:
            volplot = self.plotvolume(
                data, opens, highs, lows, closes, volumes, vollabel)
            axvol = self.pinf.daxis[data.volume]
            ax = axvol.twinx()
            self.pinf.daxis[data] = ax
            self.pinf.vaxis.append(ax)
        else:
            if pmaster is None:
                ax = self.newaxis(data, rowspan=self.pinf.sch.rowsmajor)
            elif getattr(data.plotinfo, 'sameaxis', False):
                axdatamaster = self.pinf.daxis[pmaster]
                ax = axdatamaster
            else:
                axdatamaster = self.pinf.daxis[pmaster]
                ax = axdatamaster.twinx()
                self.pinf.vaxis.append(ax)

        if hasattr(data, '_compression') and \
                hasattr(data, '_timeframe'):
            tfname = TimeFrame.getname(data._timeframe, data._compression)
            datalabel += ' (%d %s)' % (data._compression, tfname)

        plinevalues = getattr(data.plotinfo, 'plotlinevalues', True)
        if self.pinf.sch.style.startswith('line'):
            if self.pinf.sch.linevalues and plinevalues:
                datalabel += ' C:%.2f' % closes[-1]

            if axdatamaster is None:
                color = self.pinf.sch.loc
            else:
                self.pinf.nextcolor(axdatamaster)
                color = self.pinf.color(axdatamaster)

            plotted = plot_lineonclose(
                ax, self.pinf.xdata, closes,
                color=color, label=datalabel)
        else:
            if self.pinf.sch.linevalues and plinevalues:
                datalabel += ' O:%.2f H:%.2f L:%.2f C:%.2f' % \
                             (opens[-1], highs[-1], lows[-1], closes[-1])
            if self.pinf.sch.style.startswith('candle'):
                plotted = plot_candlestick(
                    ax, self.pinf.xdata, opens, highs, lows, closes,
                    colorup=self.pinf.sch.barup,
                    colordown=self.pinf.sch.bardown,
                    label=datalabel,
                    alpha=self.pinf.sch.baralpha,
                    fillup=self.pinf.sch.barupfill,
                    filldown=self.pinf.sch.bardownfill)

            elif self.pinf.sch.style.startswith('bar') or True:
                # final default option -- should be "else"
                plotted = plot_ohlc(
                    ax, self.pinf.xdata, opens, highs, lows, closes,
                    colorup=self.pinf.sch.barup,
                    colordown=self.pinf.sch.bardown,
                    label=datalabel)

        self.pinf.zorder[ax] = plotted[0].get_zorder()

        # Code to place a label at the right hand side with the last value
        vtags = data.plotinfo._get('plotvaluetags', True)
        if self.pinf.sch.valuetags and vtags:
            self.drawtag(ax, len(self.pinf.xreal), closes[-1],
                         facecolor='white', edgecolor=self.pinf.sch.loc)

        ax.yaxis.set_major_locator(mticker.MaxNLocator(prune='both'))
        # make sure "over" indicators do not change our scale
        if data.plotinfo._get('plotylimited', True):
            if axdatamaster is None:
                ax.set_ylim(ax.get_ylim())

        if self.pinf.sch.volume:
            # if not self.pinf.sch.voloverlay:
            if not voloverlay:
                self.plotvolume(
                    data, opens, highs, lows, closes, volumes, vollabel)
            else:
                # Prepare overlay scaling/pushup or manage own axis
                if self.pinf.sch.volpushup:
                    # push up overlaid axis by lowering the bottom limit
                    axbot, axtop = ax.get_ylim()
                    axbot *= (1.0 - self.pinf.sch.volpushup)
                    ax.set_ylim(axbot, axtop)

        for ind in indicators:
            self.plotind(data, ind, subinds=self.dplotsover[ind], masterax=ax)

        handles, labels = ax.get_legend_handles_labels()
        a = axdatamaster or ax
        if handles:
            # put data and volume legend entries in the 1st positions
            # because they are "collections" they are considered after Line2D
            # for the legend entries, which is not our desire
            # if self.pinf.sch.volume and self.pinf.sch.voloverlay:

            ai = self.pinf.legpos[a]
            if self.pinf.sch.volume and voloverlay:
                if volplot:
                    # even if volume plot was requested, there may be no volume
                    labels.insert(ai, vollabel)
                    handles.insert(ai, volplot)

            didx = labels.index(datalabel)
            labels.insert(ai, labels.pop(didx))
            handles.insert(ai, handles.pop(didx))

            if axdatamaster is None:
                self.pinf.handles[ax] = handles
                self.pinf.labels[ax] = labels
            else:
                self.pinf.handles[axdatamaster] = handles
                self.pinf.labels[axdatamaster] = labels
                # self.pinf.handles[axdatamaster].extend(handles)
                # self.pinf.labels[axdatamaster].extend(labels)

            h = self.pinf.handles[a]
            l = self.pinf.labels[a]

            axlegend = a
            loc = data.plotinfo.legendloc or self.pinf.sch.legenddataloc
            legend = axlegend.legend(h, l,
                                     loc=loc,
                                     frameon=False, shadow=False,
                                     fancybox=False, prop=self.pinf.prop,
                                     numpoints=1, ncol=1)

            # hack: if title is set. legend has a Vbox for the labels
            # which has a default "center" set
            legend._legend_box.align = 'left'

        for ind in indicators:
            downinds = self.dplotsdown[ind]
            for downind in downinds:
                self.plotind(data, downind,
                             subinds=self.dplotsover[downind],
                             upinds=self.dplotsup[downind],
                             downinds=self.dplotsdown[downind])

        self.pinf.legpos[a] = len(self.pinf.handles[a])

        if data.plotinfo._get('plotlog', False):
            a = axdatamaster or ax
            a.set_yscale('log')

    def show(self):
        self.mpyplot.show()

    def savefig(self, fig, filename, width=16, height=9, dpi=300, tight=True):
        fig.set_size_inches(width, height)
        bbox_inches = 'tight' * tight or None
        fig.savefig(filename, dpi=dpi, bbox_inches=bbox_inches)

    def sortdataindicators(self, strategy):
        # These lists/dictionaries hold the subplots that go above each data
        self.dplotstop = list()
        self.dplotsup = collections.defaultdict(list)
        self.dplotsdown = collections.defaultdict(list)
        self.dplotsover = collections.defaultdict(list)

        # Sort observers in the different lists/dictionaries
        for x in strategy.getobservers():
            if not x.plotinfo.plot or x.plotinfo.plotskip:
                continue

            if x.plotinfo.subplot:
                self.dplotstop.append(x)
            else:
                key = getattr(x._clock, 'owner', x._clock)
                self.dplotsover[key].append(x)

        # Sort indicators in the different lists/dictionaries
        for x in strategy.getindicators():
            if not hasattr(x, 'plotinfo'):
                # no plotting support - so far LineSingle derived classes
                continue

            if not x.plotinfo.plot or x.plotinfo.plotskip:
                continue

            x._plotinit()  # will be plotted ... call its init function

            # support LineSeriesStub which has "owner" to point to the data
            key = getattr(x._clock, 'owner', x._clock)
            if key is strategy:  # a LinesCoupler
                key = strategy.data

            if getattr(x.plotinfo, 'plotforce', False):
                if key not in strategy.datas:
                    datas = strategy.datas
                    while True:
                        if key not in strategy.datas:
                            key = key._clock
                        else:
                            break

            xpmaster = x.plotinfo.plotmaster
            if xpmaster is x:
                xpmaster = None
            if xpmaster is not None:
                key = xpmaster

            if x.plotinfo.subplot and xpmaster is None:
                if x.plotinfo.plotabove:
                    self.dplotsup[key].append(x)
                else:
                    self.dplotsdown[key].append(x)
            else:
                self.dplotsover[key].append(x)


def plot_results(results, file_name):
    '''write by myself to plot the result,and I will update this function'''
    # 总的杠杆
    df1 = pd.DataFrame([results[0].analyzers._GrossLeverage.get_analysis()]).T
    df1.columns = ['GrossLeverage']
    # 滚动的对数收益率
    df2 = pd.DataFrame([results[0].analyzers._LogReturnsRolling.get_analysis()]).T
    df2.columns = ['log_return']

    # year_rate
    df3 = pd.DataFrame([results[0].analyzers._AnnualReturn.get_analysis()]).T
    df3.columns = ['year_rate']

    #
    df4 = pd.DataFrame(results[0].analyzers._PositionsValue.get_analysis()).T
    df4['total_position_value'] = df4.sum(axis=1)

    GrossLeverage = go.Scatter(
        x=df1.index,
        y=df1.GrossLeverage,
        name="gross_leverage"
    )
    log_return = go.Scatter(
        x=df2.index,
        y=df2.log_return,
        xaxis='x2',
        yaxis='y2',
        name="log_return"
    )
    cumsum_return = go.Scatter(
        x=df2.index,
        y=df2.log_return.cumsum(),
        xaxis='x2',
        yaxis='y2',
        name="cumsum_return"
    )

    year_rate = go.Bar(
        x=df3.index,
        y=df3.year_rate,
        xaxis='x3',
        yaxis='y3',
        name="year_rate"
    )
    total_position_value = go.Scatter(
        x=df4.index,
        y=df4.total_position_value,
        xaxis='x4',
        yaxis='y4',
        name="total_position_value"
    )
    data = [GrossLeverage, log_return, cumsum_return, year_rate, total_position_value]
    layout = go.Layout(
        xaxis=dict(
            domain=[0, 0.45]
        ),
        yaxis=dict(
            domain=[0, 0.45]
        ),
        xaxis2=dict(
            domain=[0.55, 1]
        ),
        xaxis3=dict(
            domain=[0, 0.45],
            anchor='y3'
        ),
        xaxis4=dict(
            domain=[0.55, 1],
            anchor='y4'
        ),
        yaxis2=dict(
            domain=[0, 0.45],
            anchor='x2'
        ),
        yaxis3=dict(
            domain=[0.55, 1]
        ),
        yaxis4=dict(
            domain=[0.55, 1],
            anchor='x4'
        )
    )
    fig = go.Figure(data=data, layout=layout)
    py.offline.plot(fig, filename=file_name, auto_open=False)


Plot = Plot_OldSync


def create_table(df, max_rows=18):
    """基于dataframe，设置表格格式"""

    table = html.Table(
        # Header
        [
            html.Tr(
                [
                    html.Th(col) for col in df.columns
                ]
            )
        ] +
        # Body
        [
            html.Tr(
                [
                    html.Td(
                        df.iloc[i][col]
                    ) for col in df.columns
                ]
            ) for i in range(min(len(df), max_rows))
        ]
    )
    return table


def get_rate_sharpe_drawdown(data):
    # 计算夏普率，复利年化收益率，最大回撤率
    # 对于小于日线周期的，抽取每日最后的value作为一个交易日的最终的value，
    # 对于期货的分钟数据而言，并不是按照15：00收盘算，可能会影响一点点夏普率等指标的计算，但是影响不大。
    data.index = pd.to_datetime(data.index)
    data['date'] = [str(i)[:10] for i in data.index]
    data1 = data.drop_duplicates("date", keep='last')
    data1.index = pd.to_datetime(data1['date'])
    # print(data1)
    if len(data1) == 0:
        return np.NaN, np.NaN, np.NaN
    try:
        # 假设一年的交易日为252天
        data1['rate1'] = np.log(data1['total_value']) - np.log(data1['total_value'].shift(1))
        # data['rate2']=data['total_value'].pct_change()
        data1 = data1.dropna()
        sharpe_ratio = data1['rate1'].mean() * (252) ** 0.5 / (data1['rate1'].std())
        # 年化收益率为：
        value_list = list(data['total_value'])
        begin_value = value_list[0]
        end_value = value_list[-1]
        begin_date = data.index[0]
        end_date = data.index[-1]
        days = (end_date - begin_date).days
        # print(begin_date,begin_value,end_date,end_value,1/(days/365))
        # 如果计算的实际收益率为负数的话，就默认为最大为0,收益率不能为负数
        total_rate = max((end_value - begin_value) / begin_value, -0.9999)
        average_rate = (1 + total_rate) ** (1 / (days / 365)) - 1
        # 计算最大回撤
        data['rate1'] = np.log(data['total_value']) - np.log(data['total_value'].shift(1))
        df = data['rate1'].cumsum()
        df = df.dropna()
        # index_j = np.argmax(np.maximum.accumulate(df) - df)  # 结束位置
        index_j = np.argmax(np.array(np.maximum.accumulate(df) - df))
        # print("最大回撤结束时间",index_j)
        # index_i = np.argmax(df[:index_j])  # 开始位置
        index_i = np.argmax(np.array(df[:index_j]))  # 开始位置
        # print("最大回撤开始时间",index_i)
        max_drawdown = (np.e ** df[index_j] - np.e ** df[index_i]) / np.e ** df[index_i]
        '''
        begin_max_drawdown_value = data['total_value'][index_i]
        end_max_drawdown_value = data['total_value'][index_j]
        print("begin_max_drawdown_value",begin_max_drawdown_value)
        print("end_max_drawdown_value",end_max_drawdown_value)
        maxdrawdown_rate = (end_max_drawdown_value -begin_max_drawdown_value)/begin_max_drawdown_value  # 最大回撤比率
        maxdrawdown_value = data['total_value'][index_j] -data['total_value'][index_i] #最大回撤值
        print("最大回撤值为",maxdrawdown_value)
        print("最大回撤比率为",maxdrawdown_rate)
        # 绘制图像
        plt.plot(df[1:len(df)])
        plt.plot([index_i], [df[index_i]], 'o', color="r", markersize=10)
        plt.plot([index_j], [df[index_j]], 'o', color="blue", markersize=10)
        plt.show()
        '''
        return sharpe_ratio, average_rate, max_drawdown
    except:
        return np.NaN, np.NaN, np.NaN


def get_year_return(data):
    '''计算每年的年化收益率'''
    data.index = pd.to_datetime(data.index)
    data['year'] = [i.year for i in data.index]
    last_data = data.iloc[-1:, ::]
    data = data.drop_duplicates('year')
    # data = data.append(last_data)
    data = pd.concat([data, last_data], axis=0)
    data['next_year_value'] = data['total_value'].shift(-1)
    data['return'] = data['next_year_value'] / data['total_value'] - 1
    data = data.dropna()
    data['datetime'] = [str(i) + "-6-30" for i in data.year]
    data.index = pd.to_datetime(data.datetime)
    data = data[['return', 'datetime']]
    return data


def run_cerebro_and_plot(cerebro, strategy, params, score=90, port=8050, optimize=True, auto_open=True, result_path=''):
    strategy_name = strategy.__name__
    author = strategy.author
    params_str = ''
    for key in params:
        if key != "symbol_list" and key != "datas":
            params_str = params_str + '__' + key + '__' + str(params[key])
    file_name = strategy_name + params_str + '.csv'
    if result_path != "":
        file_list = os.listdir(result_path)
    else:
        file_list = os.listdir(os.getcwd())
    if file_name in file_list:
        print("backtest {} consume time  :0 because of it has run".format(params_str))
    # print("file name is {}".format(file_name))
    # print("file_list is {}".format(file_list))
    if file_name not in file_list:
        print("begin to run this params:{},now_time is {}".format(params_str,
                                                                  time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
        cerebro.addstrategy(strategy, **params)
        begin_time = time.time()
        if optimize:
            cerebro.addanalyzer(bt.analyzers.TotalValue, _name='_TotalValue')
            results = cerebro.run()
            # plot_results(results,"/home/yun/index_000300_reverse_strategy_hold_day_90.html")
            end_time = time.time()
            print("backtest {} consume time  :{},结束时间为:{}".format(params_str, end_time - begin_time,
                                                                  time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
            # 获取关键性的账户价值，并计算三大指标
            df0 = pd.DataFrame([results[0].analyzers._TotalValue.get_analysis()]).T
            df0.columns = ['total_value']
            df0['datetime'] = df0.index
            df0 = df0.sort_values("datetime")
            del df0['datetime']
            df0.to_csv(result_path + strategy_name + params_str + "___value.csv")
            # 根据每日净值，计算每年的收益
            df_return = get_year_return(copy.deepcopy(df0))
            # 计算夏普率、平均收益、最大回撤
            sharpe_ratio, average_rate, max_drawdown_rate = get_rate_sharpe_drawdown(copy.deepcopy(df0))
            # 分析交易绩效
            performance_dict = OrderedDict()
            # 绩效衡量指标
            performance_dict['sharpe_ratio'] = sharpe_ratio
            performance_dict['average_rate'] = average_rate
            performance_dict['max_drawdown_rate'] = max_drawdown_rate
            performance_dict['calmar_ratio'] = np.NaN
            performance_dict['average_drawdown_len'] = np.NaN
            performance_dict['average_drawdown_rate'] = np.NaN
            performance_dict['average_drawdown_money'] = np.NaN
            performance_dict['max_drawdown_len'] = np.NaN
            performance_dict['max_drawdown_money'] = np.NaN
            performance_dict['stddev_rate'] = np.NaN
            performance_dict['positive_year'] = np.NaN
            performance_dict['negative_year'] = np.NaN
            performance_dict['nochange_year'] = np.NaN
            performance_dict['best_year'] = np.NaN
            performance_dict['worst_year'] = np.NaN
            performance_dict['sqn_ratio'] = np.NaN
            performance_dict['vwr_ratio'] = np.NaN
            performance_dict['omega'] = np.NaN
            trade_dict_1 = OrderedDict()
            trade_dict_2 = OrderedDict()
            trade_dict_1['total_trade_num'] = np.NaN
            trade_dict_1['total_trade_opened'] = np.NaN
            trade_dict_1['total_trade_closed'] = np.NaN
            trade_dict_1['total_trade_len'] = np.NaN
            trade_dict_1['long_trade_len'] = np.NaN
            trade_dict_1['short_trade_len'] = np.NaN
            trade_dict_1['longest_win_num'] = np.NaN
            trade_dict_1['longest_lost_num'] = np.NaN
            trade_dict_1['net_total_pnl'] = np.NaN
            trade_dict_1['net_average_pnl'] = np.NaN
            trade_dict_1['win_num'] = np.NaN
            trade_dict_1['win_total_pnl'] = np.NaN
            trade_dict_1['win_average_pnl'] = np.NaN
            trade_dict_1['win_max_pnl'] = np.NaN
            trade_dict_1['lost_num'] = np.NaN
            trade_dict_1['lost_total_pnl'] = np.NaN
            trade_dict_1['lost_average_pnl'] = np.NaN
            trade_dict_1['lost_max_pnl'] = np.NaN

            trade_dict_2['long_num'] = np.NaN
            trade_dict_2['long_win_num'] = np.NaN
            trade_dict_2['long_lost_num'] = np.NaN
            trade_dict_2['long_total_pnl'] = np.NaN
            trade_dict_2['long_average_pnl'] = np.NaN
            trade_dict_2['long_win_total_pnl'] = np.NaN
            trade_dict_2['long_win_max_pnl'] = np.NaN
            trade_dict_2['long_lost_total_pnl'] = np.NaN
            trade_dict_2['long_lost_max_pnl'] = np.NaN
            trade_dict_2['short_num'] = np.NaN
            trade_dict_2['short_win_num'] = np.NaN
            trade_dict_2['short_lost_num'] = np.NaN
            trade_dict_2['short_total_pnl'] = np.NaN
            trade_dict_2['short_average_pnl'] = np.NaN
            trade_dict_2['short_win_total_pnl'] = np.NaN
            trade_dict_2['short_win_max_pnl'] = np.NaN
            trade_dict_2['short_lost_total_pnl'] = np.NaN
            trade_dict_2['short_lost_max_pnl'] = np.NaN

            assert len(performance_dict) == len(trade_dict_2) == len(trade_dict_1)
            df00 = pd.DataFrame(index=range(18))
            df01 = pd.DataFrame([performance_dict]).T
            df01.columns = ['绩效指标值']
            df02 = pd.DataFrame([trade_dict_1]).T
            df02.columns = ['普通交易指标值']
            df03 = pd.DataFrame([trade_dict_2]).T
            df03.columns = ['多空交易指标值']
            try:
                df00['绩效指标'] = df01.index
                df00['绩效指标值'] = [round(float(i), 4) for i in list(df01['绩效指标值'])]
                df00['普通交易指标'] = df02.index
                df00['普通交易指标值'] = [round(float(i), 4) for i in list(df02['普通交易指标值'])]
                df00['多空交易指标'] = df03.index
                df00['多空交易指标值'] = [round(float(i), 4) for i in list(df03['多空交易指标值'])]
            except:
                df00['绩效指标'] = df01.index
                df00['绩效指标值'] = df01['绩效指标值']
                df00['普通交易指标'] = df02.index
                df00['普通交易指标值'] = df02['普通交易指标值']
                df00['多空交易指标'] = df03.index
                df00['多空交易指标值'] = df03['多空交易指标值']
                print('绩效指标值', df01['绩效指标值'])
                print(performance_dict)
                print(strategy.__name__ + params_str)
                print(sharpe_ratio, average_rate, max_drawdown_rate)

        if not optimize:
            # 保存需要的交易指标
            # cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')
            # cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='_AnnualReturn') # 计算年化收益有问题，剔除
            cerebro.addanalyzer(bt.analyzers.Calmar, _name='_Calmar')
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name='_DrawDown')
            # cerebro.addanalyzer(bt.analyzers.TimeDrawDown, _name='_TimeDrawDown')
            cerebro.addanalyzer(bt.analyzers.GrossLeverage, _name='_GrossLeverage')
            cerebro.addanalyzer(bt.analyzers.PositionsValue, _name='_PositionsValue')
            # cerebro.addanalyzer(bt.analyzers.LogReturnsRolling, _name='_LogReturnsRolling')
            cerebro.addanalyzer(bt.analyzers.PeriodStats, _name='_PeriodStats')
            cerebro.addanalyzer(bt.analyzers.Returns, _name='_Returns')
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='_SharpeRatio')
            # cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name='_SharpeRatio_A')
            cerebro.addanalyzer(bt.analyzers.SQN, _name='_SQN')
            cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='_TimeReturn')
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='_TradeAnalyzer')
            cerebro.addanalyzer(bt.analyzers.Transactions, _name='_Transactions')
            cerebro.addanalyzer(bt.analyzers.VWR, _name='_VWR')
            cerebro.addanalyzer(bt.analyzers.TotalValue, _name='_TotalValue')
            cerebro.addanalyzer(bt.analyzers.PyFolio)
            results = cerebro.run()
            # plot_results(results,"/home/yun/index_000300_reverse_strategy_hold_day_90.html")
            end_time = time.time()
            print("backtest {} consume time  :{},结束时间为:{}".format(params_str, end_time - begin_time,
                                                                  time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
            # 分析交易绩效
            performance_dict = OrderedDict()
            drawdown_info = results[0].analyzers._DrawDown.get_analysis()
            # 计算阶段性指标
            PeriodStats_info = results[0].analyzers._PeriodStats.get_analysis()
            # 计算sqn指标
            SQN_info = results[0].analyzers._SQN.get_analysis()
            sqn_ratio = SQN_info.get('sqn', np.NaN)
            # 计算vwr指标
            VWR_info = results[0].analyzers._VWR.get_analysis()
            vwr_ratio = VWR_info.get('vwr', np.NaN)
            # 计算calmar指标
            # calmar_ratio_list = list(results[0].analyzers._Calmar.get_analysis().values())
            # calmar_ratio = calmar_ratio_list[-1] if len(calmar_ratio_list) > 0 else np.NaN
            calmar_ratio = np.NaN
            # 计算夏普率
            sharpe_info = results[0].analyzers._SharpeRatio.get_analysis()
            sharpe_ratio = sharpe_info.get('sharperatio', np.NaN)
            # 获得平均回撤指标
            average_drawdown_len = drawdown_info.get('len', np.NaN)
            average_drawdown_rate = drawdown_info.get('drawdown', np.NaN)
            average_drawdown_money = drawdown_info.get('moneydown', np.NaN)
            # 获得最大回撤指标
            max_drawdown_info = drawdown_info.get('max', {})
            max_drawdown_len = max_drawdown_info.get('len', np.NaN)
            max_drawdown_rate = max_drawdown_info.get('drawdown', np.NaN)
            max_drawdown_money = max_drawdown_info.get('moneydown', np.NaN)

            average_rate = PeriodStats_info.get('average', np.NaN)
            stddev_rate = PeriodStats_info.get('stddev', np.NaN)
            positive_year = PeriodStats_info.get('positive', np.NaN)
            negative_year = PeriodStats_info.get('negative', np.NaN)
            nochange_year = PeriodStats_info.get('nochange', np.NaN)
            best_year = PeriodStats_info.get('best', np.NaN)
            worst_year = PeriodStats_info.get('worst', np.NaN)

            # 获取关键性的账户价值，并计算三大指标
            df0 = pd.DataFrame([results[0].analyzers._TotalValue.get_analysis()]).T
            df0.columns = ['total_value']
            df0['datetime'] = df0.index
            df0 = df0.sort_values("datetime")
            del df0['datetime']
            df0.to_csv(result_path + strategy_name + params_str + "___value.csv")
            # 根据每日净值，计算每年的收益
            df_return = get_year_return(copy.deepcopy(df0))
            # 计算夏普率、平均收益、最大回撤
            sharpe_ratio, average_rate, max_drawdown_rate = get_rate_sharpe_drawdown(copy.deepcopy(df0))

            # 绩效衡量指标
            performance_dict['sharpe_ratio'] = sharpe_ratio
            performance_dict['average_rate'] = average_rate
            performance_dict['max_drawdown_rate'] = max_drawdown_rate
            performance_dict['calmar_ratio'] = calmar_ratio
            performance_dict['average_drawdown_len'] = average_drawdown_len
            performance_dict['average_drawdown_rate'] = average_drawdown_rate
            performance_dict['average_drawdown_money'] = average_drawdown_money
            performance_dict['max_drawdown_len'] = max_drawdown_len
            performance_dict['max_drawdown_money'] = max_drawdown_money
            performance_dict['stddev_rate'] = stddev_rate
            performance_dict['positive_year'] = positive_year
            performance_dict['negative_year'] = negative_year
            performance_dict['nochange_year'] = nochange_year
            performance_dict['best_year'] = best_year
            performance_dict['worst_year'] = worst_year
            performance_dict['sqn_ratio'] = sqn_ratio
            performance_dict['vwr_ratio'] = vwr_ratio
            performance_dict['omega'] = np.NaN

            trade_dict_1 = OrderedDict()
            trade_dict_2 = OrderedDict()

            try:
                trade_info = results[0].analyzers._TradeAnalyzer.get_analysis()
                total_trade_num = trade_info['total']['total']
                total_trade_opened = trade_info['total']['open']
                total_trade_closed = trade_info['total']['closed']
                total_trade_len = trade_info['len']['total']
                long_trade_len = trade_info['len']['long']['total']
                short_trade_len = trade_info['len']['short']['total']
            except:
                total_trade_num = np.NaN
                total_trade_opened = np.NaN
                total_trade_closed = np.NaN
                total_trade_len = np.NaN
                long_trade_len = np.NaN
                short_trade_len = np.NaN

            try:
                longest_win_num = trade_info['streak']['won']['longest']
                longest_lost_num = trade_info['streak']['lost']['longest']
                net_total_pnl = trade_info['pnl']['net']['total']
                net_average_pnl = trade_info['pnl']['net']['average']
                win_num = trade_info['won']['total']
                win_total_pnl = trade_info['won']['pnl']['total']
                win_average_pnl = trade_info['won']['pnl']['average']
                win_max_pnl = trade_info['won']['pnl']['max']
                lost_num = trade_info['lost']['total']
                lost_total_pnl = trade_info['lost']['pnl']['total']
                lost_average_pnl = trade_info['lost']['pnl']['average']
                lost_max_pnl = trade_info['lost']['pnl']['max']
            except:
                longest_win_num = np.NaN
                longest_lost_num = np.NaN
                net_total_pnl = np.NaN
                net_average_pnl = np.NaN
                win_num = np.NaN
                win_total_pnl = np.NaN
                win_average_pnl = np.NaN
                win_max_pnl = np.NaN
                lost_num = np.NaN
                lost_total_pnl = np.NaN
                lost_average_pnl = np.NaN
                lost_max_pnl = np.NaN

            trade_dict_1['total_trade_num'] = total_trade_num
            trade_dict_1['total_trade_opened'] = total_trade_opened
            trade_dict_1['total_trade_closed'] = total_trade_closed
            trade_dict_1['total_trade_len'] = total_trade_len
            trade_dict_1['long_trade_len'] = long_trade_len
            trade_dict_1['short_trade_len'] = short_trade_len
            trade_dict_1['longest_win_num'] = longest_win_num
            trade_dict_1['longest_lost_num'] = longest_lost_num
            trade_dict_1['net_total_pnl'] = net_total_pnl
            trade_dict_1['net_average_pnl'] = net_average_pnl
            trade_dict_1['win_num'] = win_num
            trade_dict_1['win_total_pnl'] = win_total_pnl
            trade_dict_1['win_average_pnl'] = win_average_pnl
            trade_dict_1['win_max_pnl'] = win_max_pnl
            trade_dict_1['lost_num'] = lost_num
            trade_dict_1['lost_total_pnl'] = lost_total_pnl
            trade_dict_1['lost_average_pnl'] = lost_average_pnl
            trade_dict_1['lost_max_pnl'] = lost_max_pnl

            try:
                long_num = trade_info['long']['total']
                long_win_num = trade_info['long']['won']
                long_lost_num = trade_info['long']['lost']
                long_total_pnl = trade_info['long']['pnl']['total']
                long_average_pnl = trade_info['long']['pnl']['average']
                long_win_total_pnl = trade_info['long']['pnl']['won']['total']
                long_win_max_pnl = trade_info['long']['pnl']['won']['max']
                long_lost_total_pnl = trade_info['long']['pnl']['lost']['total']
                long_lost_max_pnl = trade_info['long']['pnl']['lost']['max']

                short_num = trade_info['short']['total']
                short_win_num = trade_info['short']['won']
                short_lost_num = trade_info['short']['lost']
                short_total_pnl = trade_info['short']['pnl']['total']
                short_average_pnl = trade_info['short']['pnl']['average']
                short_win_total_pnl = trade_info['short']['pnl']['won']['total']
                short_win_max_pnl = trade_info['short']['pnl']['won']['max']
                short_lost_total_pnl = trade_info['short']['pnl']['lost']['total']
                short_lost_max_pnl = trade_info['short']['pnl']['lost']['max']
            except:
                long_num = np.NaN
                long_win_num = np.NaN
                long_lost_num = np.NaN
                long_total_pnl = np.NaN
                long_average_pnl = np.NaN
                long_win_total_pnl = np.NaN
                long_win_max_pnl = np.NaN
                long_lost_total_pnl = np.NaN
                long_lost_max_pnl = np.NaN

                short_num = np.NaN
                short_win_num = np.NaN
                short_lost_num = np.NaN
                short_total_pnl = np.NaN
                short_average_pnl = np.NaN
                short_win_total_pnl = np.NaN
                short_win_max_pnl = np.NaN
                short_lost_total_pnl = np.NaN
                short_lost_max_pnl = np.NaN

            trade_dict_2['long_num'] = long_num
            trade_dict_2['long_win_num'] = long_win_num
            trade_dict_2['long_lost_num'] = long_lost_num
            trade_dict_2['long_total_pnl'] = long_total_pnl
            trade_dict_2['long_average_pnl'] = long_average_pnl
            trade_dict_2['long_win_total_pnl'] = long_win_total_pnl
            trade_dict_2['long_win_max_pnl'] = long_win_max_pnl
            trade_dict_2['long_lost_total_pnl'] = long_lost_total_pnl
            trade_dict_2['long_lost_max_pnl'] = long_lost_max_pnl
            trade_dict_2['short_num'] = short_num
            trade_dict_2['short_win_num'] = short_win_num
            trade_dict_2['short_lost_num'] = short_lost_num
            trade_dict_2['short_total_pnl'] = short_total_pnl
            trade_dict_2['short_average_pnl'] = short_average_pnl
            trade_dict_2['short_win_total_pnl'] = short_win_total_pnl
            trade_dict_2['short_win_max_pnl'] = short_win_max_pnl
            trade_dict_2['short_lost_total_pnl'] = short_lost_total_pnl
            trade_dict_2['short_lost_max_pnl'] = short_lost_max_pnl

            assert len(performance_dict) == len(trade_dict_2) == len(trade_dict_1)
            df00 = pd.DataFrame(index=range(18))
            df01 = pd.DataFrame([performance_dict]).T
            df01.columns = ['绩效指标值']
            df02 = pd.DataFrame([trade_dict_1]).T
            df02.columns = ['普通交易指标值']
            df03 = pd.DataFrame([trade_dict_2]).T
            df03.columns = ['多空交易指标值']
            try:
                df00['绩效指标'] = df01.index
                df00['绩效指标值'] = [round(float(i), 4) for i in list(df01['绩效指标值'])]
                df00['普通交易指标'] = df02.index
                df00['普通交易指标值'] = [round(float(i), 4) for i in list(df02['普通交易指标值'])]
                df00['多空交易指标'] = df03.index
                df00['多空交易指标值'] = [round(float(i), 4) for i in list(df03['多空交易指标值'])]
            except:
                df00['绩效指标'] = df01.index
                df00['绩效指标值'] = df01['绩效指标值']
                df00['普通交易指标'] = df02.index
                df00['普通交易指标值'] = df02['普通交易指标值']
                df00['多空交易指标'] = df03.index
                df00['多空交易指标值'] = df03['多空交易指标值']
                print('绩效指标值', df01['绩效指标值'])
                print(performance_dict)
                print(strategy.__name__ + params_str)
                print(sharpe_ratio, average_rate, max_drawdown_rate)

            # Add table data
            table_data = [list(df00['绩效指标'])[:9], list(df00['绩效指标值'])[:9],
                          list(df00['绩效指标'])[9:], list(df00['绩效指标值'])[9:],
                          list(df00['普通交易指标'])[:9], list(df00['普通交易指标值'])[:9],
                          list(df00['普通交易指标'])[9:], list(df00['普通交易指标值'])[9:],
                          list(df00['多空交易指标'])[:9], list(df00['多空交易指标值'])[:9],
                          list(df00['多空交易指标'])[9:], list(df00['多空交易指标值'])[9:],
                          ]
            fig = ff.create_table(table_data)
            # Add graph data
            # Add graph data
            trace1 = go.Scatter(
                x=list(df0.index),
                y=list(df0.total_value),
                xaxis='x2', yaxis='y2',
                name="total_value",
                mode='lines'
            )
            trace2 = go.Bar(x=list(df_return.index), y=[str(round(i, 3)) + "%" for i in list(df_return['return'])],
                            xaxis='x2', yaxis='y3', name='year_profit', opacity=0.3, marker={"color": "#ffa631"})
            # Add trace data to figure
            fig.add_traces([trace1, trace2])

            # initialize xaxis2 and yaxis2
            fig['layout']['xaxis2'] = {}
            fig['layout']['yaxis2'] = {}
            fig['layout']['yaxis3'] = {}

            # Edit layout for subplots
            fig.layout.yaxis.update({'domain': [.5, 1]})
            fig.layout.yaxis2.update({'domain': [0, .5]})
            fig.layout.yaxis3.update({'domain': [0, .5]})

            # The graph's yaxis2 MUST BE anchored to the graph's xaxis2 and vice versa
            # fig.layout.yaxis3.update({'anchor': 'x2'})
            # # fig.layout.xaxis2.update({'anchor': 'y3'})
            # fig.layout.yaxis3.update({'title': 'year_profit'})
            # fig.layout.yaxis3.update({'overlaying':'y2', 'side':'right'})

            fig.layout.yaxis2.update({'anchor': 'x2'})
            fig.layout.xaxis2.update({'anchor': 'y2'})
            fig.layout.yaxis2.update({'title': 'total_value'})
            fig.layout.yaxis2.update({'type': 'log'})

            fig.layout.yaxis3.update({'anchor': 'x2'})
            # fig.layout.xaxis2.update({'anchor': 'y3'})
            fig.layout.yaxis3.update({'title': 'year_profit'})
            fig.layout.yaxis3.update({'overlaying': 'y2', 'side': 'right'})

            # Update the margins to add a title and see graph x-labels.
            fig.layout.margin.update({'t': 75, 'l': 50})
            fig.layout.update(
                {'title': {'text': strategy.__name__ + params_str, "x": 0.5, "xanchor": 'center', "yanchor": "middle",
                           "font": {"family": "Arial", "color": "red"}}})

            # Update the height because adding a graph vertically will interact with
            # the plot height calculated for the table
            fig.layout.update({'height': 800})

            py.plot(fig, auto_open=auto_open, filename=result_path + strategy.__name__ + params_str)
        df00.to_csv(result_path + strategy.__name__ + params_str + '.csv', encoding='gbk')

        return results

    # def run_cerebro_plot(cerebro,strategy,params,score = 90,port=8050,plot=True,result_path=''):
#     strategy_name = strategy.__name__
#     author = strategy.author
#     params_str=''
#     for key in params:
#         params_str=params_str+'__'+key+'__'+str(params[key])
#     file_name = strategy_name+params_str+'.csv'
#     if result_path!="":
#         file_list = os.listdir(result_path)
#     else:
#         file_list = os.listdir(os.getcwd())
#     if file_name in file_list:
#         print("backtest {} consume time  :0 because of it has run".format(params_str))
#     # print("file name is {}".format(file_name))
#     # print("file_list is {}".format(file_list))
#     if file_name not in file_list:
#         print("begin to run this params:{},now_time is {}".format(params_str,time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
#         cerebro.addstrategy(strategy,**params)
#         begin_time=time.time()
#         if plot:
#             cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')
#             cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='_AnnualReturn')
#             cerebro.addanalyzer(bt.analyzers.Calmar, _name='_Calmar')
#             cerebro.addanalyzer(bt.analyzers.DrawDown, _name='_DrawDown')
#             # cerebro.addanalyzer(bt.analyzers.TimeDrawDown, _name='_TimeDrawDown')
#             cerebro.addanalyzer(bt.analyzers.GrossLeverage, _name='_GrossLeverage')
#             cerebro.addanalyzer(bt.analyzers.PositionsValue, _name='_PositionsValue')
#             # cerebro.addanalyzer(bt.analyzers.LogReturnsRolling, _name='_LogReturnsRolling')
#             cerebro.addanalyzer(bt.analyzers.PeriodStats, _name='_PeriodStats')
#             cerebro.addanalyzer(bt.analyzers.Returns, _name='_Returns')
#             cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='_SharpeRatio')
#             # cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name='_SharpeRatio_A')
#             cerebro.addanalyzer(bt.analyzers.SQN, _name='_SQN')
#             cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='_TimeReturn')
#             cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='_TradeAnalyzer')
#             cerebro.addanalyzer(bt.analyzers.Transactions, _name='_Transactions')
#             cerebro.addanalyzer(bt.analyzers.VWR, _name='_VWR')
#             cerebro.addanalyzer(bt.analyzers.TotalValue, _name='_TotalValue')
#         else:
#             cerebro.addanalyzer(bt.analyzers.TotalValue, _name='_TotalValue')
#         results = cerebro.run()
#         # plot_results(results,"/home/yun/index_000300_reverse_strategy_hold_day_90.html")
#         end_time=time.time()
#         print("backtest {} consume time  :{},结束时间为:{}".format(params_str,end_time-begin_time,time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())))
#         # 保存交易数据
#         try:
#             transactions=results[0].analyzers._Transactions.get_analysis()
#             import pickle
#             file_name_test="C:/{}{}_transactions.pkl".format(strategy_name,params_str)
#             with open(file_name_test) as f:
#                 pickle.dump(transactions,f)
#         except:
#             pass
#             print("保存数据失败")
#         try:
#             performance_dict=OrderedDict()
#             drawdown_info=results[0].analyzers._DrawDown.get_analysis()
#             average_drawdown_len=drawdown_info['len']
#             average_drawdown_rate=drawdown_info['drawdown']
#             average_drawdown_money=drawdown_info['moneydown']
#             max_drawdown_len=drawdown_info['max']['len']
#             max_drawdown_rate=drawdown_info['max']['drawdown']
#             max_drawdown_money=drawdown_info['max']['moneydown']
#             PeriodStats_info=results[0].analyzers._PeriodStats.get_analysis()
#             average_rate=PeriodStats_info['average']
#             stddev_rate=PeriodStats_info['stddev']
#             positive_year=PeriodStats_info['positive']
#             negative_year=PeriodStats_info['negative']
#             nochange_year=PeriodStats_info['nochange']
#             best_year=PeriodStats_info['best']
#             worst_year=PeriodStats_info['worst']
#             sharpe_info=results[0].analyzers._SharpeRatio.get_analysis()
#             sharpe_ratio=sharpe_info['sharperatio']

#         except:
#             drawdown_info=np.NaN
#             average_drawdown_len=np.NaN
#             average_drawdown_rate=np.NaN
#             average_drawdown_money=np.NaN
#             max_drawdown_len=np.NaN
#             max_drawdown_rate=np.NaN
#             max_drawdown_money=np.NaN
#             PeriodStats_info=np.NaN
#             average_rate=np.NaN
#             stddev_rate=np.NaN
#             positive_year=np.NaN
#             negative_year=np.NaN
#             nochange_year=np.NaN
#             best_year=np.NaN
#             worst_year=np.NaN
#             sharpe_info=np.NaN
#             sharpe_ratio=np.NaN
#         try:
#             calmar_ratio=list(results[0].analyzers._Calmar.get_analysis().values())[-1]
#             # print(calmar_ratio)
#             SQN_info=results[0].analyzers._SQN.get_analysis()
#             sqn_ratio=SQN_info['sqn']
#             VWR_info=results[0].analyzers._VWR.get_analysis()
#             vwr_ratio=VWR_info['vwr']
#         except:
#             calmar_ratio=np.NaN
#             # print(calmar_ratio)
#             SQN_info=np.NaN
#             sqn_ratio=np.NaN
#             VWR_info=np.NaN
#             vwr_ratio=np.NaN
#         # sharpe_info=results[0].analyzers._SharpeRatio_A.get_analysis()
#         # 计算三个关键的指标
#         df0=df1=pd.DataFrame([results[0].analyzers._TotalValue.get_analysis()]).T
#         df0.columns=['total_value']
#         df0.to_csv("C:/result/"+strategy_name+params_str+"斜率策略总的账户价值.csv")
#         sharpe_ratio,average_rate,max_drawdown_rate = get_rate_sharpe_drawdown(df0)


#         performance_dict['calmar_ratio']=calmar_ratio
#         performance_dict['average_drawdown_len']=average_drawdown_len
#         performance_dict['average_drawdown_rate']=average_drawdown_rate
#         performance_dict['average_drawdown_money']=average_drawdown_money
#         performance_dict['max_drawdown_len']=max_drawdown_len
#         performance_dict['max_drawdown_rate']=max_drawdown_rate
#         performance_dict['max_drawdown_money']=max_drawdown_money
#         performance_dict['average_rate']=average_rate
#         performance_dict['stddev_rate']=stddev_rate
#         performance_dict['positive_year']=positive_year
#         performance_dict['negative_year']=negative_year
#         performance_dict['nochange_year']=nochange_year
#         performance_dict['best_year']=best_year
#         performance_dict['worst_year']=worst_year
#         performance_dict['sqn_ratio']=sqn_ratio
#         performance_dict['vwr_ratio']=vwr_ratio
#         performance_dict['sharpe_info']=sharpe_ratio
#         performance_dict['omega']=np.NaN

#         trade_dict_1=OrderedDict()
#         trade_dict_2=OrderedDict()
#         try:
#             trade_info=results[0].analyzers._TradeAnalyzer.get_analysis()
#             total_trade_num=trade_info['total']['total']
#             total_trade_opened=trade_info['total']['open']
#             total_trade_closed=trade_info['total']['closed']
#             total_trade_len=trade_info['len']['total']
#             long_trade_len=trade_info['len']['long']['total']
#             short_trade_len=trade_info['len']['short']['total']
#         except:
#             total_trade_num=np.NaN
#             total_trade_opened=np.NaN
#             total_trade_closed=np.NaN
#             total_trade_len=np.NaN
#             long_trade_len=np.NaN
#             short_trade_len=np.NaN
#         try:
#             longest_win_num=trade_info['streak']['won']['longest']
#             longest_lost_num=trade_info['streak']['lost']['longest']
#             net_total_pnl=trade_info['pnl']['net']['total']
#             net_average_pnl=trade_info['pnl']['net']['average']
#             win_num=trade_info['won']['total']
#             win_total_pnl=trade_info['won']['pnl']['total']
#             win_average_pnl=trade_info['won']['pnl']['average']
#             win_max_pnl=trade_info['won']['pnl']['max']
#             lost_num=trade_info['lost']['total']
#             lost_total_pnl=trade_info['lost']['pnl']['total']
#             lost_average_pnl=trade_info['lost']['pnl']['average']
#             lost_max_pnl=trade_info['lost']['pnl']['max']
#         except:
#             longest_win_num=np.NaN
#             longest_lost_num=np.NaN
#             net_total_pnl=np.NaN
#             net_average_pnl=np.NaN
#             win_num=np.NaN
#             win_total_pnl=np.NaN
#             win_average_pnl=np.NaN
#             win_max_pnl=np.NaN
#             lost_num=np.NaN
#             lost_total_pnl=np.NaN
#             lost_average_pnl=np.NaN
#             lost_max_pnl=np.NaN

#         trade_dict_1['total_trade_num']=total_trade_num
#         trade_dict_1['total_trade_opened']=total_trade_opened
#         trade_dict_1['total_trade_closed']=total_trade_closed
#         trade_dict_1['total_trade_len']=total_trade_len
#         trade_dict_1['long_trade_len']=long_trade_len
#         trade_dict_1['short_trade_len']=short_trade_len
#         trade_dict_1['longest_win_num']=longest_win_num
#         trade_dict_1['longest_lost_num']=longest_lost_num
#         trade_dict_1['net_total_pnl']=net_total_pnl
#         trade_dict_1['net_average_pnl']=net_average_pnl
#         trade_dict_1['win_num']=win_num
#         trade_dict_1['win_total_pnl']=win_total_pnl
#         trade_dict_1['win_average_pnl']=win_average_pnl
#         trade_dict_1['win_max_pnl']=win_max_pnl
#         trade_dict_1['lost_num']=lost_num
#         trade_dict_1['lost_total_pnl']=lost_total_pnl
#         trade_dict_1['lost_average_pnl']=lost_average_pnl
#         trade_dict_1['lost_max_pnl']=lost_max_pnl

#         try:
#             long_num=trade_info['long']['total']
#             long_win_num=trade_info['long']['won']
#             long_lost_num=trade_info['long']['lost']
#             long_total_pnl=trade_info['long']['pnl']['total']
#             long_average_pnl=trade_info['long']['pnl']['average']
#             long_win_total_pnl=trade_info['long']['pnl']['won']['total']
#             long_win_max_pnl=trade_info['long']['pnl']['won']['max']
#             long_lost_total_pnl=trade_info['long']['pnl']['lost']['total']
#             long_lost_max_pnl=trade_info['long']['pnl']['lost']['max']

#             short_num=trade_info['short']['total']
#             short_win_num=trade_info['short']['won']
#             short_lost_num=trade_info['short']['lost']
#             short_total_pnl=trade_info['short']['pnl']['total']
#             short_average_pnl=trade_info['short']['pnl']['average']
#             short_win_total_pnl=trade_info['short']['pnl']['won']['total']
#             short_win_max_pnl=trade_info['short']['pnl']['won']['max']
#             short_lost_total_pnl=trade_info['short']['pnl']['lost']['total']
#             short_lost_max_pnl=trade_info['short']['pnl']['lost']['max']
#         except:
#             long_num=np.NaN
#             long_win_num=np.NaN
#             long_lost_num=np.NaN
#             long_total_pnl=np.NaN
#             long_average_pnl=np.NaN
#             long_win_total_pnl=np.NaN
#             long_win_max_pnl=np.NaN
#             long_lost_total_pnl=np.NaN
#             long_lost_max_pnl=np.NaN

#             short_num=np.NaN
#             short_win_num=np.NaN
#             short_lost_num=np.NaN
#             short_total_pnl=np.NaN
#             short_average_pnl=np.NaN
#             short_win_total_pnl=np.NaN
#             short_win_max_pnl=np.NaN
#             short_lost_total_pnl=np.NaN
#             short_lost_max_pnl=np.NaN


#         trade_dict_2['long_num']=long_num
#         trade_dict_2['long_win_num']=long_win_num
#         trade_dict_2['long_lost_num']=long_lost_num
#         trade_dict_2['long_total_pnl']=long_total_pnl
#         trade_dict_2['long_average_pnl']=long_average_pnl
#         trade_dict_2['long_win_total_pnl']=long_win_total_pnl
#         trade_dict_2['long_win_max_pnl']=long_win_max_pnl
#         trade_dict_2['long_lost_total_pnl']=long_lost_total_pnl
#         trade_dict_2['long_lost_max_pnl']=long_lost_max_pnl
#         trade_dict_2['short_num']=short_num
#         trade_dict_2['short_win_num']=short_win_num
#         trade_dict_2['short_lost_num']=short_lost_num
#         trade_dict_2['short_total_pnl']=short_total_pnl
#         trade_dict_2['short_average_pnl']=short_average_pnl
#         trade_dict_2['short_win_total_pnl']=short_win_total_pnl
#         trade_dict_2['short_win_max_pnl']=short_win_max_pnl
#         trade_dict_2['short_lost_total_pnl']=short_lost_total_pnl
#         trade_dict_2['short_lost_max_pnl']=short_lost_max_pnl


#         len(performance_dict)==len(trade_dict_2)==len(trade_dict_1)
#         df00=pd.DataFrame(index=range(18))
#         df01=pd.DataFrame([performance_dict]).T
#         df01.columns=['绩效指标值']
#         df02=pd.DataFrame([trade_dict_1]).T
#         df02.columns=['普通交易指标值']
#         df03=pd.DataFrame([trade_dict_2]).T
#         df03.columns=['多空交易指标值']
#         df00['绩效指标']=df01.index
#         df00['绩效指标值']=[round(float(i),4) for i in list(df01['绩效指标值'])]
#         df00['普通交易指标']=df02.index
#         df00['普通交易指标值']=[round(float(i),4) for i in list(df02['普通交易指标值'])]
#         df00['多空交易指标']=df03.index
#         df00['多空交易指标值']=[round(float(i),4) for i in list(df03['多空交易指标值'])]


#         if plot is True:

#             df00.to_csv(result_path+strategy.__name__+params_str+'.csv',encoding='gbk')

#             test_time=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
#             # 账户价值
#             df0=df1=pd.DataFrame([results[0].analyzers._TotalValue.get_analysis()]).T
#             df0.columns=['total_value']
#             df0.to_csv("C:/result/"+strategy_name+params_str+"斜率策略总的账户价值.csv")

#             # 总的杠杆
#             df1=pd.DataFrame([results[0].analyzers._GrossLeverage.get_analysis()]).T
#             df1.columns=['GrossLeverage']


#             # 滚动的对数收益率
#             # df2=pd.DataFrame([results[0].analyzers._LogReturnsRolling.get_analysis()]).T
#             # df2.columns=['log_return']

#             # year_rate
#             df3=pd.DataFrame([results[0].analyzers._AnnualReturn.get_analysis()]).T
#             df3.columns=['year_rate']

#             # 总的持仓价值
#             df4=pd.DataFrame(results[0].analyzers._PositionsValue.get_analysis()).T
#             df4['total_position_value']=df4.sum(axis=1)

#             # 定义表格组件


#             app = dash.Dash()
#             # app = JupyterDash('策略评估结果')
#             # server = app.server
#             colors = dict(background = 'white', text = 'black')

#             app.layout = html.Div(
#                 style = dict(backgroundColor = colors['background']),
#                 children = [
#                     html.H1(
#                         children='{}的策略评估结果'.format(strategy_name),
#                         style = dict(textAlign='center', color = colors['text'])),
#                     html.Div(
#                         children=f'策略作者 ： {author} ___ 测试时间： {test_time} ___ 测试分数为 : {score}',
#                         style = dict(textAlign = 'center', color = colors['text'])),

#                     dcc.Graph(
#                         id='账户价值',
#                         figure = dict(
#                             data = [{'x': list(df0.index), 'y': list(df0.total_value),
#                                     #'text':[int(i*1000)/10 for i in list(df3.year_rate)],
#                                     'type': 'scatter', 'name': '账户价值',
#                                     'textposition':"outside"}],
#                             layout = dict(
#                                 title='账户价值',
#                                 plot_bgcolor = colors['background'],
#                                 paper_bgcolor = colors['background'],
#                                 font = dict(color = colors['text'],
#                             )
#                             )
#                         )
#                     ),

#                     dcc.Graph(
#                         id='持仓市值',
#                         figure = dict(
#                             data = [{'x': list(df4.index), 'y': list(df4.total_position_value),
#                                     #'text':[int(i*1000)/10 for i in list(df3.year_rate)],
#                                     'type': 'scatter', 'name': '持仓市值',
#                                     'textposition':"outside"}],
#                             layout = dict(
#                                 title='持仓市值',
#                                 plot_bgcolor = colors['background'],
#                                 paper_bgcolor = colors['background'],
#                                 font = dict(color = colors['text']),
#                             )
#                         )
#                     ),
#                     dcc.Graph(
#                         id='年化收益',
#                         figure = dict(
#                             data = [{'x': list(df3.index), 'y': list(df3.year_rate),
#                                     'text':[int(i*1000)/10 for i in list(df3.year_rate)],
#                                     'type': 'bar', 'name': '年收益率',
#                                     'textposition':"outside"}],
#                             layout = dict(
#                                 title='年化收益率',
#                                 plot_bgcolor = colors['background'],
#                                 paper_bgcolor = colors['background'],
#                                 font = dict(color = colors['text']),
#                             )
#                         )
#                     ),
#                     create_table(df00)


#                 ]
#             )
#             app.run_server(port=port)
#             # app.run_server(debug=True, host='0.0.0.0')

#         else:

#             df00.to_csv(result_path+strategy.__name__+params_str+'.csv',encod